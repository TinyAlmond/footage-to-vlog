"""Per-frame target position for a shot, so a push-in / pull-out keeps the subject dead centre -> tracks.json.

Three trackers, pick the one the subject allows (the simple ones are steadier when they work):
  --color  H0-H1[,H0-H1]/SMIN/VMIN   centroid of an HSV colour mask (OpenCV hue 0-180; red wraps: 0-12,170-180)
  --bright X,Y                       the brightest compact blob near a seed point (source px): moon, sun, lamp
  --owl "a quokka"                   OWLv2 open-vocabulary detection (google/owlv2-base-patch16-ensemble, ~600 MB)
The path is median + Gaussian smoothed (and pan-speed limited for --owl) so the framing never jitters, and covers the
transition frames around the shot. compose.py reads it for shots with "centre": "track".

usage: python track.py edl.json ROLE (--color SPEC | --bright X,Y | --owl QUERY [--seed X,Y]) [--win 25] [--smooth 6]
                       [--sample-fps 4] [--max-pan 0.18] [--sheet]
--owl follows the same object from frame to frame (the nearest good detection to the last one); --seed says which
one to start from when there are several (two boats, two people).
"""
import argparse
import json
import os
import subprocess

import cv2
import numpy as np
from scipy import ndimage as ndi

from common import load_edl, parse_fps, pre_post, probe, source_path, timeline

AW = 960                                            # analysis width


def shot_frames(edl, s, pre, post):
    """the shot's frames at the output rate, local frames -pre .. len+post-1, at analysis size (BGR)"""
    fps = parse_fps(edl['fps'])
    path = source_path(edl, s['src'])
    p = probe(path)
    ah = int(round(AW * p['h'] / p['w'] / 2)) * 2
    sp = s.get('speed', 1.0)
    n = pre + s['len_f'] + post
    t0 = s.get('t_in', 0.0) - pre / fps * sp
    pad = 0
    if t0 < 0:
        pad, t0 = int(np.ceil(-t0 * fps / sp)), 0.0
    cmd = ['ffmpeg', '-v', 'error', '-ss', f'{t0:.4f}', '-i', path,
           '-vf', f"setpts=(PTS-STARTPTS)/{sp},fps={edl['fps']},scale={AW}:{ah}", '-frames:v', str(n - pad),
           '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    fr = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.uint8).reshape(-1, ah, AW, 3)
    if pad:
        fr = np.concatenate([np.repeat(fr[:1], pad, 0), fr])
    if len(fr) < n:
        fr = np.concatenate([fr, np.repeat(fr[-1:], n - len(fr), 0)])
    return fr, p['w'] / AW


def smooth(v, med=9, sig=6.0):
    idx = np.arange(len(v))
    ok = np.isfinite(v)
    if ok.sum() < 2:
        raise SystemExit('target found in fewer than 2 frames: try another tracker or a fixed centre')
    v = np.interp(idx, idx[ok], v[ok])
    return ndi.gaussian_filter1d(ndi.median_filter(v, size=med, mode='nearest'), sig, mode='nearest')


def by_color(fr, spec, min_px=40):
    hues, smin, vmin = spec.split('/')
    ranges = [tuple(int(x) for x in r.split('-')) for r in hues.split(',')]
    xs, ys = np.full(len(fr), np.nan), np.full(len(fr), np.nan)
    for i, f in enumerate(fr):
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        m = np.zeros(hsv.shape[:2], bool)
        for a, b in ranges:
            m |= (hsv[..., 0] >= a) & (hsv[..., 0] <= b)
        m &= (hsv[..., 1] >= int(smin)) & (hsv[..., 2] >= int(vmin))
        if m.sum() >= min_px:
            yy, xx = np.nonzero(m)
            xs[i], ys[i] = xx.mean(), yy.mean()
    return xs, ys


def by_brightness(fr, seed, k, win=25):
    """brightest disc (>= 0.93 of the window's peak above its median) in a +-win px window that follows it"""
    x0, y0 = seed[0] / k, seed[1] / k
    H, W = fr.shape[1:3]
    xs, ys = np.full(len(fr), np.nan), np.full(len(fr), np.nan)
    for i, f in enumerate(fr):
        g = cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.0)
        ya, yb = int(max(y0 - win, 0)), int(min(y0 + win + 1, H))
        xa, xb = int(max(x0 - win, 0)), int(min(x0 + win + 1, W))
        w = g[ya:yb, xa:xb]
        sky = np.median(w)
        if w.max() - sky > 25:
            wt = np.clip(w - (sky + 0.93 * (w.max() - sky)), 0, None)
            Y, X = np.mgrid[0:w.shape[0], 0:w.shape[1]]
            xs[i], ys[i] = xa + (wt * X).sum() / wt.sum(), ya + (wt * Y).sum() / wt.sum()
            x0, y0 = xs[i], ys[i]
    return xs, ys


def by_owl(fr, query, fps, sample_fps=4.0, seed=None):
    import torch
    from PIL import Image
    from transformers import Owlv2ForObjectDetection, Owlv2Processor
    dev = 'mps' if torch.backends.mps.is_available() else ('cuda' if torch.cuda.is_available() else 'cpu')
    name = 'google/owlv2-base-patch16-ensemble'
    proc, model = Owlv2Processor.from_pretrained(name), Owlv2ForObjectDetection.from_pretrained(name).to(dev).eval()
    step = max(1, int(round(fps / sample_fps)))
    S = max(fr.shape[1:3])                          # OWLv2 pads to a square: boxes come back in padded coordinates
    xs, ys, sc = np.full(len(fr), np.nan), np.full(len(fr), np.nan), np.zeros(len(fr))
    last = None if seed is None else np.array(seed, float)
    for i in range(0, len(fr), step):
        inp = proc(text=[[query]], images=Image.fromarray(fr[i][..., ::-1]), return_tensors='pt').to(dev)
        with torch.no_grad():
            out = model(**inp)
        r = proc.post_process_grounded_object_detection(out, threshold=0.0, target_sizes=torch.tensor([[S, S]]),
                                                        text_labels=[[query]])[0]
        if len(r['scores']):
            boxes = r['boxes'].cpu().numpy()
            scores = r['scores'].cpu().numpy()
            cxy = np.stack([(boxes[:, 0] + boxes[:, 2]) / 2, (boxes[:, 1] + boxes[:, 3]) / 2], 1)
            if last is not None:           # prefer the same object: two boats, two quokkas - don't jump between them
                d = np.hypot(*(cxy - last).T) / fr.shape[2]
                j = int(np.argmax(scores * np.exp(-(d / 0.12) ** 2)))
            else:
                j = int(scores.argmax())
            xs[i], ys[i], sc[i] = cxy[j][0], cxy[j][1], float(scores[j])
            if scores[j] >= 0.12:
                last = cxy[j]
    ok = sc >= max(0.12, 0.35 * sc.max())            # confident detections only
    xs[~ok], ys[~ok] = np.nan, np.nan
    print(f'OWLv2 "{query}": {int(ok.sum())} confident of {len(range(0, len(fr), step))} sampled frames '
          f'(best score {sc.max():.2f})')
    return xs, ys


def limit_speed(v, max_step):
    v = v.copy()
    for i in range(1, len(v)):
        v[i] = v[i - 1] + np.clip(v[i] - v[i - 1], -max_step, max_step)
    return v


def sheet(fr, xs, ys, k, path):
    tiles = []
    for i in np.linspace(0, len(fr) - 1, 8).astype(int):
        im = fr[i].copy()
        h, w = im.shape[:2]
        cv2.drawMarker(im, (w // 2, h // 2), (255, 255, 255), cv2.MARKER_CROSS, 30, 1)
        cv2.drawMarker(im, (int(xs[i] / k), int(ys[i] / k)), (0, 255, 255), cv2.MARKER_TILTED_CROSS, 40, 3)
        cv2.putText(im, f'frame {i}', (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        tiles.append(cv2.resize(im, (480, int(480 * h / w))))
    cv2.imwrite(path, np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])]), [cv2.IMWRITE_JPEG_QUALITY, 85])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edl')
    ap.add_argument('role')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--color')
    g.add_argument('--bright', help='seed X,Y in source pixels (where the target is at the start of the shot)')
    g.add_argument('--owl', help='text query, e.g. "a quokka"')
    ap.add_argument('--seed', help='--owl: X,Y (source px) of the one you mean when there are several')
    ap.add_argument('--win', type=int, default=25, help='--bright search window (analysis px)')
    ap.add_argument('--smooth', type=float, default=6.0, help='Gaussian sigma in frames')
    ap.add_argument('--sample-fps', type=float, default=4.0, help='--owl detections per second')
    ap.add_argument('--max-pan', type=float, default=0.18, help='--owl: max pan speed, frame widths per second')
    ap.add_argument('--sheet', action='store_true', help='write track_<role>.jpg to check the path by eye')
    a = ap.parse_args()
    edl = load_edl(a.edl)
    tl = timeline(edl)
    idx = {s['role']: i for i, s in enumerate(tl)}
    if a.role not in idx:
        raise SystemExit(f'no shot {a.role!r}; roles: {", ".join(idx)}')
    i = idx[a.role]
    s = tl[i]
    pre, post = pre_post(edl, tl)[i]
    fps = parse_fps(edl['fps'])
    fr, k = shot_frames(edl, s, pre, post)
    if a.color:
        xs, ys = by_color(fr, a.color)
    elif a.bright:
        xs, ys = by_brightness(fr, [float(v) for v in a.bright.split(',')], k, a.win)
    else:
        seed = [float(v) / k for v in a.seed.split(',')] if a.seed else None
        xs, ys = by_owl(fr, a.owl, fps, a.sample_fps, seed)
    found = int(np.isfinite(xs).sum())
    sig = a.smooth if not a.owl else max(a.smooth, 0.6 * fps)
    x, y = smooth(xs, sig=sig), smooth(ys, sig=sig)
    if a.owl:
        x, y = limit_speed(x, a.max_pan * fr.shape[2] / fps), limit_speed(y, a.max_pan * fr.shape[2] / fps)
    x, y = x * k, y * k
    p = os.path.join(edl['_dir'], 'tracks.json')
    tracks = json.load(open(p)) if os.path.exists(p) else {}
    tracks[a.role] = dict(pre_f=pre, x=np.round(x, 1).tolist(), y=np.round(y, 1).tolist())
    json.dump(tracks, open(p, 'w'))
    print(f'{a.role}: target found in {found}/{len(fr)} frames; x {x.min():.0f}..{x.max():.0f}, '
          f'y {y.min():.0f}..{y.max():.0f} (source px) -> {p}')
    if a.sheet:
        sp = os.path.join(edl['_dir'], f'track_{a.role}.jpg')
        sheet(fr, x, y, k, sp)
        print('wrote', sp)


if __name__ == '__main__':
    main()
