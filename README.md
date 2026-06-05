# Clipboard Sync

Sync your clipboard across multiple Windows PCs over your local network. Copy on one machine, paste on any other — text only.

## How It Works

One machine runs as the **server**. Everyone else (including the server machine) runs the **client**. When any machine copies text, it's broadcast to all connected machines.

```
┌──────────┐     clipboard      ┌──────────┐     clipboard      ┌──────────┐
│ Client A │ ──────────────────>│  Server  │<────────────────── │ Client B │
└──────────┘                    └──────────┘                    └──────────┘
       ▲                             │                               │
       │        clipboard broadcast  │  clipboard broadcast          │
       └─────────────────────────────┘───────────────────────────────┘
```

- **Star topology** — all clients connect to the server; the server relays.
- **No echo** — a client doesn't receive its own clipboard change back.
- **Text only** — plain text. Images, files, and rich formatting are not supported.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the server

On the machine that will act as the relay:

```bash
cd server
python clipboard_server_gui.py
```

The server window shows its IP address — note this for the clients.

### 3. Start the client

On every other machine (or the same machine in a second window):

```bash
cd client
python clipboard_client_gui.py
```

Enter the server's IP address and click **Connect**.

### 4. Use it

Copy text on any machine — it appears on everyone else's clipboard within ~0.5 seconds.

## Running Without the GUI (Headless / CLI)

The original terminal-only scripts still work:

```bash
# On the server machine
cd server
python clipboard_server.py

# On client machines — first edit SERVER_IP in clipboard_client.py
cd client
python clipboard_client.py
```

## Building Standalone `.exe` Files

You can ship the apps as single `.exe` files — no Python installation needed.

```bash
pip install pyinstaller
python build.py
```

Output lands in `dist/`:

```
dist/
    ClipboardSync-Server.exe   (12.6 MB)
    ClipboardSync-Client.exe   (12.6 MB)
```

Each `.exe` is self-contained: double-click to run, uninstall by deleting the file.

## Project Structure

```
├── build.py                 Build script (PyInstaller)
├── requirements.txt         Python dependencies
├── server/
│   ├── clipboard_server.py       Original CLI server
│   └── clipboard_server_gui.py   GUI server (CustomTkinter)
├── client/
│   ├── clipboard_client.py       Original CLI client
│   └── clipboard_client_gui.py   GUI client (CustomTkinter)
└── dist/                         Built .exe files (gitignored)
```

## Technical Details

| Detail | Value |
|---|---|
| Protocol | Raw TCP, port `5556` |
| Message framing | UTF-8 text + `\n---END---\n` delimiter |
| Poll interval | 0.5 seconds |
| GUI framework | CustomTkinter (dark theme) |
| Clipboard access | pyperclip |
| Auto-reconnect | Enabled by default (client), 5-second retry |

### GUI Features

- **Dark theme** — permanent, no toggle
- **Status indicator** — coloured dot: green (connected), yellow (connecting), red (disconnected)
- **Activity log** — colour-coded entries with timestamps, auto-scrolls
- **Copy IP** button (server) — copies the server's LAN IP to clipboard
- **Auto-reconnect** checkbox (client) — persists across sessions
- **Cancel** button (client) — stop connecting or cancel a reconnect attempt
- **Config save** — last-used IP and auto-reconnect preference saved to `~/.clipboardsync.json`
- **Graceful shutdown** — closes sockets cleanly on window close

## Requirements

- **Python 3.8+**
- **Windows, macOS, or Linux** — tested on Windows 11. CustomTkinter and pyperclip work on all three.
- **Local network** — all machines must be on the same LAN (or reachable via IP).

## License

MIT
