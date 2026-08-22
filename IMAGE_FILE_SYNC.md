# Image & File Sync — Design Document

> **Status:** Proposed (not yet implemented)
>
> Goal: extend Clipboard Sync beyond plain text so screenshots, copied
> images, and copied **files** (including multi-file selections) sync between
> machines on the LAN — with a hard 100 MB transfer cap.

---

## 1. Problem

The current implementation is text-only end to end:

| Layer | Limitation |
|---|---|
| Watcher (`core/watcher.py`) | Polls `pyperclip.paste()` → strings only; images/files are invisible |
| Wire protocol (`network/client.py`, `network/server.py`) | UTF-8 payload + in-band `\n---END---\n` delimiter — cannot carry binary safely |
| Receive path | `pyperclip.copy(msg)` — text only |

## 2. Solution overview

Three coordinated changes:

1. A new **protocol v2** with length-prefixed binary envelopes and typed
   messages (text / image / file-manifest / file-chunk).
2. A new **`clipboard_io`** module that can read *and write* images and file
   lists to the Windows clipboard via `pywin32`.
3. A reworked **watcher** that detects all three content kinds by
   fingerprint instead of comparing text.

```
Sender                                          Receiver
──────                                          ────────
copy image in Paint                             watcher sees PNG fingerprint change
watcher snapshot → ("image", png)               protocol decode → ("image", png)
protocol encode [len][0x02][png]  ──TCP──▶      clipboard_io.write_image(png)
                                                paste works in Paint/Word/…
```

File transfers stream through the same channel as manifest + chunks and land
in `%USERPROFILE%\Downloads\ClipboardSync\`, then go on the clipboard as an
`CF_HDROP` file selection.

---

## 3. Protocol v2 specification

### 3.1 Framing

Every message on the TCP stream is:

```
┌──────────────┬──────────┬────────────────────────┐
│ uint32 BE    │ uint8    │ payload                │
│ length       │ type     │ (length bytes)         │
└──────────────┴──────────┴────────────────────────┘
```

- `length` counts the payload only (max `100 MB` — enforced on both ends;
  violation = connection closed with an error log).
- Reads use an exact-`recv(n)` helper (no delimiter scanning, binary-safe).

### 3.2 Message types

| Type   | Name            | Payload                                                        |
|--------|-----------------|----------------------------------------------------------------|
| `0x01` | `TEXT`          | UTF-8 encoded string                                           |
| `0x02` | `IMAGE`         | PNG-encoded bytes                                              |
| `0x03` | `FILE_MANIFEST` | UTF-8 JSON: `{"id": "<uuid>", "name": "report.pdf", "size": N}`|
| `0x04` | `FILE_CHUNK`    | raw bytes (≤ 64 KiB), belongs to the last manifest             |

### 3.3 File transfer flow

```
sender                                   receiver
manifest {id, name, size}
chunk 1..k (sequential)          ──▶     stream to Downloads\ClipboardSync\<name>
                                         size mismatch → discard + error log
                                         ok → add path to clipboard file list
```

- Multiple files = multiple manifest+chunks sequences back-to-back.
- The receiver places **all** files of one clipboard copy event on the
  clipboard together (one `CF_HDROP`), matching the sender's multi-select.
- Chunks for one manifest must complete before the next manifest starts
  (single sequential stream per connection — no interleaving).

### 3.4 Relay behaviour (server)

`ServerHost` relays any message type verbatim to other clients — no decoding,
no re-encoding. Only manifests are parsed (for logging/progress). This keeps
the server dumb and future-proof.

### 3.5 Compatibility

Protocol v2 is **incompatible with v1** (`---END---` framing). Both machines
must run the updated build; the README will state this requirement. On
garbage at the framing layer (e.g. old peer), the client logs
*"Incompatible peer — please update both machines"* and drops the link.

---

## 4. New module: `clipboard_sync/core/clipboard_io.py`

All win32 usage isolated here. Graceful degradation: if `pywin32` is missing,
image/file functions log a warning and return `None`; **text sync keeps
working**.

### Read side

```python
read_snapshot() -> Snapshot | None
```

Detection order:

1. Text present (`CF_UNICODETEXT`) → `("text", str)`
2. Else bitmap present (`CF_DIB`) → convert to PNG via Pillow
   → `("image", png_bytes, width, height)`
3. Else file list present (`CF_HDROP`) → `("files", [abs_paths])`

(Uses `win32clipboard` directly rather than `ImageGrab.grabclipboard()` for
precise format detection.)

### Write side

```python
write_text(t)                 # pyperclip (unchanged)
write_image(png_bytes) -> bool  # PNG → DIB → CF_DIB (+ CF_UNICODETEXT fallback? no — image only)
write_files(paths) -> bool      # CF_HDROP so Explorer/apps can paste real files
```

---

## 5. Watcher rework — `clipboard_sync/core/watcher.py`

```python
snapshot = clipboard_io.read_snapshot()
fingerprint = sha256(canonical(snapshot))   # text → utf8; image → png bytes;
                                            # files → sorted path list
```

Loop (unchanged cadence, `POLL_INTERVAL = 0.5s`):

1. Build snapshot + fingerprint.
2. Skip if fingerprint == last seen.
3. Skip if fingerprint == `last_remote_fingerprint` (see §6) — this is the
   echo-loop guard.
4. Enforce size cap (`max_transfer_mb`): oversize image/file → log refusal,
   do **not** send.
5. Fire `on_change(snapshot)`.

Snapshot is a small dataclass:

```python
@dataclass
class Snapshot:
    kind: str            # "text" | "image" | "files"
    text: str | None
    png: bytes | None
    paths: list[str] | None
    total_bytes: int     # used for the cap check & progress logs
```

## 6. Echo-loop prevention — `app.py`

Today's guard compares sent/received strings. Replacement:

- After **sending** any snapshot → record its fingerprint as
  `last_local_fingerprint`.
- After **receiving** and placing content on the clipboard → compute the same
  fingerprint from what we wrote (we have the exact bytes/paths) and store as
  `last_remote_fingerprint`.

The watcher (§5 step 3) suppresses exactly that fingerprint once. Note: we
store the fingerprint of what *we wrote*, not of the wire payload, because
PNG→DIB→PNG round-trips may not be byte-identical.

## 7. File destination

Received files: `%USERPROFILE%\Downloads\ClipboardSync\`

- Created on demand; name collisions get `name (2).ext` suffixes.
- Configurable later via settings (out of scope for v1 of this feature).
- Files stay there after pasting (Windows clipboards reference real files —
  there is no virtual-file mechanism without COM shell extensions).

---

## 8. Configuration

New defaults (both modes, `clipboard_sync/core/config.py`):

```python
"sync_images": True,
"sync_files": True,
"max_transfer_mb": 100,
```

Settings dialog additions (both modes):

> ☑ Sync images
> ☑ Sync files
> Max transfer size: 25 MB / 50 MB / 100 MB ▾

When `sync_images`/`sync_files` are off, the watcher ignores those snapshot
kinds entirely (they don't clear the clipboard or block text sync).

## 9. Dependencies

| Package | Status | Purpose |
|---|---|---|
| `Pillow>=10.0.0` | already required | PNG encode/decode |
| `pywin32>=306` | **new** | CF_DIB / CF_HDROP clipboard writes, HDROP reads |

`requirements.txt` gains `pywin32>=306`. PyInstaller note: PyInstaller
normally picks up `pywin32` automatically; verify after first build.

## 10. Implementation checklist

1. `network/protocol.py` — frame encode/decode helpers + unit tests
2. `core/clipboard_io.py` — read/write snapshots behind try-import guards
3. `core/watcher.py` — fingerprint loop + snapshot callback (breaking API
   change, update `app.py`)
4. `network/client.py` / `server.py` — v2 framing, chunked receive-to-disk,
   progress logs, echo fingerprints
5. Settings UI + config defaults
6. README compatibility note

## 11. Verification plan

1. **Unit:** protocol round-trips (all types, multi-chunk file, oversize
   rejection, truncated-stream handling).
2. **Two-instance test** (server instance + client instance on localhost):
   - copy text → arrives as text
   - screenshot in Snipping Tool → paste works in Paint on the other side
   - copy 2 files in Explorer → both appear in
     `Downloads\ClipboardSync\` and can be pasted in Explorer
   - >100 MB file → refused with clear log line on both ends
3. **Echo test:** confirm no ping-pong loop after each receive (§6).
4. **Degraded mode:** uninstall pywin32 → app still syncs text, logs warning.
5. **PyInstaller build** still produces a working exe.

---

## Appendix A — Risks & trade-offs

- **Files land on disk** even if never pasted (fundamental Windows design).
  Mitigation: single predictable folder; auto-clean after N days is a possible
  follow-up setting.
- **Large transfers block the connection's other traffic** (sequential
  stream). Acceptable: clipboard events are sparse; a 100 MB LAN transfer
  takes seconds.
- **PNG conversion cost** for huge bitmaps (screenshots are typically fine).
- **No encryption** — unchanged from today (LAN trust model); noted for a
  future TLS milestone.
