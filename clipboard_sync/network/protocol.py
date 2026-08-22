"""
clipboard_sync.protocol  —  Protocol v2 wire format.

Frame layout: 4-byte big-endian payload length | 1-byte type | payload.

Types:
    0x01 TEXT          UTF-8 string
    0x02 IMAGE         PNG bytes
    0x03 FILE_MANIFEST UTF-8 JSON {"id", "files": [{"name", "size"}, ...]}
    0x04 FILE_CHUNK    raw bytes, sequential, belongs to the open manifest
"""

import json
import os
import socket
import struct
import uuid

from clipboard_sync.core.config import CHUNK_SIZE

TEXT = 0x01
IMAGE = 0x02
FILE_MANIFEST = 0x03
FILE_CHUNK = 0x04

# ponytail: hard sanity cap on a single frame; per-user cap is enforced at
# send time (max_transfer_mb). Raise both together if transfers grow.
MAX_FRAME_BYTES = 200 * 1024 * 1024


class ProtocolError(Exception):
    """Raised for malformed / oversized frames (incompatible peer)."""


def encode(mtype: int, payload: bytes) -> bytes:
    return struct.pack(">IB", len(payload), mtype) + payload


def iter_messages(sock: socket.socket, stop_event):
    """Yield ``(mtype, payload)`` for each complete frame received.

    Tolerates short reads and the 0.5s recv-timeout used for stop checks.
    Raises ProtocolError on garbage (e.g. an old v1 peer).
    """
    buf = bytearray()
    sock.settimeout(0.5)
    while not stop_event.is_set():
        try:
            data = sock.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            return
        if not data:
            return
        buf += data
        while len(buf) >= 5:
            length, mtype = struct.unpack_from(">IB", buf)
            if length > MAX_FRAME_BYTES:
                raise ProtocolError(f"frame too large ({length} bytes)")
            if len(buf) < 5 + length:
                break
            payload = bytes(buf[5:5 + length])
            del buf[:5 + length]
            yield mtype, payload


def frames_for_snapshot(snapshot) -> tuple[list[bytes], int]:
    """Serialize a clipboard_io Snapshot into frames to send.

    Returns ``(frames, total_bytes)``.  Raises OSError if a file vanished.
    """
    if snapshot.kind == "text":
        payload = snapshot.text.encode("utf-8")
        return [encode(TEXT, payload)], len(payload)

    if snapshot.kind == "image":
        return [encode(IMAGE, snapshot.png)], len(snapshot.png)

    # files — one manifest covers the whole multi-file selection
    files = []
    for p in snapshot.paths:
        files.append({"name": os.path.basename(p),
                      "size": os.path.getsize(p)})
    manifest = {"id": uuid.uuid4().hex, "files": files}
    frames = [encode(FILE_MANIFEST,
                     json.dumps(manifest).encode("utf-8"))]
    for p in snapshot.paths:
        with open(p, "rb") as fh:
            while chunk := fh.read(CHUNK_SIZE):
                frames.append(encode(FILE_CHUNK, chunk))
    total = sum(f["size"] for f in files)
    return frames, total
