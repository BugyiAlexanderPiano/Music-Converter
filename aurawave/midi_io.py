"""Függőség nélküli Standard MIDI File (SMF) olvasó és író.

A cél a bitpontos adatmegőrzés: a csatorna-üzenetek nyers bájtjait
(státusz + adatbájtok) változtatás nélkül tároljuk, így a velocity
(dinamika) értékek soha nem módosulnak a feldolgozás során.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Meta esemény típusok
META_TEXT = 0x01
META_TRACK_NAME = 0x03
META_MARKER = 0x06
META_END_OF_TRACK = 0x2F
META_TEMPO = 0x51
META_TIME_SIGNATURE = 0x58
META_KEY_SIGNATURE = 0x59


class MidiError(Exception):
    """Hibás vagy nem támogatott MIDI adat."""


@dataclass
class MidiEvent:
    """Egy MIDI esemény abszolút tick időbélyeggel.

    kind: 'channel' | 'meta' | 'sysex'
    status: csatorna-üzenetnél a státuszbájt (pl. 0x90 | csatorna),
            metánál a meta típus, sysexnél 0xF0 vagy 0xF7.
    data: a nyers adatbájtok (csatorna-üzenetnél pl. [hangmagasság, velocity]).
    """

    tick: int
    kind: str
    status: int
    data: bytes
    track: int = 0

    # --- kényelmi tulajdonságok -------------------------------------------
    @property
    def channel(self) -> Optional[int]:
        return (self.status & 0x0F) if self.kind == "channel" else None

    @property
    def command(self) -> Optional[int]:
        return (self.status & 0xF0) if self.kind == "channel" else None

    @property
    def is_note_on(self) -> bool:
        return self.kind == "channel" and self.command == 0x90 and self.data[1] > 0

    @property
    def is_note_off(self) -> bool:
        return self.kind == "channel" and (
            self.command == 0x80 or (self.command == 0x90 and self.data[1] == 0)
        )

    @property
    def note(self) -> Optional[int]:
        if self.kind == "channel" and self.command in (0x80, 0x90, 0xA0):
            return self.data[0]
        return None

    @property
    def velocity(self) -> Optional[int]:
        if self.kind == "channel" and self.command in (0x80, 0x90):
            return self.data[1]
        return None

    def with_channel(self, channel: int) -> "MidiEvent":
        """Másolat új MIDI csatornával (az adatbájtok érintetlenek)."""
        if self.kind != "channel":
            return MidiEvent(self.tick, self.kind, self.status, self.data, self.track)
        return MidiEvent(self.tick, self.kind, (self.status & 0xF0) | (channel & 0x0F),
                         self.data, self.track)

    def with_tick(self, tick: int) -> "MidiEvent":
        return MidiEvent(tick, self.kind, self.status, self.data, self.track)


@dataclass
class MidiFile:
    format: int = 1
    ppq: int = 480
    tracks: List[List[MidiEvent]] = field(default_factory=list)

    # ------------------------------------------------------------------
    def merged_events(self) -> List[MidiEvent]:
        """Minden sáv eseménye egy időrendezett listában (stabil sorrend)."""
        merged: List[Tuple[int, int, int, MidiEvent]] = []
        for t_index, track in enumerate(self.tracks):
            for e_index, ev in enumerate(track):
                if ev.kind == "meta" and ev.status == META_END_OF_TRACK:
                    continue
                merged.append((ev.tick, t_index, e_index, ev))
        merged.sort(key=lambda x: (x[0], x[1], x[2]))
        return [m[3] for m in merged]

    def end_tick(self) -> int:
        end = 0
        for track in self.tracks:
            for ev in track:
                end = max(end, ev.tick)
        return end


# ----------------------------------------------------------------------
# Változó hosszúságú mennyiségek (VLQ)
# ----------------------------------------------------------------------
def read_vlq(buf: bytes, pos: int) -> Tuple[int, int]:
    value = 0
    for _ in range(4):
        if pos >= len(buf):
            raise MidiError("Váratlan fájlvég VLQ olvasás közben")
        b = buf[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, pos
    raise MidiError("Túl hosszú VLQ érték")


def write_vlq(value: int) -> bytes:
    if value < 0:
        raise MidiError("Negatív delta idő")
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


_DATA_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}


# ----------------------------------------------------------------------
# Olvasás
# ----------------------------------------------------------------------
def find_smf_start(raw: bytes) -> int:
    """Az 'MThd' fejléc helye (RIFF-RMID vagy beágyazott adat esetén is)."""
    idx = raw.find(b"MThd")
    if idx < 0:
        raise MidiError("Nem található MIDI (MThd) adat a fájlban")
    return idx


def parse_midi_bytes(raw: bytes) -> MidiFile:
    pos = find_smf_start(raw)
    if raw[pos:pos + 4] != b"MThd":
        raise MidiError("Hiányzó MThd fejléc")
    hdr_len = struct.unpack(">I", raw[pos + 4:pos + 8])[0]
    fmt, ntrks, division = struct.unpack(">HHH", raw[pos + 8:pos + 14])
    if division & 0x8000:
        raise MidiError("SMPTE időalapú MIDI fájl nem támogatott")
    pos += 8 + hdr_len

    mf = MidiFile(format=fmt, ppq=division, tracks=[])
    for t_index in range(ntrks):
        # Ismeretlen chunkok átugrása
        while pos + 8 <= len(raw) and raw[pos:pos + 4] != b"MTrk":
            clen = struct.unpack(">I", raw[pos + 4:pos + 8])[0]
            pos += 8 + clen
        if pos + 8 > len(raw):
            break
        tlen = struct.unpack(">I", raw[pos + 4:pos + 8])[0]
        start = pos + 8
        end = min(start + tlen, len(raw))
        mf.tracks.append(_parse_track(raw, start, end, t_index))
        pos = start + tlen
    if not mf.tracks:
        raise MidiError("A fájl nem tartalmaz MIDI sávot")
    return mf


def _parse_track(raw: bytes, pos: int, end: int, t_index: int) -> List[MidiEvent]:
    events: List[MidiEvent] = []
    tick = 0
    running = None
    while pos < end:
        delta, pos = read_vlq(raw, pos)
        tick += delta
        if pos >= end:
            break
        status = raw[pos]
        if status == 0xFF:  # meta
            mtype = raw[pos + 1]
            length, pos = read_vlq(raw, pos + 2)
            data = bytes(raw[pos:pos + length])
            pos += length
            events.append(MidiEvent(tick, "meta", mtype, data, t_index))
            if mtype == META_END_OF_TRACK:
                break
            continue
        if status in (0xF0, 0xF7):  # sysex
            length, pos = read_vlq(raw, pos + 1)
            data = bytes(raw[pos:pos + length])
            pos += length
            events.append(MidiEvent(tick, "sysex", status, data, t_index))
            running = None
            continue
        if status & 0x80:
            running = status
            pos += 1
        elif running is None:
            raise MidiError(f"Futó státusz hiba a(z) {t_index}. sávban")
        cmd = running & 0xF0
        n = _DATA_LEN.get(cmd)
        if n is None:
            # Rendszer-üzenetek (F1-FE) SMF-ben nem várhatók – átugorjuk
            continue
        data = bytes(raw[pos:pos + n])
        pos += n
        events.append(MidiEvent(tick, "channel", running, data, t_index))
    return events


def read_midi(path: str) -> MidiFile:
    with open(path, "rb") as fh:
        return parse_midi_bytes(fh.read())


# ----------------------------------------------------------------------
# Írás
# ----------------------------------------------------------------------
def encode_track(events: List[MidiEvent], end_tick: Optional[int] = None) -> bytes:
    """Egy sáv kódolása (futó státusz nélkül – a legkompatibilisebb forma)."""
    body = bytearray()
    last = 0
    for ev in sorted(events, key=lambda e: e.tick):
        if ev.kind == "meta" and ev.status == META_END_OF_TRACK:
            continue
        body += write_vlq(ev.tick - last)
        last = ev.tick
        if ev.kind == "channel":
            body.append(ev.status)
            body += ev.data
        elif ev.kind == "meta":
            body += bytes([0xFF, ev.status]) + write_vlq(len(ev.data)) + ev.data
        elif ev.kind == "sysex":
            body += bytes([ev.status]) + write_vlq(len(ev.data)) + ev.data
    final = max(last, end_tick if end_tick is not None else last)
    body += write_vlq(final - last) + b"\xFF\x2F\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def encode_smf(fmt: int, ppq: int, tracks: List[List[MidiEvent]],
               end_tick: Optional[int] = None) -> bytes:
    header = b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), ppq)
    return header + b"".join(encode_track(t, end_tick) for t in tracks)


# ----------------------------------------------------------------------
# Segédfüggvények
# ----------------------------------------------------------------------
def meta(tick: int, mtype: int, data: bytes) -> MidiEvent:
    return MidiEvent(tick, "meta", mtype, data)


def marker(tick: int, text: str) -> MidiEvent:
    return meta(tick, META_MARKER, text.encode("ascii", "replace"))


def tempo_bpm(ev: MidiEvent) -> float:
    us = int.from_bytes(ev.data[:3], "big")
    return 60_000_000 / us if us else 120.0


def tempo_event(tick: int, bpm: float) -> MidiEvent:
    us = int(round(60_000_000 / max(bpm, 1.0)))
    return meta(tick, META_TEMPO, us.to_bytes(3, "big"))


def time_signature_event(tick: int, num: int, den: int) -> MidiEvent:
    den_pow = max(0, int(round((den).bit_length() - 1)))
    return meta(tick, META_TIME_SIGNATURE, bytes([num, den_pow, 24, 8]))


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(note: int, yamaha: bool = True) -> str:
    """MIDI hangjegy neve. Yamaha konvenció: 60 = C3 (középső C)."""
    octave = note // 12 - (2 if yamaha else 1)
    return f"{NOTE_NAMES[note % 12]}{octave}"
