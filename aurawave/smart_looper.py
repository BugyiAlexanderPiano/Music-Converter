"""3. modul: Smart Looper & Key Mapper (vonósok, fúvósok, padek)."""

from __future__ import annotations

import csv
import os
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from . import dsp
from . import theme as T
from .audio_io import AudioData, Player, WavError, read_wav, write_wav
from .midi_io import note_name
from .widgets import AnimatedBanner, LogBox, PianoKeyboard, SeamView, WaveformView

ZONE_COLORS = [T.CYAN, T.MAGENTA, T.LIME, T.ORANGE, T.VIOLET, "#4fa3ff", "#ff5c8a"]


@dataclass
class LoopItem:
    path: str
    audio: AudioData
    root: int
    pitch_hz: Optional[float]
    instrument: str
    extra: str = ""
    tag_override: str = ""
    loop: Optional[tuple] = None
    score: float = 0.0
    processed: Optional[AudioData] = None
    xfade_samples: int = 0
    status: str = "betöltve"

    def tag(self) -> str:
        return self.tag_override.strip() or dsp.quality_tag(self.score)

    def filename(self, dyn: bool) -> str:
        extras = [self.extra] if self.extra.strip() else []
        if dyn:
            extras.append(dsp.dynamics_tag(self.audio))
        return dsp.smart_filename(self.root, self.instrument, self.tag(), extras,
                                  looped=self.loop is not None)


class SmartLooperWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Smart Looper & Key Mapper")
        self.configure(bg=T.BG)
        self.geometry("1320x920")
        self.minsize(1080, 780)
        self.items: List[LoopItem] = []
        self.cur: Optional[LoopItem] = None
        self.player = Player()
        self._loading = False

        AnimatedBanner(self, "Smart Looper & Key Mapper",
                       "Crossfade loop vonósokhoz / fúvósokhoz  •  hangmagasság-felismerés  •  "
                       "okos fájlnevek billentyű-kiosztáshoz", T.LIME).pack(fill="x")
        self._build_toolbar()
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=12, pady=8)
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)
        self._build_list(main)
        self._build_editor(main)
        self.keyboard = PianoKeyboard(self, height=96)
        self.keyboard.pack(fill="x", padx=12)
        self.log = LogBox(self, height=4)
        self.log.pack(fill="x", padx=12, pady=(6, 10))
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self, style="Panel.TFrame", padding=10)
        bar.pack(fill="x", padx=12, pady=(10, 0))
        ttk.Button(bar, text="📂  Minták betöltése", style="Accent.TButton",
                   command=self.load).pack(side="left")
        ttk.Button(bar, text="∞  Mind loopolása", command=self.loop_all).pack(side="left", padx=8)
        ttk.Button(bar, text="💾  Kijelölt mentése…", style="Hot.TButton",
                   command=self.save_selected).pack(side="right")
        ttk.Button(bar, text="💾  Mind mentése…", command=self.save_all).pack(side="right",
                                                                            padx=8)
        self.dyn_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Dinamika címke a névben (Soft/Med/Hard)",
                        variable=self.dyn_var, command=self._refresh_list
                        ).pack(side="right", padx=12)

    def _build_list(self, parent):
        lf = ttk.LabelFrame(parent, text="  Minták  ", padding=6)
        lf.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        cols = ("file", "note", "loop", "name")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", height=18)
        for c, t, w in (("file", "Forrás", 150), ("note", "Hang", 60),
                        ("loop", "Loop", 70), ("name", "Mentési név", 230)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w" if c in ("file", "name") else "center")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _build_editor(self, parent):
        ed = ttk.Frame(parent)
        ed.grid(row=0, column=1, sticky="nsew")
        self.wave = WaveformView(ed, height=230, on_marker=self._marker_moved)
        self.wave.pack(fill="both", expand=True)
        self.seam = SeamView(ed, height=110)
        self.seam.pack(fill="x", pady=(6, 0))

        ctl = ttk.Frame(ed, style="Panel.TFrame", padding=8)
        ctl.pack(fill="x", pady=(6, 0))
        for i in range(3):
            ctl.columnconfigure(i, weight=1)

        nm = ttk.LabelFrame(ctl, text="  Hang & elnevezés  ", padding=6)
        nm.grid(row=0, column=0, sticky="nsew")
        ttk.Label(nm, text="Hangszer:", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.inst_var = tk.StringVar(value="Strings")
        ic = ttk.Combobox(nm, textvariable=self.inst_var, values=dsp.INSTRUMENTS, width=14)
        ic.grid(row=0, column=1, sticky="w", pady=2)
        ic.bind("<<ComboboxSelected>>", lambda e: self._apply_fields())
        ic.bind("<KeyRelease>", lambda e: self._apply_fields())
        ttk.Label(nm, text="Alaphang (MIDI):", style="Panel.TLabel").grid(row=1, column=0,
                                                                         sticky="w")
        rf = ttk.Frame(nm, style="Panel.TFrame")
        rf.grid(row=1, column=1, sticky="w")
        self.root_var = tk.IntVar(value=60)
        ttk.Spinbox(rf, from_=0, to=127, textvariable=self.root_var, width=5,
                    command=self._apply_fields).pack(side="left")
        self.root_lbl = ttk.Label(rf, text="C3", style="Value.TLabel", width=12)
        self.root_lbl.pack(side="left", padx=4)
        ttk.Label(nm, text="Extra címke:", style="Panel.TLabel").grid(row=2, column=0, sticky="w")
        self.extra_var = tk.StringVar()
        e1 = ttk.Entry(nm, textvariable=self.extra_var, width=14)
        e1.grid(row=2, column=1, sticky="w", pady=2)
        e1.bind("<KeyRelease>", lambda e: self._apply_fields())
        ttk.Label(nm, text="Minőség címke:", style="Panel.TLabel").grid(row=3, column=0,
                                                                       sticky="w")
        self.tag_var = tk.StringVar()
        e2 = ttk.Entry(nm, textvariable=self.tag_var, width=14)
        e2.grid(row=3, column=1, sticky="w", pady=2)
        e2.bind("<KeyRelease>", lambda e: self._apply_fields())
        ttk.Label(nm, text="(üres = automatikus: Clean / Smooth / XFade)",
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Button(nm, text="🎵 Hangmagasság újraérzékelése", command=self.redetect
                   ).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        lp = ttk.LabelFrame(ctl, text="  Loop & crossfade  ", padding=6)
        lp.grid(row=0, column=1, sticky="nsew", padx=8)
        self.xf_var = tk.DoubleVar(value=120.0)
        self.minlen_var = tk.DoubleVar(value=0.6)
        self._scale(lp, "Crossfade (ms)", self.xf_var, 5, 600, 0, self._reprocess)
        self._scale(lp, "Min. loop hossz (s)", self.minlen_var, 0.1, 4.0, 1, None)
        self.curve_var = tk.StringVar(value="equal_power")
        rb = ttk.Frame(lp, style="Panel.TFrame")
        rb.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(rb, text="Equal-power", value="equal_power", variable=self.curve_var,
                        command=self._reprocess).pack(side="left")
        ttk.Radiobutton(rb, text="Lineáris", value="linear", variable=self.curve_var,
                        command=self._reprocess).pack(side="left", padx=8)
        self.release_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(lp, text="Loop utáni rész (release) megtartása",
                        variable=self.release_var, command=self._reprocess
                        ).grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Button(lp, text="∞  Auto loop keresés", style="Accent.TButton",
                   command=self.loop_selected).grid(row=4, column=0, columnspan=3,
                                                    sticky="ew", pady=(4, 0))

        pv = ttk.LabelFrame(ctl, text="  Előhallgatás & állapot  ", padding=6)
        pv.grid(row=0, column=2, sticky="nsew")
        self.stat_lbl = ttk.Label(pv, text="—", style="Value.TLabel", justify="left")
        self.stat_lbl.pack(anchor="w")
        bf = ttk.Frame(pv, style="Panel.TFrame")
        bf.pack(fill="x", pady=(6, 0))
        ttk.Button(bf, text="▶ Loop ×4", command=self.preview).pack(side="left")
        ttk.Button(bf, text="▶ Eredeti", command=self.preview_orig).pack(side="left", padx=4)
        ttk.Button(bf, text="■ Stop", command=self.player.stop).pack(side="left")

    def _scale(self, parent, text, var, lo, hi, row, cmd):
        ttk.Label(parent, text=text, style="Panel.TLabel").grid(row=row, column=0, sticky="w")
        val = ttk.Label(parent, text=f"{var.get():.1f}", style="Value.TLabel", width=6)

        def changed(v):
            val.configure(text=f"{float(v):.1f}")

        s = ttk.Scale(parent, from_=lo, to=hi, variable=var, length=140, command=changed)
        s.grid(row=row, column=1, padx=4)
        val.grid(row=row, column=2)
        if cmd:
            s.bind("<ButtonRelease-1>", lambda e: cmd())

    # ------------------------------------------------------------------
    def load(self):
        paths = filedialog.askopenfilenames(parent=self, title="Hangminták (WAV) kiválasztása",
                                            filetypes=[("WAV", "*.wav *.WAV"), ("Minden", "*.*")])
        if not paths:
            return
        self.configure(cursor="watch")
        for p in paths:
            try:
                a = read_wav(p)
            except (WavError, OSError) as exc:
                self.log.log(f"✖ {os.path.basename(p)}: {exc}", "err")
                continue
            fname = os.path.basename(p)
            root = dsp.note_from_filename(os.path.splitext(fname)[0])
            hz = None
            if a.root_note is not None and root is None:
                root = a.root_note
            freq, conf = dsp.detect_pitch(a)
            if freq and conf > 0.5:
                hz = freq
                if root is None:
                    root = dsp.freq_to_midi(freq)[0]
            if root is None:
                root = 60
            item = LoopItem(p, a, int(root), hz, dsp.guess_instrument(fname))
            if a.loop:
                item.loop = a.loop
                item.score = dsp.loop_similarity(a, *a.loop)
                item.status = "meglévő loop"
                self._process(item)
            self.items.append(item)
            self.log.log(f"Betöltve: {fname} → {note_name(item.root)}"
                         + (f" ({hz:.1f} Hz)" if hz else ""), "ok")
            self.update_idletasks()
        self.configure(cursor="")
        self._refresh_list()
        if self.items and not self.cur:
            self.tree.selection_set(str(0))

    def _refresh_list(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.items):
            loop = f"{it.score * 100:.1f}%" if it.loop else "—"
            self.tree.insert("", "end", iid=str(i), values=(
                os.path.basename(it.path), note_name(it.root), loop,
                it.filename(self.dyn_var.get())))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel)
        self._refresh_keys()

    def _refresh_keys(self):
        roots = [it.root for it in self.items]
        zones = []
        for i, (r, lo, hi) in enumerate(dsp.key_zones(roots)):
            zones.append((r, lo, hi, ZONE_COLORS[i % len(ZONE_COLORS)], note_name(r)))
        self.keyboard.set_zones(zones, self.cur.root if self.cur else None)

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.cur = self.items[int(sel[0])]
        it = self.cur
        self._loading = True
        self.inst_var.set(it.instrument)
        self.root_var.set(it.root)
        self.extra_var.set(it.extra)
        self.tag_var.set(it.tag_override)
        self._loading = False
        self.root_lbl.configure(text=self._root_text(it))
        self.wave.set_audio(it.audio)
        self._show_loop()
        self._refresh_keys()

    def _root_text(self, it: LoopItem) -> str:
        t = note_name(it.root)
        if it.pitch_hz:
            n, cents = dsp.freq_to_midi(it.pitch_hz)
            if n == it.root:
                t += f" {cents:+.0f}c"
        return t

    def _apply_fields(self):
        if self._loading or not self.cur:
            return
        it = self.cur
        it.instrument = self.inst_var.get().strip() or "Sample"
        try:
            it.root = max(0, min(127, int(self.root_var.get())))
        except (tk.TclError, ValueError):
            pass
        it.extra = self.extra_var.get()
        it.tag_override = self.tag_var.get()
        if it.processed is not None:
            it.processed.root_note = it.root
        self.root_lbl.configure(text=self._root_text(it))
        self._refresh_list()

    def redetect(self):
        if not self.cur:
            return
        freq, conf = dsp.detect_pitch(self.cur.audio)
        if not freq:
            messagebox.showinfo("Hangmagasság", "Nem sikerült megbízható hangmagasságot "
                                                "érzékelni – add meg kézzel.", parent=self)
            return
        n, cents = dsp.freq_to_midi(freq)
        self.cur.pitch_hz = freq
        self.root_var.set(n)
        self._apply_fields()
        self.log.log(f"{freq:.2f} Hz → {note_name(n)} ({cents:+.1f} cent, "
                     f"megbízhatóság {conf * 100:.0f}%)", "info")

    # ------------------------------------------------------------------
    def _find_loop(self, it: LoopItem) -> bool:
        try:
            lr = dsp.find_best_loop(it.audio, min_loop_s=float(self.minlen_var.get()))
        except ValueError as exc:
            self.log.log(f"✖ {os.path.basename(it.path)}: {exc}", "err")
            it.status = "hiba"
            return False
        it.loop = (lr.start, lr.end)
        it.score = lr.score
        it.status = "loopolva"
        self._process(it)
        return True

    def _process(self, it: LoopItem):
        if not it.loop:
            return
        s, e = it.loop
        it.processed, it.xfade_samples = dsp.apply_loop_crossfade(
            it.audio, s, e, float(self.xf_var.get()), self.curve_var.get(),
            self.release_var.get())
        it.processed.root_note = it.root

    def _reprocess(self):
        for it in self.items:
            self._process(it)
        self._show_loop()

    def loop_selected(self):
        if not self.cur:
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        ok = self._find_loop(self.cur)
        self.configure(cursor="")
        if ok:
            self.log.log(f"Loop: {self.cur.loop[0]} → {self.cur.loop[1]}  "
                         f"illeszkedés {self.cur.score * 100:.2f}%", "ok")
        self._refresh_list()
        self._show_loop()

    def loop_all(self):
        if not self.items:
            return
        self.configure(cursor="watch")
        for it in self.items:
            if self._find_loop(it):
                self.log.log(f"✔ {os.path.basename(it.path)}: {it.score * 100:.2f}%", "ok")
            self.update_idletasks()
        self.configure(cursor="")
        self._refresh_list()
        self._show_loop()

    def _marker_moved(self, name, idx):
        it = self.cur
        if not it or not it.loop:
            return
        idx = dsp.snap_rising_zero(it.audio, idx)
        s, e = it.loop
        if name == "ls":
            s = min(idx, e - 64)
        elif name == "le":
            e = max(idx, s + 64)
        else:
            return
        it.loop = (s, e)
        it.score = dsp.loop_similarity(it.audio, s, e)
        it.status = "kézi loop"
        self._process(it)
        self._refresh_list()
        self._show_loop()

    def _show_loop(self):
        it = self.cur
        if not it:
            return
        self.wave.markers.clear()
        self.wave.regions = []
        if it.loop:
            s, e = it.loop
            L = it.xfade_samples
            self.wave.regions = [(s, e, T.LIME), (e - L, e, T.ORANGE)]
            self.wave.set_marker("ls", s, T.LIME, "LOOP START")
            self.wave.set_marker("le", e, T.ORANGE, "LOOP END")
            src = it.processed.samples if it.processed is not None else it.audio.samples
            self.seam.show(src, s, e)
            r = it.audio.rate
            err = dsp.loop_seam_error(src, s, e)
            self.stat_lbl.configure(text=(
                f"Loop: {s / r:.3f} s → {e / r:.3f} s  ({(e - s) / r:.3f} s)\n"
                f"Illeszkedés: {it.score * 100:.2f}%  →  {it.tag()}\n"
                f"Crossfade: {L / r * 1000:.0f} ms ({L} minta)\n"
                f"Illesztési ugrás: {err:.2f}× természetes lépés\n"
                f"Mentési név: {it.filename(self.dyn_var.get())}"))
        else:
            self.seam.show(None)
            self.stat_lbl.configure(text="Nincs loop – kattints az „Auto loop keresés” gombra.")
        self.wave.redraw()

    def preview(self):
        it = self.cur
        if it and it.processed is not None:
            seq = dsp.render_loop_preview(it.processed, 4)
            self.player.play(it.processed.copy_with(seq))

    def preview_orig(self):
        if self.cur:
            self.player.play(self.cur.audio)

    # ------------------------------------------------------------------
    def _output_audio(self, it: LoopItem) -> AudioData:
        if it.processed is not None:
            out = it.processed
        else:
            out = it.audio.copy_with(it.audio.samples, loop=None)
        out.root_note = it.root
        return out

    def save_selected(self):
        it = self.cur
        if not it:
            messagebox.showinfo("Mentés", "Válassz ki egy mintát a listából!", parent=self)
            return
        if not it.loop and not messagebox.askyesno(
                "Mentés", "Ennek a mintának még nincs loopja. Mented loop nélkül?", parent=self):
            return
        name = it.filename(self.dyn_var.get())
        out = filedialog.asksaveasfilename(
            parent=self, title="Hova szeretnéd menteni a loopolt mintát?",
            initialdir=os.path.dirname(it.path), initialfile=name, defaultextension=".wav",
            filetypes=[("WAV", "*.wav")])
        if not out:
            return
        write_wav(out, self._output_audio(it))
        self.log.log(f"Mentve: {out}", "ok")

    def save_all(self):
        if not self.items:
            return
        dst = filedialog.askdirectory(parent=self, title="Melyik mappába mentsem a mintákat?")
        if not dst:
            return
        names = [it.filename(self.dyn_var.get()) for it in self.items]
        dup = {n for n in names if names.count(n) > 1}
        preview = "\n".join(names[:20]) + ("\n…" if len(names) > 20 else "")
        msg = f"{len(names)} fájl kerül ide:\n{dst}\n\n{preview}"
        if dup:
            msg += "\n\nAzonos nevek sorszámot kapnak (_02, _03…)."
        msg += "\n\nKészüljön billentyűkiosztás-táblázat (KeyMap.csv) is?"
        ans = messagebox.askyesnocancel("Mentés megerősítése", msg, parent=self)
        if ans is None:
            return
        zones = {r: (lo, hi) for r, lo, hi in dsp.key_zones([it.root for it in self.items])}
        rows = []
        for it, name in zip(self.items, names):
            out = dsp.unique_path(os.path.join(dst, name))
            write_wav(out, self._output_audio(it))
            lo, hi = zones[it.root]
            rows.append([os.path.basename(out), note_name(it.root), it.root, note_name(lo),
                         note_name(hi), it.loop[0] if it.loop else "", it.loop[1] if it.loop
                         else "", f"{it.score * 100:.2f}" if it.loop else ""])
            self.log.log(f"✔ {os.path.basename(out)}", "ok")
        if ans:
            with open(os.path.join(dst, "KeyMap.csv"), "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["Fájl", "Alaphang", "MIDI", "Zóna alja", "Zóna teteje",
                            "Loop start", "Loop end", "Illeszkedés %"])
                w.writerows(rows)
            self.log.log("KeyMap.csv elkészült (Yamaha Expansion Manager kiosztáshoz).", "info")
        messagebox.showinfo("Mentés", f"{len(rows)} minta mentve ide:\n{dst}", parent=self)

    def _close(self):
        self.player.stop()
        self.destroy()
