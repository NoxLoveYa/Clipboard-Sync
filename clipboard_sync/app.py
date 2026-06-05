"""
clipboard_sync.app  —  ClipboardSyncGUI orchestrator.

Ties together AppUI, TrayManager, ClientConnection, and ServerHost.
Handles mode switching, lifecycle, settings, clipboard watching, and
shutdown.
"""

import threading
import time

import pyperclip
import customtkinter as ctk

from settings import load_config, save_config, open_settings_dialog

from clipboard_sync.log import log_event, status_queue
from clipboard_sync.config import (
    POLL_INTERVAL,
    load_mode, save_mode,
    config_path, config_defaults,
)
from clipboard_sync.network import ClientConnection, ServerHost
from clipboard_sync.tray import HAS_TRAY, TrayManager
from clipboard_sync.ui import AppUI


class ClipboardSyncGUI:
    """Single GUI class handling both client and server modes."""

    def __init__(self) -> None:
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

        # ── networking ───────────────────────────────────────────
        self._client = ClientConnection(callbacks={
            "on_connected": self._on_client_connected,
            "on_disconnected": self._on_client_disconnected,
            "on_connecting": self._on_client_connecting,
        })
        self._server = ServerHost(callbacks={
            "on_client_count_changed": lambda c: None,  # status handled by queue
        })
        self._clipboard_watcher_active = False

        # ── UI ───────────────────────────────────────────────────
        self._ui = AppUI(
            self.root, self._mode, self._config,
            on_mode_switch=self._switch_mode,
            on_open_settings=self._open_settings,
        )
        self._ui.build_mode_panel(self._mode, self._config,
                                  self._get_mode_callbacks())
        self._ui.update_header(self._mode)
        self._ui.start_polling()

        # ── tray ─────────────────────────────────────────────────
        self._tray = TrayManager(
            on_show=lambda: self.root.after(0, self._show_window),
            on_quit=lambda: self.root.after(0, self._quit_app),
        )
        if self._config.get("close_action", "tray") == "tray":
            self._tray.setup(self._mode)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── start services ───────────────────────────────────────
        self._start_services()

    # ── mode-specific UI callbacks ───────────────────────────────────────

    def _get_mode_callbacks(self) -> dict:
        """Return the callbacks dict for the current mode's UI panel."""
        if self._mode == "server":
            return {"on_copy_ip": self._copy_ip}
        return {
            "on_connect": self._start_client,
            "on_disconnect": self._stop_client,
        }

    # ── service lifecycle ────────────────────────────────────────────────

    def _start_services(self) -> None:
        """Start network / watcher threads for the current mode."""
        if self._mode == "server":
            self._server.start()
            self._start_clipboard_watcher()

    def _stop_services(self) -> None:
        """Tear down all network activity for the current mode."""
        self._stop_clipboard_watcher()
        if self._mode == "server":
            self._server.stop()
        else:
            self._client.stop()

    # ── clipboard watcher ─────────────────────────────────────────────────

    def _start_clipboard_watcher(self) -> None:
        if self._clipboard_watcher_active:
            return
        self._clipboard_watcher_active = True
        threading.Thread(target=self._clipboard_watcher, daemon=True).start()

    def _stop_clipboard_watcher(self) -> None:
        self._clipboard_watcher_active = False

    def _clipboard_watcher(self) -> None:
        last_sent = ""
        try:
            last_sent = pyperclip.paste()
        except Exception:
            pass

        while self._clipboard_watcher_active:
            time.sleep(POLL_INTERVAL)
            if not self._clipboard_watcher_active:
                return
            try:
                current = pyperclip.paste()
            except Exception:
                continue
            if current != last_sent and current.strip():
                last_sent = current
                if self._mode == "server":
                    log_event(
                        f"Broadcasting clipboard ({len(current)} chars)",
                        "info",
                    )
                    self._server.broadcast(current)
                else:
                    log_event(
                        f"Clipboard changed ({len(current)} chars) — sending",
                        "success",
                    )
                    self._client.send_text(current)

    # ── mode switching ────────────────────────────────────────────────────

    def _switch_mode(self, new_mode: str) -> None:
        """Stop current mode, save config, start new mode."""
        log_event(f"Switching to {new_mode.title()} mode…", "info")

        # 1. stop current services
        self._stop_services()

        # 2. save current config
        self._save_current_config()

        # 3. switch mode & reload config
        self._mode = new_mode
        save_mode(new_mode)
        self._config = load_config(
            config_path(new_mode), config_defaults(new_mode),
        )

        # 4. apply theme
        ctk.set_appearance_mode(self._config.get("theme", "dark"))

        # 5. rebuild mode UI
        self._ui.rebuild_mode_panel(new_mode, self._config,
                                    self._get_mode_callbacks())
        self._ui.update_header(new_mode)

        # 6. recreate tray
        self._tray.recreate(
            new_mode,
            self._config.get("close_action", "tray"),
        )

        # 7. reset network state
        self._client.reset_stop_event()
        self._server.reset_stop_event()

        # 8. start new services
        self._start_services()

        log_event(f"Now in {new_mode.title()} mode", "success")

    # ── client callbacks (wrapped for main-thread dispatch) ───────────────

    def _on_client_connected(self) -> None:
        self.root.after(0, lambda: self._ui.set_button_state("connected"))

    def _on_client_disconnected(self) -> None:
        self.root.after(0, lambda: self._ui.set_button_state("idle"))

    def _on_client_connecting(self) -> None:
        self.root.after(0, lambda: self._ui.set_button_state("connecting"))

    # ── client actions ────────────────────────────────────────────────────

    def _start_client(self) -> None:
        ip, auto_reconnect = self._ui.get_connection_inputs()
        if not ip:
            log_event("Please enter a server IP address", "warn")
            return
        self._start_clipboard_watcher()
        self._client.start(ip, auto_reconnect)

    def _stop_client(self) -> None:
        self._client.stop()
        self._stop_clipboard_watcher()

    # ── server actions ────────────────────────────────────────────────────

    def _copy_ip(self) -> None:
        from clipboard_sync.network import get_local_ip
        ip = get_local_ip()
        pyperclip.copy(ip)
        log_event(f"IP {ip} copied to clipboard", "info")

    # ── config ────────────────────────────────────────────────────────────

    def _save_current_config(self) -> None:
        """Persist current config to JSON."""
        config = dict(self._config)
        if self._mode == "client":
            ip, auto = self._ui.get_connection_inputs()
            config["server_ip"] = ip
            config["auto_reconnect"] = auto
        save_config(config_path(self._mode), config)

    # ── settings ──────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        open_settings_dialog(self.root, self._config, self._apply_settings)

    def _apply_settings(self, new_config: dict) -> None:
        changed_theme = new_config.get("theme") != self._config.get("theme")
        changed_close = (
            new_config.get("close_action") !=
            self._config.get("close_action")
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

    # ── window & tray ─────────────────────────────────────────────────────

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ── shutdown ──────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        """Window close button → minimize to tray or exit."""
        if (self._config.get("close_action") == "tray"
                and self._tray.active):
            log_event("Minimized to tray", "info")
            self.root.withdraw()
        else:
            self._quit_app()

    def _quit_app(self) -> None:
        """Full application shutdown."""
        log_event("Shutting down…", "warn")

        self._stop_services()
        self._tray.stop()
        self._save_current_config()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
