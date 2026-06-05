"""
clipboard_client_gui.py  —  GUI client for Clipboard Sync
Requires: pip install customtkinter pyperclip

Usage:  python clipboard_client_gui.py
"""

import json
import os
import socket
import threading
import time
import queue

import pyperclip
import customtkinter as ctk

from settings import load_config, save_config, open_settings_dialog

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

PORT = 5556
POLL_INTERVAL = 0.5
RECONNECT_DELAY = 5
MAX_LOG_LINES = 500
CONFIG_PATH = os.path.expanduser("~/.clipboardsync.json")

# ── Thread-safe log / status queues ──────────────────────────────────────────

log_queue: "queue.Queue[tuple[str, str, str]]" = queue.Queue()
status_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()


def log_event(message: str, level: str = "info") -> None:
    """Push a timestamped log entry.  Safe to call from any thread."""
    log_queue.put((time.strftime("%H:%M:%S"), message, level))


# ── config persistence ───────────────────────────────────────────────────────

def _load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"server_ip": "", "auto_reconnect": True}


def _save_config(server_ip: str, auto_reconnect: bool, theme: str = "dark", close_action: str = "tray") -> None:
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump({
                "server_ip": server_ip,
                "auto_reconnect": auto_reconnect,
                "theme": theme,
                "close_action": close_action,
            }, f, indent=2)
    except Exception:
        pass


# ── GUI application ──────────────────────────────────────────────────────────

class ClipboardClientGUI:
    """CustomTkinter GUI for the clipboard-sync client."""

    def __init__(self) -> None:
        self._config = _load_config()
        # fill missing keys
        self._config.setdefault("close_action", "tray")
        self._config.setdefault("theme", "dark")
        ctk.set_appearance_mode(self._config.get("theme", "dark"))

        self.root = ctk.CTk()
        self.root.title("Clipboard Sync — Client")
        self.root.geometry("660x540")
        self.root.minsize(520, 400)

        # ── network state ──────────────────────────────────────
        self._sock: socket.socket | None = None
        self._sock_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._connected = False
        self._last_sent = ""

        self._build_ui(self._config)
        self._poll_log_queue()
        self._poll_status_queue()

        self._tray_icon = None
        if HAS_TRAY and self._config.get("close_action", "tray") == "tray":
            self._setup_tray()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI builder ───────────────────────────────────────────────────────────

    def _build_ui(self, config: dict) -> None:
        # ── header ─────────────────────────────────────────────
        header = ctk.CTkFrame(self.root, corner_radius=0, fg_color="#1e1e1e")
        header.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            header, text="Clipboard Sync",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left", padx=15, pady=12)

        ctk.CTkLabel(
            header, text="CLIENT",
            font=("Segoe UI", 11, "bold"),
            fg_color="#3a7ebf", corner_radius=4,
            text_color="white", padx=8,
        ).pack(side="left", padx=(0, 15), pady=12)

        ctk.CTkButton(
            header, text="⚙", width=32, height=28,
            command=self._open_settings,
            fg_color="transparent", hover_color="#3a3a3a",
            font=("Segoe UI", 16),
        ).pack(side="right", padx=(0, 12))

        # ── connect row ────────────────────────────────────────
        conn_frame = ctk.CTkFrame(self.root)
        conn_frame.pack(fill="x", padx=15, pady=(10, 0))

        ctk.CTkLabel(
            conn_frame, text="Server IP:",
            font=("Segoe UI", 13),
        ).pack(side="left", padx=(10, 5), pady=10)

        self._ip_var = ctk.StringVar(value=config.get("server_ip", ""))
        self._ip_entry = ctk.CTkEntry(
            conn_frame, textvariable=self._ip_var,
            width=180, placeholder_text="192.168.x.x",
        )
        self._ip_entry.pack(side="left", padx=5, pady=10)

        self._connect_btn = ctk.CTkButton(
            conn_frame, text="Connect", width=90,
            command=self._start_client,
        )
        self._connect_btn.pack(side="left", padx=5, pady=10)

        self._disconnect_btn = ctk.CTkButton(
            conn_frame, text="Disconnect", width=90,
            state="disabled",
            command=self._stop_client,
            fg_color="#c0392b", hover_color="#e74c3c",
        )
        self._disconnect_btn.pack(side="left", padx=5, pady=10)

        # ── auto-reconnect checkbox ────────────────────────────
        self._auto_var = ctk.BooleanVar(value=config.get("auto_reconnect", True))
        ctk.CTkCheckBox(
            self.root, text="Auto-reconnect",
            variable=self._auto_var, onvalue=True, offvalue=False,
            font=("Segoe UI", 11),
        ).pack(anchor="w", padx=25, pady=(3, 0))

        # ── status row ─────────────────────────────────────────
        status_frame = ctk.CTkFrame(self.root)
        status_frame.pack(fill="x", padx=15, pady=(5, 0))

        self._status_canvas = ctk.CTkCanvas(
            status_frame, width=20, height=20,
            highlightthickness=0, bg="#2d2d2d",
        )
        self._status_canvas.pack(side="left", padx=(10, 6), pady=10)
        self._status_dot = self._status_canvas.create_oval(
            2, 2, 18, 18, fill="#f44336", outline="",
        )

        self._status_text = ctk.StringVar(value="Disconnected")
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

    # ── button state helpers (main thread only) ──────────────────────────────

    def _enable_idle_mode(self) -> None:
        self._connect_btn.configure(state="normal", text="Connect")
        self._disconnect_btn.configure(state="disabled", text="Disconnect")
        self._ip_entry.configure(state="normal")

    def _enable_connected_mode(self) -> None:
        self._connect_btn.configure(state="disabled", text="Connect")
        self._disconnect_btn.configure(state="normal", text="Disconnect")
        self._ip_entry.configure(state="disabled")

    def _enable_connecting_mode(self) -> None:
        self._connect_btn.configure(state="disabled", text="Connect")
        self._disconnect_btn.configure(state="normal", text="Cancel")
        self._ip_entry.configure(state="disabled")

    # ── status ───────────────────────────────────────────────────────────────

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
        tag = level if level in {"info", "success", "warn", "error"} else "default"
        self._log_box.insert("end", f"{msg}\n", tag)
        self._truncate_log()
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    def _truncate_log(self) -> None:
        n = int(self._log_box.index("end-1c").split(".")[0])
        if n > MAX_LOG_LINES:
            self._log_box.delete("1.0", f"{n - MAX_LOG_LINES}.0")

    # ── client lifecycle ─────────────────────────────────────────────────────

    def _start_client(self) -> None:
        ip = self._ip_var.get().strip()
        if not ip:
            log_event("Please enter a server IP address", "warn")
            return

        self._stop_event.clear()
        self._enable_connecting_mode()
        status_queue.put(("#ff9800", "Connecting…"))
        log_event(f"Connecting to {ip}:{PORT}…", "info")

        auto_reconnect = self._auto_var.get()  # capture on main thread
        threading.Thread(
            target=self._connect_loop, args=(ip, auto_reconnect), daemon=True,
        ).start()
        threading.Thread(
            target=self._clipboard_watcher, daemon=True,
        ).start()

    def _stop_client(self) -> None:
        log_event("Disconnecting…", "warn")
        self._stop_event.set()

        with self._sock_lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

        self._connected = False
        self._enable_idle_mode()
        status_queue.put(("#f44336", "Disconnected"))

    # ── connection loop (background thread) ────────────────────

    def _connect_loop(self, ip: str, auto_reconnect: bool) -> None:
        while not self._stop_event.is_set():
            conn: socket.socket | None = None
            try:
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                conn.settimeout(3)
                conn.connect((ip, PORT))

                # connected successfully
                with self._sock_lock:
                    self._sock = conn
                self._connected = True

                log_event("Connected!", "success")
                status_queue.put(("#4caf50", "Connected"))
                self.root.after(0, self._enable_connected_mode)

                try:
                    self._last_sent = pyperclip.paste()
                except Exception:
                    self._last_sent = ""

                self._receive_loop(conn)

                # receive loop exited — check cause
                if self._stop_event.is_set():
                    break  # intentional disconnect

                # unexpected disconnect
                log_event("Connection lost", "error")
                status_queue.put(("#f44336", "Connection lost"))
                self.root.after(0, self._enable_idle_mode)

            except ConnectionRefusedError:
                if self._stop_event.is_set():
                    break
                log_event("Connection refused — is the server running?", "error")
            except socket.timeout:
                if self._stop_event.is_set():
                    break
                log_event("Connection timed out", "warn")
            except OSError as e:
                if self._stop_event.is_set():
                    break
                log_event(f"Connection error: {e}", "error")
            except Exception as e:
                if self._stop_event.is_set():
                    break
                log_event(f"Unexpected error: {e}", "error")
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                with self._sock_lock:
                    self._sock = None
                self._connected = False

            if self._stop_event.is_set():
                break

            if not auto_reconnect:
                self.root.after(0, self._enable_idle_mode)
                status_queue.put(("#f44336", "Disconnected"))
                return

            # auto-reconnect: count down
            log_event(f"Retrying in {RECONNECT_DELAY}s…", "warn")
            status_queue.put(("#ff9800", f"Retrying in {RECONNECT_DELAY}s…"))
            self.root.after(0, self._enable_connecting_mode)

            for _ in range(RECONNECT_DELAY * 2):
                if self._stop_event.is_set():
                    return
                time.sleep(0.5)

        # clean exit from while loop
        self.root.after(0, self._enable_idle_mode)
        status_queue.put(("#f44336", "Disconnected"))

    def _receive_loop(self, conn: socket.socket) -> None:
        """Blocking receive loop — runs inside _connect_loop.  Exits on
        disconnect / stop_event."""
        buffer = ""
        try:
            while not self._stop_event.is_set():
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
                        log_event(
                            f"Received from server ({len(msg)} chars)", "info",
                        )
                        pyperclip.copy(msg)
                        self._last_sent = msg
        except Exception:
            pass

    def _send_text(self, text: str) -> None:
        with self._sock_lock:
            if self._sock is None:
                return
            try:
                self._sock.sendall((text + "\n---END---\n").encode("utf-8"))
            except Exception:
                pass

    # ── clipboard watcher (background thread) ──────────────────

    def _clipboard_watcher(self) -> None:
        try:
            self._last_sent = pyperclip.paste()
        except Exception:
            self._last_sent = ""

        while not self._stop_event.is_set():
            time.sleep(POLL_INTERVAL)
            try:
                current = pyperclip.paste()
            except Exception:
                continue
            if current != self._last_sent and current.strip():
                self._last_sent = current
                log_event(
                    f"Clipboard changed ({len(current)} chars) — sending", "success",
                )
                self._send_text(current)

    # ── settings ────────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        open_settings_dialog(self.root, self._config, self._apply_settings)

    def _apply_settings(self, new_config: dict) -> None:
        changed_theme = new_config.get("theme") != self._config.get("theme")
        changed_close = new_config.get("close_action") != self._config.get("close_action")

        self._config = new_config
        _save_config(
            self._config.get("server_ip", ""),
            self._config.get("auto_reconnect", True),
            self._config.get("theme", "dark"),
            self._config.get("close_action", "tray"),
        )

        if changed_theme:
            theme = self._config.get("theme", "dark")
            ctk.set_appearance_mode(theme)
            log_event(f"Theme changed to: {theme.title()}", "success")

        if changed_close:
            action = self._config.get("close_action", "tray")
            if action == "tray" and self._tray_icon is None and HAS_TRAY:
                self._setup_tray()
                log_event("Close action: minimize to tray", "info")
            elif action == "exit" and self._tray_icon is not None:
                self._tray_icon.stop()
                self._tray_icon = None
                log_event("Close action: exit", "info")
            else:
                log_event(f"Close action: {action}", "info")

    # ── system tray ─────────────────────────────────────────────────────────

    @staticmethod
    def _create_tray_image():
        """Build a 64x64 tray icon (blue circle with clipboard symbol)."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 62, 62], fill="#3a7ebf")
        # Clipboard body
        draw.rectangle([18, 16, 46, 54], fill=None, outline="white", width=4)
        # Clipboard clip
        draw.rectangle([26, 8, 38, 18], fill="white", outline="white", width=2)
        # Horizontal lines
        draw.line([(24, 28), (40, 28)], fill="white", width=3)
        draw.line([(24, 36), (40, 36)], fill="white", width=3)
        draw.line([(24, 44), (36, 44)], fill="white", width=3)
        return img

    def _setup_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Show Window", self._on_tray_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_tray_quit),
        )
        self._tray_icon = pystray.Icon(
            "clipboard-sync-client",
            self._create_tray_image(),
            "Clipboard Sync — Client",
            menu,
        )
        threading.Thread(target=self._tray_icon.run, daemon=True).start()
        log_event("System tray icon active", "info")

    def _on_tray_show(self) -> None:
        """Called from pystray background thread — dispatch to main thread."""
        self.root.after(0, self._show_window)

    def _on_tray_quit(self) -> None:
        """Called from pystray background thread — dispatch to main thread."""
        self.root.after(0, self._quit_app)

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ── shutdown ─────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        """Window close button → minimize to tray or exit, per settings."""
        if self._config.get("close_action") == "tray" and self._tray_icon is not None:
            log_event("Minimized to tray", "info")
            self.root.withdraw()
        else:
            self._quit_app()

    def _quit_app(self) -> None:
        """Full application shutdown."""
        log_event("Shutting down…", "warn")
        self._stop_event.set()

        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass

        with self._sock_lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

        _save_config(
            self._ip_var.get().strip(),
            self._auto_var.get(),
            self._config.get("theme", "dark"),
            self._config.get("close_action", "tray"),
        )
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


# ── entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    ClipboardClientGUI().run()
