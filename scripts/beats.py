"""Analyse an existing song so the film can be cut on it: beats, bar starts (downbeats), loudness per bar, sections.
-> beats.json (read by common.timeline() when the EDL's "music" has a "file") + beats.png to look at.

Beats and downbeats come from beat_this (CPJKU, a transformer beat tracker: pip install beat_this; checkpoint ~80 MB
on first use), which follows the song's real timing - a ballad drifts, and a constant-BPM grid would slide off it.
Without beat_this, librosa's tracker is used, with bar starts chosen as the beat phase where the bass hits and the
harmony changes; it can lock onto the off-beats of songs without a clear kick. Either way every beat is snapped back
to the start of its attack (onset detectors peak 20-50 ms late, a cut would land a frame late). Sections come from
changes in harmony and timbre and are labelled by loudness: the strongest shot on the chorus, quiet beats on the
verse. Check the tempo against how the song feels; with librosa, --bpm-hint / --half / --double fix a tracker that
locked onto double or half time.

usage: python beats.py SONG [--out beats.json] [--bpm-hint 72] [--half | --double] [--meter 4] [--sections 8]
"""
import argparse
import json
import os
import subprocess

import cv2
import numpy as np

SR = 22050
HOP = 512


def load(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def zs(v):
    v = np.asarray(v, float)
    return (v - v.mean()) / (v.std() + 1e-9)


def neural_beats(y):
    """(beats, downbeats) in seconds from beat_this, or None when it is not installed"""
    try:
        import torch
        from beat_this.inference import Audio2Beats
    except ImportError:
        return None
    dev = 'mps' if torch.backends.mps.is_available() else ('cuda' if torch.cuda.is_available() else 'cpu')
    beats, downs = Audio2Beats(checkpoint_path='final0', device=dev, dbn=False)(y, SR)
    return np.asarray(beats, float), np.asarray(downs, float)


def constant_grid(bt, model_downs, meter, duration):
    """most studio songs are recorded to a click: fit t = t0 + k * P to the tracked beats, ignoring outliers (beats
    the tracker lost in a quiet passage), and put bar starts where the model's downbeats vote. Returns the grid and
    how well it fits (p90 residual of the inliers, share of beats that are inliers)."""
    d = np.diff(bt)
    P0 = float(np.median(d))
    best = None
    for P in np.linspace(0.96 * P0, 1.04 * P0, 801):
        ph = np.angle(np.exp(2j * np.pi * bt / P).mean()) / (2 * np.pi) * P
        r = (bt - ph + P / 2) % P - P / 2
        score = np.median(np.abs(r))
        if best is None or score < best[0]:
            best = (score, P, ph)
    _, P, ph = best
    k = np.round((bt - ph) / P)
    r = bt - (ph + k * P)
    inl = np.abs(r) < 0.06
    A = np.vstack([np.ones(inl.sum()), k[inl]]).T
    (t0, P), *_ = np.linalg.lstsq(A, bt[inl], rcond=None)
    r = bt[inl] - (t0 + k[inl] * P)
    k0 = int(np.ceil(-t0 / P))
    grid = t0 + P * np.arange(k0, int((duration - t0) / P) + 1)
    votes = np.zeros(meter)
    if model_downs is not None and len(model_downs):
        for dt in model_downs:
            kk = int(np.round((dt - t0) / P))
            if abs(dt - (t0 + kk * P)) < 0.08:
                votes[kk % meter] += 1
    phase = int(np.argmax(votes)) if votes.sum() else 0
    bars = grid[[i for i, kk in enumerate(range(k0, k0 + len(grid))) if kk % meter == phase]]
    return dict(period=round(float(P), 5), bpm=round(60 / float(P), 2), t0=round(float(t0), 4),
                residual_ms_p90=round(float(np.percentile(np.abs(r), 90)) * 1000, 1),
                inliers=round(float(inl.mean()), 3), phase_votes=votes.tolist(),
                beats=[round(float(t), 3) for t in grid], bars=[round(float(t), 3) for t in bars])


def analyse(y, bpm_hint=None, mult=1.0, meter=4, n_sections=None, engine='auto'):
    import librosa
    onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    nb = neural_beats(y) if engine in ('auto', 'beat_this') else None
    if nb is not None and len(nb[0]) > 8:
        bt, downs_nb = nb
        tempo = 60.0 / float(np.median(np.diff(bt)))
        used = 'beat_this'
    else:
        kw = dict(onset_envelope=onset, sr=SR, hop_length=HOP, tightness=100)
        if bpm_hint:
            kw['start_bpm'] = bpm_hint
        tempo, beats = librosa.beat.beat_track(**kw)
        tempo = float(np.atleast_1d(tempo)[0])
        bt = librosa.frames_to_time(beats, sr=SR, hop_length=HOP)
        downs_nb = None
        used = 'librosa'
    # the onset envelope peaks 20-50 ms after a note starts: snap each beat back to the start of its attack
    starts = librosa.onset.onset_detect(onset_envelope=onset, sr=SR, hop_length=HOP, backtrack=True, units='time')
    for i, b in enumerate(bt):
        near = starts[(starts >= b - 0.09) & (starts <= b + 0.03)]
        bt[i] = near[np.argmin(np.abs(near - b))] if len(near) else b - 0.025
    bt = np.maximum(bt, 0.0)
    agree = None
    if downs_nb is not None and mult == 1.0 and len(downs_nb):
        # the model's bar starts can wobble where the music thins out. Choose bar starts on the beats by dynamic
        # programming: reward the model's downbeats, charge bars that are not `meter` beats long - one misplaced
        # model downbeat is outvoted, a run of them (a real dropped beat or metre change) is followed
        model = np.zeros(len(bt))
        for d in downs_nb:
            model[int(np.argmin(np.abs(bt - d)))] = 1.0
        cost = {g: (0.0 if g == meter else 1.2 if abs(g - meter) == 1 else 4.0) for g in range(2, 2 * meter + 1)}
        best = np.full(len(bt), -np.inf)
        prev = np.full(len(bt), -1)
        best[:meter] = model[:meter]
        for i in range(len(bt)):
            for g, c in cost.items():
                if i - g >= 0 and best[i - g] - c + model[i] > best[i]:
                    best[i], prev[i] = best[i - g] - c + model[i], i - g
        end = int(np.argmax(best[max(0, len(bt) - meter):])) + max(0, len(bt) - meter)
        clean = [end]
        while prev[clean[-1]] >= 0:
            clean.append(int(prev[clean[-1]]))
        clean = clean[::-1]
        gaps = np.diff(clean)
        agree = float((gaps == meter).mean()) if len(gaps) else 1.0
        phase, phase_score = clean[0], []
        downbeats = bt[clean]
    if mult == 0.5:                                      # tracker at double time: keep every other beat
        bt = bt[::2]
        tempo /= 2
    elif mult == 2.0:                                    # tracker at half time: add the beats in between
        bt = np.sort(np.concatenate([bt, (bt[:-1] + bt[1:]) / 2]))
        tempo *= 2
    # bar starts: the beat phase with the strongest bass onsets and harmony changes
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    low = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[freqs < 160]), sr=SR, hop_length=HOP)
    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
    bf = librosa.time_to_frames(bt, sr=SR, hop_length=HOP)
    bf = np.clip(bf, 0, chroma.shape[1] - 1)
    seg = np.split(np.arange(chroma.shape[1]), bf)
    cb = np.stack([chroma[:, s].mean(1) if len(s) else np.zeros(12) for s in seg[1:]] + [np.zeros(12)])[:len(bf)]
    cb /= np.linalg.norm(cb, axis=1, keepdims=True) + 1e-9
    change = np.r_[0, 1 - (cb[1:] * cb[:-1]).sum(1)]     # harmony change into each beat
    accent = zs(low[bf]) + zs(change)
    if downs_nb is None or mult != 1.0:
        phase_score = [accent[p::meter].mean() for p in range(meter)]
        phase = int(np.argmax(phase_score))
        downbeats = bt[phase::meter]
    # a constant-tempo grid fitted to the beats; used for the bars when it fits (a song recorded to a click)
    grid = constant_grid(bt, downs_nb if downs_nb is not None else downbeats, meter, len(y) / SR)
    grid['use'] = bool(grid['residual_ms_p90'] <= 60 and grid['inliers'] >= 0.75)   # within tracking noise
    if grid['use']:
        downbeats = np.array(grid['bars'])
    # loudness per bar (RMS dB) and sections from beat-synchronous chroma + timbre
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    edges = np.r_[downbeats, len(y) / SR]
    bars = []
    for i in range(len(downbeats)):
        f0, f1 = librosa.time_to_frames([edges[i], edges[i + 1]], sr=SR, hop_length=HOP)
        bars.append(dict(i=i, t=round(float(downbeats[i]), 3),
                         db=round(float(20 * np.log10(rms[f0:max(f1, f0 + 1)].mean() + 1e-9)), 1)))
    mfcc = librosa.feature.mfcc(y=y, sr=SR, hop_length=HOP, n_mfcc=13)
    dbf = np.clip(librosa.time_to_frames(downbeats, sr=SR, hop_length=HOP), 0, chroma.shape[1] - 1)
    feat = np.vstack([librosa.util.sync(chroma, dbf), zs(librosa.util.sync(mfcc, dbf)) * 0.3])
    k = n_sections or int(np.clip(round(len(y) / SR / 22), 3, 12))
    bounds = librosa.segment.agglomerative(feat, k) if feat.shape[1] > k else np.arange(feat.shape[1])
    bounds = sorted(set([0] + [int(b) for b in bounds] + [len(bars)]))
    secs = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b <= a:
            continue
        db = float(np.mean([x['db'] for x in bars[a:b]]))
        secs.append(dict(bar0=a, bar1=b, t0=bars[a]['t'], t1=round(float(edges[b]), 3), db=round(db, 1)))
    lo, hi = np.percentile([s['db'] for s in secs], [33, 67]) if secs else (0, 0)
    for s in secs:
        s['level'] = 'quiet' if s['db'] <= lo else ('loud' if s['db'] >= hi else 'medium')
    return dict(engine=used, tempo=round(tempo, 1), meter=meter, phase=phase, downbeat_agreement=agree, grid=grid,
                phase_score=[round(float(v), 2) for v in phase_score], beats=[round(float(t), 3) for t in bt],
                bars=bars, sections=secs, duration=round(len(y) / SR, 3))


def plot(res, y, path):
    W, H = 2400, 520
    img = np.full((H, W, 3), 22, np.uint8)
    T = res['duration']
    x = lambda t: int(20 + (W - 40) * t / T)
    for s in res['sections']:
        col = {'quiet': (60, 45, 35), 'medium': (70, 70, 45), 'loud': (40, 60, 95)}[s['level']]
        cv2.rectangle(img, (x(s['t0']), 40), (x(s['t1']), H - 60), col, -1)
    n = len(y) // (W - 40)
    env = np.sqrt((y[:n * (W - 40)].reshape(W - 40, n) ** 2).mean(1))
    env = 20 * np.log10(env + 1e-6)
    env = np.clip((env - env.max() + 40) / 40, 0, 1)
    for i, v in enumerate(env):
        cv2.line(img, (20 + i, H - 60), (20 + i, int(H - 60 - v * (H - 120))), (200, 200, 200), 1)
    for b in res['bars']:
        cv2.line(img, (x(b['t']), 40), (x(b['t']), H - 60), (90, 160, 230), 1)
        if b['i'] % 4 == 0:
            cv2.putText(img, str(b['i']), (x(b['t']) + 2, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (90, 200, 255), 1)
    for t in range(0, int(T) + 1, 10):
        cv2.putText(img, f'{t // 60}:{t % 60:02d}', (x(t), H - 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(img, f"{res['tempo']} BPM, bars every {res['meter']} beats; sections: blue = loud, olive = medium, "
                     f"brown = quiet; bar numbers every 4", (20, H - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (230, 230, 230), 1)
    cv2.imwrite(path, img)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('song')
    ap.add_argument('--out', default='beats.json')
    ap.add_argument('--bpm-hint', type=float)
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--half', action='store_true', help='the tracker found double time: keep every other beat')
    g.add_argument('--double', action='store_true', help='the tracker found half time: add the beats in between')
    ap.add_argument('--meter', type=int, default=4)
    ap.add_argument('--sections', type=int, help='how many sections to split the song into (default: by length)')
    ap.add_argument('--engine', default='auto', choices=['auto', 'beat_this', 'librosa'])
    a = ap.parse_args()
    y = load(a.song)
    res = analyse(y, a.bpm_hint, 0.5 if a.half else (2.0 if a.double else 1.0), a.meter, a.sections, a.engine)
    res['file'] = os.path.abspath(a.song)
    json.dump(res, open(a.out, 'w'), indent=1)
    png = os.path.splitext(a.out)[0] + '.png'
    plot(res, y, png)
    bars = res['bars']
    iv = np.diff([b['t'] for b in bars])
    print(f"{a.song}: {res['duration']:.1f}s, {res['tempo']:.1f} BPM ({res['engine']}), {len(res['beats'])} beats, "
          f"{len(bars)} bars (bar length {np.median(iv):.2f}s, {iv.min():.2f}-{iv.max():.2f})")
    g = res['grid']
    print(f"constant-tempo grid: {g['bpm']} BPM, residual p90 {g['residual_ms_p90']} ms, {g['inliers']:.0%} of beats "
          f"on it -> " + ('the bars follow this grid (the song keeps a steady tempo)' if g['use'] else
                          'NOT used: the tempo drifts; bars follow the tracked beats'))
    ag = None if g['use'] else res.get('downbeat_agreement')
    if ag is not None and ag < 0.8:
        print(f'WARNING: only {ag:.0%} of the bars are {res["meter"]} beats long - a metre change, a 3/4 or 6/8 song '
              f'(--meter 3 / 6), dropped beats in a quiet passage, or rubato: check beats.png against the song')
    for s in res['sections']:
        print(f"  bars {s['bar0']:3d}-{s['bar1'] - 1:3d}  {s['t0']:6.1f}-{s['t1']:6.1f}s  {s['db']:6.1f} dB  {s['level']}")
    print('wrote', a.out, 'and', png)


if __name__ == '__main__':
    main()
