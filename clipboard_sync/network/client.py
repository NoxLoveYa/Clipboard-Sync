"""
clipboard_sync.client_network  —  ClientConnection class.

Manages a single client socket to a clipboard-sync server (protocol v2:
length-prefixed binary frames).  Does not import tkinter; all UI updates
happen via thread-safe queues (log.py) or plain callbacks provided by
app.py.
"""

import socket
import threading
import time

from clipboard_sync.core.log import log_event, status_queue
from clipboard_sync.core.config import PORT, RECONNECT_DELAY, RECEIVED_FILES_DIR
from clipboard_sync.core.receiver import Inbox
from clipboard_sync.network.protocol import iter_messages, ProtocolError


class ClientConnection:
    """Manages a single client socket to a clipboard-sync server.

    Parameters
    ----------
    callbacks : dict
        ``on_connected``, ``on_disconnected``, ``on_connecting`` and
        ``on_remote_applied(fingerprint)`` — each called from a background
        thread (the caller should dispatch to the main thread if needed).
    """

    def __init__(self, callbacks: dict) -> None:
        self._callbacks = callbacks
        self._sock: socket.socket | None = None
        self._sock_lock = threading.Lock()
        self._connected = False
        self._stop_event = threading.Event()
        self._reconnect_delay = RECONNECT_DELAY

    # -- public API -----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def reconnect_delay(self) -> int:
        """Seconds to wait between reconnect attempts (read each retry)."""
        return self._reconnect_delay

    @reconnect_delay.setter
    def reconnect_delay(self, value: int) -> None:
        self._reconnect_delay = max(1, int(value))

    def start(self, server_ip: str, auto_reconnect: bool,
              reconnect_delay: int | None = None) -> None:
        """Begin connecting.  Spawns the connect-loop thread."""
        if reconnect_delay is not None:
            self.reconnect_delay = reconnect_delay
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

    def send_frames(self, frames: list[bytes]) -> bool:
        """Send pre-encoded frames to the server (no-op if not connected)."""
        with self._sock_lock:
            if self._sock is None:
                return False
            try:
                for frame in frames:
                    self._sock.sendall(frame)
                return True
            except Exception:
                return False

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
        # capture THIS generation's stop event — reset_stop_event() swaps in
        # a fresh Event on mode switch, and reading self._stop_event
        # dynamically would make an old retry loop see "not stopping" forever.
        stop = self._stop_event
        while not stop.is_set():
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

                self._receive_loop(conn)

                if stop.is_set():
                    break

                log_event("Connection lost", "error")
                status_queue.put(("#f44336", "Connection lost"))
                self._callbacks.get("on_disconnected", lambda: None)()

            except ConnectionRefusedError:
                if stop.is_set():
                    break
                log_event("Connection refused — is the server running?",
                          "error")
            except socket.timeout:
                if stop.is_set():
                    break
                log_event("Connection timed out", "warn")
            except OSError as e:
                if stop.is_set():
                    break
                log_event(f"Connection error: {e}", "error")
            except Exception as e:
                if stop.is_set():
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

            if stop.is_set():
                break

            if not auto_reconnect:
                self._callbacks.get("on_disconnected", lambda: None)()
                status_queue.put(("#f44336", "Disconnected"))
                return

            delay = self._reconnect_delay
            log_event(f"Retrying in {delay}s…", "warn")
            status_queue.put(
                ("#ff9800", f"Retrying in {delay}s…"))
            self._callbacks.get("on_connecting", lambda: None)()

            deadline = time.monotonic() + max(1, int(delay))
            while not stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.25, remaining))

        self._callbacks.get("on_disconnected", lambda: None)()
        status_queue.put(("#f44336", "Disconnected"))

    def _receive_loop(self, conn: socket.socket) -> None:
        """Blocking receive loop.  Exits on disconnect / stop_event."""
        inbox = Inbox(RECEIVED_FILES_DIR)
        try:
            for mtype, payload in iter_messages(conn, stop):
                try:
                    desc, fp = inbox.feed(mtype, payload)
                except Exception as e:
                    log_event(f"Failed to apply received data: {e}", "error")
                    continue
                if fp is not None:
                    self._callbacks.get(
                        "on_remote_applied", lambda f: None)(fp)
                if desc:
                    log_event(f"Received {desc}", "info")
        except ProtocolError as e:
            log_event(f"Incompatible peer — update both machines ({e})",
                      "error")
        except Exception:
            pass
        finally:
            inbox.close()
