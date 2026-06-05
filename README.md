# Clipboard Sync

Sync your clipboard across multiple Windows PCs over your local network. Copy on one machine, paste on any other — text only.

![Preview](https://github.com/NoxLoveYa/Clipboard-Sync/blob/8f39c58eab442fc41e44078c821e5293bce9cfbc/image.png?raw=true)

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

### 2. Launch the app

```bash
python clipboard_sync.py
```

The app starts in **Client** mode by default. Use the dropdown in the header bar to switch to **Server** mode.

### 3. Start the server

On the machine acting as the relay, switch the mode dropdown to **SERVER**. The window shows the server's IP — note this for clients. The server starts listening automatically.

### 4. Connect clients

On every other machine, enter the server's IP in **Client** mode and click **Connect**.

### 5. Use it

Copy text on any machine — it appears on everyone else's clipboard within ~0.5 seconds.

## Building a Standalone `.exe`

```bash
pip install pyinstaller
python build.py
```

Output: `dist/ClipboardSync.exe` — self-contained, double-click to run.

## Project Structure

```
├── clipboard_sync.py           Entry point
├── clipboard_sync/             Core package
│   ├── __init__.py               Package exports
│   ├── log.py                    Thread-safe logging queues
│   ├── config.py                 Constants, config paths, mode persistence
│   ├── network.py                ClientConnection + ServerHost classes
│   ├── tray.py                   System-tray icon (TrayManager)
│   ├── ui.py                     GUI widgets (AppUI)
│   └── app.py                    Orchestrator (ClipboardSyncGUI)
├── settings.py                 Shared config helpers & settings dialog
├── build.py                    PyInstaller build script
├── requirements.txt            Python dependencies
└── dist/                       Built .exe (gitignored)
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

- **Mode switching** — toggle between Client and Server from the header dropdown at runtime
- **Dark/Light/System theme** — configurable in Settings
- **Status indicator** — coloured dot: green (connected), yellow (connecting), red (disconnected)
- **Activity log** — colour-coded entries with timestamps, auto-scrolls
- **Copy IP** button (server mode) — copies the server's LAN IP to clipboard
- **Auto-reconnect** checkbox (client mode) — persists across sessions
- **System tray** — minimize to tray or exit on close (configurable)
- **Config save** — settings and last-used mode saved automatically

## Requirements

- **Python 3.8+**
- **Windows, macOS, or Linux** — tested on Windows 11. CustomTkinter and pyperclip work on all three.
- **Local network** — all machines must be on the same LAN (or reachable via IP).

## License

MIT
