"""
clipboard_sync.network  —  Client and server networking classes.

ClientConnection  — manages a single client socket to the server.
ServerHost        — manages the server socket and all client connections.

Neither class imports tkinter; all UI updates happen via thread-safe
queues (log.py) or plain callbacks provided by app.py.
"""

import socket
import threading
import time

import pyperclip

from clipboard_sync.log import log_event, status_queue
from clipboard_sync.config import PORT, POLL_INTERVAL, RECONNECT_DELAY, FRAME_DELIMITER


# ── utility ──────────────────────────────────────────────────────────────────

def get_local_ip() -> str:
    """Discover the primary LAN IP by connecting to a public address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ═══════════════════════════════════════════════════════════════════════════════
# CLIENT CONNECTION
# ═══════════════════════════════════════════════════════════════════════════════

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
        """Begin connecting.  Spawns connect-loop + clipboard-watcher threads."""
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


# ═══════════════════════════════════════════════════════════════════════════════
# SERVER HOST
# ═══════════════════════════════════════════════════════════════════════════════

class ServerHost:
    """Hosts a clipboard-sync server: accept clients, relay clipboard text.

    Parameters
    ----------
    callbacks : dict
        ``on_client_count_changed(count)`` — called when a client
        connects or disconnects (from a background thread).
    """

    def __init__(self, callbacks: dict) -> None:
        self._callbacks = callbacks
        self.server_sock: socket.socket | None = None
        self.clients: dict[socket.socket, bool] = {}
        self.clients_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._last_sent = ""

    # -- public API -----------------------------------------------------------

    @property
    def last_sent(self) -> str:
        return self._last_sent

    @last_sent.setter
    def last_sent(self, value: str) -> None:
        self._last_sent = value

    def start(self) -> None:
        """Bind, listen, and start accept + clipboard-watcher threads."""
        self._stop_event.clear()

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        local_ip = get_local_ip()
        try:
            self.server_sock.bind(("0.0.0.0", PORT))
            self.server_sock.listen(5)
        except OSError as e:
            log_event(f"Failed to bind port {PORT}: {e}", "error")
            status_queue.put(("#f44336", f"Error: {e}"))
            return

        log_event(f"Server started on {local_ip}:{PORT}", "success")
        status_queue.put(("#ff9800", f"Listening on {local_ip}:{PORT}"))

        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self) -> None:
        """Close server socket and all client connections."""
        self._stop_event.set()
        if self.server_sock is not None:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None
        with self.clients_lock:
            for conn in list(self.clients):
                try:
                    conn.close()
                except Exception:
                    pass
            self.clients.clear()

    def broadcast(self, text: str,
                  source_conn: socket.socket | None = None) -> None:
        """Send *text* to all connected clients except *source_conn*."""
        dead: list[socket.socket] = []
        payload = (text + FRAME_DELIMITER).encode("utf-8")

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
            log_event(
                f"Broadcast finished; {len(dead)} stale client(s) removed",
                "warn",
            )

    def reset_stop_event(self) -> None:
        """Create a fresh stop_event (used after mode switch)."""
        self._stop_event = threading.Event()

    # -- internals ------------------------------------------------------------

    def _register_client(self, conn: socket.socket) -> int:
        with self.clients_lock:
            self.clients[conn] = True
            return len(self.clients)

    def _unregister_client(self, conn: socket.socket) -> int:
        with self.clients_lock:
            self.clients.pop(conn, None)
            return len(self.clients)

    def _accept_loop(self) -> None:
        assert self.server_sock is not None

        while not self._stop_event.is_set():
            try:
                self.server_sock.settimeout(1.0)
                conn, addr = self.server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            log_event(f"Client connected: {addr[0]}", "success")
            n = self._register_client(conn)
            status_queue.put((
                "#4caf50",
                f"Listening — {n} client{'s' if n != 1 else ''} connected",
            ))
            self._callbacks.get("on_client_count_changed",
                                lambda c: None)(n)

            threading.Thread(
                target=self._handle_client, args=(conn, addr), daemon=True,
            ).start()

    def _handle_client(self, conn: socket.socket, addr: tuple) -> None:
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
                            f"Received from {addr[0]} ({len(msg)} chars)",
                            "info",
                        )
                        pyperclip.copy(msg)
                        self._last_sent = msg
                        self.broadcast(msg, source_conn=conn)
        except Exception:
            pass
        finally:
            conn.close()
            n = self._unregister_client(conn)
            log_event(f"Client disconnected: {addr[0]}", "warn")
            if n == 0:
                status_queue.put(("#ff9800", "Listening — 0 clients"))
            self._callbacks.get("on_client_count_changed",
                                lambda c: None)(n)
