"""Főablak: futurisztikus, animált indítóképernyő a három modullal."""

from __future__ import annotations

import math
import random
import tkinter as tk
from tkinter import messagebox

from . import APP_NAME, APP_VERSION
from . import theme as T
from .widgets import NeonButton


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "r", "color", "life")

    def __init__(self, w, h):
        self.reset(w, h, initial=True)

    def reset(self, w, h, initial=False):
        self.x = random.uniform(0, w)
        self.y = random.uniform(0, h) if initial else h + 10
        self.vx = random.uniform(-0.3, 0.3)
        self.vy = random.uniform(-1.3, -0.3)
        self.r = random.uniform(1.0, 3.2)
        self.color = random.choice(T.ACCENTS)
        self.life = random.uniform(0.4, 1.0)


class MainWindow:
    FPS_MS = 33

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"{APP_NAME}  v{APP_VERSION}")
        root.configure(bg=T.BG)
        root.geometry("1100x700")
        root.minsize(900, 600)
        T.apply_theme(root)

        self.canvas = tk.Canvas(root, bg=T.BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.t = 0.0
        self.particles = []
        self.bars = [random.random() for _ in range(48)]
        self.windows = {}

        self.buttons = [
            NeonButton(self.canvas, "Style Studio", lambda: self.open("style"), T.CYAN,
                       "MIDI / STL → Genos 2 .STY  •  ütemszeletelő", "♫", 330, 84),
            NeonButton(self.canvas, "Precíziós Sample Vágó", lambda: self.open("cutter"),
                       T.MAGENTA, "Zero-crossing vágás  •  0 ms latency", "✂", 330, 84),
            NeonButton(self.canvas, "Smart Looper & Key Mapper", lambda: self.open("looper"),
                       T.LIME, "Crossfade loop  •  okos fájlnevek", "∞", 330, 84),
        ]
        self.btn_ids = [self.canvas.create_window(0, 0, window=b) for b in self.buttons]
        self.canvas.bind("<Configure>", self._on_resize)
        root.protocol("WM_DELETE_WINDOW", self._quit)
        self._job = None
        self._animate()

    # ------------------------------------------------------------------
    def _on_resize(self, _e=None):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        self._draw_background(w, h)
        if len(self.particles) < 70:
            self.particles = [Particle(w, h) for _ in range(70)]
        spacing = 350
        total = spacing * 3 - 20
        x0 = (w - total) / 2 + 165
        for i, bid in enumerate(self.btn_ids):
            self.canvas.coords(bid, x0 + i * spacing, h * 0.70)

    def _draw_background(self, w, h):
        self.canvas.delete("bg")
        steps = 40
        for i in range(steps):
            c = T.blend("#0a0f2e", "#03040c", i / steps)
            self.canvas.create_rectangle(0, h * i / steps, w, h * (i + 1) / steps + 1,
                                         fill=c, outline="", tags="bg")
        # perspektivikus rácspadló
        horizon = h * 0.52
        for i in range(-20, 21):
            self.canvas.create_line(w / 2 + i * 30, horizon, w / 2 + i * 160, h,
                                    fill="#141c46", tags="bg")
        self.canvas.tag_lower("bg")

    def _animate(self):
        self.t += 0.045
        cv = self.canvas
        w, h = max(cv.winfo_width(), 400), max(cv.winfo_height(), 300)
        cv.delete("anim")

        horizon = h * 0.52
        # mozgó vízszintes rácsvonalak
        for k in range(12):
            p = ((k + (self.t * 0.6) % 1.0) / 12.0) ** 2
            y = horizon + (h - horizon) * p
            cv.create_line(0, y, w, y, fill=T.blend("#03040c", T.VIOLET, 0.15 + 0.5 * p),
                           tags="anim")

        # hullámok
        waves = [(T.CYAN, 38, 0.011, 1.0), (T.MAGENTA, 28, 0.016, -1.3),
                 (T.VIOLET, 22, 0.008, 0.7), (T.LIME, 12, 0.023, 1.9)]
        for col, amp, freq, speed in waves:
            pts = []
            for x in range(0, w + 16, 16):
                env = math.sin(math.pi * x / w)
                y = h * 0.40 + math.sin(x * freq + self.t * speed * 2) * amp * env \
                    * (0.7 + 0.3 * math.sin(self.t + amp))
                pts += [x, y]
            cv.create_line(pts, fill=T.blend("#03040c", col, 0.35), width=6, smooth=True,
                           tags="anim")
            cv.create_line(pts, fill=col, width=2, smooth=True, tags="anim")

        # spektrum-oszlopok
        n = len(self.bars)
        bw = w / n
        for i in range(n):
            target = abs(math.sin(self.t * 1.7 + i * 0.37) * math.cos(self.t * 0.9 + i * 0.11))
            self.bars[i] += (target - self.bars[i]) * 0.25
            bh = 6 + self.bars[i] * h * 0.10
            col = T.ACCENTS[i % len(T.ACCENTS)]
            cv.create_rectangle(i * bw + 2, h - bh, (i + 1) * bw - 2, h,
                                fill=T.blend("#03040c", col, 0.55), outline="", tags="anim")

        # részecskék
        for p in self.particles:
            p.x += p.vx
            p.y += p.vy
            if p.y < -10:
                p.reset(w, h)
            cv.create_oval(p.x - p.r, p.y - p.r, p.x + p.r, p.y + p.r,
                           fill=T.blend("#03040c", p.color, p.life), outline="", tags="anim")

        # cím pulzáló fénnyel
        glow = 0.5 + 0.5 * math.sin(self.t * 1.5)
        for off, a in ((4, 0.18), (2, 0.35)):
            cv.create_text(w / 2 + off, h * 0.15 + off, text="AuraWave",
                           fill=T.blend("#03040c", T.MAGENTA, a + 0.2 * glow),
                           font=(T.FONT_FAMILY, 44, "bold"), tags="anim")
        cv.create_text(w / 2, h * 0.15, text="AuraWave", fill=T.blend(T.CYAN, "#ffffff", glow * 0.5),
                       font=(T.FONT_FAMILY, 44, "bold"), tags="anim")
        cv.create_text(w / 2, h * 0.15 + 46, text="G E N O S   S T U D I O   P R O",
                       fill=T.TEXT, font=(T.FONT_FAMILY, 15, "bold"), tags="anim")
        cv.create_text(w / 2, h * 0.15 + 72,
                       text="Yamaha Genos 2 stílus- és sample-műhely",
                       fill=T.MUTED, font=T.FONT, tags="anim")
        cv.create_text(w - 12, h - 12, text=f"v{APP_VERSION}", anchor="se", fill=T.MUTED,
                       font=T.FONT_SMALL, tags="anim")

        for i, b in enumerate(self.buttons):
            b.pulse(self.t * 2 + i)
        if cv.find_withtag("bg"):
            cv.tag_lower("bg")
        self._job = self.root.after(self.FPS_MS, self._animate)

    # ------------------------------------------------------------------
    def open(self, key: str):
        win = self.windows.get(key)
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_force()
            return
        try:
            if key == "style":
                from .style_studio import StyleStudioWindow as W
            elif key == "cutter":
                from .sample_cutter import SampleCutterWindow as W
            else:
                from .smart_looper import SmartLooperWindow as W
            self.windows[key] = W(self.root)
        except Exception as exc:  # pragma: no cover - GUI hibajelzés
            messagebox.showerror(APP_NAME, f"Nem sikerült megnyitni az ablakot:\n{exc}")
            raise

    def _quit(self):
        if self._job:
            self.root.after_cancel(self._job)
        self.root.destroy()


def run():
    import os
    import sys
    import traceback

    root = tk.Tk()
    selftest = os.environ.get("AURAWAVE_SELFTEST") == "1"
    errors = []
    if selftest:
        def report(exc, val, tb):
            errors.append("".join(traceback.format_exception(exc, val, tb)))
        root.report_callback_exception = report
    mw = MainWindow(root)
    if selftest:
        # Automatikus próba: mindhárom modulablak megnyitása, majd kilépés.
        def step(i=0):
            keys = ["style", "cutter", "looper"]
            if i < len(keys):
                try:
                    mw.open(keys[i])
                except Exception:
                    errors.append(traceback.format_exc())
                root.after(1500, lambda: step(i + 1))
            else:
                root.after(2000, root.destroy)
        root.after(2000, step)
    root.mainloop()
    if selftest:
        log = os.path.join(os.path.expanduser("~"), "aurawave_selftest.log")
        with open(log, "w", encoding="utf-8") as fh:
            fh.write("\n".join(errors) if errors else "OK")
        sys.exit(1 if errors else 0)
