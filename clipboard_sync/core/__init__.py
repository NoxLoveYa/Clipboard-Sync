"""
clipboard_sync.core  —  Foundational modules: logging, config, clipboard watcher.
"""

from clipboard_sync.core.log import log_event, log_queue, status_queue
from clipboard_sync.core.config import (
    PORT, POLL_INTERVAL, RECONNECT_DELAY, MAX_LOG_LINES, FRAME_DELIMITER,
    CLIENT_CONFIG_PATH, SERVER_CONFIG_PATH, MODE_DIR, MODE_FILE,
    load_mode, save_mode, config_path, config_defaults, get_local_ip,
)
from clipboard_sync.core.watcher import ClipboardWatcher
