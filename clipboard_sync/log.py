"""
clipboard_sync.log  —  Thread-safe logging and status queues.

Importable from any module, including background threads.
"""

import queue
import time

# ── thread-safe queues ──────────────────────────────────────────────────────

log_queue: "queue.Queue[tuple[str, str, str]]" = queue.Queue()
status_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()


def log_event(message: str, level: str = "info") -> None:
    """Push a timestamped log entry.  Safe to call from any thread."""
    log_queue.put((time.strftime("%H:%M:%S"), message, level))
