"""
clipboard_client.py  —  Run this on the OTHER PC (connects to the server)
Requires: pip install pyperclip

What it does:
  - Connects to the server PC over your local WiFi
  - Watches your clipboard every 0.5 seconds
  - Sends changes to the server (which forwards to all other clients)
  - Receives clipboard updates from the server and applies them locally

Usage:
  1. Edit SERVER_IP below to match the IP shown when you ran the server
  2. python clipboard_client.py
"""

import socket
import threading
import time
import pyperclip
import sys

# ── EDIT THIS ──────────────────────────────────────────────
SERVER_IP = "192.168.1.XXX"   # <-- paste the IP shown by the server script
# ───────────────────────────────────────────────────────────

PORT = 5556
POLL_INTERVAL = 0.5
RECONNECT_DELAY = 5  # seconds before retry on disconnect

last_sent = ""
sock = None
sock_lock = threading.Lock()


def send_text(text):
    """Send clipboard text to server."""
    with sock_lock:
        if sock is None:
            return
        try:
            msg = (text + "\n---END---\n").encode("utf-8")
            sock.sendall(msg)
        except Exception:
            pass


def clipboard_watcher():
    """Poll local clipboard and send changes to server."""
    global last_sent
    last_sent = pyperclip.paste()
    while True:
        time.sleep(POLL_INTERVAL)
        try:
            current = pyperclip.paste()
        except Exception:
            continue
        if current != last_sent:
            last_sent = current
            if current.strip():
                print(f"  [→] Sending clipboard ({len(current)} chars)")
                send_text(current)


def receive_loop(conn):
    """Listen for clipboard updates from the server."""
    global last_sent
    buffer = ""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buffer += data.decode("utf-8", errors="replace")
            while "\n---END---\n" in buffer:
                msg, buffer = buffer.split("\n---END---\n", 1)
                if msg:
                    print(f"  [←] Received from server ({len(msg)} chars)")
                    pyperclip.copy(msg)
                    last_sent = msg
    except Exception:
        pass


def main():
    global sock, last_sent

    if SERVER_IP == "192.168.1.XXX":
        print("ERROR: Please edit SERVER_IP in this file first!")
        print("  Open clipboard_client.py and set SERVER_IP to the IP")
        print("  shown when you started clipboard_server.py on the other PC.")
        sys.exit(1)

    print("=" * 50)
    print("  Clipboard Sync  —  CLIENT")
    print("=" * 50)
    print(f"  Connecting to server: {SERVER_IP}:{PORT}")
    print()

    watcher = threading.Thread(target=clipboard_watcher, daemon=True)
    watcher.start()

    while True:
        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.connect((SERVER_IP, PORT))
            with sock_lock:
                sock = conn
            print(f"  [✓] Connected!")
            last_sent = pyperclip.paste()
            receive_loop(conn)
        except ConnectionRefusedError:
            print(f"  [!] Could not connect — is the server running? Retrying in {RECONNECT_DELAY}s...")
        except Exception as e:
            print(f"  [!] Connection lost ({e}). Retrying in {RECONNECT_DELAY}s...")
        finally:
            with sock_lock:
                sock = None
            try:
                conn.close()
            except Exception:
                pass
        time.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    main()
