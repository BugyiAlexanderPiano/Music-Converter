"""2. modul: Precíziós Sample Vágó (Zero-Latency)."""

from __future__ import annotations

import glob
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import numpy as np

from . import dsp
from . import theme as T
from .audio_io import AudioData, Player, WavError, read_wav, write_wav
from .widgets import AnimatedBanner, LogBox, WaveformView


class SampleCutterWindow(tk.Toplevel):
    ZOOM_MS = 6.0

    def __init__(self, master):
        super().__init__(master)
        self.title("Precíziós Sample Vágó – Zero-Latency")
        self.configure(bg=T.BG)
        self.geometry("1280x880")
        self.minsize(1000, 740)
        self.audio: Optional[AudioData] = None
        self.player = Player()
        self.start = 0
        self.end = 0
        self.onset = 0

        AnimatedBanner(self, "Precíziós Sample Vágó",
                       "Mintapontos vágás nullátmeneten  •  csend nélküli indulás = 0 ms késés "
                       "ritmusban", T.MAGENTA).pack(fill="x")
        self._build_toolbar()
        self._build_views()
        self._build_controls()
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self, style="Panel.TFrame", padding=10)
        bar.pack(fill="x", padx=12, pady=(10, 0))
        ttk.Button(bar, text="📂  WAV betöltése", style="Accent.TButton",
                   command=self.load).pack(side="left")
        ttk.Button(bar, text="📁  Mappa kötegelt vágása", command=self.batch).pack(side="left",
                                                                                  padx=8)
        self.file_lbl = ttk.Label(bar, text="Nincs betöltött fájl", style="Panel.TLabel")
        self.file_lbl.pack(side="left", padx=10)
        self.info_lbl = ttk.Label(bar, text="", style="Value.TLabel")
        self.info_lbl.pack(side="right")

    def _build_views(self):
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True, padx=12, pady=8)
        self.wave = WaveformView(f, height=260, on_marker=self._marker_moved)
        self.wave.pack(fill="both", expand=True)
        ttk.Label(f, text="Görgő: zoom  •  Shift+görgő / jobb gomb: görgetés  •  dupla "
                          "kattintás: teljes nézet  •  a színes markerek húzhatók",
                  style="TLabel", foreground=T.MUTED, font=T.FONT_SMALL).pack(anchor="w")
        zf = ttk.Frame(f)
        zf.pack(fill="x", pady=(6, 0))
        zf.columnconfigure(0, weight=1)
        zf.columnconfigure(1, weight=1)
        ttk.Label(zf, text="◀ ELEJE – mintapontos nagyítás", foreground=T.LIME
                  ).grid(row=0, column=0, sticky="w")
        ttk.Label(zf, text="VÉGE – mintapontos nagyítás ▶", foreground=T.RED
                  ).grid(row=0, column=1, sticky="e")
        self.zoom_start = WaveformView(zf, height=150, on_marker=self._marker_moved,
                                       show_ruler=True)
        self.zoom_end = WaveformView(zf, height=150, on_marker=self._marker_moved,
                                     show_ruler=True)
        self.zoom_start.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        self.zoom_end.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        for z in (self.zoom_start, self.zoom_end):
            z.bind("<Double-Button-1>", lambda e: self._update_views())

    def _build_controls(self):
        c = ttk.Frame(self, style="Panel.TFrame", padding=10)
        c.pack(fill="x", padx=12, pady=(0, 10))

        det = ttk.LabelFrame(c, text="  Automatikus érzékelés  ", padding=8)
        det.grid(row=0, column=0, sticky="nsew")
        self.th_start = tk.DoubleVar(value=-48.0)
        self.th_end = tk.DoubleVar(value=-60.0)
        self._scale(det, "Kezdő küszöb (dB a csúcshoz)", self.th_start, -90, -6, 0)
        self._scale(det, "Lecsengés küszöb (dB)", self.th_end, -100, -20, 1)
        ttk.Button(det, text="🎯  Auto vágópontok", style="Accent.TButton",
                   command=self.auto).grid(row=2, column=0, columnspan=3, sticky="ew",
                                           pady=(6, 0))

        man = ttk.LabelFrame(c, text="  Kézi finomítás (nullpontra ugrik)  ", padding=8)
        man.grid(row=0, column=1, sticky="nsew", padx=10)
        for r, (label, which) in enumerate((("Eleje", "start"), ("Vége", "end"))):
            ttk.Label(man, text=label, style="Panel.TLabel").grid(row=r, column=0, sticky="w")
            ttk.Button(man, text="◀◀ előző 0-pont",
                       command=lambda w=which: self.nudge(w, -1)).grid(row=r, column=1, padx=3,
                                                                       pady=2)
            ttk.Button(man, text="következő 0-pont ▶▶",
                       command=lambda w=which: self.nudge(w, 1)).grid(row=r, column=2, padx=3,
                                                                      pady=2)
        ttk.Button(man, text="Mindkettőt nullpontra igazít", command=self.snap_both
                   ).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        fd = ttk.LabelFrame(c, text="  Fade & formátum  ", padding=8)
        fd.grid(row=0, column=2, sticky="nsew")
        self.fade_in = tk.DoubleVar(value=0.0)
        self.fade_out = tk.DoubleVar(value=3.0)
        self._scale(fd, "Fade-in (ms) – 0 = éles tranziens", self.fade_in, 0, 10, 0)
        self._scale(fd, "Fade-out (ms)", self.fade_out, 0, 50, 1)
        ttk.Label(fd, text="Bitmélység:", style="Panel.TLabel").grid(row=2, column=0, sticky="w")
        self.bits_var = tk.StringVar(value="Eredeti")
        ttk.Combobox(fd, textvariable=self.bits_var, values=["Eredeti", "16 bit", "24 bit"],
                     state="readonly", width=10).grid(row=2, column=1, sticky="w")

        act = ttk.LabelFrame(c, text="  Eredmény  ", padding=8)
        act.grid(row=0, column=3, sticky="nsew", padx=(10, 0))
        self.res_lbl = ttk.Label(act, text="—", style="Value.TLabel", justify="left")
        self.res_lbl.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(act, text="▶ Eredeti", command=lambda: self.play(False)).grid(
            row=1, column=0, sticky="ew", pady=(6, 2))
        ttk.Button(act, text="▶ Vágott", command=lambda: self.play(True)).grid(
            row=1, column=1, sticky="ew", pady=(6, 2), padx=(4, 0))
        ttk.Button(act, text="■ Stop", command=self.player.stop).grid(row=2, column=0,
                                                                      sticky="ew")
        ttk.Button(act, text="💾 Mentés…", style="Hot.TButton", command=self.save).grid(
            row=2, column=1, sticky="ew", padx=(4, 0))
        for i in range(4):
            c.columnconfigure(i, weight=1)
        self.log = LogBox(self, height=4)
        self.log.pack(fill="x", padx=12, pady=(0, 10))

    def _scale(self, parent, text, var, lo, hi, row):
        ttk.Label(parent, text=text, style="Panel.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Scale(parent, from_=lo, to=hi, variable=var, length=150,
                  command=lambda v: val.configure(text=f"{float(v):.1f}")
                  ).grid(row=row, column=1, padx=6)
        val = ttk.Label(parent, text=f"{var.get():.1f}", style="Value.TLabel", width=6)
        val.grid(row=row, column=2)

    # ------------------------------------------------------------------
    def load(self):
        path = filedialog.askopenfilename(parent=self, title="WAV minta kiválasztása",
                                          filetypes=[("WAV", "*.wav *.WAV"), ("Minden", "*.*")])
        if not path:
            return
        try:
            self.audio = read_wav(path)
        except (WavError, OSError) as exc:
            messagebox.showerror("Betöltési hiba", str(exc), parent=self)
            return
        a = self.audio
        self.file_lbl.configure(text=os.path.basename(path))
        self.info_lbl.configure(text=f"{a.rate} Hz • {a.bits} bit{' float' if a.is_float else ''}"
                                     f" • {a.channels} csat. • {a.duration:.3f} s")
        self.wave.set_audio(a)
        self.zoom_start.set_audio(a)
        self.zoom_end.set_audio(a)
        self.log.log(f"Betöltve: {path}", "ok")
        self.auto()

    def auto(self):
        if not self.audio:
            return
        tr = dsp.auto_trim_points(self.audio, self.th_start.get(), self.th_end.get())
        self.start, self.end, self.onset = tr.start, tr.end, tr.onset
        self._update_views()

    def _marker_moved(self, name, idx):
        if not self.audio:
            return
        if name == "start":
            self.start = dsp.snap_to_zero(self.audio, idx, 1.0, "nearest")
            self.start = min(self.start, self.end - 1)
        elif name == "end":
            self.end = dsp.snap_to_zero(self.audio, idx, 1.0, "nearest")
            self.end = max(self.end, self.start + 1)
        self._update_views()

    def nudge(self, which, direction):
        if not self.audio:
            return
        mono = self.audio.mono()
        cur = self.start if which == "start" else self.end
        zc = dsp.zero_crossings(mono)
        if direction < 0:
            cand = zc[zc < cur]
            new = int(cand[-1]) if cand.size else cur
        else:
            cand = zc[zc > cur]
            new = int(cand[0]) if cand.size else cur
        if which == "start":
            self.start = min(new, self.end - 1)
        else:
            self.end = max(new, self.start + 1)
        self._update_views()

    def snap_both(self):
        if not self.audio:
            return
        self.start = dsp.snap_to_zero(self.audio, self.start, 2.0, "before")
        self.end = dsp.snap_to_zero(self.audio, self.end, 2.0, "after")
        self._update_views()

    def _update_views(self):
        a = self.audio
        if not a:
            return
        for v in (self.wave, self.zoom_start, self.zoom_end):
            v.regions = [(0, self.start, T.RED), (self.end + 1, a.frames, T.RED)]
            v.set_marker("start", self.start, T.LIME, "START")
            v.set_marker("end", self.end, T.RED, "END")
            v.set_marker("onset", self.onset, T.ORANGE, "tranziens", draggable=False)
        self.wave.redraw()
        span = int(a.rate * self.ZOOM_MS / 1000)
        self.zoom_start.focus_on(self.start + span // 4, span)
        self.zoom_end.focus_on(self.end - span // 4, span)
        lat = max(0, self.onset - self.start) * 1000 / a.rate
        sv = float(np.max(np.abs(a.samples[self.start])))
        ev = float(np.max(np.abs(a.samples[self.end])))
        cut_head = self.start * 1000 / a.rate
        self.res_lbl.configure(
            text=f"Start: {self.start} minta ({cut_head:.2f} ms levágva)\n"
                 f"End:   {self.end} minta\n"
                 f"Hossz: {(self.end - self.start + 1) / a.rate:.4f} s\n"
                 f"Késés a tranziensig: {lat:.3f} ms\n"
                 f"Érték a vágásnál: {dsp.lin_to_db(sv):.0f} / {dsp.lin_to_db(ev):.0f} dBFS")

    def _bits(self):
        v = self.bits_var.get()
        if v.startswith("16"):
            return 16, False
        if v.startswith("24"):
            return 24, False
        return None, None

    def _trimmed(self) -> AudioData:
        return dsp.apply_trim(self.audio, self.start, self.end, self.fade_in.get(),
                              self.fade_out.get())

    def play(self, trimmed: bool):
        if not self.audio:
            return
        a = self._trimmed() if trimmed else self.audio
        self.player.play(a)

    def save(self):
        if not self.audio:
            return
        base = os.path.splitext(os.path.basename(self.audio.path))[0]
        out = filedialog.asksaveasfilename(
            parent=self, title="Hova mentsem a vágott mintát?", defaultextension=".wav",
            initialdir=os.path.dirname(self.audio.path),
            initialfile=f"{base}_ZeroCut.wav", filetypes=[("WAV", "*.wav")])
        if not out:
            return
        bits, flt = self._bits()
        res = self._trimmed()
        res.root_note = None
        write_wav(out, res, bits=bits, is_float=flt, write_smpl=False)
        self.log.log(f"Mentve: {out}  ({res.frames} minta)", "ok")

    def batch(self):
        src = filedialog.askdirectory(parent=self, title="Melyik mappa WAV fájljait vágjam?")
        if not src:
            return
        dst = filedialog.askdirectory(parent=self, title="Hova mentsem a vágott fájlokat?")
        if not dst:
            return
        files = sorted(set(glob.glob(os.path.join(src, "*.wav")) +
                           glob.glob(os.path.join(src, "*.WAV"))))
        if not files:
            messagebox.showinfo("Kötegelt vágás", "Nincs WAV fájl a mappában.", parent=self)
            return
        bits, flt = self._bits()
        done = 0
        for p in files:
            try:
                a = read_wav(p)
                tr = dsp.auto_trim_points(a, self.th_start.get(), self.th_end.get())
                res = dsp.apply_trim(a, tr.start, tr.end, self.fade_in.get(),
                                     self.fade_out.get())
                res.root_note = None
                name = os.path.splitext(os.path.basename(p))[0] + "_ZeroCut.wav"
                out = dsp.unique_path(os.path.join(dst, name))
                write_wav(out, res, bits=bits, is_float=flt, write_smpl=False)
                self.log.log(f"✔ {os.path.basename(out)}  késés: {tr.latency_ms:.3f} ms", "ok")
                done += 1
            except Exception as exc:  # egy hibás fájl ne állítsa le a köteget
                self.log.log(f"✖ {os.path.basename(p)}: {exc}", "err")
            self.update_idletasks()
        messagebox.showinfo("Kötegelt vágás", f"{done}/{len(files)} fájl kész.", parent=self)

    def _close(self):
        self.player.stop()
        self.destroy()
