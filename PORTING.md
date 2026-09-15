# Cross-Platform Port — Windows / macOS / Linux

Goal: any platform can be server, any platform can connect to any platform. Protocol v2 (TCP 5556 + UDP 5557) is already pure-Python and needs **no changes** — all work is OS integration.

## 1. What already works everywhere

| Area | Status |
|---|---|
| Protocol (`network/protocol.py`), client/server, discovery broadcast | pure stdlib sockets — universal, no change |
| Text clipboard (`pyperclip`) | Win/Mac/Linux already |
| GUI (`customtkinter`) | Win/Mac/Linux already |
| Config paths (`~/.clipboardsync*.json`), `Downloads/ClipboardSync` receive dir | `expanduser` + `os.path.join` — universal |
| Tray (`pystray` + Pillow) | mostly universal (see §3) |

## 2. Blockers (all of them)

| # | File | Windows-only code | Fix |
|---|---|---|---|
| 1 | `clipboard_sync/core/clipboard_io.py` | `win32clipboard` (CF_DIB images, CF_HDROP files); fallback is text-only | Platform backend abstraction (see §4) |
| 2 | `requirements.txt` | `pywin32>=306` unconditional → `pip install` fails on Mac/Linux | Environment markers (see §3) |
| 3 | `settings.py` | `winreg` Run-key autostart; checkbox says "Start with Windows" | Per-OS autostart (see §5) |
| 4 | `build.py` | Outputs only `dist/ClipboardSync.exe` | Per-OS PyInstaller targets (see §6) |
| 5 | `settings.py`, `app.py`, UI fonts | `"Segoe UI"` font, "Windows Firewall" string, `pythonw.exe` path | Font fallback + string tweaks (see §7) |

## 3. Dependencies

```txt
# requirements.txt
customtkinter>=5.2.0
pyperclip>=1.8.0
pystray>=0.19.0
Pillow>=10.0.0
pywin32>=306; sys_platform == "win32"
pyobjc-framework-Cocoa>=10.0; sys_platform == "darwin"
# Linux: no new pip dep — rely on system xclip (X11) or wl-clipboard (Wayland),
# detected at runtime. Document: apt install xclip / wl-clipboard
```

Linux tray note: `pystray` needs AppIndicator (`libappindicator3-1`) on GNOME; if import fails, `HAS_TRAY=False` path already handles it (app runs without tray).

## 4. `clipboard_io.py` — the real work

Introduce one tiny dispatcher; keep the `Snapshot` / `fingerprint` / `read_snapshot` / `write_*` signatures unchanged so `watcher.py`, `receiver.py`, `app.py` don't change.

```python
# clipboard_io.py
import platform
_OS = platform.system()  # "Windows" | "Darwin" | "Linux"
```

- **Text:** keep `pyperclip` everywhere (no change).
- **Images:**
  - Windows: keep existing CF_DIB code.
  - macOS: read via `PIL.ImageGrab.grabclipboard()` (works); write via `AppKit.NSPasteboard` (`pyobjc-framework-Cocoa`): `NSPasteboard.generalPasteboard().setData_forType_(tiffData, NSTIFFPboardType)`. Convert PNG→TIFF in memory with Pillow.
  - Linux: read via `ImageGrab.grabclipboard()` where available, else `xclip -selection clipboard -t image/png -o`; write via `xclip -selection clipboard -t image/png` (X11) or `wl-copy --type image/png` (Wayland, detected via `$WAYLAND_DISPLAY`).
- **Files:**
  - Windows: keep existing CF_HDROP code.
  - macOS: write downloaded paths via `NSFilenamesPboardType` (`pasteboardURLs`); read via `AppKit` pasteboard file URLs. Copying *outbound* local files on Mac: read `NSFilenamesPboardType` same way.
  - Linux: files = `text/uri-list` (`file:///…` per line, `%`-quoted). Read/write via `xclip -selection clipboard -t text/uri-list`. Outbound: only `file://` URIs that are local paths; skip GNOME `x-special/nautilus-clipboard` copy/cut metadata on first pass (treat as plain paths).
- **Echo fingerprints:** keep `kind[0] + content` scheme. Mac PNG→TIFF→PNG round-trip differs like the existing DIB round-trip — reuse the existing read-back pattern (`write_image` re-reads clipboard for the canonical fp).

Keep `HAS_WIN32` name as an alias for compat, add `HAS_IMAGES` / `HAS_FILES` flags per backend so `receiver.feed()` raises the same "cannot receive X on this platform" error instead of crashing.

Priority order: text (done) → images → files. Shipping text+images first and leaving files text-only on Mac/Linux is a valid milestone — gate with `sync_files` config already present.

## 5. Autostart per OS (`settings.py`)

Split `get_autostart` / `set_autostart` by `platform.system()`:

- **Windows:** keep HKCU Run key as-is.
- **macOS:** `~/Library/LaunchAgents/com.clipboardsync.plist` (Label + ProgramArguments `[sys.executable or binary, --minimized]`, RunAtLoad=true). `launchctl load/unload` on toggle.
- **Linux:** `~/.config/autostart/clipboardsync.desktop` (`[Desktop Entry]`, `Type=Application`, `Exec=… --minimized`, `X-GNOME-Autostart-enabled=true`).

Rename checkbox "Start with Windows (minimized to tray)" → "Start at login (minimized to tray)". `_autostart_command()` needs a frozen branch per OS (`.app` bundle path vs `.exe` vs binary).

## 6. Build per OS (`build.py`)

PyInstaller must run **on** each target OS (no cross-compiling):

| OS | Command / output |
|---|---|
| Windows | existing: `--onefile --windowed` → `ClipboardSync.exe` |
| macOS | `--windowed --name ClipboardSync` (`--onefile` optional; `--onedir` + `hdiutil` .dmg for distribution). Notarize for Gatekeeper if distributing. |
| Linux | `--onefile` → `ClipboardSync` binary (document system deps: `xclip`/`wl-clipboard`); optional AppImage. |

Detect output suffix via `platform.system()` instead of hardcoding `.exe`; keep `--windowed` only on Win/Mac (on Linux it drops console output — keep it for a first pass, remove only if tray-only is confirmed working).

CI sketch: three GitHub Actions runners (`windows-latest`, `macos-latest`, `ubuntu-latest`), each `pip install -r requirements.txt; python build.py`, upload artifact.

## 7. Small cleanups

- Fonts: `("Segoe UI", 13)` → `ctk.CTkFont(family=…)` with fallback: try Segoe UI → SFNSDisplay (Mac) → DejaVu Sans (Linux). One helper in `ui/`.
- `app.py:_discovery_timeout` string mentions "Windows Firewall" — make it "system firewall".
- `settings._autostart_command` `pythonw.exe` branch: Windows-only, guard by OS.

## 8. Test matrix

- [ ] Win↔Win (regression: text, image, multi-file, discovery)
- [ ] Mac↔Win, Linux↔Win (text first, then images, then files)
- [ ] Mac as server + Linux as client (neither is Windows — proves server is platform-free)
- [ ] Discovery on each OS (some routers block `255.255.255.255`; fallback is manual IP, already supported)
- [ ] `pip install -r requirements.txt` clean on fresh Mac + Linux (validates §3 markers)
- [ ] Tray absent (Linux without AppIndicator): app still runs, close→tray falls back to minimize

## Suggested order

1. §3 markers (one-line fix, unblocks Mac/Linux installs).
2. §4 text verification + image backends.
3. §4 file backends.
4. §5 autostart, §7 strings/fonts.
5. §6 builds + §8 matrix.
