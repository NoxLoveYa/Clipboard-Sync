"""
clipboard_sync.clipboard_io  —  Windows clipboard read/write beyond text.

Reads and writes images (CF_DIB, PNG-encoded on our side) and file lists
(CF_HDROP).  All win32 usage lives here; without pywin32 the module
degrades to text-only via pyperclip.

Every ``write_*`` returns a fingerprint of the resulting clipboard content,
computed exactly like :func:`fingerprint` computes it from a fresh read —
this is what lets the watcher suppress echo of received content.
"""

import hashlib
import io
import os
import struct
from dataclasses import dataclass, field

import pyperclip
from PIL import Image, ImageGrab

try:
    import win32clipboard
    HAS_WIN32 = True
except ImportError:
    win32clipboard = None
    HAS_WIN32 = False


@dataclass
class Snapshot:
    """One poll of the local clipboard."""
    kind: str                      # "text" | "image" | "files"
    text: str | None = None
    png: bytes | None = None
    paths: list[str] = field(default_factory=list)
    total_bytes: int = 0


def fingerprint(snapshot: Snapshot) -> str:
    """Stable hash of a snapshot's content (kind-aware)."""
    h = hashlib.sha256()
    h.update(snapshot.kind[0].upper().encode())
    if snapshot.kind == "text":
        h.update(snapshot.text.encode("utf-8"))
    elif snapshot.kind == "image":
        h.update(snapshot.png)
    else:
        h.update("\n".join(sorted(snapshot.paths)).encode("utf-8"))
    return h.hexdigest()


# ── read ─────────────────────────────────────────────────────────────────────

def read_snapshot() -> Snapshot | None:
    """Return current clipboard content, or None if empty/locked/unknown."""
    if not HAS_WIN32:
        # ponytail: no-pywin32 fallback is text-only by design; images/files
        # simply don't sync until pywin32 is installed.
        try:
            text = pyperclip.paste()
        except Exception:
            return None
        if not isinstance(text, str) or text == "":
            return None
        return Snapshot("text", text=text,
                        total_bytes=len(text.encode("utf-8")))

    try:
        win32clipboard.OpenClipboard()
    except Exception:
        return None  # clipboard busy — retry next poll

    try:
        avail = win32clipboard.IsClipboardFormatAvailable
        if avail(win32clipboard.CF_HDROP):
            try:
                paths = [p for p in win32clipboard.GetClipboardData(
                    win32clipboard.CF_HDROP) if os.path.isfile(p)]
            except Exception:
                paths = []
            if paths:
                total = sum(os.path.getsize(p) for p in paths)
                return Snapshot("files", paths=paths, total_bytes=total)
            return None
        if avail(win32clipboard.CF_DIB):
            kind = "image"
        elif avail(win32clipboard.CF_UNICODETEXT):
            text = win32clipboard.GetClipboardData(
                win32clipboard.CF_UNICODETEXT)
            if not isinstance(text, str) or text == "":
                return None
            return Snapshot("text", text=text,
                            total_bytes=len(text.encode("utf-8")))
        else:
            return None
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass

    # image path — grabclipboard opens its own handle, must run after close
    try:
        img = ImageGrab.grabclipboard()
    except Exception:
        return None
    if not isinstance(img, Image.Image):
        return None
    buf = io.BytesIO()
    img.save(buf, "PNG")
    png = buf.getvalue()
    return Snapshot("image", png=png, total_bytes=len(png))


# ── write ────────────────────────────────────────────────────────────────────

def _open_empty() -> bool:
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        return True
    except Exception:
        return False


def _close() -> None:
    try:
        win32clipboard.CloseClipboard()
    except Exception:
        pass


def _png_to_dib(png: bytes) -> bytes:
    img = Image.open(io.BytesIO(png))
    if img.mode != "RGB":
        img = img.convert("RGB")
    bmp = io.BytesIO()
    img.save(bmp, "BMP")
    return bmp.getvalue()[14:]  # strip BITMAPFILEHEADER → raw DIB


def _read_image_png() -> bytes | None:
    """Re-read the clipboard bitmap as PNG (canonical fingerprint source)."""
    try:
        img = ImageGrab.grabclipboard()
    except Exception:
        return None
    if not isinstance(img, Image.Image):
        return None
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def write_text(text: str) -> str | None:
    pyperclip.copy(text)
    h = hashlib.sha256()
    h.update(b"T")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def write_image(png: bytes) -> str | None:
    """Place a PNG on the clipboard as CF_DIB. Returns echo fingerprint."""
    if not HAS_WIN32:
        return None
    try:
        dib = _png_to_dib(png)
    except Exception:
        return None
    if not _open_empty():
        return None
    try:
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
    finally:
        _close()
    read_back = _read_image_png()  # PNG→DIB→PNG may differ from input
    if read_back is None:
        return None  # ponytail: rare failure loses echo suppression only;
        # worst case is one redundant send, never a loop.
    h = hashlib.sha256()
    h.update(b"I")
    h.update(read_back)
    return h.hexdigest()


def write_files(paths: list[str]) -> str | None:
    """Place file paths on the clipboard as CF_HDROP. Returns fingerprint."""
    if not HAS_WIN32:
        return None
    # DROPFILES header (pFiles=20, pt=0,0, fNC=0, fWide=1) + wide-char list
    payload = struct.pack("Iiiii", 20, 0, 0, 0, 1)
    payload += ("\0".join(paths) + "\0\0").encode("utf-16-le")
    if not _open_empty():
        return None
    try:
        win32clipboard.SetClipboardData(win32clipboard.CF_HDROP, payload)
    finally:
        _close()
    h = hashlib.sha256()
    h.update(b"F")
    h.update("\n".join(sorted(paths)).encode("utf-8"))
    return h.hexdigest()
