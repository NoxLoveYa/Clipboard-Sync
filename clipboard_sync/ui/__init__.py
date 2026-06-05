"""
clipboard_sync.ui  —  GUI widgets: AppUI, LogView, TrayManager, panel builders.
"""

from clipboard_sync.ui.app_ui import AppUI
from clipboard_sync.ui.log_view import LogView
from clipboard_sync.ui.tray import TrayManager, HAS_TRAY, create_tray_image
from clipboard_sync.ui.panels import build_client_panel, build_server_panel
