"""
clipboard_sync.watcher  —  Clipboard polling in a background thread.

Calls ``on_change(text)`` when the clipboard content differs from
the last observed value.  Safe to start/stop from the main thread.
"""

import threading
import time

import pyperclip

from clipboard_sync.core.log import log_event
from clipboard_sync.core.config import POLL_INTERVAL


class ClipboardWatcher:
    """Polls the clipboard on a background thread and fires a callback
    when the content changes.

    Parameters
    ----------
    on_change : callable
        Called with the new clipboard text (str) from the watcher thread.
    get_mode_label : callable
        Called to get a log label like ``"server"`` or ``"client"``
        (used for log messages only).
    """

    def __init__(self, on_change: callable,
                 get_mode_label: callable) -> None:
        self._on_change = on_change
        self._get_mode_label = get_mode_label
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

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
        last_sent = ""
        try:
            last_sent = pyperclip.paste()
        except Exception:
            pass

        while self._active:
            time.sleep(POLL_INTERVAL)
            if not self._active:
                return
            try:
                current = pyperclip.paste()
            except Exception:
                continue
            if current != last_sent and current.strip():
                last_sent = current
                label = self._get_mode_label()
                if label == "server":
                    log_event(
                        f"Broadcasting clipboard ({len(current)} chars)",
                        "info",
                    )
                else:
                    log_event(
                        f"Clipboard changed ({len(current)} chars) — sending",
                        "success",
                    )
                self._on_change(current)
