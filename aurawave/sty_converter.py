"""MIDI / STL -> Yamaha Genos 2 .STY stílus konverter ütem-szeletelővel.

A Yamaha stílusfájl (SFF1) egy 0-s típusú Standard MIDI File, amelyben
markerek jelölik a szekciókat ("SFF1", "SInt", "Intro A", "Main A",
"Fill In AA", "Ending A" ...). A stílus sávjai a 9-16. MIDI csatornán
szólnak:

    9  Rhythm 1 (Sub)   10 Rhythm 2 (Main)   11 Bass
    12 Chord 1          13 Chord 2           14 Pad
    15 Phrase 1         16 Phrase 2

A CASM (akkordkezelési) blokkot szándékosan NEM írjuk: hiánya esetén a
hangszer gyári alapértékeket használ (forrásakkord: C Maj7), a pontos
beállítás pedig a Genos Style Creator > Channel / Parameter menüjében
végezhető el, ahol a hangszer maga írja meg helyesen a CASM-et.

Velocity garancia: a hang-események nyers adatbájtjait változatlanul
másoljuk, csak a csatorna (státuszbájt alsó 4 bitje) és az időbélyeg
változik. A konverzió végén a kész fájlt visszaolvassuk, és hangról
hangra összevetjük a forrással (verify_conversion).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from .midi_io import (META_TEMPO, META_TIME_SIGNATURE, META_TRACK_NAME, MidiError,
                      MidiEvent, MidiFile, encode_smf, marker, meta, parse_midi_bytes,
                      tempo_bpm, tempo_event, time_signature_event)

TARGET_PPQ = 1920  # A Yamaha stílusok szabványos felbontása

# Yamaha stílus csatornák (0-alapú index -> megnevezés)
STYLE_PARTS: Dict[int, str] = {
    8: "Ch 9  - Rhythm 1 (Sub)",
    9: "Ch 10 - Rhythm 2 (Main)",
    10: "Ch 11 - Bass",
    11: "Ch 12 - Chord 1",
    12: "Ch 13 - Chord 2",
    13: "Ch 14 - Pad",
    14: "Ch 15 - Phrase 1",
    15: "Ch 16 - Phrase 2",
}

# Genos 2 szekciónevek a Yamaha szabványos sorrendjében
SECTION_NAMES: List[str] = [
    "Intro A", "Intro B", "Intro C",
    "Main A", "Main B", "Main C", "Main D",
    "Fill In AA", "Fill In BB", "Fill In CC", "Fill In DD", "Fill In BA",
    "Ending A", "Ending B", "Ending C",
]

SECTION_HINTS = {
    "Intro A": "Intro 1", "Intro B": "Intro 2", "Intro C": "Intro 3",
    "Fill In BA": "Break", "Ending A": "Ending 1", "Ending B": "Ending 2",
    "Ending C": "Ending 3",
}

SUPPORTED_INPUTS = (".mid", ".midi", ".kar", ".rmi", ".stl", ".sty", ".prs", ".bcs")


# ----------------------------------------------------------------------
# Adatszerkezetek
# ----------------------------------------------------------------------
@dataclass
class Note:
    channel: int
    pitch: int
    on_tick: int
    off_tick: Optional[int]
    on_event: MidiEvent
    off_event: Optional[MidiEvent]

    @property
    def velocity(self) -> int:
        return self.on_event.data[1]


@dataclass
class ChannelInfo:
    channel: int
    note_count: int = 0
    min_pitch: int = 127
    max_pitch: int = 0
    pitch_sum: int = 0
    min_vel: int = 127
    max_vel: int = 0
    program: Optional[int] = None
    bank_msb: Optional[int] = None
    bank_lsb: Optional[int] = None
    name: str = ""

    @property
    def avg_pitch(self) -> float:
        return self.pitch_sum / self.note_count if self.note_count else 0.0

    @property
    def is_drum(self) -> bool:
        return self.channel == 9 or (self.bank_msb in (126, 127))


@dataclass
class Section:
    name: str
    start_bar: int  # 1-alapú, beleértve
    end_bar: int    # 1-alapú, beleértve

    @property
    def bar_count(self) -> int:
        return self.end_bar - self.start_bar + 1


@dataclass
class ConversionResult:
    output_path: str
    note_count: int
    sections: List[Tuple[str, int, int]]  # (név, ütemek, hangok)
    velocity_ok: bool
    velocity_report: str
    warnings: List[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# Ütemtérkép
# ----------------------------------------------------------------------
class BarMap:
    """Ütem <-> tick átszámítás az ütemmutató-változások figyelembevételével."""

    def __init__(self, ppq: int, events: List[MidiEvent], end_tick: int):
        self.ppq = ppq
        sigs: List[Tuple[int, int, int]] = []
        for ev in events:
            if ev.kind == "meta" and ev.status == META_TIME_SIGNATURE and len(ev.data) >= 2:
                num, den = ev.data[0], 2 ** ev.data[1]
                if sigs and sigs[-1][0] == ev.tick:
                    sigs[-1] = (ev.tick, num, den)
                else:
                    sigs.append((ev.tick, num, den))
        if not sigs or sigs[0][0] != 0:
            sigs.insert(0, (0, 4, 4))
        self.signatures = sigs
        self.bar_starts: List[int] = []
        self.bar_sigs: List[Tuple[int, int]] = []
        tick, idx = 0, 0
        limit = max(end_tick, 1)
        while tick < limit or not self.bar_starts:
            while idx + 1 < len(sigs) and sigs[idx + 1][0] <= tick:
                idx += 1
            _, num, den = sigs[idx]
            self.bar_starts.append(tick)
            self.bar_sigs.append((num, den))
            tick += self.bar_length(num, den)
        self.bar_starts.append(tick)  # lezáró határ

    def bar_length(self, num: int, den: int) -> int:
        return int(self.ppq * 4 * num / den)

    @property
    def bar_count(self) -> int:
        return len(self.bar_starts) - 1

    def bar_tick(self, bar: int) -> int:
        """1-alapú ütem kezdő tickje (bar_count+1 = a dal vége)."""
        if bar < 1:
            raise ValueError("Az ütemszám 1-től indul")
        while bar > len(self.bar_starts):
            num, den = self.bar_sigs[-1]
            self.bar_starts.append(self.bar_starts[-1] + self.bar_length(num, den))
            self.bar_sigs.append((num, den))
        return self.bar_starts[bar - 1]

    def signature_at_bar(self, bar: int) -> Tuple[int, int]:
        self.bar_tick(bar + 1)
        return self.bar_sigs[bar - 1]


# ----------------------------------------------------------------------
# Forrás betöltése és elemzése
# ----------------------------------------------------------------------
class StyleSource:
    def __init__(self, path: str):
        self.path = path
        self.midi = load_source_file(path)
        self.events = self.midi.merged_events()
        self.ppq = self.midi.ppq
        self.notes = _pair_notes(self.events)
        end = max([self.midi.end_tick()] + [n.off_tick or n.on_tick for n in self.notes])
        self.bar_map = BarMap(self.ppq, self.events, end)
        self.channels = _channel_stats(self.events, self.notes)
        self.tempo = 120.0
        for ev in self.events:
            if ev.kind == "meta" and ev.status == META_TEMPO:
                self.tempo = tempo_bpm(ev)
                break
        self.tempo_changes = sum(1 for ev in self.events
                                 if ev.kind == "meta" and ev.status == META_TEMPO)
        self.signature_changes = len(self.bar_map.signatures) - 1

    @property
    def name(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    def auto_channel_map(self) -> Dict[int, Optional[int]]:
        """Intelligens csatorna-hozzárendelés a Genos stílus sávjaihoz."""
        mapping: Dict[int, Optional[int]] = {}
        used = [c for c in self.channels.values() if c.note_count > 0]
        drums = [c for c in used if c.is_drum]
        melodic = [c for c in used if not c.is_drum]

        drums.sort(key=lambda c: (c.channel != 9, -c.note_count))
        drum_slots = [9, 8]
        for c in drums:
            mapping[c.channel] = drum_slots.pop(0) if drum_slots else None

        free = [11, 12, 13, 14, 15]
        bass = None
        if melodic:
            cand = min(melodic, key=lambda c: c.avg_pitch)
            if cand.avg_pitch < 55:
                bass = cand
                mapping[cand.channel] = 10
        rest = [c for c in melodic if c is not bass]
        rest.sort(key=lambda c: (-c.note_count, c.channel))
        for c in rest:
            mapping[c.channel] = free.pop(0) if free else None
        if bass is None and rest and 10 not in mapping.values():
            pass  # nincs egyértelmű basszus – a csatorna szabad marad
        return mapping

    def suggest_sections(self) -> List[Section]:
        """Alapjavaslat: a dal négyütemes blokkjai sorban Main A-D-re."""
        bars = self.bar_map.bar_count
        sections: List[Section] = []
        block = 4 if bars >= 4 else bars
        names = ["Main A", "Main B", "Main C", "Main D"]
        start = 1
        for name in names:
            if start > bars:
                break
            sections.append(Section(name, start, min(bars, start + block - 1)))
            start += block
        return sections


def load_source_file(path: str) -> MidiFile:
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        return parse_midi_bytes(raw)
    except MidiError as exc:
        if ext == ".stl":
            raise MidiError(
                "Ebben a Roland STL fájlban nincs szabványos MIDI (MThd) adat.\n\n"
                "A Roland STL formátum zárt, nyilvánosan nem dokumentált, ezért "
                "közvetlenül nem olvasható be minden változata. Megoldás: a Roland "
                "hangszeren (vagy a Roland Style Converter / EZ Arranger szoftverrel) "
                "exportáld a stílust MIDI (SMF) fájlba, majd azt töltsd be ide – "
                "a velocity így is 100%-ban megmarad."
            ) from exc
        raise


def _pair_notes(events: List[MidiEvent]) -> List[Note]:
    open_notes: Dict[Tuple[int, int], List[Note]] = {}
    notes: List[Note] = []
    for ev in events:
        if ev.kind != "channel":
            continue
        key = (ev.channel, ev.note) if ev.note is not None else None
        if ev.is_note_on:
            n = Note(ev.channel, ev.data[0], ev.tick, None, ev, None)
            open_notes.setdefault(key, []).append(n)
            notes.append(n)
        elif ev.is_note_off:
            stack = open_notes.get(key)
            if stack:
                n = stack.pop(0)
                n.off_tick, n.off_event = ev.tick, ev
    return notes


def _channel_stats(events: List[MidiEvent], notes: List[Note]) -> Dict[int, ChannelInfo]:
    info: Dict[int, ChannelInfo] = {}
    for ev in events:
        if ev.kind == "channel":
            ci = info.setdefault(ev.channel, ChannelInfo(ev.channel))
            if ev.command == 0xC0 and ci.program is None:
                ci.program = ev.data[0]
            elif ev.command == 0xB0 and ev.data[0] == 0 and ci.bank_msb is None:
                ci.bank_msb = ev.data[1]
            elif ev.command == 0xB0 and ev.data[0] == 32 and ci.bank_lsb is None:
                ci.bank_lsb = ev.data[1]
        elif ev.kind == "meta" and ev.status == META_TRACK_NAME:
            pass
    for n in notes:
        ci = info.setdefault(n.channel, ChannelInfo(n.channel))
        ci.note_count += 1
        ci.min_pitch = min(ci.min_pitch, n.pitch)
        ci.max_pitch = max(ci.max_pitch, n.pitch)
        ci.pitch_sum += n.pitch
        ci.min_vel = min(ci.min_vel, n.velocity)
        ci.max_vel = max(ci.max_vel, n.velocity)
    return info


# ----------------------------------------------------------------------
# Konverzió
# ----------------------------------------------------------------------
def _sort_key(section_order: int, ev: MidiEvent) -> int:
    if ev.kind == "meta" and ev.status == 0x06:
        return 0  # marker legelöl
    if ev.kind == "meta":
        return 1
    if ev.kind == "sysex":
        return 2
    if ev.is_note_off:
        return 3
    if ev.command in (0xB0, 0xC0, 0xE0, 0xD0, 0xA0):
        if ev.command == 0xB0 and ev.data[0] in (0, 32):
            return 4
        if ev.command == 0xC0:
            return 5
        return 6
    return 7  # note on


def convert_to_sty(source: StyleSource, sections: List[Section],
                   channel_map: Dict[int, Optional[int]], output_path: str,
                   tempo: Optional[float] = None, style_name: Optional[str] = None,
                   gm_drums_to_xg: bool = True) -> ConversionResult:
    """A forrás MIDI szeletelése és Yamaha .STY fájl írása."""
    warnings: List[str] = []
    if not sections:
        raise MidiError("Adj meg legalább egy szekciót (pl. Main A)!")
    names_seen = set()
    for s in sections:
        if s.name not in SECTION_NAMES:
            raise MidiError(f"Ismeretlen szekciónév: {s.name}")
        if s.name in names_seen:
            raise MidiError(f"A(z) '{s.name}' szekció kétszer szerepel")
        names_seen.add(s.name)
        if s.start_bar < 1 or s.end_bar < s.start_bar:
            raise MidiError(f"Hibás ütemtartomány: {s.name} ({s.start_bar}-{s.end_bar})")
        if s.end_bar > source.bar_map.bar_count:
            raise MidiError(f"{s.name}: a forrás csak {source.bar_map.bar_count} ütemes")
    if not any(v is not None for v in channel_map.values()):
        raise MidiError("Egyetlen csatorna sincs hozzárendelve a stílus sávjaihoz")
    dests = [v for v in channel_map.values() if v is not None]
    if len(dests) != len(set(dests)):
        warnings.append("Több forráscsatorna ugyanarra a stílussávra kerül (összevonva).")

    ordered = sorted(sections, key=lambda s: SECTION_NAMES.index(s.name))
    sigs = {source.bar_map.signature_at_bar(b) for s in ordered
            for b in range(s.start_bar, s.end_bar + 1)}
    if len(sigs) > 1:
        warnings.append("A kijelölt ütemekben eltérő ütemmutatók vannak; "
                        "a stílus az első szekció ütemmutatóját kapja.")
    num, den = source.bar_map.signature_at_bar(ordered[0].start_bar)

    scale = Fraction(TARGET_PPQ, source.ppq)
    if scale.denominator != 1:
        warnings.append(f"A forrás felbontása ({source.ppq} PPQ) nem osztója az "
                        f"1920-nak; az időzítés a legközelebbi tickre kerekítve.")

    def sc(t: int) -> int:
        return int(round(t * scale))

    out: List[Tuple[int, int, int, MidiEvent]] = []
    seq = 0

    def add(ev: MidiEvent):
        nonlocal seq
        out.append((ev.tick, _sort_key(0, ev), seq, ev))
        seq += 1

    # --- SInt (beállító szekció, 1 ütem) ---------------------------------
    bpm = tempo if tempo else source.tempo
    add(marker(0, "SFF1"))
    add(marker(0, "SInt"))
    name = (style_name or source.name)[:64]
    add(meta(0, META_TRACK_NAME, name.encode("ascii", "replace")))
    add(tempo_event(0, bpm))
    add(time_signature_event(0, num, den))
    # XG System On
    add(MidiEvent(0, "sysex", 0xF0, bytes([0x43, 0x10, 0x4C, 0x00, 0x00, 0x7E, 0x00, 0xF7])))

    setup_tick = TARGET_PPQ // 4
    for src_ch, dst in sorted(channel_map.items()):
        if dst is None:
            continue
        ci = source.channels.get(src_ch, ChannelInfo(src_ch))
        msb, lsb, prog = ci.bank_msb, ci.bank_lsb, ci.program
        if gm_drums_to_xg and src_ch == 9 and msb is None:
            msb, lsb = 127, 0
        if msb is not None:
            add(MidiEvent(setup_tick, "channel", 0xB0 | dst, bytes([0, msb])))
        if lsb is not None:
            add(MidiEvent(setup_tick, "channel", 0xB0 | dst, bytes([32, lsb])))
        if prog is not None or msb is not None:
            add(MidiEvent(setup_tick, "channel", 0xC0 | dst, bytes([prog or 0])))
        # Kezdeti kontrollerek (hangerő, pan, effekt küldések)
        initial = _initial_controllers(source.events, src_ch)
        for cc, val in initial.items():
            add(MidiEvent(setup_tick + 10, "channel", 0xB0 | dst, bytes([cc, val])))

    sint_len = int(TARGET_PPQ * 4 * num / den)
    cursor = sint_len

    # --- Szekciók ----------------------------------------------------------
    total_notes = 0
    sec_report: List[Tuple[str, int, int]] = []
    for s in ordered:
        s_tick = source.bar_map.bar_tick(s.start_bar)
        e_tick = source.bar_map.bar_tick(s.end_bar + 1)
        out_len = sc(e_tick - s_tick)
        add(marker(cursor, s.name))

        count = 0
        for n in source.notes:
            dst = channel_map.get(n.channel)
            if dst is None or not (s_tick <= n.on_tick < e_tick):
                continue
            on_t = cursor + sc(n.on_tick - s_tick)
            if n.off_tick is None or n.off_tick >= e_tick:
                off_t = cursor + out_len - 1
            else:
                off_t = cursor + sc(n.off_tick - s_tick)
            off_t = max(off_t, on_t + 1) if on_t + 1 < cursor + out_len else off_t
            add(n.on_event.with_channel(dst).with_tick(on_t))
            if n.off_event is not None:
                add(n.off_event.with_channel(dst).with_tick(off_t))
            else:
                add(MidiEvent(off_t, "channel", 0x80 | dst, bytes([n.pitch, 64])))
            count += 1

        # Egyéb csatorna-események (kontrollerek, pitch bend, aftertouch)
        bend_state: Dict[int, bytes] = {}
        for ev in source.events:
            if ev.kind != "channel" or ev.command in (0x80, 0x90):
                continue
            dst = channel_map.get(ev.channel)
            if dst is None or not (s_tick <= ev.tick < e_tick):
                continue
            if ev.command == 0xC0 or (ev.command == 0xB0 and ev.data[0] in (0, 32)):
                continue  # hangszínváltás csak az SInt-ben
            add(ev.with_channel(dst).with_tick(cursor + sc(ev.tick - s_tick)))
            if ev.command == 0xE0:
                bend_state[dst] = ev.data
        for dst, data in bend_state.items():
            if data != bytes([0x00, 0x40]):
                add(MidiEvent(cursor + out_len - 1, "channel", 0xE0 | dst, bytes([0, 0x40])))

        sec_report.append((s.name, s.bar_count, count))
        total_notes += count
        cursor += out_len

    out.sort(key=lambda x: (x[0], x[1], x[2]))
    events = [x[3] for x in out]
    data = encode_smf(0, TARGET_PPQ, [events], end_tick=cursor)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as fh:
        fh.write(data)

    ok, report = verify_conversion(source, ordered, channel_map, output_path)
    return ConversionResult(output_path, total_notes, sec_report, ok, report, warnings)


def _initial_controllers(events: List[MidiEvent], channel: int) -> Dict[int, int]:
    """Az első hang előtti hangerő/pan/reverb/chorus értékek."""
    wanted = (7, 10, 11, 91, 93, 94)
    result: Dict[int, int] = {}
    for ev in events:
        if ev.kind != "channel" or ev.channel != channel:
            continue
        if ev.is_note_on:
            break
        if ev.command == 0xB0 and ev.data[0] in wanted:
            result[ev.data[0]] = ev.data[1]
    return result


# ----------------------------------------------------------------------
# Ellenőrzés: hangról hangra velocity-összevetés
# ----------------------------------------------------------------------
def read_sty_sections(path: str) -> Dict[str, List[Note]]:
    with open(path, "rb") as fh:
        mf = parse_midi_bytes(fh.read())
    events = mf.merged_events()
    notes = _pair_notes(events)
    bounds: List[Tuple[int, str]] = []
    for ev in events:
        if ev.kind == "meta" and ev.status == 0x06:
            bounds.append((ev.tick, ev.data.decode("ascii", "replace")))
    result: Dict[str, List[Note]] = {}
    for n in notes:
        name = None
        for t, nm in bounds:
            if t <= n.on_tick:
                name = nm
            else:
                break
        result.setdefault(name or "?", []).append(n)
    return result


def verify_conversion(source: StyleSource, sections: List[Section],
                      channel_map: Dict[int, Optional[int]], sty_path: str
                      ) -> Tuple[bool, str]:
    produced = read_sty_sections(sty_path)
    scale = Fraction(TARGET_PPQ, source.ppq)
    total, mismatches = 0, 0
    for s in sections:
        s_tick = source.bar_map.bar_tick(s.start_bar)
        e_tick = source.bar_map.bar_tick(s.end_bar + 1)
        expected = sorted(
            (int(round((n.on_tick - s_tick) * scale)), channel_map[n.channel], n.pitch,
             n.velocity)
            for n in source.notes
            if channel_map.get(n.channel) is not None and s_tick <= n.on_tick < e_tick)
        got_notes = produced.get(s.name, [])
        base = min((n.on_tick for n in got_notes), default=0)
        # A szekció kezdete a marker pozíciója – a jegyzetek relatív idejéhez
        marker_tick = _marker_tick(sty_path, s.name)
        if marker_tick is not None:
            base = marker_tick
        got = sorted((n.on_tick - base, n.channel, n.pitch, n.velocity) for n in got_notes)
        total += len(expected)
        if expected != got:
            mismatches += max(1, sum(1 for a, b in zip(expected, got) if a != b)
                              + abs(len(expected) - len(got)))
    if mismatches == 0:
        return True, (f"Velocity ellenőrzés: {total} hang – 100% egyezés "
                      f"(hangmagasság, időzítés és dinamika bitpontosan azonos).")
    return False, f"FIGYELEM: {mismatches} eltérés {total} hangból!"


def _marker_tick(path: str, name: str) -> Optional[int]:
    with open(path, "rb") as fh:
        mf = parse_midi_bytes(fh.read())
    for ev in mf.merged_events():
        if ev.kind == "meta" and ev.status == 0x06 and ev.data.decode("ascii", "replace") == name:
            return ev.tick
    return None


def default_output_name(source_path: str) -> str:
    base = os.path.splitext(os.path.basename(source_path))[0]
    return f"{base}_Genos2.sty"
