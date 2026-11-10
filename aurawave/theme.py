"""Futurisztikus sötét neon téma a tkinter/ttk felülethez."""

import sys
import tkinter as tk
from tkinter import ttk

BG = "#070b1a"
BG2 = "#0d1330"
PANEL = "#111a3d"
PANEL2 = "#18234f"
BORDER = "#2a3a7a"
TEXT = "#e8ecff"
MUTED = "#8c96c8"
CYAN = "#00e5ff"
MAGENTA = "#ff2fd1"
VIOLET = "#8b5cff"
LIME = "#7dff6b"
ORANGE = "#ffb02e"
RED = "#ff4d6d"

ACCENTS = [CYAN, MAGENTA, VIOLET, LIME, ORANGE]

if sys.platform.startswith("win"):
    FONT_FAMILY = "Segoe UI"
elif sys.platform == "darwin":
    FONT_FAMILY = "Helvetica Neue"
else:
    FONT_FAMILY = "DejaVu Sans"

FONT = (FONT_FAMILY, 10)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL = (FONT_FAMILY, 9)
FONT_TITLE = (FONT_FAMILY, 26, "bold")
FONT_H1 = (FONT_FAMILY, 16, "bold")
FONT_H2 = (FONT_FAMILY, 12, "bold")
FONT_MONO = ("Consolas" if sys.platform.startswith("win") else "DejaVu Sans Mono", 9)


def blend(c1: str, c2: str, t: float) -> str:
    """Két hex szín keverése (t=0 -> c1, t=1 -> c2)."""
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def apply_theme(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.option_add("*Font", FONT)
    root.option_add("*TCombobox*Listbox.background", PANEL2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", VIOLET)

    style.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL2,
                    bordercolor=BORDER, lightcolor=PANEL2, darkcolor=BG2,
                    troughcolor=BG2, focuscolor=CYAN, font=FONT)
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=FONT_SMALL)
    style.configure("H1.TLabel", background=BG, foreground=CYAN, font=FONT_H1)
    style.configure("H2.TLabel", background=PANEL, foreground=CYAN, font=FONT_H2)
    style.configure("Value.TLabel", background=PANEL, foreground=LIME, font=FONT_MONO)
    style.configure("TLabelframe", background=PANEL, bordercolor=BORDER, relief="solid")
    style.configure("TLabelframe.Label", background=PANEL, foreground=CYAN, font=FONT_BOLD)
    style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
    style.map("TCheckbutton", background=[("active", PANEL2)],
              indicatorcolor=[("selected", CYAN), ("!selected", PANEL2)])
    style.configure("TRadiobutton", background=PANEL, foreground=TEXT)
    style.map("TRadiobutton", background=[("active", PANEL2)],
              indicatorcolor=[("selected", MAGENTA), ("!selected", PANEL2)])
    style.configure("TButton", background=PANEL2, foreground=TEXT, bordercolor=BORDER,
                    padding=(10, 5), font=FONT_BOLD)
    style.map("TButton", background=[("active", VIOLET), ("disabled", BG2)],
              foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background="#005f73", foreground="white")
    style.map("Accent.TButton", background=[("active", CYAN)],
              foreground=[("active", BG)])
    style.configure("Hot.TButton", background="#7a1466", foreground="white")
    style.map("Hot.TButton", background=[("active", MAGENTA)])
    style.configure("TEntry", fieldbackground=PANEL2, foreground=TEXT, insertcolor=CYAN)
    style.configure("TSpinbox", fieldbackground=PANEL2, foreground=TEXT,
                    arrowcolor=CYAN, insertcolor=CYAN)
    style.configure("TCombobox", fieldbackground=PANEL2, foreground=TEXT,
                    arrowcolor=CYAN, background=PANEL2)
    style.map("TCombobox", fieldbackground=[("readonly", PANEL2)],
              foreground=[("readonly", TEXT)])
    style.configure("Horizontal.TScale", background=PANEL, troughcolor=BG2)
    style.configure("Treeview", background=BG2, fieldbackground=BG2, foreground=TEXT,
                    rowheight=24, bordercolor=BORDER)
    style.map("Treeview", background=[("selected", VIOLET)])
    style.configure("Treeview.Heading", background=PANEL2, foreground=CYAN,
                    font=FONT_BOLD, relief="flat")
    style.map("Treeview.Heading", background=[("active", BORDER)])
    style.configure("Horizontal.TProgressbar", background=CYAN, troughcolor=BG2)
    style.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=BG2,
                    arrowcolor=CYAN)
    style.configure("Horizontal.TScrollbar", background=PANEL2, troughcolor=BG2,
                    arrowcolor=CYAN)
    return style
