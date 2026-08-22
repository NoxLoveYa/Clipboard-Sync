"""
clipboard_sync.receiver  —  Applies inbound protocol messages locally.

One Inbox per connection: writes received files to disk, places text /
images / file lists on the local clipboard, and returns the echo
fingerprint that the watcher should suppress.
"""

import json
import os
from pathlib import Path

from clipboard_sync.core import clipboard_io
from clipboard_sync.core.config import RECEIVED_FILES_DIR
from clipboard_sync.core.log import log_event
from clipboard_sync.network.protocol import TEXT, IMAGE, FILE_MANIFEST, FILE_CHUNK

_PROGRESS_STEP = 4 * 1024 * 1024  # log every ~4 MB


class Inbox:
    """Assembles inbound messages onto the local machine."""

    def __init__(self, dest_dir: str = RECEIVED_FILES_DIR) -> None:
        self._dir = Path(dest_dir)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log_event(f"Cannot create {self._dir}: {e}", "error")
            self._dir = None
        self.reset()

    def reset(self) -> None:
        self._queue: list[dict] = []       # remaining {"name","size"}
        self._fh = None
        self._path: Path | None = None
        self._remaining = 0
        self._received = 0
        self._declared_total = 0
        self._next_log = _PROGRESS_STEP
        self._paths: list[str] = []

    def close(self) -> None:
        """Connection dropped — discard any partially written file."""
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            try:
                os.unlink(self._path)
            except Exception:
                pass
        self.reset()

    # ── message entry point ──────────────────────────────────────────────

    def feed(self, mtype: int, payload: bytes) -> tuple[str | None, str | None]:
        """Process one message. Returns ``(description, echo_fingerprint)``;
        either may be None (e.g. mid-file-transfer chunks)."""
        if mtype == TEXT:
            text = payload.decode("utf-8", errors="replace")
            return f"text ({len(text)} chars)", clipboard_io.write_text(text)

        if mtype == IMAGE:
            fp = clipboard_io.write_image(payload)
            if fp is None and not clipboard_io.HAS_WIN32:
                raise RuntimeError("pywin32 missing — cannot receive images")
            return f"image ({len(payload) // 1024} KB)", fp

        if mtype == FILE_MANIFEST:
            return self._start_manifest(json.loads(payload))

        if mtype == FILE_CHUNK:
            return self._chunk(payload)

        raise ValueError(f"unknown message type {mtype}")

    # ── file assembly ────────────────────────────────────────────────────

    def _start_manifest(self, manifest: dict) -> tuple[str | None, str | None]:
        self.reset()
        files = manifest.get("files") or []
        total = sum(int(f["size"]) for f in files)
        if total > 200 * 1024 * 1024:
            # ponytail: matches protocol.MAX_FRAME_BYTES sanity cap; the
            # user-facing cap (max_transfer_mb) is enforced on the sender.
            raise ValueError(f"transfer too large ({total // 1048576} MB)")
        n = len(files)
        label = f"{n} file(s)" if n != 1 else f"'{files[0]['name']}'"
        self._queue = list(files)
        self._declared_total = total
        if total >= _PROGRESS_STEP:
            log_event(f"Receiving {label} ({total // 1048576} MB)…", "info")
            desc = None
        else:
            desc = f"file transfer: {label} ({total} bytes)"
        self._open_next()
        return desc, None

    def _open_next(self) -> None:
        entry = self._queue.pop(0)
        path = self._unique(entry["name"])
        self._fh = open(path, "wb")
        self._path = path
        self._remaining = int(entry["size"])

    def _chunk(self, payload: bytes) -> tuple[str | None, str | None]:
        if self._fh is None:
            raise ValueError("file chunk without an open manifest")
        if len(payload) > self._remaining:
            raise ValueError("chunk overruns declared file size")
        self._fh.write(payload)
        self._remaining -= len(payload)
        self._received += len(payload)

        if self._received >= self._next_log and \
                self._received < self._declared_total:
            log_event(f"Receiving files… "
                      f"{self._received // 1048576}/{self._declared_total // 1048576} MB",
                      "info")
            self._next_log += _PROGRESS_STEP

        if self._remaining == 0:
            self._fh.close()
            self._fh = None
            self._paths.append(str(self._path))
            if self._queue:
                self._open_next()
                return None, None

            desc = f"{len(self._paths)} file(s) → {self._dir}"
            paths = self._paths
            self.reset()
            return desc, clipboard_io.write_files(paths)

        return None, None

    def _unique(self, name: str) -> Path:
        base = self._dir / name
        if not base.exists():
            return base
        stem, ext = base.stem, base.suffix
        i = 2
        while True:
            cand = self._dir / f"{stem} ({i}){ext}"
            if not cand.exists():
                return cand
            i += 1
