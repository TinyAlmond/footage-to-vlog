"""The final mix: score + each shot's own sound + narration -> mix_<lang>.wav (48 kHz stereo).

Natural sound, per shot ("natural": target LUFS; leave it out for silence): high-passed ("hpf": Hz, for wind),
levelled shot by shot (a phone and an action camera can differ by 17 dB), with bumps and gusts held 15 dB above the
target so nothing jumps out. "speech": [[a, b], ...] (seconds into the shot; [a, b, "words"] also lets
finish.py --verify check them) marks people talking on camera: their words go to -20 LUFS, just under the
narration, while the rest of the shot keeps its natural level. The music ducks under the narration and the
on-camera speech ("duck_db" 9 dB, "speech_duck_db" 12 dB), natural sound under the narration. Then -16 LUFS, true peak
<= -1.5 dBFS (4x oversampled lookahead limiter). The report gives the loudness of every section of the finished
mix - the dynamics you designed must survive the mix; a spread under ~4 LU sounds flat.

With an existing song ("music": {"file": ..., "start_bar": n}), the song plays from that bar and fades out with the
picture ("fade_out" s, default the last shot's fade + 0.3).

usage: python mix.py edl.json [--lang zh] [--music music.wav] [--no-narration] [--no-music] [--out FILE]
EDL "mix": {"lufs": -16, "duck_db": 9, "speech_duck_db": 12, "ceiling": -1.5}
"""
import argparse
import os
import subprocess

import numpy as np
from scipy import ndimage as ndi
from scipy import signal
from scipy.io import wavfile

import synth as S
from common import line_events, line_lang, load_edl, out_path, sections, song, source_path, timeline, trans_frames, \
    parse_fps, is_still, probe

SR = S.SR


def src_audio(path, t0, dur, speed=1.0):
    af = ['aformat=channel_layouts=stereo']
    if speed != 1.0:
        sp, chain = speed, []
        while sp < 0.5:                                  # atempo takes 0.5..2 per stage
            chain.append('atempo=0.5')
            sp /= 0.5
        chain.append(f'atempo={sp:.5f}')
        af = chain + af
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{max(t0, 0):.4f}', '-i', path, '-t', f'{dur * speed:.4f}',
                          '-vn', '-af', ','.join(af), '-ac', '2', '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True).stdout
    x = np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)
    if t0 < 0:
        x = np.concatenate([np.zeros((int(-t0 / speed * SR), 2)), x])
    n = int(round(dur * SR))
    return np.pad(x, ((0, max(0, n - len(x))), (0, 0)))[:n]


def fades(x, fin, fout):
    x = x.copy()
    for k, rev in ((min(len(x), int(fin * SR)), False), (min(len(x), int(fout * SR)), True)):
        if k:
            r = np.linspace(0, 1, k) ** 2
            if rev:
                x[-k:] *= r[::-1, None]
            else:
                x[:k] *= r[:, None]
    return x


def to_lufs(x, target):
    v = S.lufs(x)
    return x * 10 ** ((target - v) / 20) if v > -69 else x


def natural(edl, tl, N):
    """every shot's own sound at its level; returns the bed and the on-camera speech windows (global seconds)"""
    fps = parse_fps(edl['fps'])
    tr = trans_frames(edl, tl)
    nat = np.zeros((N, 2))
    speech = []
    for i, s in enumerate(tl):
        if s.get('natural') is None:
            continue
        path = source_path(edl, s['src'])
        if is_still(path) or not probe(path)['audio']:
            print(f"  {s['role']}: 'natural' set but the source has no sound")
            continue
        pre = tr[i][1] / fps if i in tr else 0.0
        sp = s.get('speed', 1.0)
        x = src_audio(path, s.get('t_in', 0.0) - pre * sp, s['dur'] + pre, sp)
        if s.get('hpf'):
            b, a = signal.butter(2, s['hpf'] / (SR / 2), 'high')
            x = signal.lfilter(b, a, x, axis=0)
        if s.get('speech'):
            # the words to -20 LUFS (just under the narration); the rest of the shot stays at its natural level
            tt = np.arange(len(x)) / SR - pre                     # seconds from the shot's start
            inv = np.zeros(len(x), bool)
            for w in s['speech']:
                inv |= (tt >= w[0]) & (tt <= w[1])
                speech.append((s['start'] + w[0], s['start'] + w[1]))
            gv = -20.0 - S.lufs(x[inv])
            ga = s['natural'] - S.lufs(x[~inv]) if (~inv).sum() > SR // 2 else gv - 10.0
            if gv - ga > 12:
                print(f"  {s['role']}: the speech is buried in the ambience; lifting it only 12 dB over it")
                gv = ga + 12
            g = np.full(len(x), ga)
            for w in s['speech']:
                wg = np.interp(tt, [w[0] - 0.3, w[0], w[1], w[1] + 0.3], [ga, gv, gv, ga])
                g = np.where(np.abs(wg - ga) > np.abs(g - ga), wg, g)
            x = S.limiter(x * 10 ** (g / 20)[:, None], ceil_db=-5.0, look=0.01)[0]
            print(f"  {s['role']}: speech to -20 LUFS ({gv - ga:+.1f} dB against the ambience at {s['natural']} LUFS)")
        else:
            x = to_lufs(x, s['natural'])
            x = S.limiter(x, ceil_db=s['natural'] + 15, look=0.01)[0]
        nxt = tl[i + 1] if i + 1 < len(tl) else None
        fin = max(pre * 2, 0.25) if pre else (0.06 if i and tl[i - 1].get('natural') is not None else 0.25)
        fout = 0.25 if (nxt is None or nxt.get('natural') is None) else 0.06
        if i + 1 in tr:                                   # the outgoing half of a transition
            post = tr[i + 1][1] / fps
            x = np.concatenate([x, src_audio(path, s.get('t_in', 0.0) + s['dur'] * sp, post, sp) *
                                10 ** ((s['natural'] - S.lufs(x)) / 20 if S.lufs(x) > -69 else 0)])
            fout = max(post * 2, 0.25)
        S.add(nat, s['start'] - pre, fades(x, fin, fout))
    return nat, speech


def ducking(wins, T, N, depth_db):
    """gain curve: -depth_db under the windows (120 ms early, 80 ms late), smooth edges (built at 1 kHz: fast)"""
    m = np.zeros(int(T * 1000) + 2)
    for x0, x1 in wins:
        m[int(max(x0 - 0.12, 0) * 1000):int(min(x1 + 0.08, T) * 1000)] = 1
    m = np.clip(ndi.gaussian_filter1d(m, 80), 0, 1)
    g = 1 - (1 - 10 ** (-depth_db / 20)) * m
    return np.interp(np.arange(N) / SR, np.arange(len(g)) / 1000, g)


def narration(edl, tl, lang, N):
    nar = np.zeros((N, 2))
    wins = []
    for k, a, _, _, _ in line_events(edl, tl, lang):
        p = os.path.join(edl['_dir'], 'narration', lang, f'line_{k}.wav')
        if not os.path.exists(p):
            print(f'  line {k}: no {p} (run narrate.py) - left out')
            continue
        sr, y = wavfile.read(p)
        S.add(nar, a, y.astype(np.float64))
        wins.append((a, a + len(y) / SR))
    return nar, wins


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edl')
    ap.add_argument('--lang')
    ap.add_argument('--music', help='default: the EDL\'s song, else music.wav next to the EDL (score.py)')
    ap.add_argument('--no-narration', action='store_true')
    ap.add_argument('--no-music', action='store_true', help='leave the music out (to add the song in the app)')
    ap.add_argument('--out')
    a = ap.parse_args()
    edl = load_edl(a.edl)
    cfg = dict(dict(lufs=-16.0, duck_db=9.0, speech_duck_db=12.0, ceiling=-1.5), **edl.get('mix', {}))
    tl = timeline(edl)
    T = tl[-1]['start'] + tl[-1]['dur']
    N = int(round(T * SR))
    lang = line_lang(edl, a.lang)
    sg = song(edl)
    mp = a.music or (sg['path'] if sg else os.path.join(edl['_dir'], 'music.wav'))
    if os.path.exists(mp):
        m = edl.get('music', {})
        mus = src_audio(mp, sg['start'] if (sg and not a.music) else 0.0, T)
        if sg and not a.music:                       # a song cut out of the middle: ease in, fade with the picture
            fin = int(m.get('fade_in', 0.02) * SR)
            fout = int(m.get('fade_out', max(tl[-1].get('fade_out', 2.0) + 0.3, 1.5)) * SR)
            if fin:
                mus[:fin] *= (np.linspace(0, 1, fin) ** 2)[:, None]
            mus[-fout:] *= (np.linspace(1, 0, fout) ** 1.5)[:, None]
            print(f"music: {os.path.basename(mp)} from {sg['start']:.2f}s, fading out over the last {fout / SR:.1f}s")
    else:
        print(f'no music at {mp}: natural sound and narration only')
        mus = np.zeros((N, 2))
    print('natural sound:')
    nat, speech = natural(edl, tl, N)
    nar, wins = (np.zeros((N, 2)), []) if (a.no_narration or not edl.get('lines')) else narration(edl, tl, lang, N)
    # the music ducks under every voice - deeper under on-camera speech, which is rougher than the narration and
    # loses its consonants first; natural sound ducks only under the narration (speech shots are levelled already)
    nduck = ducking(wins, T, N, cfg['duck_db'])
    duck = np.minimum(nduck, ducking(speech, T, N, cfg['speech_duck_db']))
    mix = mus * duck[:, None] + nat * nduck[:, None] + nar
    gain = 10 ** ((cfg['lufs'] - S.lufs(mix)) / 20)
    if a.no_music:                                   # same levels as the full mix, so the song added later fits
        mix = nat * nduck[:, None] + nar
    mix *= gain
    mix, gmin = S.limiter(mix, ceil_db=cfg['ceiling'])
    out = a.out or out_path(edl, f"mix_{lang}.wav" if (edl.get('lines') and not a.no_narration) else 'mix.wav')
    wavfile.write(out, SR, mix.astype(np.float32))
    print(f'{out}: {S.lufs(mix):.1f} LUFS, peak {20 * np.log10(np.abs(mix).max() + 1e-12):.1f} dBFS, '
          f'limiter max {20 * np.log10(gmin):.1f} dB')
    lv = []
    for name, x0, x1 in sections(tl):
        v = S.lufs(mix[int(x0 * SR):int(x1 * SR)])
        lv.append(v)
        print(f'  {name:10s} {x0:6.2f}-{x1:6.2f}s  {v:6.1f} LUFS')
    for x0, x1 in wins:
        print(f'  voice {x0:6.2f}-{x1:6.2f}s')
    if len(lv) > 2 and max(lv) - min(lv) < 4:
        print(f'NOTE: sections span only {max(lv) - min(lv):.1f} LU' +
              (" - that is the song's own shape (fine if it builds; a chorus at the climax still lifts)" if sg else
               ' - it will sound flat; widen the score targets'))
    if 20 * np.log10(gmin) < -4:
        print('NOTE: the limiter works hard (> 4 dB): something is much louder than the rest - '
              'check the natural levels')


if __name__ == '__main__':
    main()
