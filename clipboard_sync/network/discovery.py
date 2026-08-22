"""
clipboard_sync.discovery  —  Zero-setup LAN discovery via UDP beacons.

The server broadcasts ``CLIPSYNC_V1|<hostname>|<tcp_port>|<uuid>`` to
255.255.255.255 every few seconds; clients listen on the same port and
report each newly seen server.  The instance UUID (persisted per machine)
lets listeners ignore their own beacons and dedupe repeats.
"""

import json
import os
import queue
import socket
import threading
import uuid

from clipboard_sync.core.config import (
    PORT, DISCOVERY_PORT, BEACON_INTERVAL, BEACON_MAGIC, INSTANCE_FILE,
    MODE_DIR,
)
from clipboard_sync.core.log import log_event

# Discovered servers land here as ``(ip,)`` tuples so the GUI can pick them
# up from the main thread — never touch tkinter from listener threads.
found_queue: "queue.Queue[tuple[str]]" = queue.Queue()


def get_instance_id() -> str:
    """Stable per-machine UUID so peers can ignore their own beacons."""
    os.makedirs(MODE_DIR, exist_ok=True)
    try:
        with open(INSTANCE_FILE) as f:
            return json.load(f)["id"]
    except Exception:
        pass
    iid = uuid.uuid4().hex
    try:
        with open(INSTANCE_FILE, "w") as f:
            json.dump({"id": iid}, f)
    except Exception:
        pass
    return iid


def parse_beacon(data: bytes) -> tuple[str, int, str] | None:
    """Return ``(hostname, tcp_port, instance_id)`` or None for junk."""
    try:
        magic, host, port, iid = data.decode("utf-8").split("|")
        if magic != BEACON_MAGIC:
            return None
        return host, int(port), iid
    except (UnicodeDecodeError, ValueError):
        return None


class DiscoveryBroadcaster:
    """Server side: periodically broadcasts this machine's beacon."""

    def __init__(self, instance_id: str | None = None,
                 tcp_port: int = PORT,
                 broadcast_addr: tuple = ("255.255.255.255", DISCOVERY_PORT)) -> None:
        self._id = instance_id or get_instance_id()
        self._port = tcp_port
        # ponytail: broadcast_addr param exists only so tests can aim at
        # 127.0.0.1; production always uses the default.
        self._addr = broadcast_addr
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._stop_event.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        msg = f"{BEACON_MAGIC}|{socket.gethostname()}|{self._port}|{self._id}".encode("utf-8")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            return
        while not self._stop_event.is_set():
            try:
                sock.sendto(msg, self._addr)
            except OSError:
                pass
            self._stop_event.wait(BEACON_INTERVAL)
        sock.close()


class DiscoveryListener:
    """Client side: listens for beacons, fires once per discovered server."""

    def __init__(self, on_found: callable,
                 instance_id: str | None = None) -> None:
        self._on_found = on_found          # (hostname, ip, tcp_port)
        self._ignore = instance_id or get_instance_id()
        self._seen: set[tuple[str, str]] = set()
        self._stop_event = threading.Event()

    @property
    def searching(self) -> bool:
        return not self._stop_event.is_set()

    def start(self) -> None:
        self._stop_event.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(0.5)
        except OSError as e:
            log_event(f"LAN discovery unavailable: {e}", "warn")
            return

        while not self._stop_event.is_set():
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = parse_beacon(data)
            if parsed is None:
                continue
            hostname, tcp_port, iid = parsed
            if iid == self._ignore:
                continue
            key = (iid, addr[0])
            if key in self._seen:
                continue
            log_event(
                f"Discovered Clipboard Sync server '{hostname}' "
                f"at {addr[0]}:{tcp_port}", "success")
            found_queue.put((addr[0],))
            self._seen.add(key)
        sock.close()
