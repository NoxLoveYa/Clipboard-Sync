"""
clipboard_sync  —  Modular Clipboard Sync GUI package.

Usage:
    from clipboard_sync import main
    main()
"""

from clipboard_sync.app import ClipboardSyncGUI
from clipboard_sync.config import load_mode


def main() -> None:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    ClipboardSyncGUI().run()
