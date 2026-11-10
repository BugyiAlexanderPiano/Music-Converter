"""Hangfeldolgozó algoritmusok: nullpont-keresés, tranziens-detektálás,
precíziós vágás, loop-pont keresés, crossfade, hangmagasság-felismerés,
intelligens fájlnév-generálás és billentyűzóna-kiosztás.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .audio_io import AudioData
from .midi_io import NOTE_NAMES, note_name


# ----------------------------------------------------------------------
# Alapok
# ----------------------------------------------------------------------
def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def lin_to_db(x: float) -> float:
    return 20.0 * math.log10(max(x, 1e-12))


def envelope(samples: np.ndarray) -> np.ndarray:
    """Csatornánkénti abszolút érték maximuma (a leghangosabb csatorna dönt)."""
    return np.max(np.abs(samples), axis=1)


def zero_crossings(signal: np.ndarray, rising_only: bool = False) -> np.ndarray:
    """Azon i indexek, ahol a jel előjelet vált (i-1 -> i) vagy pontosan 0."""
    s = np.signbit(signal)
    if rising_only:
        idx = np.nonzero(s[:-1] & ~s[1:])[0] + 1
    else:
        idx = np.nonzero(s[:-1] != s[1:])[0] + 1
    exact = np.nonzero(signal == 0)[0]
    if exact.size and not rising_only:
        idx = np.union1d(idx, exact)
    return idx


def _best_zero_point(samples: np.ndarray, lo: int, hi: int, target: int,
                     prefer: str) -> int:
    """A [lo, hi] ablakban a target-hez legközelebbi nullpont.

    Többcsatornás jelnél a pont, ahol MINDEN csatorna a lehető legközelebb
    van a nullához (a csatornák abszolút maximumát minimalizáljuk a
    nullátmenetek közül)."""
    lo = max(0, lo)
    hi = min(samples.shape[0] - 1, hi)
    if hi <= lo:
        return int(np.clip(target, 0, samples.shape[0] - 1))
    seg = samples[lo:hi + 1]
    mid = seg.mean(axis=1)
    zc = zero_crossings(mid)
    env = envelope(seg)
    if zc.size == 0:
        return lo + int(np.argmin(env))
    # Az előjelváltásnál a kisebb abszolút értékű szomszéd a valódi nullpont
    cand = []
    for i in zc:
        j = i if i == 0 or env[i] <= env[i - 1] else i - 1
        cand.append(j)
    cand = np.unique(np.array(cand))
    noise_floor = max(np.min(env[cand]) * 4.0, 1e-5)
    good = cand[env[cand] <= noise_floor]
    if good.size == 0:
        good = cand
    t = target - lo
    if prefer == "before":
        before = good[good <= t]
        pick = before.max() if before.size else good.min()
    elif prefer == "after":
        after = good[good >= t]
        pick = after.min() if after.size else good.max()
    else:
        pick = good[np.argmin(np.abs(good - t))]
    return lo + int(pick)


# ----------------------------------------------------------------------
# Precíziós Sample Vágó (Zero-Latency)
# ----------------------------------------------------------------------
@dataclass
class TrimResult:
    start: int
    end: int           # beleértve
    onset: int
    tail: int
    latency_ms: float  # a vágáspont és az első hallható tranziens közti idő
    start_value: float
    end_value: float


def detect_onset(samples: np.ndarray, threshold_db: float = -48.0) -> int:
    """Az első minta, amely a csúcshoz képest threshold_db fölé emelkedik."""
    env = envelope(samples)
    peak = float(env.max()) if env.size else 0.0
    if peak <= 0:
        return 0
    thr = peak * db_to_lin(threshold_db)
    idx = np.nonzero(env >= thr)[0]
    return int(idx[0]) if idx.size else 0


def detect_tail(samples: np.ndarray, threshold_db: float = -60.0) -> int:
    """Az utolsó minta, amely még a küszöb fölött van."""
    env = envelope(samples)
    peak = float(env.max()) if env.size else 0.0
    if peak <= 0:
        return samples.shape[0] - 1
    thr = peak * db_to_lin(threshold_db)
    idx = np.nonzero(env >= thr)[0]
    return int(idx[-1]) if idx.size else samples.shape[0] - 1


def auto_trim_points(audio: AudioData, start_threshold_db: float = -48.0,
                     end_threshold_db: float = -60.0,
                     search_ms: float = 5.0) -> TrimResult:
    x = audio.samples
    onset = detect_onset(x, start_threshold_db)
    tail = detect_tail(x, end_threshold_db)
    w = max(4, int(audio.rate * search_ms / 1000.0))
    start = _best_zero_point(x, onset - w, onset, onset, "before")
    end = _best_zero_point(x, tail, tail + w, tail, "after")
    if end <= start:
        end = x.shape[0] - 1
    lat = (onset - start) * 1000.0 / audio.rate
    return TrimResult(start, end, onset, tail, max(0.0, lat),
                      float(np.max(np.abs(x[start]))), float(np.max(np.abs(x[end]))))


def snap_to_zero(audio: AudioData, index: int, search_ms: float = 2.0,
                 prefer: str = "nearest") -> int:
    w = max(2, int(audio.rate * search_ms / 1000.0))
    return _best_zero_point(audio.samples, index - w, index + w, index, prefer)


def apply_trim(audio: AudioData, start: int, end: int, fade_in_ms: float = 0.0,
               fade_out_ms: float = 0.0) -> AudioData:
    """Vágás a [start, end] tartományra (end beleértve), opcionális mikro-fade-ekkel.

    A fade-in alapértéke 0 ms: a nullpontos vágás miatt nincs kattanás, és
    így a tranziens egyetlen mintája sem tompul – ritmikus mintáknál ez
    adja a 0 ms késést."""
    y = audio.samples[start:end + 1].copy()
    n = y.shape[0]
    fi = min(n, int(audio.rate * fade_in_ms / 1000.0))
    fo = min(n, int(audio.rate * fade_out_ms / 1000.0))
    if fi > 1:
        y[:fi] *= np.linspace(0.0, 1.0, fi)[:, None]
    if fo > 1:
        y[-fo:] *= np.linspace(1.0, 0.0, fo)[:, None] ** 2
    loop = None
    return audio.copy_with(y, loop=loop)


# ----------------------------------------------------------------------
# Hangmagasság-felismerés (YIN)
# ----------------------------------------------------------------------
def detect_pitch(audio: AudioData, fmin: float = 27.5, fmax: float = 2100.0
                 ) -> Tuple[Optional[float], float]:
    """Visszatér: (frekvencia Hz-ben vagy None, megbízhatóság 0..1)."""
    x = audio.mono()
    n = x.shape[0]
    if n < 2048:
        return None, 0.0
    onset = detect_onset(audio.samples, -30.0)
    start = min(n - 1, onset + int(0.08 * audio.rate))
    win = min(16384, max(4096, int(audio.rate * 0.25)))
    if start + win > n:
        start = max(0, n - win)
        win = n - start
    seg = x[start:start + win] - np.mean(x[start:start + win])
    if np.max(np.abs(seg)) < 1e-6:
        return None, 0.0
    tau_max = min(int(audio.rate / fmin), win // 2)
    tau_min = max(2, int(audio.rate / fmax))
    w = win - tau_max
    if w < 256:
        return None, 0.0
    # Különbségfüggvény FFT-vel
    size = 1 << int(np.ceil(np.log2(win + w)))
    fx = np.fft.rfft(seg, size)
    fy = np.fft.rfft(seg[:w][::-1], size)
    conv = np.fft.irfft(fx * fy, size)[w - 1:w - 1 + tau_max + 1]
    cs = np.concatenate(([0.0], np.cumsum(seg ** 2)))
    e0 = cs[w] - cs[0]
    taus = np.arange(tau_max + 1)
    et = cs[taus + w] - cs[taus]
    d = e0 + et - 2.0 * conv
    d[0] = 0.0
    cmnd = np.ones_like(d)
    running = np.cumsum(d[1:])
    cmnd[1:] = d[1:] * np.arange(1, tau_max + 1) / np.maximum(running, 1e-12)
    tau = None
    for t in range(tau_min, tau_max):
        if cmnd[t] < 0.15:
            while t + 1 < tau_max and cmnd[t + 1] < cmnd[t]:
                t += 1
            tau = t
            break
    if tau is None:
        tau = tau_min + int(np.argmin(cmnd[tau_min:tau_max]))
    conf = float(max(0.0, 1.0 - cmnd[tau]))
    # Parabolikus interpoláció
    if 1 <= tau < tau_max:
        a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
        den = a - 2 * b + c
        shift = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
    else:
        shift = 0.0
    freq = audio.rate / (tau + shift)
    return float(freq), conf


def freq_to_midi(freq: float) -> Tuple[int, float]:
    m = 69.0 + 12.0 * math.log2(freq / 440.0)
    note = int(round(m))
    return note, (m - note) * 100.0


# ----------------------------------------------------------------------
# Smart Looper
# ----------------------------------------------------------------------
@dataclass
class LoopResult:
    start: int
    end: int        # beleértve
    score: float    # 0..1 hasonlóság az illesztési pontnál
    crossfade: int  # minták száma


def find_best_loop(audio: AudioData, region_start: Optional[int] = None,
                   region_end: Optional[int] = None, min_loop_s: float = 0.25,
                   window: int = 1024, search_fraction: float = 0.25) -> LoopResult:
    """A legjobb (start, end) loop-pár keresése emelkedő nullátmeneteken,
    normalizált keresztkorrelációval az illesztési pont környezetében."""
    x = audio.samples
    mono = audio.mono()
    n = x.shape[0]
    if region_start is None or region_end is None:
        onset = detect_onset(x, -30.0)
        tail = detect_tail(x, -40.0)
        body = max(1, tail - onset)
        region_start = onset + int(body * 0.30)
        region_end = onset + int(body * 0.92)
    region_start = int(np.clip(region_start, window + 1, n - window - 2))
    region_end = int(np.clip(region_end, region_start + 1, n - window - 2))
    length = region_end - region_start
    min_len = int(min_loop_s * audio.rate)
    if length < max(min_len, 2 * window):
        raise ValueError("Túl rövid a minta vagy a kijelölt tartomány a loopoláshoz")

    span = max(window, int(length * search_fraction))
    zc = zero_crossings(mono, rising_only=True)
    starts = zc[(zc >= region_start) & (zc <= region_start + span)]
    ends = zc[(zc >= region_end - span) & (zc <= region_end)]
    if starts.size == 0 or ends.size == 0:
        raise ValueError("Nem található nullátmenet a loop-tartományban")
    starts = _thin(starts, 64)
    ends = _thin(ends, 400)

    half = window // 2

    def mats(idx: np.ndarray) -> np.ndarray:
        offs = np.arange(-half, half)
        m = mono[idx[:, None] + offs[None, :]]
        m = m - m.mean(axis=1, keepdims=True)
        norm = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.maximum(norm, 1e-12), norm.ravel()

    S, sn = mats(starts)
    # Az end+1 mintának kell a start mintára "hasonlítania"
    E, en = mats(ends + 1)
    corr = E @ S.T  # (ends, starts)
    level = np.minimum(en[:, None], sn[None, :]) / np.maximum(
        np.maximum(en[:, None], sn[None, :]), 1e-12)
    valid = (ends[:, None] - starts[None, :]) >= min_len
    score = np.where(valid, corr * (0.75 + 0.25 * level), -np.inf)
    ei, si = np.unravel_index(int(np.argmax(score)), score.shape)
    best = float(score[ei, si])
    if not np.isfinite(best):
        raise ValueError("Nincs elég hosszú loop-jelölt – növeld a tartományt")
    return LoopResult(int(starts[si]), int(ends[ei]), max(0.0, min(1.0, best)), 0)


def loop_similarity(audio: AudioData, start: int, end: int, window: int = 1024) -> float:
    """Kézzel megadott loop-pontok illeszkedése (0..1)."""
    mono = audio.mono()
    half = window // 2
    if start - half < 0 or end + 1 + half > mono.size:
        return 0.0
    a = mono[start - half:start + half]
    b = mono[end + 1 - half:end + 1 + half]
    a = a - a.mean()
    b = b - b.mean()
    den = np.linalg.norm(a) * np.linalg.norm(b)
    return float(max(0.0, np.dot(a, b) / den)) if den > 0 else 0.0


def snap_rising_zero(audio: AudioData, index: int, search_ms: float = 3.0) -> int:
    """A legközelebbi emelkedő nullátmenet (loop-pontokhoz)."""
    mono = audio.mono()
    w = max(4, int(audio.rate * search_ms / 1000.0))
    lo, hi = max(1, index - w), min(mono.size - 1, index + w)
    zc = zero_crossings(mono[lo - 1:hi + 1], rising_only=True) + lo - 1
    if zc.size == 0:
        return int(index)
    return int(zc[np.argmin(np.abs(zc - index))])


def guess_instrument(filename: str, default: str = "Strings") -> str:
    low = filename.lower()
    aliases = {"violin": "Strings", "viola": "Strings", "cello": "Strings", "str": "Strings",
               "trp": "Trumpet", "tbn": "Trombone", "sax": "Sax", "horn": "Horn",
               "brass": "Brass", "choir": "Choir", "pad": "Pad", "flute": "Flute",
               "organ": "Organ", "piano": "Piano", "accord": "Accordion", "vox": "Vocal"}
    for inst in INSTRUMENTS:
        if inst.lower() in low:
            return inst
    for k, v in aliases.items():
        if k in low:
            return v
    return default


def _thin(idx: np.ndarray, max_count: int) -> np.ndarray:
    if idx.size <= max_count:
        return idx
    pick = np.linspace(0, idx.size - 1, max_count).round().astype(int)
    return idx[np.unique(pick)]


def apply_loop_crossfade(audio: AudioData, start: int, end: int, xfade_ms: float = 120.0,
                         curve: str = "equal_power", keep_release: bool = False
                         ) -> Tuple[AudioData, int]:
    """Crossfade a loop végén: az utolsó L minta átúszik a loop-start előtti
    L mintába, így a lejátszás end -> start ugrása tökéletesen folytonos.

    Visszatér: (új AudioData beállított loop-pontokkal, tényleges xfade minták)."""
    x = audio.samples.copy()
    L = int(audio.rate * xfade_ms / 1000.0)
    L = max(0, min(L, start, (end - start) // 2))
    if L > 1:
        t = np.linspace(0.0, 1.0, L)
        if curve == "linear":
            g_out, g_in = 1.0 - t, t
        else:
            g_out, g_in = np.cos(t * np.pi / 2), np.sin(t * np.pi / 2)
        a = x[end - L + 1:end + 1]
        b = audio.samples[start - L:start]
        x[end - L + 1:end + 1] = a * g_out[:, None] + b * g_in[:, None]
    y = x if keep_release else x[:end + 1]
    return audio.copy_with(y, loop=(start, end)), L


def loop_seam_error(samples: np.ndarray, start: int, end: int) -> float:
    """Az end -> start ugrás hibája a természetes lépésközhöz viszonyítva."""
    jump = np.abs(samples[start] - samples[end])
    natural = np.abs(samples[end] - samples[end - 1]) + 1e-9
    return float(np.max(jump / natural))


def render_loop_preview(audio: AudioData, repeats: int = 4) -> np.ndarray:
    if not audio.loop:
        return audio.samples
    s, e = audio.loop
    head = audio.samples[:e + 1]
    body = audio.samples[s:e + 1]
    return np.concatenate([head] + [body] * (repeats - 1), axis=0)


# ----------------------------------------------------------------------
# Intelligens fájlnevek és billentyűkiosztás
# ----------------------------------------------------------------------
INSTRUMENTS = ["Strings", "Brass", "Trumpet", "Trombone", "Horn", "Sax", "Choir",
               "Pad", "Flute", "Organ", "Piano", "Synth", "Guitar", "Bass", "Accordion",
               "Vocal", "FX"]

NOTE_RE = re.compile(r"(?<![A-Za-z])([A-Ga-g])([#sb]?)(-?\d)(?!\d)")


def note_from_filename(name: str) -> Optional[int]:
    """Hang kiolvasása fájlnévből (pl. 'Violin_C#3.wav' -> 61, Yamaha oktáv)."""
    m = NOTE_RE.search(name)
    if not m:
        return None
    letter, acc, octv = m.group(1).upper(), m.group(2), int(m.group(3))
    pc = NOTE_NAMES.index(letter)
    if acc in ("#", "s"):
        pc += 1
    elif acc == "b":
        pc -= 1
    note = (octv + 2) * 12 + pc
    return note if 0 <= note <= 127 else None


def dynamics_tag(audio: AudioData) -> str:
    rms = float(np.sqrt(np.mean(audio.samples ** 2))) if audio.frames else 0.0
    db = lin_to_db(rms)
    if db < -26:
        return "Soft"
    if db < -14:
        return "Med"
    return "Hard"


def quality_tag(score: float) -> str:
    if score >= 0.97:
        return "Clean"
    if score >= 0.90:
        return "Smooth"
    return "XFade"


def sanitize(part: str) -> str:
    part = re.sub(r"[^A-Za-z0-9#\-]+", "", part.replace(" ", ""))
    return part or "X"


def smart_filename(root_note: int, instrument: str, tag: str = "Clean",
                   extra: Sequence[str] = (), looped: bool = True) -> str:
    parts = [note_name(root_note), sanitize(instrument)]
    if looped:
        parts.append("Loop")
    parts += [sanitize(e) for e in extra if e]
    if tag:
        parts.append(sanitize(tag))
    return "_".join(parts) + ".wav"


def unique_path(path: str) -> str:
    import os
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base}_{i:02d}{ext}"):
        i += 1
    return f"{base}_{i:02d}{ext}"


def key_zones(roots: Sequence[int], low_limit: int = 0, high_limit: int = 127
              ) -> List[Tuple[int, int, int]]:
    """Billentyűzónák: (alaphang, legalsó, legfelső) – a szomszédos
    alaphangok közti felezőpontnál váltva."""
    rs = sorted(set(int(r) for r in roots))
    zones = []
    for i, r in enumerate(rs):
        lo = low_limit if i == 0 else (rs[i - 1] + r) // 2 + 1
        hi = high_limit if i == len(rs) - 1 else (r + rs[i + 1]) // 2
        zones.append((r, lo, hi))
    return zones
