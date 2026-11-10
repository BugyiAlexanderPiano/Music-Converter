#!/usr/bin/env python3
"""AuraWave Genos Studio Pro – indítófájl.

Futtatás:  python main.py
"""

import sys


def _check():
    missing = []
    try:
        import tkinter  # noqa: F401
    except ImportError:
        missing.append("tkinter (Linuxon: sudo apt install python3-tk)")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy (pip install -r requirements.txt)")
    if missing:
        print("Hiányzó összetevők:\n  - " + "\n  - ".join(missing))
        sys.exit(1)


if __name__ == "__main__":
    if sys.version_info < (3, 8):
        print("Python 3.8 vagy újabb szükséges.")
        sys.exit(1)
    _check()
    if sys.platform.startswith("win"):
        try:  # éles megjelenítés nagy DPI-s Windows kijelzőkön
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    from aurawave.main_window import run
    run()
