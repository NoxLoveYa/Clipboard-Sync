"""
clipboard_sync.watcher  —  Clipboard polling in a background thread.

Polls all clipboard content kinds (text / image / files) via
clipboard_io.read_snapshot() and fires ``on_change(snapshot)`` when the
content fingerprint differs from the last observed value and is not the
echo of something we just received.  Safe to start/stop from any thread.
"""

import threading
import time

from clipboard_sync.core import clipboard_io
from clipboard_sync.core.config import POLL_INTERVAL
from clipboard_sync.core.log import log_event


def _human(n: int) -> str:
    return f"{n // 1024} chars" if n < 1048576 else f"{n / 1048576:.1f} MB"


class ClipboardWatcher:
    """Polls the clipboard on a background thread and fires a callback
    when its content changes.

    Parameters
    ----------
    on_change : callable
        Called with a ``clipboard_io.Snapshot`` from the watcher thread.
    get_mode_label : callable
        Called to get a log label like ``"server"`` or ``"client"``
        (used for log messages only).
    """

    def __init__(self, on_change: callable,
                 get_mode_label: callable) -> None:
        self._on_change = on_change
        self._get_mode_label = get_mode_label
        self._active = False
        self._suppressed_fp: str | None = None

    @property
    def active(self) -> bool:
        return self._active

    def suppress_next(self, fingerprint: str) -> None:
        """Skip one watcher fire for *fingerprint* (echo guard). Called
        after received content is placed on the local clipboard."""
        self._suppressed_fp = fingerprint

    def start(self) -> None:
        """Begin watching the clipboard in a daemon thread."""
        if self._active:
            return
        self._active = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        """Signal the watcher thread to exit."""
        self._active = False

    def _run(self) -> None:
        last_fp = self._baseline()
        while self._active:
            time.sleep(POLL_INTERVAL)
            if not self._active:
                return
            try:
                snap = clipboard_io.read_snapshot()
            except Exception:
                continue
            if snap is None:
                continue
            fp = clipboard_io.fingerprint(snap)
            if fp == last_fp:
                continue
            last_fp = fp  # seen it either way — never re-fire for same fp
            if fp == self._suppressed_fp:
                self._suppressed_fp = None  # echo of received content
                continue
            log_event(
                f"Clipboard changed: {snap.kind} "
                f"({_human(snap.total_bytes)}) — sending",
                "success",
            )
            self._on_change(snap)

    def _baseline(self) -> str | None:
        """Fingerprint the clipboard at startup so we don't fire on boot."""
        try:
            snap = clipboard_io.read_snapshot()
        except Exception:
            return None
        if snap is None or (snap.kind == "text" and not snap.text.strip()):
            return None
        return clipboard_io.fingerprint(snap)
