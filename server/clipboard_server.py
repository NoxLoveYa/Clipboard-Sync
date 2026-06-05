"""
clipboard_server.py  —  Run this on ONE of your two PCs (the "host")
Requires: pip install pyperclip

What it does:
  - Watches your clipboard every 0.5 seconds
  - When it changes, broadcasts the new text to all connected clients
  - Also receives clipboard updates from clients and applies them locally

Usage:
  python clipboard_server.py
  (then run clipboard_client.py on the other PC)
"""

import socket
import threading
import time
import pyperclip
import sys

PORT = 5556
POLL_INTERVAL = 0.5  # seconds between clipboard checks


def get_local_ip():
    """Find the local WiFi IP (not 127.0.0.1, not VPN adapter)."""
    try:
        # Connect to a public address to discover which interface is used for LAN
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


clients = []
clients_lock = threading.Lock()

last_sent = ""


def broadcast(text, source_conn=None):
    """Send text to all connected clients except the one that sent it."""
    dead = []
    with clients_lock:
        for conn in clients:
            if conn is source_conn:
                continue
            try:
                msg = (text + "\n---END---\n").encode("utf-8")
                conn.sendall(msg)
            except Exception:
                dead.append(conn)
        for conn in dead:
            clients.remove(conn)


def handle_client(conn, addr):
    print(f"  [+] Client connected: {addr[0]}")
    with clients_lock:
        clients.append(conn)
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
                    print(f"  [←] Received from client ({len(msg)} chars)")
                    pyperclip.copy(msg)
                    global last_sent
                    last_sent = msg
                    broadcast(msg, source_conn=conn)
    except Exception:
        pass
    finally:
        with clients_lock:
            if conn in clients:
                clients.remove(conn)
        conn.close()
        print(f"  [-] Client disconnected: {addr[0]}")


def clipboard_watcher():
    """Poll local clipboard and broadcast any changes."""
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
                print(f"  [→] Broadcasting clipboard ({len(current)} chars)")
                broadcast(current)


def main():
    local_ip = get_local_ip()
    print("=" * 50)
    print("  Clipboard Sync  —  SERVER")
    print("=" * 50)
    print(f"  Listening on : {local_ip}:{PORT}")
    print(f"  Tell the other PC to connect to: {local_ip}")
    print("  Waiting for client...")
    print()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", PORT))
    except OSError as e:
        print(f"ERROR: Could not bind to port {PORT}: {e}")
        print(f"Try changing PORT at the top of this file to something else (e.g. 5557).")
        sys.exit(1)

    server.listen(5)

    watcher = threading.Thread(target=clipboard_watcher, daemon=True)
    watcher.start()

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
