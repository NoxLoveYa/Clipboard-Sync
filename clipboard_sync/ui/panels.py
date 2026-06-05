"""
clipboard_sync.panels  —  Mode-specific UI panel builders.

Standalone functions that populate a parent frame with client or
server mode widgets.  Each returns a dict of widget references so
the caller can read inputs or attach further behaviour.
"""

import customtkinter as ctk

from clipboard_sync.core.log import status_queue
from clipboard_sync.core.config import get_local_ip


def build_client_panel(parent: ctk.CTkFrame, config: dict,
                       callbacks: dict) -> dict:
    """Create client-mode widgets inside *parent*.

    Returns a dict with keys:
    ``ip_var``, ``ip_entry``, ``connect_btn``, ``disconnect_btn``,
    ``auto_var``.
    """
    conn_frame = ctk.CTkFrame(parent)
    conn_frame.pack(fill="x", padx=0, pady=0)

    ctk.CTkLabel(
        conn_frame, text="Server IP:",
        font=("Segoe UI", 13),
    ).pack(side="left", padx=(10, 5), pady=10)

    ip_var = ctk.StringVar(value=config.get("server_ip", ""))
    ip_entry = ctk.CTkEntry(
        conn_frame, textvariable=ip_var,
        width=180, placeholder_text="192.168.x.x",
    )
    ip_entry.pack(side="left", padx=5, pady=10)

    connect_btn = ctk.CTkButton(
        conn_frame, text="Connect", width=90,
        command=callbacks["on_connect"],
    )
    connect_btn.pack(side="left", padx=5, pady=10)

    disconnect_btn = ctk.CTkButton(
        conn_frame, text="Disconnect", width=90,
        state="disabled",
        command=callbacks["on_disconnect"],
        fg_color="#c0392b", hover_color="#e74c3c",
    )
    disconnect_btn.pack(side="left", padx=5, pady=10)

    auto_var = ctk.BooleanVar(
        value=config.get("auto_reconnect", True),
    )
    ctk.CTkCheckBox(
        parent, text="Auto-reconnect",
        variable=auto_var, onvalue=True, offvalue=False,
        font=("Segoe UI", 11),
    ).pack(anchor="w", padx=10, pady=(3, 0))

    status_queue.put(("#f44336", "Disconnected"))

    return {
        "ip_var": ip_var,
        "ip_entry": ip_entry,
        "connect_btn": connect_btn,
        "disconnect_btn": disconnect_btn,
        "auto_var": auto_var,
    }


def build_server_panel(parent: ctk.CTkFrame,
                       callbacks: dict) -> dict:
    """Create server-mode widgets inside *parent*.

    Returns a dict with key ``server_ip_var``.
    """
    ip_frame = ctk.CTkFrame(parent)
    ip_frame.pack(fill="x", padx=0, pady=0)

    ctk.CTkLabel(
        ip_frame, text="Server IP:",
        font=("Segoe UI", 13),
    ).pack(side="left", padx=(10, 5), pady=10)

    local_ip = get_local_ip()
    server_ip_var = ctk.StringVar(value=local_ip)
    ctk.CTkEntry(
        ip_frame, textvariable=server_ip_var,
        width=200, state="readonly",
    ).pack(side="left", padx=5, pady=10)

    ctk.CTkButton(
        ip_frame, text="Copy IP", width=90,
        command=callbacks["on_copy_ip"],
    ).pack(side="left", padx=5, pady=10)

    return {"server_ip_var": server_ip_var}
