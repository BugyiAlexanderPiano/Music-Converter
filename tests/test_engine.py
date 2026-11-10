"""Motor-tesztek (GUI nélkül): python -m pytest tests  vagy  python tests/test_engine.py"""

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurawave import dsp  # noqa: E402
from aurawave.audio_io import AudioData, read_wav, write_wav  # noqa: E402
from aurawave.midi_io import (MidiEvent, encode_smf, marker, read_midi,  # noqa: E402
                              tempo_event, time_signature_event)
from aurawave.sty_converter import (Section, StyleSource, convert_to_sty,  # noqa: E402
                                    read_sty_sections)

RNG = np.random.default_rng(7)


def make_test_midi(path, ppq=480, bars=8):
    bar = ppq * 4
    t_meta = [tempo_event(0, 112), time_signature_event(0, 4, 4)]
    drums, bass, chords = [], [], []
    for b in range(bars):
        for beat in range(4):
            t = b * bar + beat * ppq
            v = int(RNG.integers(1, 128))
            drums += [MidiEvent(t, "channel", 0x99, bytes([36 if beat % 2 == 0 else 38, v])),
                      MidiEvent(t + 60, "channel", 0x89, bytes([36 if beat % 2 == 0 else 38, 0]))]
            hv = int(RNG.integers(1, 128))
            drums += [MidiEvent(t + ppq // 2, "channel", 0x99, bytes([42, hv])),
                      MidiEvent(t + ppq // 2 + 30, "channel", 0x99, bytes([42, 0]))]
        bv = int(RNG.integers(1, 128))
        bass += [MidiEvent(b * bar, "channel", 0x92, bytes([36 + b % 5, bv])),
                 MidiEvent(b * bar + bar - 10, "channel", 0x82, bytes([36 + b % 5, 33]))]
        for p in (60, 64, 67, 71):
            cv = int(RNG.integers(1, 128))
            # szándékosan ütemhatáron átlógó akkordhang
            chords += [MidiEvent(b * bar + ppq, "channel", 0x91, bytes([p, cv])),
                       MidiEvent(b * bar + ppq + bar, "channel", 0x81, bytes([p, 0]))]
        chords.append(MidiEvent(b * bar + 10, "channel", 0xE1, bytes([0, 0x50])))
    chords.insert(0, MidiEvent(0, "channel", 0xC1, bytes([48])))
    chords.insert(0, MidiEvent(0, "channel", 0xB1, bytes([7, 90])))
    with open(path, "wb") as fh:
        fh.write(encode_smf(1, ppq, [t_meta, drums, bass, chords]))


def test_sty_conversion_preserves_velocity():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "song.mid")
    make_test_midi(src)
    s = StyleSource(src)
    assert s.bar_map.bar_count >= 8
    cmap = s.auto_channel_map()
    assert cmap[9] == 9 and cmap[2] == 10 and cmap[1] == 11, cmap
    secs = [Section("Main A", 3, 6), Section("Intro A", 1, 2), Section("Ending A", 7, 8)]
    out = os.path.join(d, "song.sty")
    res = convert_to_sty(s, secs, cmap, out)
    assert res.velocity_ok, res.velocity_report
    mf = read_midi(out)
    assert mf.format == 0 and mf.ppq == 1920
    names = [e.data.decode() for e in mf.tracks[0] if e.kind == "meta" and e.status == 6]
    assert names == ["SFF1", "SInt", "Intro A", "Main A", "Ending A"], names
    # minden hang a 9-16. csatornán
    chans = {e.channel for e in mf.tracks[0] if e.kind == "channel"}
    assert chans <= set(range(8, 16)), chans
    # nincs beragadt hang: on/off párok egyeznek
    ons = sum(1 for e in mf.tracks[0] if e.is_note_on)
    offs = sum(1 for e in mf.tracks[0] if e.is_note_off)
    assert ons == offs
    # minden velocity pontos a forráshoz képest
    src_vels = sorted(n.velocity for n in s.notes)
    got = read_sty_sections(out)
    out_vels = sorted(n.velocity for v in got.values() for n in v)
    assert out_vels == src_vels
    return res


def test_verify_detects_tampering():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "song.mid")
    make_test_midi(src)
    s = StyleSource(src)
    cmap = s.auto_channel_map()
    out = os.path.join(d, "song.sty")
    convert_to_sty(s, [Section("Main A", 1, 4)], cmap, out)
    raw = bytearray(open(out, "rb").read())
    i = raw.find(bytes([0x99, 36]))
    raw[i + 2] = (raw[i + 2] % 126) + 1
    open(out, "wb").write(raw)
    from aurawave.sty_converter import verify_conversion
    ok, _ = verify_conversion(s, [Section("Main A", 1, 4)], cmap, out)
    assert not ok


def test_zero_latency_trim():
    rate = 44100
    sil = np.zeros(3000)
    noise = RNG.normal(0, 1e-5, 3000)
    t = np.arange(rate // 2) / rate
    hit = np.sin(2 * np.pi * 180 * t + 0.7) * np.exp(-t * 8)
    sig = np.concatenate([sil + noise, hit, np.zeros(4000)])
    stereo = np.stack([sig, sig * 0.8], axis=1)
    a = AudioData(stereo, rate, 24)
    tr = dsp.auto_trim_points(a, -48, -70)
    assert tr.start <= tr.onset
    assert tr.latency_ms < 1.0, tr
    assert tr.start_value < 0.02, tr
    out = dsp.apply_trim(a, tr.start, tr.end)
    assert np.max(np.abs(out.samples[0])) < 0.02
    d = tempfile.mkdtemp()
    p = os.path.join(d, "kick.wav")
    write_wav(p, out)
    back = read_wav(p)
    assert back.frames == out.frames and back.bits == 24
    assert np.max(np.abs(back.samples - out.samples)) < 1e-6
    return tr


def test_loop_and_naming():
    rate = 44100
    t = np.arange(rate * 3) / rate
    f = 261.6256
    vib = 0.002 * np.sin(2 * np.pi * 5.5 * t)
    phase = 2 * np.pi * f * np.cumsum(1 + vib) / rate
    tone = (np.sin(phase) + 0.4 * np.sin(2 * phase) + 0.2 * np.sin(3 * phase)) * 0.5
    env = np.minimum(1, t / 0.15)
    sig = tone * env + RNG.normal(0, 0.002, t.size)
    a = AudioData(np.stack([sig, sig], axis=1), rate, 16)
    freq, conf = dsp.detect_pitch(a)
    note, cents = dsp.freq_to_midi(freq)
    assert note == 60, (freq, note)
    lr = dsp.find_best_loop(a)
    assert lr.end - lr.start > rate * 0.25
    looped, L = dsp.apply_loop_crossfade(a, lr.start, lr.end, 100)
    looped.root_note = note
    err = dsp.loop_seam_error(looped.samples, lr.start, lr.end)
    assert err < 3.0, err
    name = dsp.smart_filename(note, "Strings", dsp.quality_tag(max(lr.score, 0.97)))
    assert name == "C3_Strings_Loop_Clean.wav", name
    d = tempfile.mkdtemp()
    p = os.path.join(d, name)
    write_wav(p, looped)
    back = read_wav(p)
    assert back.loop == (lr.start, lr.end) and back.root_note == 60
    assert dsp.note_from_filename("Violin_C#3_ff.wav") == 61
    assert dsp.key_zones([48, 60, 72]) == [(48, 0, 54), (60, 55, 66), (72, 67, 127)]
    return lr, err, freq


if __name__ == "__main__":
    r = test_sty_conversion_preserves_velocity()
    print("STY:", r.velocity_report, r.sections, r.warnings)
    test_verify_detects_tampering()
    print("Manipuláció-felismerés: OK")
    print("Trim:", test_zero_latency_trim())
    print("Loop:", test_loop_and_naming())
    print("MINDEN TESZT SIKERES")
