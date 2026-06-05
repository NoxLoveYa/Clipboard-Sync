"""
clipboard_sync.server_network  —  ServerHost class.

Manages the server socket and all client connections.
Does not import tkinter; all UI updates happen via thread-safe
queues (log.py) or plain callbacks provided by app.py.
"""

import socket
import threading

import pyperclip

from clipboard_sync.core.log import log_event, status_queue
from clipboard_sync.core.config import PORT, FRAME_DELIMITER, get_local_ip


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
        """Bind, listen, and start the accept-loop thread."""
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
