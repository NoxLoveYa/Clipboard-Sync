"""
clipboard_sync.log_view  —  Status indicator and activity log display.

LogView owns the status dot, status text, and log textbox widgets.
It polls the module-level log/status queues from ``log.py`` and
updates the display on the main thread via ``root.after``.
"""

import customtkinter as ctk

from clipboard_sync.core.log import log_queue, status_queue
from clipboard_sync.core.config import MAX_LOG_LINES


class LogView:
    """Status dot + label, and a colour-coded scrollable log textbox.

    Call ``pack(parent)`` to place the widgets, then ``start_polling()``
    to begin reading from the shared log/status queues.
    """

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root

        # ── status row ─────────────────────────────────────────
        status_frame = ctk.CTkFrame(root)
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
        log_frame = ctk.CTkFrame(root)
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

    # ── status ─────────────────────────────────────────────────

    def update_status(self, color: str, text: str) -> None:
        self._status_canvas.itemconfig(self._status_dot, fill=color)
        self._status_text.set(text)

    # ── polling ────────────────────────────────────────────────

    def start_polling(self) -> None:
        """Begin draining the shared log/status queues via root.after."""
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
        self._truncate()
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    def _truncate(self) -> None:
        n = int(self._log_box.index("end-1c").split(".")[0])
        if n > MAX_LOG_LINES:
            self._log_box.delete("1.0", f"{n - MAX_LOG_LINES}.0")
