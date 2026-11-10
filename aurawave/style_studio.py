"""1. modul: Stílus Konverter & Ütem Szeletelő (Style Studio)."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from . import theme as T
from .midi_io import MidiError, note_name
from .sty_converter import (SECTION_HINTS, SECTION_NAMES, STYLE_PARTS, Section, StyleSource,
                            convert_to_sty, default_output_name)
from .widgets import AnimatedBanner, LogBox

SKIP = "— kihagyás —"
PART_COLORS = {8: "#ff7a59", 9: T.ORANGE, 10: T.LIME, 11: T.CYAN, 12: "#4fa3ff",
               13: T.VIOLET, 14: T.MAGENTA, 15: "#ff5c8a"}
SECTION_COLORS = {"Intro": T.LIME, "Main": T.CYAN, "Fill": T.ORANGE, "Ending": T.MAGENTA}


def section_color(name: str) -> str:
    for k, v in SECTION_COLORS.items():
        if name.startswith(k):
            return v
    return T.VIOLET


class StyleStudioWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Style Studio – Stílus Konverter & Ütem Szeletelő")
        self.configure(bg=T.BG)
        self.geometry("1280x860")
        self.minsize(1050, 720)
        self.source: Optional[StyleSource] = None
        self.sections: List[Section] = []
        self.map_vars: Dict[int, tk.StringVar] = {}
        self._drag_bar = None
        self.px_per_bar = 40

        AnimatedBanner(self, "Style Studio",
                       "Roland STL / MIDI  →  Yamaha Genos 2 .STY   •   100% velocity-hű "
                       "konverzió   •   egyedi ütemvágás", T.CYAN).pack(fill="x")
        self._build_toolbar()
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=(6, 0))
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)
        self._build_channels(body)
        self._build_sections(body)
        self._build_roll(body)
        self._build_bottom()

    # ------------------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self, style="Panel.TFrame", padding=10)
        bar.pack(fill="x", padx=12, pady=(10, 0))
        ttk.Button(bar, text="📂  Forrás betöltése (MIDI / STL)", style="Accent.TButton",
                   command=self.load).pack(side="left")
        self.file_lbl = ttk.Label(bar, text="Nincs betöltött fájl", style="Panel.TLabel")
        self.file_lbl.pack(side="left", padx=14)
        self.info_lbl = ttk.Label(bar, text="", style="Value.TLabel")
        self.info_lbl.pack(side="right")

    def _build_channels(self, parent):
        lf = ttk.LabelFrame(parent, text="  Csatorna-hozzárendelés (forrás → Genos sáv)  ",
                            padding=8)
        lf.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 10))
        self.chan_frame = ttk.Frame(lf, style="Panel.TFrame")
        self.chan_frame.pack(fill="both", expand=True)
        ttk.Label(self.chan_frame, text="Tölts be egy forrásfájlt…", style="Muted.TLabel"
                  ).pack(anchor="w")
        btns = ttk.Frame(lf, style="Panel.TFrame")
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Automatikus kiosztás", command=self.auto_map).pack(side="left")
        ttk.Label(lf, text="Tipp: a dobok a Ch 10-re (Rhythm 2), a basszus a Ch 11-re kerül.\n"
                           "A dallamsávokat C Maj7 akkordban érdemes felvenni.",
                  style="Muted.TLabel", justify="left").pack(anchor="w", pady=(8, 0))

    def _build_sections(self, parent):
        lf = ttk.LabelFrame(parent, text="  Szekciók és ütemvágás  ", padding=8)
        lf.grid(row=0, column=1, sticky="nsew")
        cols = ("name", "genos", "start", "end", "bars")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", height=7)
        heads = {"name": "Szekció", "genos": "Genos gomb", "start": "Kezdő ütem",
                 "end": "Záró ütem", "bars": "Hossz"}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=110 if c != "name" else 140, anchor="center")
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        ed = ttk.Frame(lf, style="Panel.TFrame")
        ed.pack(fill="x", pady=(8, 0))
        ttk.Label(ed, text="Szekció:", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.sec_var = tk.StringVar(value="Main A")
        cb = ttk.Combobox(ed, textvariable=self.sec_var, values=SECTION_NAMES,
                          state="readonly", width=14)
        cb.grid(row=0, column=1, padx=6)
        ttk.Label(ed, text="Kezdő ütem:", style="Panel.TLabel").grid(row=0, column=2)
        self.start_var = tk.IntVar(value=1)
        self.start_sp = ttk.Spinbox(ed, from_=1, to=999, textvariable=self.start_var, width=6,
                                    command=self._redraw_roll)
        self.start_sp.grid(row=0, column=3, padx=6)
        ttk.Label(ed, text="Záró ütem:", style="Panel.TLabel").grid(row=0, column=4)
        self.end_var = tk.IntVar(value=4)
        self.end_sp = ttk.Spinbox(ed, from_=1, to=999, textvariable=self.end_var, width=6,
                                  command=self._redraw_roll)
        self.end_sp.grid(row=0, column=5, padx=6)

        bb = ttk.Frame(lf, style="Panel.TFrame")
        bb.pack(fill="x", pady=(8, 0))
        ttk.Button(bb, text="➕ Hozzáadás / frissítés", command=self.add_section).pack(side="left")
        ttk.Button(bb, text="🗑 Törlés", command=self.remove_section).pack(side="left", padx=6)
        ttk.Button(bb, text="✨ Javaslat (Main A–D)", command=self.suggest).pack(side="left")
        ttk.Button(bb, text="Mind törlése", command=self.clear_sections).pack(side="left", padx=6)
        ttk.Label(lf, text="A kezdő és záró ütem is beleszámít. Tipp: az alsó kottasávon "
                           "egérrel húzva is kijelölheted az ütemeket.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

    def _build_roll(self, parent):
        lf = ttk.LabelFrame(parent, text="  Ütem-térkép (piano roll)  ", padding=6)
        lf.grid(row=1, column=1, sticky="nsew", pady=(10, 0))
        self.roll = tk.Canvas(lf, bg=T.BG2, height=230, highlightthickness=0)
        sb = ttk.Scrollbar(lf, orient="horizontal", command=self.roll.xview)
        self.roll.configure(xscrollcommand=sb.set)
        self.roll.pack(fill="both", expand=True)
        sb.pack(fill="x")
        self.roll.bind("<Configure>", lambda e: self._redraw_roll())
        self.roll.bind("<ButtonPress-1>", self._roll_press)
        self.roll.bind("<B1-Motion>", self._roll_drag)
        self.roll.bind("<ButtonRelease-1>", self._roll_release)

    def _build_bottom(self):
        bot = ttk.Frame(self, style="Panel.TFrame", padding=10)
        bot.pack(fill="x", padx=12, pady=10)
        opt = ttk.Frame(bot, style="Panel.TFrame")
        opt.pack(fill="x")
        ttk.Label(opt, text="Stílus neve:", style="Panel.TLabel").pack(side="left")
        self.name_var = tk.StringVar()
        ttk.Entry(opt, textvariable=self.name_var, width=24).pack(side="left", padx=6)
        ttk.Label(opt, text="Tempó (BPM):", style="Panel.TLabel").pack(side="left", padx=(12, 0))
        self.tempo_var = tk.DoubleVar(value=120.0)
        ttk.Spinbox(opt, from_=20, to=400, increment=1, textvariable=self.tempo_var,
                    width=7).pack(side="left", padx=6)
        self.xg_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="GM dob → Yamaha dobkészlet (Bank 127)",
                        variable=self.xg_var).pack(side="left", padx=12)
        ttk.Button(opt, text="⚡  KONVERTÁLÁS  .STY", style="Hot.TButton",
                   command=self.convert).pack(side="right")
        self.log = LogBox(bot, height=7)
        self.log.pack(fill="x", pady=(10, 0))
        self.log.log("Üdv a Style Studióban! 1) Tölts be egy MIDI/STL fájlt  2) Rendeld a "
                     "csatornákat a sávokhoz  3) Add meg a szekciók ütemeit  4) Konvertálj.",
                     "info")

    # ------------------------------------------------------------------
    def load(self):
        path = filedialog.askopenfilename(
            parent=self, title="Forrás kiválasztása",
            filetypes=[("MIDI / Roland STL / Yamaha STY", "*.mid *.midi *.kar *.rmi *.stl "
                        "*.STL *.sty *.STY *.MID"), ("Minden fájl", "*.*")])
        if not path:
            return
        try:
            self.source = StyleSource(path)
        except (MidiError, OSError, ValueError) as exc:
            messagebox.showerror("Betöltési hiba", str(exc), parent=self)
            self.log.log(f"Hiba: {exc}", "err")
            return
        s = self.source
        self.file_lbl.configure(text=os.path.basename(path))
        num, den = s.bar_map.signature_at_bar(1)
        self.info_lbl.configure(text=f"{s.bar_map.bar_count} ütem  •  {num}/{den}  •  "
                                     f"{s.tempo:.1f} BPM  •  {s.ppq} PPQ  •  "
                                     f"{len(s.notes)} hang")
        self.tempo_var.set(round(s.tempo, 2))
        self.name_var.set(s.name[:24])
        for sp in (self.start_sp, self.end_sp):
            sp.configure(to=s.bar_map.bar_count)
        self._build_channel_rows()
        self.sections = s.suggest_sections()
        self._refresh_tree()
        self.log.log(f"Betöltve: {path}", "ok")
        if s.tempo_changes > 1:
            self.log.log("Figyelem: a fájlban tempóváltások vannak – a stílus egyetlen "
                         "(beállítható) tempót kap.", "warn")
        if s.signature_changes:
            self.log.log("Figyelem: ütemmutató-váltás a fájlban – a szekciókat azonos "
                         "ütemmutatójú részből válaszd.", "warn")

    def _build_channel_rows(self):
        for w in self.chan_frame.winfo_children():
            w.destroy()
        self.map_vars.clear()
        values = [SKIP] + list(STYLE_PARTS.values())
        mapping = self.source.auto_channel_map()
        row = 0
        for ch in sorted(self.source.channels):
            ci = self.source.channels[ch]
            if ci.note_count == 0:
                continue
            kind = "Dob" if ci.is_drum else f"{note_name(ci.min_pitch)}–{note_name(ci.max_pitch)}"
            txt = (f"Ch {ch + 1:>2}  •  {ci.note_count} hang  •  {kind}\n"
                   f"         velocity {ci.min_vel}–{ci.max_vel}"
                   + (f"  •  prog {ci.program + 1}" if ci.program is not None else ""))
            ttk.Label(self.chan_frame, text=txt, style="Panel.TLabel", font=T.FONT_MONO
                      ).grid(row=row, column=0, sticky="w", pady=3)
            dst = mapping.get(ch)
            var = tk.StringVar(value=STYLE_PARTS[dst] if dst is not None else SKIP)
            cb = ttk.Combobox(self.chan_frame, textvariable=var, values=values,
                              state="readonly", width=24)
            cb.grid(row=row, column=1, padx=6)
            cb.bind("<<ComboboxSelected>>", lambda e: self._redraw_roll())
            self.map_vars[ch] = var
            row += 1

    def channel_map(self) -> Dict[int, Optional[int]]:
        rev = {v: k for k, v in STYLE_PARTS.items()}
        return {ch: rev.get(var.get()) for ch, var in self.map_vars.items()}

    def auto_map(self):
        if not self.source:
            return
        mapping = self.source.auto_channel_map()
        for ch, var in self.map_vars.items():
            dst = mapping.get(ch)
            var.set(STYLE_PARTS[dst] if dst is not None else SKIP)
        self._redraw_roll()

    # ------------------------------------------------------------------
    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.sections.sort(key=lambda s: SECTION_NAMES.index(s.name))
        for s in self.sections:
            self.tree.insert("", "end", iid=s.name, values=(
                s.name, SECTION_HINTS.get(s.name, s.name), s.start_bar, s.end_bar,
                f"{s.bar_count} ütem"))
        self._redraw_roll()

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        s = next((x for x in self.sections if x.name == sel[0]), None)
        if s:
            self.sec_var.set(s.name)
            self.start_var.set(s.start_bar)
            self.end_var.set(s.end_bar)
            self._redraw_roll()

    def _read_range(self):
        try:
            a, b = int(self.start_var.get()), int(self.end_var.get())
        except (tk.TclError, ValueError):
            raise ValueError("Az ütemszám egész szám legyen")
        if a < 1 or b < a:
            raise ValueError("A záró ütem nem lehet kisebb a kezdő ütemnél")
        if self.source and b > self.source.bar_map.bar_count:
            raise ValueError(f"A forrás csak {self.source.bar_map.bar_count} ütemes")
        return a, b

    def add_section(self):
        try:
            a, b = self._read_range()
        except ValueError as exc:
            messagebox.showwarning("Ütemvágás", str(exc), parent=self)
            return
        name = self.sec_var.get()
        self.sections = [s for s in self.sections if s.name != name]
        self.sections.append(Section(name, a, b))
        self._refresh_tree()
        self.log.log(f"{name}: {a}. – {b}. ütem ({b - a + 1} ütem)", "info")
        # következő szekció automatikus előkészítése
        idx = SECTION_NAMES.index(name)
        used = {s.name for s in self.sections}
        nxt = next((n for n in SECTION_NAMES[idx + 1:] if n not in used), None)
        if nxt:
            self.sec_var.set(nxt)
            span = b - a
            total = self.source.bar_map.bar_count if self.source else 999
            if b + 1 <= total:
                self.start_var.set(b + 1)
                self.end_var.set(min(total, b + 1 + span))

    def remove_section(self):
        for iid in self.tree.selection():
            self.sections = [s for s in self.sections if s.name != iid]
        self._refresh_tree()

    def clear_sections(self):
        self.sections = []
        self._refresh_tree()

    def suggest(self):
        if self.source:
            self.sections = self.source.suggest_sections()
            self._refresh_tree()

    # ------------------------------------------------------------------
    def _redraw_roll(self):
        cv = self.roll
        cv.delete("all")
        h = max(cv.winfo_height(), 120)
        w = max(cv.winfo_width(), 300)
        if not self.source:
            cv.create_text(w / 2, h / 2, text="Itt jelenik meg a forrás ütemtérképe",
                           fill=T.MUTED, font=T.FONT_H2)
            return
        s = self.source
        bars = s.bar_map.bar_count
        self.px_per_bar = max(28.0, (w - 10) / max(bars, 1))
        total_w = self.px_per_bar * bars + 10
        cv.configure(scrollregion=(0, 0, total_w, h))
        top = 34
        cmap = self.channel_map()

        def bx(bar):  # 1-alapú ütem bal széle
            return 5 + (bar - 1) * self.px_per_bar

        for sec in self.sections:
            col = section_color(sec.name)
            cv.create_rectangle(bx(sec.start_bar), 16, bx(sec.end_bar + 1), h,
                                fill=T.blend(T.BG2, col, 0.18), outline=col)
            cv.create_text(bx(sec.start_bar) + 4, 24, text=sec.name, anchor="w", fill=col,
                           font=(T.FONT_FAMILY, 8, "bold"))
        try:
            a, b = self._read_range()
            cv.create_rectangle(bx(a), 14, bx(b + 1), h, outline=T.TEXT, dash=(5, 3), width=2)
        except ValueError:
            pass

        for bar in range(1, bars + 2):
            x = bx(bar)
            cv.create_line(x, 14, x, h, fill=T.BORDER)
            if bar <= bars and (self.px_per_bar >= 22 or bar % 4 == 1):
                cv.create_text(x + self.px_per_bar / 2, 7, text=str(bar), fill=T.MUTED,
                               font=(T.FONT_FAMILY, 7))

        if s.notes:
            lo = min(n.pitch for n in s.notes)
            hi = max(n.pitch for n in s.notes)
            span = max(12, hi - lo + 1)
            ph = (h - top - 4) / span
            for n in s.notes:
                b0 = self._tick_to_x(n.on_tick)
                b1 = self._tick_to_x(n.off_tick if n.off_tick is not None else n.on_tick + s.ppq // 4)
                y = h - 4 - (n.pitch - lo + 1) * ph
                dst = cmap.get(n.channel)
                col = PART_COLORS.get(dst, "#3a4370") if dst is not None else "#3a4370"
                shade = T.blend(T.BG2, col, 0.35 + 0.65 * n.velocity / 127)
                cv.create_rectangle(b0, y, max(b0 + 2, b1), y + max(2, ph), fill=shade,
                                    outline="")

    def _tick_to_x(self, tick: int) -> float:
        bm = self.source.bar_map
        import bisect
        i = max(0, bisect.bisect_right(bm.bar_starts, tick) - 1)
        i = min(i, len(bm.bar_starts) - 2)
        a, b = bm.bar_starts[i], bm.bar_starts[i + 1]
        frac = (tick - a) / max(1, b - a)
        return 5 + (i + frac) * self.px_per_bar

    def _x_to_bar(self, x_screen) -> int:
        x = self.roll.canvasx(x_screen)
        bar = int((x - 5) // self.px_per_bar) + 1
        return max(1, min(bar, self.source.bar_map.bar_count))

    def _roll_press(self, e):
        if self.source:
            self._drag_bar = self._x_to_bar(e.x)
            self.start_var.set(self._drag_bar)
            self.end_var.set(self._drag_bar)
            self._redraw_roll()

    def _roll_drag(self, e):
        if self.source and self._drag_bar:
            b = self._x_to_bar(e.x)
            self.start_var.set(min(self._drag_bar, b))
            self.end_var.set(max(self._drag_bar, b))
            self._redraw_roll()

    def _roll_release(self, _e):
        self._drag_bar = None

    # ------------------------------------------------------------------
    def convert(self):
        if not self.source:
            messagebox.showinfo("Style Studio", "Előbb tölts be egy forrásfájlt!", parent=self)
            return
        if not self.sections:
            messagebox.showinfo("Style Studio", "Adj meg legalább egy szekciót!", parent=self)
            return
        out = filedialog.asksaveasfilename(
            parent=self, title="Hova mentsem a Genos stílust?", defaultextension=".sty",
            initialfile=(self.name_var.get().strip() or "Style") + ".sty"
            if self.name_var.get().strip() else default_output_name(self.source.path),
            filetypes=[("Yamaha Style", "*.sty")])
        if not out:
            return
        try:
            tempo = float(self.tempo_var.get())
        except (tk.TclError, ValueError):
            tempo = None
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            res = convert_to_sty(self.source, self.sections, self.channel_map(), out,
                                 tempo=tempo, style_name=self.name_var.get().strip() or None,
                                 gm_drums_to_xg=self.xg_var.get())
        except (MidiError, OSError, ValueError) as exc:
            messagebox.showerror("Konverziós hiba", str(exc), parent=self)
            self.log.log(f"Hiba: {exc}", "err")
            return
        finally:
            self.configure(cursor="")
        self.log.log("─" * 60)
        self.log.log(f"Kész: {res.output_path}", "ok")
        for name, bars, notes in res.sections:
            self.log.log(f"   {name:<11} {bars:>3} ütem   {notes:>5} hang")
        for w in res.warnings:
            self.log.log("Figyelem: " + w, "warn")
        self.log.log(res.velocity_report, "ok" if res.velocity_ok else "err")
        self.log.log("Genos 2: másold USB-re, majd STYLE > USB > a fájl. Finomhangolás: "
                     "Style Creator > Channel / Parameter.", "info")
        if res.velocity_ok:
            messagebox.showinfo("Siker", f"A stílus elkészült!\n\n{res.velocity_report}",
                                parent=self)
        else:
            messagebox.showwarning("Ellenőrzés", res.velocity_report, parent=self)
