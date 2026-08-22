"""
clipboard_sync.config  —  Constants, config paths, mode persistence, and
                          network utilities.

No imports from other clipboard_sync modules (pure leaf).
"""

import json
import os
import socket

# ── network constants ───────────────────────────────────────────────────────

PORT = 5556
POLL_INTERVAL = 0.5
RECONNECT_DELAY = 5
MAX_LOG_LINES = 500
FRAME_DELIMITER = "\n---END---\n"

# ── config file paths ───────────────────────────────────────────────────────

CLIENT_CONFIG_PATH = os.path.expanduser("~/.clipboardsync.json")
SERVER_CONFIG_PATH = os.path.expanduser("~/.clipboardsync-server.json")
MODE_DIR = os.path.expanduser("~/.clipboard-sync")
MODE_FILE = os.path.join(MODE_DIR, "mode.json")

# ── mode persistence ────────────────────────────────────────────────────────


def load_mode() -> str:
    """Return 'client' or 'server'.  Defaults to 'client'."""
    try:
        with open(MODE_FILE) as f:
            return json.load(f).get("mode", "client")
    except (FileNotFoundError, json.JSONDecodeError):
        return "client"


def save_mode(mode: str) -> None:
    """Persist the current mode choice."""
    os.makedirs(MODE_DIR, exist_ok=True)
    with open(MODE_FILE, "w") as f:
        json.dump({"mode": mode}, f)


# ── mode-aware config helpers ───────────────────────────────────────────────


def config_path(mode: str) -> str:
    """Return the JSON config path for the given mode."""
    return SERVER_CONFIG_PATH if mode == "server" else CLIENT_CONFIG_PATH


def config_defaults(mode: str) -> dict:
    """Return the default config dict for the given mode."""
    if mode == "server":
        return {"close_action": "tray", "theme": "dark",
                "autostart": False}
    return {
        "server_ip": "", "auto_reconnect": True,
        "last_connected_ip": "",
        "reconnect_delay": 5,
        "close_action": "tray", "theme": "dark",
        "autostart": False,
    }


# ── network utility ─────────────────────────────────────────────────────────


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
