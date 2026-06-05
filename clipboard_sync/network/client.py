"""
clipboard_sync.client_network  —  ClientConnection class.

Manages a single client socket to a clipboard-sync server.
Does not import tkinter; all UI updates happen via thread-safe
queues (log.py) or plain callbacks provided by app.py.
"""

import socket
import threading
import time

import pyperclip

from clipboard_sync.core.log import log_event, status_queue
from clipboard_sync.core.config import PORT, RECONNECT_DELAY, FRAME_DELIMITER


class ClientConnection:
    """Manages a single client socket to a clipboard-sync server.

    Parameters
    ----------
    callbacks : dict
        ``on_connected``, ``on_disconnected``, ``on_connecting`` —
        each called from a background thread (the caller should dispatch
        to the main thread if needed via ``root.after(0, ...)``).
    """

    def __init__(self, callbacks: dict) -> None:
        self._callbacks = callbacks
        self._sock: socket.socket | None = None
        self._sock_lock = threading.Lock()
        self._connected = False
        self._stop_event = threading.Event()
        self._last_sent = ""

    # -- public API -----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_sent(self) -> str:
        return self._last_sent

    @last_sent.setter
    def last_sent(self, value: str) -> None:
        self._last_sent = value

    def start(self, server_ip: str, auto_reconnect: bool) -> None:
        """Begin connecting.  Spawns the connect-loop thread."""
        self._stop_event.clear()
        self._callbacks.get("on_connecting", lambda: None)()
        status_queue.put(("#ff9800", "Connecting…"))
        log_event(f"Connecting to {server_ip}:{PORT}…", "info")

        threading.Thread(
            target=self._connect_loop,
            args=(server_ip, auto_reconnect), daemon=True,
        ).start()

    def stop(self) -> None:
        """Disconnect and stop reconnection attempts."""
        log_event("Disconnecting…", "warn")
        self._stop_event.set()
        self._close_socket()
        self._connected = False
        self._callbacks.get("on_disconnected", lambda: None)()
        status_queue.put(("#f44336", "Disconnected"))

    def send_text(self, text: str) -> None:
        """Send text to the server (no-op if not connected)."""
        with self._sock_lock:
            if self._sock is None:
                return
            try:
                self._sock.sendall(
                    (text + FRAME_DELIMITER).encode("utf-8"))
            except Exception:
                pass

    def reset_stop_event(self) -> None:
        """Create a fresh stop_event (used after mode switch)."""
        self._stop_event = threading.Event()

    # -- internals ------------------------------------------------------------

    def _close_socket(self) -> None:
        with self._sock_lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def _connect_loop(self, server_ip: str, auto_reconnect: bool) -> None:
        while not self._stop_event.is_set():
            conn: socket.socket | None = None
            try:
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                conn.settimeout(3)
                conn.connect((server_ip, PORT))

                with self._sock_lock:
                    self._sock = conn
                self._connected = True

                log_event("Connected!", "success")
                status_queue.put(("#4caf50", "Connected"))
                self._callbacks.get("on_connected", lambda: None)()

                try:
                    self._last_sent = pyperclip.paste()
                except Exception:
                    self._last_sent = ""

                self._receive_loop(conn)

                if self._stop_event.is_set():
                    break

                log_event("Connection lost", "error")
                status_queue.put(("#f44336", "Connection lost"))
                self._callbacks.get("on_disconnected", lambda: None)()

            except ConnectionRefusedError:
                if self._stop_event.is_set():
                    break
                log_event("Connection refused — is the server running?",
                          "error")
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
                self._callbacks.get("on_disconnected", lambda: None)()
                status_queue.put(("#f44336", "Disconnected"))
                return

            log_event(f"Retrying in {RECONNECT_DELAY}s…", "warn")
            status_queue.put(
                ("#ff9800", f"Retrying in {RECONNECT_DELAY}s…"))
            self._callbacks.get("on_connecting", lambda: None)()

            for _ in range(RECONNECT_DELAY * 2):
                if self._stop_event.is_set():
                    return
                time.sleep(0.5)

        self._callbacks.get("on_disconnected", lambda: None)()
        status_queue.put(("#f44336", "Disconnected"))

    def _receive_loop(self, conn: socket.socket) -> None:
        """Blocking receive loop.  Exits on disconnect / stop_event."""
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
                while FRAME_DELIMITER in buffer:
                    msg, buffer = buffer.split(FRAME_DELIMITER, 1)
                    if msg:
                        log_event(
                            f"Received from server ({len(msg)} chars)",
                            "info",
                        )
                        pyperclip.copy(msg)
                        self._last_sent = msg
        except Exception:
            pass
