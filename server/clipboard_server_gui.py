"""
clipboard_server_gui.py  —  GUI server for Clipboard Sync
Requires: pip install customtkinter pyperclip

Usage:  python clipboard_server_gui.py
"""

import socket
import threading
import time
import queue

import pyperclip
import customtkinter as ctk

PORT = 5556
POLL_INTERVAL = 0.5
MAX_LOG_LINES = 500

# ── Thread-safe log / status queues ──────────────────────────────────────────

log_queue: "queue.Queue[tuple[str, str, str]]" = queue.Queue()
status_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()


def log_event(message: str, level: str = "info") -> None:
    """Push a timestamped log entry.  Safe to call from any thread."""
    log_queue.put((time.strftime("%H:%M:%S"), message, level))


# ── GUI application ──────────────────────────────────────────────────────────

class ClipboardServerGUI:
    """CustomTkinter GUI for the clipboard-sync server."""

    def __init__(self) -> None:
        self.root = ctk.CTk()
        self.root.title("Clipboard Sync — Server")
        self.root.geometry("660x540")
        self.root.minsize(520, 400)

        # ── network state ──────────────────────────────────────
        self.server_sock: socket.socket | None = None
        self.stop_event = threading.Event()
        self.clients: dict[socket.socket, bool] = {}
        self.clients_lock = threading.Lock()
        self._last_sent = ""
        self._local_ip = self._get_local_ip()

        # ── build UI and start ─────────────────────────────────
        self._build_ui()
        self._start_server()
        self._poll_log_queue()
        self._poll_status_queue()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _get_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # ── UI builder ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── header ─────────────────────────────────────────────
        header = ctk.CTkFrame(self.root, corner_radius=0, fg_color="#1e1e1e")
        header.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            header, text="Clipboard Sync",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left", padx=15, pady=12)

        ctk.CTkLabel(
            header, text="SERVER",
            font=("Segoe UI", 11, "bold"),
            fg_color="#3a7ebf", corner_radius=4,
            text_color="white", padx=8,
        ).pack(side="left", padx=(0, 15), pady=12)

        # ── IP row ─────────────────────────────────────────────
        ip_frame = ctk.CTkFrame(self.root)
        ip_frame.pack(fill="x", padx=15, pady=(10, 0))

        ctk.CTkLabel(
            ip_frame, text="Server IP:",
            font=("Segoe UI", 13),
        ).pack(side="left", padx=(10, 5), pady=10)

        self._ip_var = ctk.StringVar(value=self._local_ip)
        ip_entry = ctk.CTkEntry(
            ip_frame, textvariable=self._ip_var,
            width=200, state="readonly",
        )
        ip_entry.pack(side="left", padx=5, pady=10)

        ctk.CTkButton(
            ip_frame, text="Copy IP", width=90,
            command=self._copy_ip,
        ).pack(side="left", padx=5, pady=10)

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

    # ── actions ──────────────────────────────────────────────────────────────

    def _copy_ip(self) -> None:
        pyperclip.copy(self._local_ip)
        log_event(f"IP {self._local_ip} copied to clipboard", "info")

    def _update_status(self, color: str, text: str) -> None:
        self._status_canvas.itemconfig(self._status_dot, fill=color)
        self._status_text.set(text)

    # ── queue polling (main-thread via root.after) ───────────────────────────

    def _poll_log_queue(self) -> None:
        while not log_queue.empty():
            ts, msg, level = log_queue.get_nowait()
            self._append_log(ts, msg, level)
        self.root.after(150, self._poll_log_queue)

    def _poll_status_queue(self) -> None:
        while not status_queue.empty():
            color, text = status_queue.get_nowait()
            self._update_status(color, text)
        self.root.after(200, self._poll_status_queue)

    def _append_log(self, ts: str, msg: str, level: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.insert("end", f"[{ts}]  ", "ts")
        self._log_box.insert("end", f"{msg}\n", level if level in {"info", "success", "warn", "error"} else "default")
        self._truncate_log()
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    def _truncate_log(self) -> None:
        n = int(self._log_box.index("end-1c").split(".")[0])
        if n > MAX_LOG_LINES:
            self._log_box.delete("1.0", f"{n - MAX_LOG_LINES}.0")

    # ── server lifecycle ─────────────────────────────────────────────────────

    def _start_server(self) -> None:
        self.stop_event.clear()

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.server_sock.bind(("0.0.0.0", PORT))
            self.server_sock.listen(5)
        except OSError as e:
            log_event(f"Failed to bind port {PORT}: {e}", "error")
            status_queue.put(("#f44336", f"Error: {e}"))
            return

        log_event(f"Server started on {self._local_ip}:{PORT}", "success")
        status_queue.put(("#ff9800", f"Listening on {self._local_ip}:{PORT}"))

        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._clipboard_watcher, daemon=True).start()

    # ── accept loop ────────────────────────────────────────────

    def _accept_loop(self) -> None:
        assert self.server_sock is not None

        while not self.stop_event.is_set():
            try:
                self.server_sock.settimeout(1.0)
                conn, addr = self.server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            log_event(f"Client connected: {addr[0]}", "success")
            n = self._register_client(conn)
            status_queue.put(
                ("#4caf50", f"Listening — {n} client{'s' if n != 1 else ''} connected"),
            )

            threading.Thread(
                target=self._handle_client, args=(conn, addr), daemon=True,
            ).start()

    def _register_client(self, conn: socket.socket) -> int:
        with self.clients_lock:
            self.clients[conn] = True
            return len(self.clients)

    def _unregister_client(self, conn: socket.socket) -> int:
        with self.clients_lock:
            self.clients.pop(conn, None)
            return len(self.clients)

    # ── per-client handler ──────────────────────────────────────

    def _handle_client(self, conn: socket.socket, addr: tuple) -> None:
        buffer = ""
        try:
            while not self.stop_event.is_set():
                try:
                    conn.settimeout(1.0)
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break

                buffer += data.decode("utf-8", errors="replace")
                while "\n---END---\n" in buffer:
                    msg, buffer = buffer.split("\n---END---\n", 1)
                    if msg:
                        log_event(f"Received from {addr[0]} ({len(msg)} chars)", "info")
                        pyperclip.copy(msg)
                        self._last_sent = msg
                        self._broadcast(msg, source_conn=conn)
        except Exception:
            pass
        finally:
            conn.close()
            n = self._unregister_client(conn)
            log_event(f"Client disconnected: {addr[0]}", "warn")
            if n == 0:
                status_queue.put(("#ff9800", f"Listening — 0 clients"))

    def _broadcast(self, text: str, source_conn: socket.socket | None = None) -> None:
        dead: list[socket.socket] = []
        payload = (text + "\n---END---\n").encode("utf-8")

        with self.clients_lock:
            for conn in list(self.clients):
                if conn is source_conn:
                    continue
                try:
                    conn.sendall(payload)
                except Exception:
                    dead.append(conn)
            for conn in dead:
                self.clients.pop(conn, None)

        if dead:
            log_event(f"Broadcast finished; {len(dead)} stale client(s) removed", "warn")

    # ── clipboard watcher ──────────────────────────────────────

    def _clipboard_watcher(self) -> None:
        try:
            self._last_sent = pyperclip.paste()
        except Exception:
            self._last_sent = ""

        while not self.stop_event.is_set():
            time.sleep(POLL_INTERVAL)
            try:
                current = pyperclip.paste()
            except Exception:
                continue
            if current != self._last_sent and current.strip():
                self._last_sent = current
                log_event(f"Broadcasting clipboard ({len(current)} chars)", "info")
                self._broadcast(current)

    # ── shutdown ─────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        log_event("Shutting down server…", "warn")
        self.stop_event.set()

        if self.server_sock is not None:
            try:
                self.server_sock.close()
            except Exception:
                pass

        with self.clients_lock:
            for conn in list(self.clients):
                try:
                    conn.close()
                except Exception:
                    pass
            self.clients.clear()

        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


# ── entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    ClipboardServerGUI().run()
