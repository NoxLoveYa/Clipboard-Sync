"""
clipboard_sync.app  —  ClipboardSyncGUI orchestrator.

Ties together AppUI, TrayManager, ClientConnection, ServerHost,
and ClipboardWatcher.  Handles mode switching, lifecycle, settings,
and shutdown.
"""

import queue
import sys

import pyperclip
import customtkinter as ctk

from settings import (
    load_config, save_config, open_settings_dialog,
    set_autostart, get_autostart,
)

from clipboard_sync.core.log import log_event, status_queue
from clipboard_sync.core.config import (
    load_mode, save_mode,
    config_path, config_defaults, get_local_ip,
)
from clipboard_sync.core import clipboard_io
from clipboard_sync.network import protocol
from clipboard_sync.network.discovery import DiscoveryListener, found_queue
from clipboard_sync.network.client import ClientConnection
from clipboard_sync.network.server import ServerHost
from clipboard_sync.ui.tray import TrayManager
from clipboard_sync.ui.app_ui import AppUI
from clipboard_sync.core.watcher import ClipboardWatcher


class ClipboardSyncGUI:
    """Single GUI class handling both client and server modes."""

    START_MINIMIZED = "--minimized" in sys.argv

    def __init__(self) -> None:
        self._discovery: DiscoveryListener | None = None
        # ── mode & config ────────────────────────────────────────
        self._mode: str = load_mode()
        self._config = load_config(
            config_path(self._mode), config_defaults(self._mode),
        )
        ctk.set_appearance_mode(self._config.get("theme", "dark"))

        # ── window ───────────────────────────────────────────────
        self.root = ctk.CTk()
        self.root.geometry("660x540")
        self.root.minsize(520, 400)
        if self.START_MINIMIZED:
            self.root.withdraw()

        # ── watcher ──────────────────────────────────────────────
        self._watcher = ClipboardWatcher(
            on_change=self._on_clipboard_change,
            get_mode_label=lambda: self._mode,
        )

        # ── networking ───────────────────────────────────────────
        self._client = ClientConnection(callbacks={
            "on_connected": self._on_client_connected,
            "on_disconnected": self._on_client_disconnected,
            "on_connecting": self._on_client_connecting,
            "on_remote_applied": self._suppress_remote_echo,
        })
        self._server = ServerHost(callbacks={
            "on_client_count_changed": lambda c: None,
            "on_remote_applied": self._suppress_remote_echo,
        })

        # ── UI ───────────────────────────────────────────────────
        self._ui = AppUI(
            self.root, self._mode, self._config,
            on_mode_switch=self._switch_mode,
            on_open_settings=self._open_settings,
        )
        self._ui.build_mode_panel(self._mode, self._config,
                                  self._get_mode_callbacks())
        self._ui.update_header(self._mode)
        self._ui.log_view.start_polling()

        # ── tray ─────────────────────────────────────────────────
        self._tray = TrayManager(
            on_show=lambda: self.root.after(0, self._show_window),
            on_quit=lambda: self.root.after(0, self._quit_app),
        )
        if (self._config.get("close_action", "tray") == "tray"
                or self.START_MINIMIZED):
            self._tray.setup(self._mode)

        # ── sync autostart with config ───────────────────────────
        if bool(self._config.get("autostart", False)) != get_autostart():
            self._apply_autostart()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── start services ───────────────────────────────────────
        self._start_services()

    # ── mode-specific UI callbacks ───────────────────────────────────────

    def _get_mode_callbacks(self) -> dict:
        if self._mode == "server":
            return {"on_copy_ip": self._copy_ip}
        return {
            "on_connect": self._start_client,
            "on_disconnect": self._stop_client,
        }

    # ── service lifecycle ────────────────────────────────────────────────

    def _start_services(self) -> None:
        if self._mode == "server":
            self._server.start()
            self._watcher.start()
            return

        # client mode — auto-connect to last known good IP
        ip = ((self._config.get("last_connected_ip")
               or self._config.get("server_ip") or "").strip())
        if ip:
            self._ui.set_ip(ip)
            log_event(f"Auto-connecting to last server {ip}…", "info")
            self._start_client()
            return

        # no known server — zero-setup LAN discovery
        if self._config.get("auto_discover", True):
            self._start_discovery()
        else:
            log_event(
                "No saved server IP — enter one and click Connect", "warn")

    # ── zero-setup LAN discovery ─────────────────────────────────────────

    def _start_discovery(self) -> None:
        if self._discovery is not None:
            return
        log_event("Searching for servers on LAN…", "info")
        status_queue.put(("#ff9800", "Searching for servers…"))
        self._discovery = DiscoveryListener(
            on_found=lambda hostname, ip, port: found_queue.put((ip,)))
        self._discovery.start()
        self.root.after(300, self._drain_discovery)
        self.root.after(15000, self._discovery_timeout)

    def _stop_discovery(self) -> None:
        if self._discovery is not None:
            self._discovery.stop()
            self._discovery = None

    def _drain_discovery(self) -> None:
        """Main-thread poller: connect to the first discovered server."""
        try:
            (ip,) = found_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self._stop_discovery()  # first server wins
            if (self._mode == "client"
                    and not self._client.connected
                    and ip != get_local_ip()):
                log_event(f"Auto-connecting to discovered server {ip}…",
                          "info")
                self._config["server_ip"] = ip
                save_config(config_path(self._mode), self._config)
                self._ui.set_ip(ip)
                self._start_client()
            return
        if self._discovery is not None:
            self.root.after(300, self._drain_discovery)

    def _discovery_timeout(self) -> None:
        if (self._mode == "client" and self._discovery is not None
                and not self._client.connected):
            log_event("No servers found in 15 s — is the server running, "
                      "and did you allow the app through Windows Firewall?",
                      "warn")

    def _stop_services(self) -> None:
        self._watcher.stop()
        self._stop_discovery()
        if self._mode == "server":
            self._server.stop()
        else:
            self._client.stop()

    # ── clipboard change handler ─────────────────────────────────────────

    def _on_clipboard_change(self, snapshot) -> None:
        kind = snapshot.kind
        if kind == "image" and \
                not self._config.get("sync_images", True):
            return
        if kind == "files" and not self._config.get("sync_files", True):
            return

        max_bytes = int(self._config.get("max_transfer_mb", 100)) * 1048576
        if snapshot.total_bytes > max_bytes:
            log_event(
                f"{kind} too large "
                f"({snapshot.total_bytes / 1048576:.1f} MB > "
                f"max {max_bytes // 1048576} MB) — not sending",
                "warn",
            )
            return

        try:
            frames, total = protocol.frames_for_snapshot(snapshot)
        except OSError as e:
            log_event(f"Cannot send {kind}: {e}", "error")
            return

        size = (f"{total} chars" if total < 1048576
                else f"{total / 1048576:.1f} MB")
        if self._mode == "server":
            self._server.broadcast_frames(frames)
            log_event(f"Broadcasting {kind} ({size})", "info")
        else:
            if self._client.send_frames(frames):
                log_event(f"Sent {kind} ({size})", "success")

    def _suppress_remote_echo(self, fingerprint: str) -> None:
        """Called from network threads after received content lands on the
        local clipboard — stops the watcher echoing it back."""
        if fingerprint:
            self._watcher.suppress_next(fingerprint)

    # ── mode switching ────────────────────────────────────────────────────

    def _switch_mode(self, new_mode: str) -> None:
        log_event(f"Switching to {new_mode.title()} mode…", "info")

        self._stop_services()
        self._save_current_config()

        self._mode = new_mode
        save_mode(new_mode)
        self._config = load_config(
            config_path(new_mode), config_defaults(new_mode),
        )

        ctk.set_appearance_mode(self._config.get("theme", "dark"))

        self._ui.rebuild_mode_panel(new_mode, self._config,
                                    self._get_mode_callbacks())
        self._ui.update_header(new_mode)

        self._tray.recreate(
            new_mode,
            self._config.get("close_action", "tray"),
        )

        self._client.reset_stop_event()
        self._server.reset_stop_event()

        self._start_services()

        log_event(f"Now in {new_mode.title()} mode", "success")

    # ── client callbacks (main-thread dispatch) ───────────────────────────

    def _on_client_connected(self) -> None:
        def _update() -> None:
            self._ui.set_button_state("connected")
            ip, _ = self._ui.get_connection_inputs()
            if ip and ip != self._config.get("last_connected_ip"):
                self._config["last_connected_ip"] = ip
                save_config(config_path(self._mode), self._config)
        self.root.after(0, _update)

    def _on_client_disconnected(self) -> None:
        self.root.after(0, lambda: self._ui.set_button_state("idle"))

    def _on_client_connecting(self) -> None:
        self.root.after(0, lambda: self._ui.set_button_state("connecting"))

    # ── client / server actions ───────────────────────────────────────────

    def _start_client(self) -> None:
        self._stop_discovery()  # manual connect wins over discovery
        ip, auto_reconnect = self._ui.get_connection_inputs()
        if not ip:
            log_event("Please enter a server IP address", "warn")
            return
        self._watcher.start()
        self._client.start(
            ip, auto_reconnect,
            reconnect_delay=int(self._config.get("reconnect_delay", 5)),
        )

    def _stop_client(self) -> None:
        self._client.stop()
        self._watcher.stop()

    def _copy_ip(self) -> None:
        ip = get_local_ip()
        pyperclip.copy(ip)
        log_event(f"IP {ip} copied to clipboard", "info")

    # ── config ────────────────────────────────────────────────────────────

    def _save_current_config(self) -> None:
        config = dict(self._config)
        if self._mode == "client":
            ip, auto = self._ui.get_connection_inputs()
            config["server_ip"] = ip
            config["auto_reconnect"] = auto
        save_config(config_path(self._mode), config)

    # ── settings ──────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        open_settings_dialog(
            self.root, self._config, self._apply_settings,
            show_reconnect=self._mode == "client",
        )

    def _apply_settings(self, new_config: dict) -> None:
        changed_theme = new_config.get("theme") != self._config.get("theme")
        changed_close = (
            new_config.get("close_action") !=
            self._config.get("close_action")
        )
        changed_autostart = (
            bool(new_config.get("autostart", False)) !=
            bool(self._config.get("autostart", False))
        )
        changed_delay = (
            new_config.get("reconnect_delay") !=
            self._config.get("reconnect_delay")
        )

        self._config = new_config
        self._save_current_config()

        if changed_theme:
            theme = self._config.get("theme", "dark")
            ctk.set_appearance_mode(theme)
            log_event(f"Theme changed to: {theme.title()}", "success")

        if changed_close:
            action = self._config.get("close_action", "tray")
            if action == "tray" and not self._tray.active:
                self._tray.setup(self._mode)
                log_event("Close action: minimize to tray", "info")
            elif action == "exit" and self._tray.active:
                self._tray.stop()
                log_event("Close action: exit", "info")
            else:
                log_event(f"Close action: {action}", "info")

        if changed_autostart:
            self._apply_autostart()

        if changed_delay:
            delay = int(new_config.get("reconnect_delay", 5))
            self._client.reconnect_delay = delay
            log_event(f"Reconnect delay set to {delay}s", "success")

    # ── windows autostart ────────────────────────────────────────────────

    def _apply_autostart(self) -> None:
        enabled = bool(self._config.get("autostart", False))
        try:
            set_autostart(enabled)
            state = "enabled — will start minimized to tray" if enabled \
                else "disabled"
            log_event(f"Start with Windows {state}", "info")
        except Exception as e:
            log_event(f"Failed to update startup entry: {e}", "error")

    # ── window & tray ─────────────────────────────────────────────────────

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ── shutdown ──────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if (self._config.get("close_action") == "tray"
                and self._tray.active):
            log_event("Minimized to tray", "info")
            self.root.withdraw()
        else:
            self._quit_app()

    def _quit_app(self) -> None:
        log_event("Shutting down…", "warn")

        self._stop_services()
        self._tray.stop()
        self._save_current_config()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
