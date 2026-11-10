"""Egyedi, neon stílusú vezérlők: animált gomb, hullámforma-nézet húzható
markerekkel, loop-illesztés nagyító és billentyűzet-zónatérkép."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from . import theme as T
from .midi_io import note_name


def rounded_rect(cv: tk.Canvas, x1, y1, x2, y2, r=14, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


# ----------------------------------------------------------------------
class NeonButton(tk.Canvas):
    """Lekerekített, fénylő gomb hover-effekttel és pulzáló kerettel."""

    def __init__(self, master, text: str, command: Callable, color: str = T.CYAN,
                 subtitle: str = "", icon: str = "", width: int = 260, height: int = 64,
                 bg: str = T.BG, font=None):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.subtitle, self.icon = text, subtitle, icon
        self.color, self.command = color, command
        self.w, self.h = width, height
        self.font = font or T.FONT_H2
        self.hover = False
        self.phase = 0.0
        self.enabled = True
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.draw()

    def _set_hover(self, v: bool):
        self.hover = v
        self.draw()

    def _click(self, _e):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self.draw()

    def pulse(self, phase: float):
        self.phase = phase
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.w, self.h
        col = self.color if self.enabled else T.MUTED
        glow = 0.5 + 0.5 * math.sin(self.phase)
        if self.hover and self.enabled:
            for i in range(4, 0, -1):
                rounded_rect(self, 4 - i, 4 - i, w - 4 + i, h - 4 + i, r=16,
                             fill="", outline=T.blend(T.BG, col, 0.25 * (5 - i)), width=1)
        fill = T.blend(T.PANEL, col, 0.30 if self.hover else 0.10)
        border = T.blend(col, "#ffffff", 0.3 * glow) if self.enabled else T.BORDER
        rounded_rect(self, 4, 4, w - 4, h - 4, r=14, fill=fill, outline=border, width=2)
        x = 22
        if self.icon:
            self.create_text(x + 6, h / 2, text=self.icon, fill=col,
                             font=(T.FONT_FAMILY, int(h * 0.36), "bold"))
            x += 40
        if self.subtitle:
            self.create_text(x, h / 2 - 9, text=self.text, anchor="w", fill=T.TEXT,
                             font=self.font)
            self.create_text(x, h / 2 + 12, text=self.subtitle, anchor="w", fill=T.MUTED,
                             font=T.FONT_SMALL)
        else:
            self.create_text(w / 2 if not self.icon else x, h / 2, text=self.text,
                             anchor="center" if not self.icon else "w",
                             fill=T.TEXT, font=self.font)


# ----------------------------------------------------------------------
class AnimatedBanner(tk.Canvas):
    """Vékony, mozgó hullámsáv a modulablakok tetején."""

    def __init__(self, master, title: str, subtitle: str, color: str, height: int = 74):
        super().__init__(master, height=height, bg=T.BG, highlightthickness=0)
        self.title, self.subtitle, self.color = title, subtitle, color
        self.t = 0.0
        self._job = None
        self.bind("<Configure>", lambda e: self._draw())
        self._tick()

    def _tick(self):
        self.t += 0.06
        self._draw()
        self._job = self.after(40, self._tick)

    def destroy(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
        super().destroy()

    def _draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 200)
        h = int(self["height"])
        for i in range(0, h, 4):
            self.create_line(0, i, w, i, fill=T.blend(T.BG2, T.BG, i / h), width=4)
        for k, c in enumerate([self.color, T.VIOLET, T.MAGENTA]):
            pts = []
            for x in range(0, w + 12, 12):
                y = h / 2 + math.sin(x / (55 + 20 * k) + self.t * (1 + k * 0.4)) * (10 + 6 * k)
                pts += [x, y]
            self.create_line(pts, fill=T.blend(T.BG, c, 0.55 - 0.12 * k), width=2,
                             smooth=True)
        self.create_text(24, h / 2 - 10, text=self.title, anchor="w", fill=T.TEXT,
                         font=T.FONT_H1)
        self.create_text(24, h / 2 + 16, text=self.subtitle, anchor="w", fill=self.color,
                         font=T.FONT_SMALL)
        self.create_line(0, h - 1, w, h - 1, fill=self.color, width=2)


# ----------------------------------------------------------------------
class WaveformView(tk.Canvas):
    """Hullámforma-megjelenítő zoommal, görgetéssel és húzható markerekkel.

    Egér: görgő = zoom, Shift+görgő vagy jobb gombos húzás = görgetés,
    dupla kattintás = teljes nézet, bal gomb a marker közelében = húzás.
    """

    def __init__(self, master, height: int = 220, on_marker: Optional[Callable] = None,
                 show_ruler: bool = True, show_dots: bool = True):
        super().__init__(master, height=height, bg=T.BG2, highlightthickness=1,
                         highlightbackground=T.BORDER)
        self.audio = None
        self.v0, self.v1 = 0, 1
        self.markers: Dict[str, Tuple[int, str, str, bool]] = {}
        self.regions: List[Tuple[int, int, str]] = []
        self.on_marker = on_marker
        self.show_ruler = show_ruler
        self.show_dots = show_dots
        self._drag: Optional[str] = None
        self._pan = None
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", lambda e: self.zoom_full())
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Shift-MouseWheel>", self._shift_wheel)
        self.bind("<Button-4>", lambda e: self._zoom_at(e.x, 0.8))
        self.bind("<Button-5>", lambda e: self._zoom_at(e.x, 1.25))
        self.bind("<ButtonPress-3>", self._pan_start)
        self.bind("<B3-Motion>", self._pan_move)

    # ---- adat ------------------------------------------------------------
    def set_audio(self, audio):
        self.audio = audio
        self.markers.clear()
        self.regions.clear()
        self.zoom_full()

    def set_marker(self, name: str, index: int, color: str, label: str = "",
                   draggable: bool = True):
        self.markers[name] = (int(index), color, label, draggable)

    def remove_marker(self, name: str):
        self.markers.pop(name, None)

    def zoom_full(self):
        if self.audio is not None:
            self.v0, self.v1 = 0, self.audio.frames
        self.redraw()

    def focus_on(self, index: int, span: int):
        if self.audio is None:
            return
        span = max(8, span)
        self.v0 = int(index - span // 2)
        self.v1 = self.v0 + span
        self.redraw()

    # ---- koordináták ------------------------------------------------------
    def _w(self):
        return max(self.winfo_width(), 50)

    def x_of(self, idx: float) -> float:
        return (idx - self.v0) / max(1e-9, (self.v1 - self.v0)) * self._w()

    def idx_of(self, x: float) -> int:
        return int(round(self.v0 + x / self._w() * (self.v1 - self.v0)))

    # ---- rajzolás --------------------------------------------------------
    def redraw(self):
        self.delete("all")
        w = self._w()
        h = max(self.winfo_height(), 40)
        if self.audio is None:
            self.create_text(w / 2, h / 2, text="Tölts be egy WAV fájlt…", fill=T.MUTED,
                             font=T.FONT_H2)
            return
        x = self.audio.samples
        n = x.shape[0]
        top = 18 if self.show_ruler else 2
        ch = x.shape[1]
        lane = (h - top) / ch

        for (a, b, col) in self.regions:
            xa, xb = self.x_of(a), self.x_of(b)
            if xb >= 0 and xa <= w:
                self.create_rectangle(max(0, xa), top, min(w, xb), h,
                                      fill=T.blend(T.BG2, col, 0.22), outline="")

        lo, hi = max(0, self.v0), min(n, self.v1)
        for c in range(ch):
            y0 = top + lane * c
            mid = y0 + lane / 2
            amp = lane / 2 - 3
            self.create_line(0, mid, w, mid, fill=T.BORDER)
            if hi - lo < 2:
                continue
            col = T.CYAN if c == 0 else T.MAGENTA
            seg = x[lo:hi, c]
            spp = (self.v1 - self.v0) / w
            if spp > 1.5:
                cols = int(min(w, (hi - lo) / spp))
                edges = np.linspace(0, seg.size, max(cols, 1) + 1).astype(int)
                edges = np.unique(np.clip(edges, 0, seg.size - 1))
                mx = np.maximum.reduceat(seg, edges)
                mn = np.minimum.reduceat(seg, edges)
                xs = self.x_of(lo + edges)
                coords = []
                for xi, a, b in zip(xs, mx, mn):
                    coords.append((xi, mid - a * amp, xi, mid - b * amp))
                for xa_, ya, xb_, yb in coords:
                    self.create_line(xa_, ya, xb_, yb + 1, fill=col)
            else:
                idx = np.arange(lo, hi)
                xs = self.x_of(idx)
                ys = mid - seg * amp
                pts = np.column_stack([xs, ys]).ravel().tolist()
                if len(pts) >= 4:
                    self.create_line(pts, fill=col, width=1.5)
                if self.show_dots and spp < 0.25:
                    for xi, yi in zip(xs, ys):
                        self.create_oval(xi - 2, yi - 2, xi + 2, yi + 2, fill=col, outline="")

        if self.show_ruler:
            self._ruler(w)
        for name, (idx, colr, label, _d) in self.markers.items():
            xm = self.x_of(idx)
            if -2 <= xm <= w + 2:
                self.create_line(xm, top, xm, h, fill=colr, width=2)
                self.create_polygon(xm - 6, top, xm + 6, top, xm, top + 9, fill=colr)
                if label:
                    self.create_text(xm + 8, top + 10, text=label, anchor="w", fill=colr,
                                     font=T.FONT_SMALL)

    def _ruler(self, w):
        rate = self.audio.rate
        span_s = (self.v1 - self.v0) / rate
        if span_s <= 0:
            return
        raw = span_s / 8
        mag = 10 ** math.floor(math.log10(raw))
        step = min((m * mag for m in (1, 2, 5, 10) if m * mag >= raw), default=mag)
        t = math.ceil(self.v0 / rate / step) * step
        self.create_rectangle(0, 0, w, 16, fill=T.BG, outline="")
        while t * rate < self.v1:
            xm = self.x_of(t * rate)
            self.create_line(xm, 10, xm, 16, fill=T.MUTED)
            label = f"{t * 1000:.1f} ms" if span_s < 0.5 else f"{t:.3f} s"
            self.create_text(xm + 3, 7, text=label, anchor="w", fill=T.MUTED,
                             font=(T.FONT_FAMILY, 7))
            t += step

    # ---- egér -------------------------------------------------------------
    def _press(self, e):
        best, bd = None, 8
        for name, (idx, _c, _l, drag) in self.markers.items():
            d = abs(self.x_of(idx) - e.x)
            if drag and d < bd:
                best, bd = name, d
        self._drag = best

    def _motion(self, e):
        if self._drag and self.audio is not None:
            idx = int(np.clip(self.idx_of(e.x), 0, self.audio.frames - 1))
            _, c, l, d = self.markers[self._drag]
            self.markers[self._drag] = (idx, c, l, d)
            self.redraw()

    def _release(self, _e):
        if self._drag and self.on_marker:
            self.on_marker(self._drag, self.markers[self._drag][0])
        self._drag = None

    def _wheel(self, e):
        self._zoom_at(e.x, 0.8 if e.delta > 0 else 1.25)

    def _shift_wheel(self, e):
        span = self.v1 - self.v0
        shift = int(span * (-0.15 if e.delta > 0 else 0.15))
        self.v0 += shift
        self.v1 += shift
        self.redraw()

    def _zoom_at(self, x, factor):
        if self.audio is None:
            return
        center = self.idx_of(x)
        span = max(16, int((self.v1 - self.v0) * factor))
        span = min(span, self.audio.frames * 2)
        frac = x / self._w()
        self.v0 = int(center - span * frac)
        self.v1 = self.v0 + span
        self.redraw()

    def _pan_start(self, e):
        self._pan = (e.x, self.v0, self.v1)

    def _pan_move(self, e):
        if not self._pan:
            return
        x0, a, b = self._pan
        d = int((x0 - e.x) / self._w() * (b - a))
        self.v0, self.v1 = a + d, b + d
        self.redraw()


# ----------------------------------------------------------------------
class SeamView(tk.Canvas):
    """A loop illesztési pontjának nagyítója: [end-N..end] | [start..start+N]."""

    def __init__(self, master, height: int = 120):
        super().__init__(master, height=height, bg=T.BG2, highlightthickness=1,
                         highlightbackground=T.BORDER)
        self.data = None
        self.bind("<Configure>", lambda e: self.redraw())

    def show(self, samples: Optional[np.ndarray], start: int = 0, end: int = 0,
             n: int = 120):
        if samples is None:
            self.data = None
        else:
            n = min(n, end - start)
            a = samples[max(0, end - n + 1):end + 1].mean(axis=1)
            b = samples[start:start + n].mean(axis=1)
            self.data = (a, b)
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 50), max(self.winfo_height(), 40)
        self.create_text(8, 10, text="Loop illesztés (vége ⟶ eleje)", anchor="w",
                         fill=T.MUTED, font=T.FONT_SMALL)
        if self.data is None:
            return
        a, b = self.data
        y = np.concatenate([a, b])
        peak = max(float(np.max(np.abs(y))), 1e-6)
        mid = h / 2 + 6
        amp = (h / 2 - 14) / peak
        self.create_line(0, mid, w, mid, fill=T.BORDER)
        xs = np.linspace(4, w - 4, y.size)
        pts = np.column_stack([xs, mid - y * amp]).ravel().tolist()
        seam = xs[a.size - 1] + (xs[1] - xs[0]) / 2 if y.size > 1 else w / 2
        self.create_rectangle(seam, 18, w, h, fill=T.blend(T.BG2, T.LIME, 0.08), outline="")
        if len(pts) >= 4:
            self.create_line(pts, fill=T.LIME, width=2)
        self.create_line(seam, 18, seam, h, fill=T.ORANGE, dash=(4, 3))


# ----------------------------------------------------------------------
class PianoKeyboard(tk.Canvas):
    """Billentyűzet a zónák és alaphangok megjelenítésére (Yamaha oktávszámozás)."""

    BLACK = {1, 3, 6, 8, 10}

    def __init__(self, master, low: int = 24, high: int = 108, height: int = 110):
        super().__init__(master, height=height, bg=T.BG, highlightthickness=0)
        self.low, self.high = low, high
        self.zones: List[Tuple[int, int, int, str, str]] = []
        self.selected: Optional[int] = None
        self.bind("<Configure>", lambda e: self.redraw())

    def set_zones(self, zones, selected_root: Optional[int] = None):
        self.zones = list(zones)
        self.selected = selected_root
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 200), max(self.winfo_height(), 60)
        whites = [n for n in range(self.low, self.high + 1) if n % 12 not in self.BLACK]
        ww = w / len(whites)
        zone_h = 22
        key_top = zone_h + 4
        pos = {}
        for i, n in enumerate(whites):
            pos[n] = i * ww
        for (root, lo, hi, col, label) in self.zones:
            xs = [self._x(n, pos, ww) for n in (max(lo, self.low), min(hi, self.high))]
            if xs[0] is None or xs[1] is None:
                continue
            sel = root == self.selected
            self.create_rectangle(xs[0][0], 2, xs[1][1], zone_h,
                                  fill=T.blend(T.BG, col, 0.75 if sel else 0.4),
                                  outline=col)
            self.create_text((xs[0][0] + xs[1][1]) / 2, zone_h / 2 + 1, text=label,
                             fill=T.TEXT, font=(T.FONT_FAMILY, 7))
        roots = {z[0]: z[3] for z in self.zones}
        for n in whites:
            x = pos[n]
            fill = T.blend("#ffffff", roots[n], 0.7) if n in roots else "#e9ecff"
            self.create_rectangle(x, key_top, x + ww - 1, h - 2, fill=fill, outline=T.BG2)
            if n % 12 == 0:
                self.create_text(x + ww / 2, h - 10, text=note_name(n), fill=T.BG,
                                 font=(T.FONT_FAMILY, 7, "bold"))
        for n in range(self.low, self.high + 1):
            if n % 12 in self.BLACK and n - 1 in pos:
                x = pos[n - 1] + ww * 0.65
                fill = roots.get(n, "#151a33")
                self.create_rectangle(x, key_top, x + ww * 0.7, key_top + (h - key_top) * 0.6,
                                      fill=fill, outline=T.BG)

    def _x(self, n, pos, ww):
        if n in pos:
            return pos[n], pos[n] + ww
        if n - 1 in pos:
            return pos[n - 1] + ww * 0.65, pos[n - 1] + ww * 1.35
        return None


class LogBox(tk.Text):
    def __init__(self, master, height=7):
        super().__init__(master, height=height, bg=T.BG2, fg=T.TEXT, insertbackground=T.CYAN,
                         relief="flat", font=T.FONT_MONO, wrap="word",
                         highlightthickness=1, highlightbackground=T.BORDER)
        self.tag_configure("ok", foreground=T.LIME)
        self.tag_configure("warn", foreground=T.ORANGE)
        self.tag_configure("err", foreground=T.RED)
        self.tag_configure("info", foreground=T.CYAN)
        self.configure(state="disabled")

    def log(self, text: str, tag: str = ""):
        self.configure(state="normal")
        self.insert("end", text + "\n", tag)
        self.see("end")
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")
