"""
settings.py  —  Shared settings dialog and config helpers for Clipboard Sync.

Both server_gui and client_gui import from this module.
"""

import json
import os
import sys

import customtkinter as ctk

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    winreg = None
    HAS_WINREG = False

# ── display → stored value mappings ──────────────────────────────────────────

CLOSE_ACTION_MAP: dict[str, str] = {
    "Minimize to tray": "tray",
    "Exit": "exit",
}
THEME_MAP: dict[str, str] = {
    "Dark": "dark",
    "Light": "light",
    "System": "system",
}
RECONNECT_DELAY_MAP: dict[str, int] = {
    "1 second": 1,
    "2 seconds": 2,
    "3 seconds": 3,
    "5 seconds": 5,
    "10 seconds": 10,
    "15 seconds": 15,
    "30 seconds": 30,
    "60 seconds": 60,
}
MAX_TRANSFER_MAP: dict[str, int] = {
    "25 MB": 25,
    "50 MB": 50,
    "100 MB": 100,
}


# ── windows autostart (HKCU Run key) ─────────────────────────────────────────

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "ClipboardSync"


def _autostart_command() -> str:
    """Build the command used for the autostart entry."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    python = sys.executable
    pythonw = os.path.join(
        os.path.dirname(python),
        "pythonw.exe" if os.path.basename(python).lower() == "python.exe"
        else os.path.basename(python),
    )
    script = os.path.abspath(sys.argv[0])
    return f'"{pythonw}" "{script}" --minimized'


def get_autostart() -> bool:
    """Return True if the Run-key entry exists."""
    if not HAS_WINREG:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    """Create or remove the HKCU Run-key entry (starts minimized to tray)."""
    if not HAS_WINREG:
        raise RuntimeError("Windows registry is not available")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ,
                              _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass


# ── config helpers ───────────────────────────────────────────────────────────

def load_config(path: str, defaults: dict | None = None) -> dict:
    """Load JSON config file, filling missing keys from *defaults*."""
    result = dict(defaults or {})
    try:
        with open(path) as f:
            result.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return result


def save_config(path: str, config: dict) -> None:
    """Persist config dict to JSON file (atomic write)."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass


# ── settings dialog ──────────────────────────────────────────────────────────

def open_settings_dialog(
    parent: ctk.CTk,
    current_config: dict,
    on_save: callable,
    show_reconnect: bool = False,
) -> None:
    """Open a modal settings dialog.

    Parameters
    ----------
    parent : ctk.CTk
        The parent window (dialog is modal to this).
    current_config : dict
        Must contain at least ``close_action`` and ``theme`` keys.
    on_save : callable
        Called with the updated config dict when the user clicks Save.
    show_reconnect : bool
        Show the client-only reconnect-delay row.
    """
    WIN_W, WIN_H = 360, 470 + (82 if show_reconnect else 0)

    dialog = ctk.CTkToplevel(parent)
    dialog.title("Settings")
    dialog.geometry(f"{WIN_W}x{WIN_H}")
    dialog.minsize(WIN_W, WIN_H)
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    # centre on parent
    dx = (parent.winfo_width() - WIN_W) // 2
    dy = (parent.winfo_height() - WIN_H) // 2
    dialog.geometry(f"+{parent.winfo_x() + dx}+{parent.winfo_y() + dy}")

    # ── helper: label + themed OptionMenu row ───────────────────
    def _option_row(label: str, value_map: dict[str, str], config_key: str,
                    top_pad: int, bottom_pad: int) -> ctk.StringVar:
        ctk.CTkLabel(dialog, text=label, font=("Segoe UI", 13), anchor="w").pack(
            fill="x", padx=20, pady=(top_pad, 4))
        display = {v: k for k, v in value_map.items()}.get(
            current_config.get(config_key, list(value_map.values())[0]),
            list(value_map.keys())[0],
        )
        var = ctk.StringVar(value=display)
        ctk.CTkOptionMenu(
            dialog, variable=var, values=list(value_map.keys()),
            dynamic_resizing=False,
        ).pack(fill="x", padx=20, pady=(0, bottom_pad))
        return var

    # ── settings rows ──────────────────────────────────────────
    close_var = _option_row("When closing window:", CLOSE_ACTION_MAP,
                            "close_action", top_pad=18, bottom_pad=10)
    theme_var = _option_row("Theme:", THEME_MAP,
                            "theme", top_pad=4, bottom_pad=10)

    delay_var: ctk.StringVar | None = None
    discover_var: ctk.BooleanVar | None = None
    if show_reconnect:
        delay_var = _option_row(
            "Reconnect delay (unlimited retries):", RECONNECT_DELAY_MAP,
            "reconnect_delay", top_pad=4, bottom_pad=10)
        discover_var = ctk.BooleanVar(
            value=bool(current_config.get("auto_discover", True)))
        ctk.CTkCheckBox(
            dialog, text="Auto-discover servers on LAN",
            variable=discover_var, onvalue=True, offvalue=False,
            font=("Segoe UI", 12),
        ).pack(anchor="w", padx=20, pady=(0, 10))

    autostart_var = ctk.BooleanVar(
        value=bool(current_config.get("autostart", False)))
    ctk.CTkCheckBox(
        dialog, text="Start with Windows (minimized to tray)",
        variable=autostart_var, onvalue=True, offvalue=False,
        font=("Segoe UI", 12),
    ).pack(anchor="w", padx=20, pady=(2, 4))

    images_var = ctk.BooleanVar(
        value=bool(current_config.get("sync_images", True)))
    ctk.CTkCheckBox(
        dialog, text="Sync images",
        variable=images_var, onvalue=True, offvalue=False,
        font=("Segoe UI", 12),
    ).pack(anchor="w", padx=20, pady=(2, 4))

    files_var = ctk.BooleanVar(
        value=bool(current_config.get("sync_files", True)))
    ctk.CTkCheckBox(
        dialog, text="Sync files",
        variable=files_var, onvalue=True, offvalue=False,
        font=("Segoe UI", 12),
    ).pack(anchor="w", padx=20, pady=(2, 10))

    max_transfer_var = _option_row(
        "Max transfer size:", MAX_TRANSFER_MAP,
        "max_transfer_mb", top_pad=0, bottom_pad=18)

    # ── buttons ────────────────────────────────────────────────
    btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_frame.pack(fill="x", padx=20, pady=(0, 16))

    ctk.CTkButton(
        btn_frame, text="Cancel", width=90,
        command=dialog.destroy,
        fg_color="transparent", border_width=1,
    ).pack(side="right", padx=(6, 0))

    def _save() -> None:
        new_config = dict(current_config)
        new_config["close_action"] = CLOSE_ACTION_MAP[close_var.get()]
        new_config["theme"] = THEME_MAP[theme_var.get()]
        new_config["autostart"] = bool(autostart_var.get())
        new_config["sync_images"] = bool(images_var.get())
        new_config["sync_files"] = bool(files_var.get())
        new_config["max_transfer_mb"] = MAX_TRANSFER_MAP[max_transfer_var.get()]
        if delay_var is not None:
            new_config["reconnect_delay"] = RECONNECT_DELAY_MAP[delay_var.get()]
            new_config["auto_discover"] = bool(discover_var.get())
        on_save(new_config)
        dialog.destroy()

    ctk.CTkButton(
        btn_frame, text="Save", width=90,
        command=_save,
    ).pack(side="right")

    dialog.focus_set()
    dialog.wait_window()
