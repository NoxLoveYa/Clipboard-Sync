"""
clipboard_sync.tray  —  System-tray icon management.

Encapsulates the optional pystray / Pillow imports so the rest of the
codebase doesn't need to check HAS_TRAY.
"""

import threading

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

from clipboard_sync.log import log_event


def create_tray_image():
    """Build a 64x64 tray icon (blue circle with clipboard symbol)."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill="#3a7ebf")
    # Clipboard body
    draw.rectangle([18, 16, 46, 54], fill=None, outline="white", width=4)
    # Clipboard clip
    draw.rectangle([26, 8, 38, 18], fill="white", outline="white", width=2)
    # Horizontal lines
    draw.line([(24, 28), (40, 28)], fill="white", width=3)
    draw.line([(24, 36), (40, 36)], fill="white", width=3)
    draw.line([(24, 44), (36, 44)], fill="white", width=3)
    return img


class TrayManager:
    """Manages the pystray system-tray icon.

    Parameters
    ----------
    on_show : callable
        Called (from background thread) when the user clicks "Show Window".
    on_quit : callable
        Called (from background thread) when the user clicks "Quit".
    """

    def __init__(self, on_show: callable, on_quit: callable) -> None:
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon = None

    @property
    def active(self) -> bool:
        return self._icon is not None

    def setup(self, mode: str) -> None:
        """Create and start the tray icon for *mode* ('client' or 'server')."""
        if not HAS_TRAY:
            return
        self.stop()

        tray_id = f"clipboard-sync-{mode}"
        title = f"Clipboard Sync — {'Server' if mode == 'server' else 'Client'}"
        menu = pystray.Menu(
            pystray.MenuItem("Show Window", self._on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )
        self._icon = pystray.Icon(
            tray_id, create_tray_image(), title, menu,
        )
        threading.Thread(target=self._icon.run, daemon=True).start()
        log_event("System tray icon active", "info")

    def stop(self) -> None:
        """Stop and remove the tray icon if present."""
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def recreate(self, mode: str, close_action: str) -> None:
        """Recreate the tray icon after a mode or settings change."""
        if close_action == "tray":
            self.setup(mode)
        else:
            self.stop()
