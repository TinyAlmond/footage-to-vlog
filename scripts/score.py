"""Original score on the edit's bar grid, synthesised here (no licence to worry about) -> music.wav + cues.json.

The arrangement follows the EDL's sections (runs of shots with the same "sec"); "music" in the EDL says how each
section plays:
  "music": {"key": "E", "seed": 7,
            "sections": {"hook":  {"style": "intro",  "chords": ["C#m9", "Aadd9"]},
                         "above": {"style": "groove", "chords": ["E", "B/D#", "C#m", "A"], "hit": true},
                         "water": {"style": "light",  "uw": true}, ...}}
Styles (each has a default loudness target, so the film has dynamics by design):
  intro     pad + an arpeggio that grows and brightens through the section (-19 LUFS)
  groove    full band: kick, clap, 16th shaker, pumping bass, arpeggio, kalimba tune (-14.5)
  light     no kick: soft shaker, half-note bass, sparser tune - room for natural sound (-19)
  halftime  kick on 1, clap on 3, the tune an octave up (-16.5)
  breath    pad and a few notes: a quiet beat (留白) (-23)
  ambient   pad, low bass, a few high notes, long reverb (-24.5)
  outro     ambient + a slow arpeggio; the last chord rings out with the picture's fade (-22.5)
Per section: "chords" (cycled one per bar; default from the key), "lufs", "ramp" (s, the loudness change into the
section: short = a hit, long = a breath), "hit" (riser + boom + crash into it), "uw" (heard from under water:
low-passed, wet, wobbling, with bubbles, a plunge in and a swish out), "tune" ({"bar": [[beat, note, beats], ...]},
bars counted from the section start, notes as MIDI numbers or names like "E5") to write the melody by hand,
"tune_octave" (+12 / -12). Without a tune, a melody is generated from the chords (seeded, stepwise, chord tones on
strong beats); its notes drop 10 dB under the narration. Whip pans get a whoosh, the rot2fit turn a sweep, long
dissolves into ambient/outro a shimmer.

usage: python score.py edl.json [--out music.wav]
"""
import argparse
import json
import re

import numpy as np
from scipy import signal
from scipy.io import wavfile

import synth as S
from common import bar_seconds, line_events, line_lang, load_edl, out_path, parse_fps, sections, timeline, \
    trans_frames
from synth import (add, bass, bubbles, clap, kalimba, kick, noise_burst, pad_note, pluck, plunge, reverb, shaker,
                   sweep, swish, underwater, whoosh)

SR = S.SR
NOTE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
ACC = {'#': 1, 'b': -1, '': 0}
QUAL = {'': [0, 4, 7], 'maj': [0, 4, 7], 'M': [0, 4, 7], 'm': [0, 3, 7], 'min': [0, 3, 7], '-': [0, 3, 7],
        '7': [0, 4, 7, 10], 'maj7': [0, 4, 7, 11], 'M7': [0, 4, 7, 11], 'm7': [0, 3, 7, 10], 'min7': [0, 3, 7, 10],
        '6': [0, 4, 7, 9], 'm6': [0, 3, 7, 9], 'sus2': [0, 2, 7], 'sus4': [0, 5, 7], 'sus': [0, 5, 7],
        'add9': [0, 4, 7, 14], 'madd9': [0, 3, 7, 14], '9': [0, 4, 7, 10, 14], 'maj9': [0, 4, 7, 11, 14],
        'm9': [0, 3, 7, 10, 14], 'dim': [0, 3, 6], 'aug': [0, 4, 8], '5': [0, 7], 'm7b5': [0, 3, 6, 10]}
MAJOR, MINOR = [0, 2, 4, 5, 7, 9, 11], [0, 2, 3, 5, 7, 8, 10]
STYLES = {  # layer levels in dB (None = layer off), loudness target, ramp into the section
    'intro': dict(lufs=-19.0, ramp=0.5, attack=0.8, pad=-4, arp=-3, arp_mode='rise'),
    'groove': dict(lufs=-14.5, ramp=0.5, attack=0.35, pad=-6, arp=-4, bass='pump', bass_db=-2, drums='full',
                   drums_db=-1, tune='busy', tune_db=-3),
    'light': dict(lufs=-19.0, ramp=0.8, attack=0.6, pad=-4, arp=-7, bass='half', bass_db=-5, drums='shaker',
                  drums_db=-6, tune='sparse', tune_db=-4),
    'halftime': dict(lufs=-16.5, ramp=1.0, attack=0.8, pad=-3, arp=-9, arp_oct=12, bass='dotted', bass_db=-3,
                     drums='half', drums_db=-3, tune='busy', tune_db=-2, tune_oct=12, cutoff=1800),
    'breath': dict(lufs=-23.0, ramp=1.6, attack=1.0, pad=-4, bass='long', bass_db=-10, tune='sparse', tune_db=-4,
                   tune_big=True),
    'ambient': dict(lufs=-24.5, ramp=0.5, attack=1.2, big=True, bass='long', tune='few'),
    'outro': dict(lufs=-22.5, ramp=1.2, attack=1.4, big=True, bass='long', tune='few', arp_mode='slow'),
}
DEFAULT_DEGREES = {'major': {'intro': [6, 4], 'groove': [1, 5, 6, 4], 'light': [4, 5, 3, 6], 'halftime': [4, 1, 6, 5],
                             'breath': [4], 'ambient': [6, 4, 5], 'outro': [4, 1, 1]},
                   'minor': {'intro': [1, 6], 'groove': [1, 6, 3, 7], 'light': [6, 7, 1, 1], 'halftime': [6, 3, 7, 1],
                             'breath': [6], 'ambient': [1, 6, 7], 'outro': [6, 1, 1]}}


# ---- harmony --------------------------------------------------------------------------------------------------------
def parse_key(key, mode=None):
    m = re.match(r'^([A-G])([#b]?)(m|min|minor)?$', key.strip())
    if not m:
        raise SystemExit(f'key {key!r}: use e.g. "E", "F#", "Bb", "Am"')
    return (NOTE[m[1]] + ACC[m[2]]) % 12, ('minor' if (m[3] or mode == 'minor') else 'major')


def parse_chord(sym):
    m = re.match(r'^([A-G])([#b]?)([^/]*)(?:/([A-G])([#b]?))?$', sym.strip())
    if not m or m[3] not in QUAL:
        raise SystemExit(f'chord {sym!r}: root A-G (#/b), quality one of {sorted(QUAL)}, optional /bass')
    root = (NOTE[m[1]] + ACC[m[2]]) % 12
    return dict(sym=sym, root=root, iv=QUAL[m[3]], bass=(NOTE[m[4]] + ACC[m[5]]) % 12 if m[4] else root)


SHARP = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
FLAT = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']


def degree_chord(tonic, mode, d):
    """the diatonic triad on scale degree d (1-7) of the key"""
    sc = MAJOR if mode == 'major' else MINOR
    pcs = [sc[(d - 1 + k) % 7] for k in (0, 2, 4)]
    root = (tonic + pcs[0]) % 12
    iv = [0, (pcs[1] - pcs[0]) % 12, (pcs[2] - pcs[0]) % 12]
    flats = (tonic in (5, 10, 3, 8, 1, 6)) if mode == 'major' else (tonic in (2, 7, 0, 5, 10, 3))
    q = {(4, 7): '', (3, 7): 'm', (3, 6): 'dim', (4, 8): 'aug'}.get((iv[1], iv[2]), '')
    return dict(sym=(FLAT if flats else SHARP)[root] + q, root=root, iv=iv, bass=root)


def pcs_of(ch):
    return sorted({(ch['root'] + i) % 12 for i in ch['iv']})


def voicings(ch):
    """(bass note, pad voicing, 4 arpeggio notes) in MIDI numbers"""
    b = 36 + ch['bass']
    base = sorted(52 + (pc - 52) % 12 for pc in pcs_of(ch))
    pad = list(base)
    for n in base:
        if len(pad) >= 5:
            break
        if n + 12 <= 71:
            pad.append(n + 12)
    tones = sorted(61 + (pc - 61) % 12 for pc in pcs_of(ch))
    arp = tones[:4] if len(tones) >= 4 else tones + [tones[0] + 12]
    return b, sorted(pad), arp


def note_num(v):
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r'^([A-G])([#b]?)(-?\d)$', v.strip())
    return 12 * (int(m[3]) + 1) + NOTE[m[1]] + ACC[m[2]]


# ---- melody ---------------------------------------------------------------------------------------------------------
RHYTHM = {'busy': [[(0, 1), (1, .5), (1.5, .5), (2, 1), (3, 1)], [(0, 1.5), (1.5, .5), (2, 2)],
                   [(0, 1), (1, 1), (2, 1), (3, 1)], [(0, 1.5), (1.5, .5), (2, 1), (3, 1)]],
          'sparse': [[(0, 2), (2, 2)], [(0, 1), (1, 1), (2, 2)], [(0, 2), (2, 1), (3, 1)]],
          'few': [[(0, 2), (2, 2)], [(1, 3)], [(0, 4)]]}
RESOLVE = {'busy': [(0, 1.5), (1.5, .5), (2, 2)], 'sparse': [(0, 4)], 'few': [(0, 4)]}


def melody(rng, chords, mode_name, scale_pcs, oct_shift, prev):
    """one section's tune: [(bar offset, beat, midi, beats)]; chord tones on strong beats, scale steps between,
    2-bar phrases (the second bar resolves), the section's last bar lands long on a chord tone"""
    lo, hi = 66 + oct_shift, 86 + oct_shift
    out = []
    nb = len(chords)
    for k, ch in enumerate(chords):
        cps = pcs_of(ch)
        ct = [n for n in range(lo, hi + 1) if n % 12 in cps]
        sc = [n for n in range(lo, hi + 1) if n % 12 in scale_pcs]
        if k == nb - 1:
            rh = RESOLVE[mode_name] if mode_name != 'busy' else [(0, 2), (2, 2)]
        elif k % 2 == 1:
            rh = RESOLVE[mode_name]
        else:
            rh = RHYTHM[mode_name][int(rng.integers(len(RHYTHM[mode_name])))]
        for beat, ln in rh:
            strong = beat in (0, 2) or ln >= 1.5
            pool = ct if strong else sc
            if prev is None:
                prev = min(ct, key=lambda n: abs(n - (76 + oct_shift)))
                n = prev
            else:
                near = sorted(pool, key=lambda n: (abs(n - prev), n))
                cand = [n for n in near[:4] if n != prev] or near[:1]
                w = np.array([1.0 / (1 + abs(n - prev)) for n in cand])
                n = int(rng.choice(cand, p=w / w.sum()))
            if k == nb - 1 and beat == rh[-1][0]:      # cadence: the root or third of the last chord
                n = min([x for x in ct if x % 12 in (ch['root'], (ch['root'] + ch['iv'][1]) % 12)] or ct,
                        key=lambda x: abs(x - prev))
            out.append((k, beat, n, ln))
            prev = n
    return out, prev


# ---- the score ------------------------------------------------------------------------------------------------------
def build(edl):
    tl = timeline(edl)
    fps = parse_fps(edl['fps'])
    BAR = bar_seconds(edl)
    BEAT = BAR / edl['beats_per_bar']
    bpb = edl['beats_per_bar']
    T = tl[-1]['start'] + tl[-1]['dur']
    N = int(np.ceil(T * SR))
    spec = edl.get('music', {})
    tonic, mode = parse_key(spec.get('key', 'C'), spec.get('mode'))
    scale_pcs = {(tonic + i) % 12 for i in (MAJOR if mode == 'major' else MINOR)}
    rng = np.random.default_rng(spec.get('seed', 7))
    S.rng = np.random.default_rng(spec.get('seed', 7) + 1)
    secs = sections(tl)
    layers = {k: np.zeros((N + 6 * SR, 2)) for k in ('pads', 'arp', 'bass', 'drums', 'tune', 'big', 'fx', 'uwfx')}
    plan, prev_note = [], None
    # the lead (kalimba) steps back under the narration: a melody note on a consonant buries the word
    voice = [(a - 0.15, b + 0.05) for _, a, b, _, _ in line_events(edl, tl, line_lang(edl))] if edl.get('lines') else []
    under_voice = lambda t: any(a <= t <= b for a, b in voice)
    last_bar = int(round(T / BAR)) - 1               # a tail shorter than half a bar rings on the last chord
    for si, (name, t0, t1) in enumerate(secs):
        sp = dict(spec.get('sections', {}).get(name, {}))
        style = sp.get('style') or ('intro' if si == 0 else 'outro' if si == len(secs) - 1 else 'groove')
        st = dict(STYLES[style], **{k: v for k, v in sp.items() if k in STYLES[style] or k in ('lufs', 'ramp')})
        b0 = int(round(t0 / BAR))
        b1 = int(round(t1 / BAR)) if si < len(secs) - 1 else last_bar + 1
        if abs(t0 - b0 * BAR) > 0.1:
            print(f'NOTE: section {name} starts {t0 - b0 * BAR:+.2f}s off the bar grid')
        if b1 <= b0:
            b1 = b0 + 1
        syms = sp.get('chords')
        chords = [parse_chord(c) for c in syms] if syms else \
            [degree_chord(tonic, mode, d) for d in DEFAULT_DEGREES[mode][style]]
        bar_chords = [chords[(b - b0) % len(chords)] for b in range(b0, b1)]
        hit = sp.get('hit', style == 'groove' and si > 0 and plan[-1]['style'] in ('intro', 'breath', 'ambient'))
        plan.append(dict(name=name, style=style, t0=t0, t1=t1, b0=b0, b1=b1, st=st, hit=hit, uw=sp.get('uw', False),
                         chords=[c['sym'] for c in bar_chords]))
        # tune for the section
        tmode = st.get('tune')
        tune = []
        if sp.get('tune'):
            for bk, notes in sp['tune'].items():
                tune += [(int(bk), float(bt), note_num(m), float(ln)) for bt, m, ln in notes]
        elif tmode:
            octave = st.get('tune_oct', 0) + sp.get('tune_octave', 0)
            tune, prev_note = melody(rng, bar_chords, tmode, scale_pcs, octave, prev_note)
        for j, b in enumerate(range(b0, b1)):
            ch = bar_chords[j]
            root, voicing, notes = voicings(ch)
            tb = b * BAR
            final = b == last_bar
            dur = (T - tb + 0.2) if final else BAR + 0.05
            g = lambda db: 10 ** (db / 20)
            # pads
            bus = layers['big'] if st.get('big') else layers['pads']
            pg = g(st.get('pad', 0)) if not st.get('big') else 1.0
            for k, m in enumerate(voicing):
                add(bus, tb, pad_note(m, dur, attack=st['attack'], cutoff=st.get('cutoff', 1500)) * pg,
                    pan=(k - 2) * 0.25)
            # arpeggio
            am = st.get('arp_mode', '8th' if st.get('arp') is not None else None)
            pattern = [0, 1, 2, 3, 2, 1, 2, 3]
            if am in ('8th', 'rise'):
                for qn in range(2 * bpb):
                    tq = tb + qn * BEAT / 2
                    p = (tq - t0) / max(t1 - t0, 1e-6) if am == 'rise' else 1.0
                    gg = (0.4 + 0.6 * p ** 1.5 if am == 'rise' else 1.0) * (0.9 if qn % 2 == 0 else 0.7)
                    br = 0.6 + 1.6 * p if am == 'rise' else 1.0
                    add(layers['arp'], tq + S.rng.normal(0, 0.004),
                        pluck(notes[pattern[qn % 8]] + st.get('arp_oct', 0), 1.0, br) * gg * g(st.get('arp', 0)),
                        pan=0.35 if qn % 2 else -0.35)
            elif am == 'slow' and not final:
                for qn in range(bpb):
                    add(layers['big'], tb + qn * BEAT, pluck(notes[qn % len(notes)] + 12, 2.0, 0.8) * 0.5,
                        pan=-0.3 + 0.2 * qn)
            # bass
            bm, bg = st.get('bass'), g(st.get('bass_db', 0))
            if bm == 'pump':
                for qn in range(bpb):
                    add(layers['bass'], tb + qn * BEAT, bass(root, BEAT * 0.9) * bg)
                add(layers['bass'], tb + (bpb - 0.5) * BEAT, bass(root + 12, BEAT * 0.4) * 0.6 * bg)
            elif bm == 'half':
                for qn in range(0, bpb, 2):
                    add(layers['bass'], tb + qn * BEAT, bass(root, 2 * BEAT - 0.1) * 0.8 * bg)
            elif bm == 'dotted':
                add(layers['bass'], tb, bass(root, 3 * BEAT) * 0.9 * bg)
                add(layers['bass'], tb + 3 * BEAT, bass(root + 7 if root + 7 < 50 else root - 5, BEAT * 0.9) * 0.6 * bg)
            elif bm == 'long':
                dst = layers['big'] if st.get('big') else layers['bass']
                add(dst, tb, bass(root, dur - 0.3, bright=0.1) * 0.6 * bg)
            # drums
            dm, dg = st.get('drums'), g(st.get('drums_db', 0))
            if dm == 'full':
                for qn in range(0, bpb, 2):
                    add(layers['drums'], tb + qn * BEAT, kick() * dg)
                if (b - b0) % 2 == 1:
                    add(layers['drums'], tb + (bpb - 0.5) * BEAT, kick(0.7) * 0.6 * dg)
                for qn in range(1, bpb, 2):
                    add(layers['drums'], tb + qn * BEAT + S.rng.normal(0, 0.003), clap() * 0.35 * dg, pan=0.1)
                for qn in range(4 * bpb):
                    add(layers['drums'], tb + qn * BEAT / 4 + S.rng.normal(0, 0.003),
                        shaker([0.5, 0.22, 0.8, 0.25][qn % 4]) * 0.10 * dg, pan=0.45)
            elif dm in ('shaker', 'half'):
                if dm == 'half':
                    add(layers['drums'], tb, kick(0.8) * 0.9 * dg)
                    add(layers['drums'], tb + 2 * BEAT, clap() * 0.30 * dg, pan=0.1)
                for qn in range(2 * bpb):
                    add(layers['drums'], tb + qn * BEAT / 2 + S.rng.normal(0, 0.004),
                        shaker([0.6, 0.3][qn % 2]) * 0.07 * dg, pan=0.45)
            # tune
            for (bk, beat, m, ln) in tune:
                if bk == j:
                    dst = layers['big'] if (st.get('big') or st.get('tune_big')) else layers['tune']
                    tn = tb + beat * BEAT
                    duck = 0.3 if under_voice(tn) else 1.0
                    add(dst, tn + S.rng.normal(0, 0.006), kalimba(m, 0.5 + ln * BEAT) * (0.85 + 0.15 * S.rng.random())
                        * g(st.get('tune_db', 0)) * duck, pan=0.1)
    # ---- sound design at the cuts ----
    cues = dict(bar=BAR, hits=[], whips=[], sections=[(p['name'], p['t0'], p['t1']) for p in plan])
    fx, big = layers['fx'], layers['big']
    for p in plan:
        if p['hit']:
            t = p['b0'] * BAR
            add(fx, t - BAR, sweep(BAR, 400, 9000, lambda u: u ** 2.4) * 0.30)
            add(fx, t, kick(1.3) * 1.1)
            add(fx, t, noise_burst(2.2, 3500, 0.7) * 0.10)
            cues['hits'].append(t)
    tr = trans_frames(edl, tl)
    for i, (typ, half, extra) in tr.items():
        tc = tl[i]['start']
        if typ == 'whip':
            add(fx, tc - 0.28, whoosh(0.55, -1 if extra == 'right' else 1) * 0.55)
            cues['whips'].append(tc)
        elif typ == 'dissolve' and 2 * half / fps >= 1.2:
            dest = next((p for p in plan if p['t0'] <= tc + 0.01 < p['t1']), None)
            if dest and dest['st'].get('big'):
                add(big, tc - 1.4, sweep(2.6, 2500, 9000, lambda v: np.sin(np.pi * v) ** 2) * 0.10)
    for s in tl:
        if s.get('morph') and s.get('v') in ('rot2fit', 'rot2box'):
            a, b = s['morph']
            add(fx, s['start'] + a, sweep(b - a + 0.3, 300, 7000, lambda u: np.sin(np.pi * u) ** 1.5) * 0.22)
    for x in spec.get('fx', []):
        t = {s['role']: s['start'] for s in tl}[x['shot']] + x.get('at', 0.0)
        d = x.get('dur', BAR)
        kind = x['type']
        if kind == 'riser':
            add(fx, t - d, sweep(d, 400, 9000, lambda u: u ** 2.4) * 0.30)
        elif kind == 'boom':
            add(fx, t, kick(1.3) * 1.1)
        elif kind == 'crash':
            add(fx, t, noise_burst(2.2, 3500, 0.7) * 0.10)
        elif kind == 'whoosh':
            add(fx, t - 0.28, whoosh(0.55, -1 if x.get('direction') == 'right' else 1) * 0.55)
        elif kind == 'shimmer':
            add(big, t - 1.4, sweep(2.6, 2500, 9000, lambda v: np.sin(np.pi * v) ** 2) * 0.10)
        elif kind == 'sweep':
            add(fx, t, sweep(d, 300, 7000, lambda u: np.sin(np.pi * u) ** 1.5) * 0.22)
    # ---- mix the layers ----
    Nt = N
    t = np.arange(Nt) / SR
    dry = sum(layers[k][:Nt] for k in ('pads', 'arp', 'bass', 'drums', 'tune'))
    mix = reverb(dry, 1.8, 0.26, 7000, 1)
    uw_secs = [p for p in plan if p['uw']]
    if uw_secs:
        m = np.zeros(Nt)
        for p in uw_secs:
            m[int(p['t0'] * SR):int(p['t1'] * SR)] = 1
        k = int(0.4 * SR)
        m = np.convolve(m, np.ones(k) / k, 'same')
        uw = underwater(dry)
        uw *= 10 ** (-3 / 20) * np.sqrt((mix ** 2).mean() / max((uw ** 2).mean(), 1e-12))
        mix = mix * (1 - m[:, None]) + uw * m[:, None]
        uwfx = layers['uwfx']
        for p in uw_secs:
            add(uwfx, p['t0'] - 0.05, plunge())
            bubbles(uwfx, p['t0'] + 0.05, 14, 0.7, 420)
            tc = p['t0'] + 1.5
            while tc < p['t1'] - 1.0:
                bubbles(uwfx, tc, int(S.rng.integers(3, 8)), 0.2 + 0.4 * S.rng.random(), 520)
                tc += S.rng.exponential(1.8) + 0.8
            if p['t1'] < T - 0.5:
                add(uwfx, p['t1'] - 0.25, swish())
        b, a = signal.butter(2, 3200 / (SR / 2))
        mix += 0.30 * signal.lfilter(b, a, uwfx[:Nt], axis=0) * np.abs(mix).max() / max(np.abs(uwfx).max(), 1e-9)
    mix += fx[:Nt]
    mix += reverb(big[:Nt], 3.4, 0.5, 5000, 3) * 0.9
    # ---- dynamics by design: each section to its loudness target, eased ramps at the boundaries ----
    gains = []
    for p in plan:
        seg = mix[int(p['t0'] * SR):int(min(p['t1'], T) * SR)]
        gains.append(p['st']['lufs'] - S.lufs(seg))
    pts_t, pts_g = [0.0], [gains[0]]
    for j in range(1, len(plan)):
        tb_ = plan[j]['t0']
        r = plan[j]['st']['ramp'] if 'ramp' in spec.get('sections', {}).get(plan[j]['name'], {}) else \
            (0.04 if plan[j]['hit'] else plan[j]['st']['ramp'])
        pts_t += [tb_ - r / 2, tb_ + r / 2]
        pts_g += [gains[j - 1], gains[j]]
    pts_t.append(T + 1)
    pts_g.append(gains[-1])
    mix *= (10 ** (np.interp(t, pts_t, pts_g) / 20))[:, None]
    # audible from the first frame (a silent first second loses viewers); fade out with the picture, reverb ringing
    fin = 0.25
    fade = tl[-1].get('fade_out', 2.0) + 0.3
    mix *= (np.clip(t / fin, 0, 1) ** 2 * np.clip((T - t) / fade, 0, 1) ** 1.5)[:, None]
    mix *= 10 ** ((-16.0 - S.lufs(mix)) / 20)
    pk = np.abs(mix).max()
    if pk > 0.89:
        mix *= 0.89 / pk
    return mix, plan, cues, T


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edl')
    ap.add_argument('--out')
    a = ap.parse_args()
    edl = load_edl(a.edl)
    mix, plan, cues, T = build(edl)
    out = a.out or out_path(edl, 'music.wav')
    wavfile.write(out, SR, mix.astype(np.float32))
    print(f'{out}: {T:.2f}s, {S.lufs(mix):.1f} LUFS, peak {np.abs(mix).max():.2f}')
    for p in plan:
        seg = mix[int(p['t0'] * SR):int(min(p['t1'], T) * SR)]
        print(f"  {p['name']:10s} {p['style']:8s} bars {p['b0']:3d}-{p['b1'] - 1:3d}  {p['t0']:6.2f}-{p['t1']:6.2f}s "
              f"{S.lufs(seg):6.1f} LUFS  {' '.join(dict.fromkeys(p['chords']))}"
              f"{'  HIT' if p['hit'] else ''}{'  UNDERWATER' if p['uw'] else ''}")
    json.dump(cues, open(out_path(edl, 'cues.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
