"""
clipboard_sync.ui  —  GUI widget creation and display.

AppUI builds and owns all CustomTkinter widgets.  It has no dependency
on networking or tray logic — it receives callbacks from app.py.
"""

import customtkinter as ctk

from clipboard_sync.log import log_queue, status_queue
from clipboard_sync.config import MAX_LOG_LINES


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

        # widget references (populated by _build_*)
        self._mode_badge: ctk.CTkLabel | None = None
        self._mode_var: ctk.StringVar | None = None
        self._mode_frame: ctk.CTkFrame | None = None
        self._status_canvas: ctk.CTkCanvas | None = None
        self._status_dot = None
        self._status_text: ctk.StringVar | None = None
        self._log_box: ctk.CTkTextbox | None = None

        # client-specific widget refs
        self._ip_var: ctk.StringVar | None = None
        self._ip_entry: ctk.CTkEntry | None = None
        self._connect_btn: ctk.CTkButton | None = None
        self._disconnect_btn: ctk.CTkButton | None = None
        self._auto_var: ctk.BooleanVar | None = None

        self._build_ui(on_open_settings)

    # ── full UI construction ───────────────────────────────────────────────

    def _build_ui(self, on_open_settings: callable) -> None:
        """Build the complete window: header, mode panel, status, log."""
        # ── header ─────────────────────────────────────────────
        header = ctk.CTkFrame(self.root, corner_radius=0, fg_color="#1e1e1e")
        header.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            header, text="Clipboard Sync",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left", padx=15, pady=12)

        mode_label = "SERVER" if self._mode == "server" else "CLIENT"
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
        self._mode_frame = ctk.CTkFrame(self.root)
        self._mode_frame.pack(fill="x", padx=15, pady=(10, 0))

        # ── status row ─────────────────────────────────────────
        status_frame = ctk.CTkFrame(self.root)
        status_frame.pack(fill="x", padx=15, pady=(5, 0))

        self._status_canvas = ctk.CTkCanvas(
            status_frame, width=20, height=20,
            highlightthickness=0, bg="#2d2d2d",
        )
        self._status_canvas.pack(side="left", padx=(10, 6), pady=10)
        self._status_dot = self._status_canvas.create_oval(
            2, 2, 18, 18, fill="#ff9800", outline="",
        )

        self._status_text = ctk.StringVar(value="Starting…")
        ctk.CTkLabel(
            status_frame, textvariable=self._status_text,
            font=("Segoe UI", 12),
        ).pack(side="left", pady=10)

        # ── activity log ───────────────────────────────────────
        log_frame = ctk.CTkFrame(self.root)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(8, 15))

        ctk.CTkLabel(
            log_frame, text="Activity Log",
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 2))

        self._log_box = ctk.CTkTextbox(
            log_frame, state="disabled",
            wrap="word", font=("Consolas", 11),
            fg_color="#0d0d0d",
        )
        self._log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # colour tags
        self._log_box.tag_config("ts",      foreground="#666666")
        self._log_box.tag_config("default", foreground="#c8c8c8")
        self._log_box.tag_config("info",    foreground="#2196f3")
        self._log_box.tag_config("success", foreground="#4caf50")
        self._log_box.tag_config("warn",    foreground="#ffa726")
        self._log_box.tag_config("error",   foreground="#ef5350")

    # ── mode dropdown ──────────────────────────────────────────────────────

    def _on_mode_dropdown(self, selection: str) -> None:
        new_mode = "server" if selection == "SERVER" else "client"
        if new_mode != self._mode:
            self._on_mode_switch(new_mode)

    # ── mode panel construction ────────────────────────────────────────────

    def build_mode_panel(self, mode: str, config: dict,
                         callbacks: dict) -> None:
        """Create mode-specific widgets inside the mode frame.

        *callbacks* must contain the keys relevant to the mode:
        client — ``on_connect``, ``on_disconnect``
        server — ``on_copy_ip``
        """
        self._mode = mode
        self._config = config

        if mode == "server":
            self._build_server_panel(callbacks)
        else:
            self._build_client_panel(callbacks)

    def rebuild_mode_panel(self, mode: str, config: dict,
                           callbacks: dict) -> None:
        """Clear the mode frame and rebuild for *mode*."""
        for w in self._mode_frame.winfo_children():
            w.destroy()
        self.build_mode_panel(mode, config, callbacks)

    def _build_client_panel(self, callbacks: dict) -> None:
        """Client mode: IP entry, Connect/Disconnect, auto-reconnect."""
        conn_frame = ctk.CTkFrame(self._mode_frame)
        conn_frame.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            conn_frame, text="Server IP:",
            font=("Segoe UI", 13),
        ).pack(side="left", padx=(10, 5), pady=10)

        ip = self._config.get("server_ip", "")
        self._ip_var = ctk.StringVar(value=ip)
        self._ip_entry = ctk.CTkEntry(
            conn_frame, textvariable=self._ip_var,
            width=180, placeholder_text="192.168.x.x",
        )
        self._ip_entry.pack(side="left", padx=5, pady=10)

        self._connect_btn = ctk.CTkButton(
            conn_frame, text="Connect", width=90,
            command=callbacks["on_connect"],
        )
        self._connect_btn.pack(side="left", padx=5, pady=10)

        self._disconnect_btn = ctk.CTkButton(
            conn_frame, text="Disconnect", width=90,
            state="disabled",
            command=callbacks["on_disconnect"],
            fg_color="#c0392b", hover_color="#e74c3c",
        )
        self._disconnect_btn.pack(side="left", padx=5, pady=10)

        self._auto_var = ctk.BooleanVar(
            value=self._config.get("auto_reconnect", True),
        )
        ctk.CTkCheckBox(
            self._mode_frame, text="Auto-reconnect",
            variable=self._auto_var, onvalue=True, offvalue=False,
            font=("Segoe UI", 11),
        ).pack(anchor="w", padx=10, pady=(3, 0))

        status_queue.put(("#f44336", "Disconnected"))

    def _build_server_panel(self, callbacks: dict) -> None:
        """Server mode: readonly IP display, Copy IP button."""
        ip_frame = ctk.CTkFrame(self._mode_frame)
        ip_frame.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            ip_frame, text="Server IP:",
            font=("Segoe UI", 13),
        ).pack(side="left", padx=(10, 5), pady=10)

        from clipboard_sync.network import get_local_ip
        local_ip = get_local_ip()
        self._server_ip_var = ctk.StringVar(value=local_ip)
        ctk.CTkEntry(
            ip_frame, textvariable=self._server_ip_var,
            width=200, state="readonly",
        ).pack(side="left", padx=5, pady=10)

        ctk.CTkButton(
            ip_frame, text="Copy IP", width=90,
            command=callbacks["on_copy_ip"],
        ).pack(side="left", padx=5, pady=10)

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

    # ── status display ─────────────────────────────────────────────────────

    def update_status(self, color: str, text: str) -> None:
        self._status_canvas.itemconfig(self._status_dot, fill=color)
        self._status_text.set(text)

    # ── log display & queue polling ────────────────────────────────────────

    def start_polling(self) -> None:
        """Begin polling the log and status queues via ``root.after``."""
        self._poll_log_queue()
        self._poll_status_queue()

    def _poll_log_queue(self) -> None:
        while not log_queue.empty():
            ts, msg, level = log_queue.get_nowait()
            self._append_log(ts, msg, level)
        self.root.after(150, self._poll_log_queue)

    def _poll_status_queue(self) -> None:
        while not status_queue.empty():
            color, text = status_queue.get_nowait()
            self.update_status(color, text)
        self.root.after(200, self._poll_status_queue)

    def _append_log(self, ts: str, msg: str, level: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.insert("end", f"[{ts}]  ", "ts")
        tag = level if level in {"info", "success", "warn", "error"} else "default"
        self._log_box.insert("end", f"{msg}\n", tag)
        self._truncate_log()
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    def _truncate_log(self) -> None:
        n = int(self._log_box.index("end-1c").split(".")[0])
        if n > MAX_LOG_LINES:
            self._log_box.delete("1.0", f"{n - MAX_LOG_LINES}.0")
