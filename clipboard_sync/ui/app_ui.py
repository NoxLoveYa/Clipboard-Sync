"""
clipboard_sync.ui  —  GUI shell: header bar, mode dropdown, settings gear,
                      and mode-frame container.

Delegates log / status display to LogView and mode-panel construction
to panels.py.  Has no dependency on networking or tray logic.
"""

import customtkinter as ctk

from clipboard_sync.ui.log_view import LogView
from clipboard_sync.ui.panels import build_client_panel, build_server_panel


class AppUI:
    """Builds and manages all GUI widgets for the Clipboard Sync window.

    Parameters
    ----------
    root : ctk.CTk
        The main application window.
    mode : str
        Initial mode: ``"client"`` or ``"server"``.
    config : dict
        Current config (used to pre-fill fields like server IP).
    on_mode_switch : callable
        Called with ``"client"`` or ``"server"`` when the user picks a
        mode from the header dropdown.
    on_open_settings : callable
        Called when the user clicks the gear button.
    """

    def __init__(self, root: ctk.CTk, mode: str, config: dict,
                 on_mode_switch: callable,
                 on_open_settings: callable) -> None:
        self.root = root
        self._mode = mode
        self._config = config
        self._on_mode_switch = on_mode_switch

        # ── header ─────────────────────────────────────────────
        header = ctk.CTkFrame(root, corner_radius=0, fg_color="#1e1e1e")
        header.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            header, text="Clipboard Sync",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left", padx=15, pady=12)

        mode_label = "SERVER" if mode == "server" else "CLIENT"
        self._mode_badge = ctk.CTkLabel(
            header, text=mode_label,
            font=("Segoe UI", 11, "bold"),
            fg_color="#3a7ebf", corner_radius=4,
            text_color="white", padx=8,
        )
        self._mode_badge.pack(side="left", padx=(0, 15), pady=12)

        self._mode_var = ctk.StringVar(value=mode_label)
        ctk.CTkOptionMenu(
            header, variable=self._mode_var,
            values=["CLIENT", "SERVER"],
            command=self._on_mode_dropdown,
            width=100,
            dynamic_resizing=False,
        ).pack(side="left", padx=(0, 5), pady=12)

        ctk.CTkButton(
            header, text="⚙", width=32, height=28,
            command=on_open_settings,
            fg_color="transparent", hover_color="#3a3a3a",
            font=("Segoe UI", 16),
        ).pack(side="right", padx=(0, 12))

        # ── mode-specific UI container ─────────────────────────
        self._mode_frame = ctk.CTkFrame(root)
        self._mode_frame.pack(fill="x", padx=15, pady=(10, 0))

        # ── log / status (delegated) ───────────────────────────
        self._log_view = LogView(root)

        # panel widget refs (populated by build_mode_panel)
        self._ip_var: ctk.StringVar | None = None
        self._ip_entry: ctk.CTkEntry | None = None
        self._connect_btn: ctk.CTkButton | None = None
        self._disconnect_btn: ctk.CTkButton | None = None
        self._auto_var: ctk.BooleanVar | None = None

    # ── mode dropdown ──────────────────────────────────────────────────────

    def _on_mode_dropdown(self, selection: str) -> None:
        new_mode = "server" if selection == "SERVER" else "client"
        if new_mode != self._mode:
            self._on_mode_switch(new_mode)

    # ── mode panel construction ────────────────────────────────────────────

    def build_mode_panel(self, mode: str, config: dict,
                         callbacks: dict) -> None:
        """Create mode-specific widgets inside the mode frame."""
        self._mode = mode
        self._config = config

        if mode == "server":
            build_server_panel(self._mode_frame, callbacks)
        else:
            refs = build_client_panel(self._mode_frame, config, callbacks)
            self._ip_var = refs["ip_var"]
            self._ip_entry = refs["ip_entry"]
            self._connect_btn = refs["connect_btn"]
            self._disconnect_btn = refs["disconnect_btn"]
            self._auto_var = refs["auto_var"]

    def rebuild_mode_panel(self, mode: str, config: dict,
                           callbacks: dict) -> None:
        """Clear the mode frame and rebuild for *mode*."""
        for w in self._mode_frame.winfo_children():
            w.destroy()
        self.build_mode_panel(mode, config, callbacks)

    # ── header updates ─────────────────────────────────────────────────────

    def update_header(self, mode: str) -> None:
        """Update badge text, window title, and dropdown for *mode*."""
        label = "SERVER" if mode == "server" else "CLIENT"
        self._mode = mode
        self._mode_badge.configure(text=label)
        self._mode_var.set(label)
        self.root.title(
            f"Clipboard Sync — {'Server' if mode == 'server' else 'Client'}")

    # ── button states (client mode) ────────────────────────────────────────

    def set_button_state(self, state: str) -> None:
        """Set client button states: ``"idle"``, ``"connected"``, or
        ``"connecting"``."""
        if state == "idle":
            self._connect_btn.configure(state="normal", text="Connect")
            self._disconnect_btn.configure(state="disabled",
                                           text="Disconnect")
            self._ip_entry.configure(state="normal")
        elif state == "connected":
            self._connect_btn.configure(state="disabled", text="Connect")
            self._disconnect_btn.configure(state="normal",
                                           text="Disconnect")
            self._ip_entry.configure(state="disabled")
        elif state == "connecting":
            self._connect_btn.configure(state="disabled", text="Connect")
            self._disconnect_btn.configure(state="normal", text="Cancel")
            self._ip_entry.configure(state="disabled")

    # ── connection inputs (for config save) ────────────────────────────────

    def get_connection_inputs(self) -> tuple[str, bool]:
        """Return ``(ip, auto_reconnect)`` from the client panel widgets."""
        ip = self._ip_var.get().strip() if self._ip_var else ""
        auto = self._auto_var.get() if self._auto_var else True
        return ip, auto

    def set_ip(self, ip: str) -> None:
        """Pre-fill the server IP entry (used by launch auto-connect)."""
        if self._ip_var is not None:
            self._ip_var.set(ip)

    # ── log / status delegation ────────────────────────────────────────────

    @property
    def log_view(self) -> LogView:
        return self._log_view
