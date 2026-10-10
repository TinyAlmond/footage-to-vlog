"""Lyric line cut times for an existing song: cut the picture on each sung line.

    lyrics.py song.wav --from 62.9 [--to 124] [--out lyrics/lines.json] [--gap 0.6] [--snap 0.12]

1. Whisper (large-v3-turbo) word timestamps, in short overlapping windows: one long pass over a full mix
   can drop a whole loud section (it did: 17 s of chorus came back as one word).
2. Words are grouped into lines on pauses longer than --gap seconds.
3. Each line start is moved to the strongest vocal-band (300-3400 Hz) onset within -0.30/+0.20 s of Whisper's time,
   then snapped to the nearest beat (beats.json next to the EDL) if within --snap seconds. Pickups sung before the
   beat keep their own onset.

Writes [{"cut", "onset", "whisper", "beat_off_ms", "words"}] - a DRAFT (see references/sound.md): read it, merge or split lines by hand where the
song's phrasing says so (a repeated ad-lib can be its own line; one breath can be two lines), then set
"music": {"lines": "lyrics/lines.json"} in the EDL and give shots "lines": 1. The printed table shows times and the
first word only; check the cuts by ear in the preview.
"""
import argparse
import json
import os

import numpy as np


def words(path, t_from, t_to, win=12.0, hop=8.0):
    import librosa
    import torch
    from transformers import pipeline
    y, sr = librosa.load(path, sr=16000, mono=True)
    t_to = min(t_to or len(y) / sr, len(y) / sr)
    dev = 'mps' if torch.backends.mps.is_available() else ('cuda' if torch.cuda.is_available() else 'cpu')
    p = pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo',
                 dtype=torch.float16 if dev != 'cpu' else torch.float32, device=dev)
    out, a = [], t_from
    while a < t_to - 1.0:
        b = min(a + win, t_to)
        r = p(y[int(a * sr):int(b * sr)], return_timestamps='word', generate_kwargs={'language': 'en'})
        for c in r['chunks']:
            t0 = c['timestamp'][0] + a
            t1 = (c['timestamp'][1] or c['timestamp'][0]) + a
            # keep a word from the window where it sits furthest from an edge
            if (a > t_from and t0 < a + 1.0) or (b < t_to and t1 > b - 1.0):
                continue
            out.append(dict(w=c['text'].strip(), t0=round(t0, 3), t1=round(t1, 3)))
        a += hop
    out.sort(key=lambda x: x['t0'])
    dedup = []
    for x in out:
        if dedup and abs(x['t0'] - dedup[-1]['t0']) < 0.15:
            continue
        dedup.append(x)
    return dedup


def lines_from(ws, gap):
    lines = []
    for x in ws:
        if not lines or x['t0'] - lines[-1]['t1'] > gap:
            lines.append(dict(t0=x['t0'], t1=x['t1'], words=[x['w']]))
        else:
            lines[-1]['t1'] = x['t1']
            lines[-1]['words'].append(x['w'])
    return lines


def refine(path, lines, beats, snap):
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=256))
    f = librosa.fft_frequencies(sr=sr, n_fft=2048)
    band = (f > 300) & (f < 3400)
    on = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[band]), sr=sr, hop_length=256)
    tt = librosa.frames_to_time(np.arange(len(on)), sr=sr, hop_length=256)
    out = []
    for ln in lines:
        c = ln['t0']
        m = (tt > c - 0.30) & (tt < c + 0.20)
        t = float(tt[m][np.argmax(on[m])]) if m.any() else c
        cut, off = t, None
        if len(beats):
            nb = float(beats[np.argmin(abs(beats - t))])
            off = round((t - nb) * 1000)
            if abs(t - nb) <= snap:
                cut = nb
        out.append(dict(cut=round(cut, 3), onset=round(t, 3), whisper=c, beat_off_ms=off, words=' '.join(ln['words'])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('song')
    ap.add_argument('--from', dest='t_from', type=float, default=0.0)
    ap.add_argument('--to', dest='t_to', type=float)
    ap.add_argument('--beats', default='beats.json')
    ap.add_argument('--out', default='lyrics/lines.json')
    ap.add_argument('--gap', type=float, default=0.6)
    ap.add_argument('--snap', type=float, default=0.12)
    a = ap.parse_args()
    beats = []
    if os.path.exists(a.beats):
        b = json.load(open(a.beats))
        g = b.get('grid', {})
        beats = g['beats'] if g.get('use') else b['beats']
    ws = words(a.song, a.t_from, a.t_to)
    res = refine(a.song, lines_from(ws, a.gap), np.array(beats), a.snap)
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)
    for i, r in enumerate(res):
        first = r['words'].split()[0] if r['words'] else ''
        print(f"L{i + 1:<3d} cut {r['cut']:8.3f}  onset {r['onset']:8.3f}  beat {r['beat_off_ms']:+5d} ms  {first}")
    print(f'{len(res)} lines -> {a.out}')


if __name__ == '__main__':
    main()
