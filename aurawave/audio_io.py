"""WAV olvasás/írás (PCM 8/16/24/32 bit, 32/64 bit float) 'smpl' loop chunkkal,
valamint platformfüggetlen előhallgatás.

A Yamaha Expansion Manager a WAV fájl 'smpl' chunkjából olvassa ki a
loop-pontokat és az alaphangot (MIDI unity note), ezért a Smart Looper
ide írja a loop adatait.
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_FLOAT = 0x0003
WAVE_FORMAT_EXTENSIBLE = 0xFFFE


class WavError(Exception):
    pass


@dataclass
class AudioData:
    """Lebegőpontos (-1..1) minták, alakja: (minták, csatornák)."""

    samples: np.ndarray
    rate: int
    bits: int = 24
    is_float: bool = False
    loop: Optional[Tuple[int, int]] = None   # (start, end) mintaindex, end beleértve
    root_note: Optional[int] = None
    path: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def frames(self) -> int:
        return self.samples.shape[0]

    @property
    def channels(self) -> int:
        return self.samples.shape[1]

    @property
    def duration(self) -> float:
        return self.frames / float(self.rate)

    def mono(self) -> np.ndarray:
        return self.samples.mean(axis=1)

    def copy_with(self, samples: np.ndarray, **kw) -> "AudioData":
        d = AudioData(samples, self.rate, self.bits, self.is_float, self.loop,
                      self.root_note, self.path)
        for k, v in kw.items():
            setattr(d, k, v)
        return d


# ----------------------------------------------------------------------
# Olvasás
# ----------------------------------------------------------------------
def read_wav(path: str) -> AudioData:
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) < 12 or raw[:4] not in (b"RIFF", b"RF64") or raw[8:12] != b"WAVE":
        raise WavError("Nem érvényes WAV (RIFF/WAVE) fájl")
    pos = 12
    fmt = None
    data = None
    loop = None
    root = None
    while pos + 8 <= len(raw):
        cid = raw[pos:pos + 4]
        size = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            data = body
        elif cid == b"smpl" and len(body) >= 36:
            root = struct.unpack("<I", body[12:16])[0]
            nloops = struct.unpack("<I", body[28:32])[0]
            if nloops and len(body) >= 36 + 24:
                _, _, ls, le, _, _ = struct.unpack("<IIIIII", body[36:60])
                loop = (ls, le)
        pos += 8 + size + (size & 1)
    if fmt is None or data is None:
        raise WavError("Hiányzó 'fmt ' vagy 'data' chunk")

    tag, ch, rate, _, block, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == WAVE_FORMAT_EXTENSIBLE and len(fmt) >= 26:
        tag = struct.unpack("<H", fmt[24:26])[0]
    if ch < 1:
        raise WavError("Érvénytelen csatornaszám")
    width = bits // 8
    n = len(data) // (width * ch)
    data = data[: n * width * ch]

    if tag == WAVE_FORMAT_FLOAT:
        dt = "<f4" if bits == 32 else "<f8"
        x = np.frombuffer(data, dtype=dt).astype(np.float64)
        is_float = True
    elif tag == WAVE_FORMAT_PCM:
        is_float = False
        if bits == 8:
            x = (np.frombuffer(data, dtype=np.uint8).astype(np.float64) - 128) / 128.0
        elif bits == 16:
            x = np.frombuffer(data, dtype="<i2").astype(np.float64) / 32768.0
        elif bits == 24:
            b = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
            v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            v = np.where(v & 0x800000, v - 0x1000000, v)
            x = v.astype(np.float64) / 8388608.0
        elif bits == 32:
            x = np.frombuffer(data, dtype="<i4").astype(np.float64) / 2147483648.0
        else:
            raise WavError(f"Nem támogatott bitmélység: {bits}")
    else:
        raise WavError(f"Nem támogatott WAV kódolás (formátum: {tag:#x})")

    x = x.reshape(-1, ch)
    return AudioData(x, rate, bits, is_float, loop, root, path)


# ----------------------------------------------------------------------
# Írás
# ----------------------------------------------------------------------
def _encode(samples: np.ndarray, bits: int, is_float: bool) -> bytes:
    x = np.clip(samples, -1.0, 1.0)
    if is_float:
        return x.astype("<f4").tobytes()
    if bits == 16:
        return np.round(x * 32767.0).astype("<i2").tobytes()
    if bits == 24:
        v = np.round(x * 8388607.0).astype(np.int32).reshape(-1)
        v = np.where(v < 0, v + 0x1000000, v).astype(np.uint32)
        b = np.empty((v.size, 3), dtype=np.uint8)
        b[:, 0] = v & 0xFF
        b[:, 1] = (v >> 8) & 0xFF
        b[:, 2] = (v >> 16) & 0xFF
        return b.tobytes()
    if bits == 32:
        return np.round(x * 2147483647.0).astype("<i4").tobytes()
    if bits == 8:
        return (np.round(x * 127.0) + 128).astype(np.uint8).tobytes()
    raise WavError(f"Nem támogatott bitmélység: {bits}")


def build_smpl_chunk(rate: int, root_note: int, loop: Optional[Tuple[int, int]]) -> bytes:
    period = int(round(1e9 / rate))
    loops = [loop] if loop else []
    body = struct.pack("<IIIIIIIII", 0, 0, period, int(root_note), 0, 0, 0,
                       len(loops), 0)
    for ls, le in loops:
        # cue id, típus (0 = előre), start, end (beleértve), fraction, play count (0 = végtelen)
        body += struct.pack("<IIIIII", 0, 0, int(ls), int(le), 0, 0)
    return b"smpl" + struct.pack("<I", len(body)) + body


def write_wav(path: str, audio: AudioData, bits: Optional[int] = None,
              is_float: Optional[bool] = None, write_smpl: bool = True) -> None:
    bits = bits or audio.bits
    is_float = audio.is_float if is_float is None else is_float
    if is_float:
        bits = 32
    if bits not in (8, 16, 24, 32):
        bits = 24
    ch = audio.channels
    pcm = _encode(audio.samples, bits, is_float)
    block = ch * bits // 8
    fmt = struct.pack("<HHIIHH", WAVE_FORMAT_FLOAT if is_float else WAVE_FORMAT_PCM,
                      ch, audio.rate, audio.rate * block, block, bits)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(pcm)) + pcm
    if len(pcm) & 1:
        chunks += b"\x00"
    if write_smpl and (audio.loop is not None or audio.root_note is not None):
        chunks += build_smpl_chunk(audio.rate, audio.root_note if audio.root_note
                                   is not None else 60, audio.loop)
    riff = b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(riff)


# ----------------------------------------------------------------------
# Előhallgatás
# ----------------------------------------------------------------------
class Player:
    """Egyszerű lejátszó: Windows-on winsound, macOS-en afplay, Linuxon aplay/paplay.
    Ha a 'sounddevice' csomag telepítve van, azt használja elsőként."""

    def __init__(self):
        self._proc = None
        self._tmp = None
        try:
            import sounddevice  # type: ignore
            self._sd = sounddevice
        except Exception:
            self._sd = None

    def play(self, audio: AudioData, start: int = 0, end: Optional[int] = None,
             loop_times: int = 1) -> None:
        self.stop()
        seg = audio.samples[start:end]
        if loop_times > 1:
            seg = np.concatenate([seg] * loop_times, axis=0)
        if seg.size == 0:
            return
        if self._sd is not None:
            self._sd.play(seg.astype(np.float32), audio.rate)
            return
        fd, tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        write_wav(tmp, AudioData(seg, audio.rate, 16), bits=16, is_float=False,
                  write_smpl=False)
        self._tmp = tmp
        if sys.platform.startswith("win"):
            import winsound  # type: ignore
            winsound.PlaySound(tmp, winsound.SND_FILENAME | winsound.SND_ASYNC)
        elif sys.platform == "darwin":
            self._proc = subprocess.Popen(["afplay", tmp])
        else:
            for cmd in (["paplay", tmp], ["aplay", "-q", tmp], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp]):
                try:
                    self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL)
                    break
                except FileNotFoundError:
                    continue

    def stop(self) -> None:
        if self._sd is not None:
            try:
                self._sd.stop()
            except Exception:
                pass
        if sys.platform.startswith("win"):
            try:
                import winsound  # type: ignore
                winsound.PlaySound(None, 0)
            except Exception:
                pass
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
