"""
settings.py  —  Shared settings dialog and config helpers for Clipboard Sync.

Both server_gui and client_gui import from this module.
"""

import json
import os

import customtkinter as ctk

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
    """
    WIN_W, WIN_H = 360, 250

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
                            "theme", top_pad=4, bottom_pad=18)

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
        on_save(new_config)
        dialog.destroy()

    ctk.CTkButton(
        btn_frame, text="Save", width=90,
        command=_save,
    ).pack(side="right")

    dialog.focus_set()
    dialog.wait_window()
