"""Find the moments that have a subject: CLIP zero-shot scoring of every clip, second by second.

Each sampled frame gets a softmax over subject prompts (--pos) and everything-else prompts (--neg); the subject
probability is written per frame, and the best windows (runs above --thresh) are printed - the shortlist to look at
on contact sheets. Decodes the DJI .LRF proxy when there is one (fast); --align maps proxy times back to the main file
(the offset can change inside a clip). Model: openai/clip-vit-base-patch16 (downloads once, ~600 MB).

usage: python scan.py CLIP_OR_FOLDER... --pos "a fish underwater" [--pos ...] [--neg ...] [--fps 1] [--thresh 0.5]
                      [--align] [--out scan.csv]
"""
import argparse
import csv
import subprocess

import numpy as np

from common import hwaccel, probe, proxy_of, proxy_offset, proxy_to_main
from inventory import files

NEG = ['an empty landscape', 'the sky', 'the ground', 'a blurry photo', 'a dark photo', 'the surface of water',
       'a wall', 'a road', 'trees and bushes', 'the inside of a car or boat']


def frames(path, src, fps, t1):
    w, h = 336, 336 * probe(path)['h'] // probe(path)['w'] // 2 * 2
    cmd = ['ffmpeg', '-v', 'error'] + (hwaccel() if src == path else []) + \
          ['-i', src, '-t', f'{t1:.2f}', '-vf', f'fps={fps},scale={w}:{h}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def windows(ts, ps, thresh, gap=1.0, min_len=1.0):
    """runs where p >= thresh (gaps < `gap` s bridged): [(t0, t1, peak, mean)] best first"""
    out, cur = [], None
    for t, p in zip(ts, ps):
        if p >= thresh:
            if cur and t - cur[1] <= gap:
                cur[1] = t
                cur[2].append(p)
            else:
                if cur:
                    out.append(cur)
                cur = [t, t, [p]]
    if cur:
        out.append(cur)
    res = [(a, b, max(v), float(np.mean(v))) for a, b, v in out if b - a >= min_len - 1e-6 or max(v) > 0.9]
    return sorted(res, key=lambda r: -(r[3] + 0.3 * r[2] + 0.03 * min(r[1] - r[0], 8)))   # sustained beats spiky


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--pos', action='append', required=True, help='subject prompt (repeat for several)')
    ap.add_argument('--neg', action='append', help='not-the-subject prompt (repeat); has sensible defaults')
    ap.add_argument('--fps', type=float, default=1.0)
    ap.add_argument('--thresh', type=float, default=0.5)
    ap.add_argument('--align', action='store_true', help='map proxy times to main-file times')
    ap.add_argument('--top', type=int, default=8, help='windows to print per clip')
    ap.add_argument('--out', default='scan.csv')
    a = ap.parse_args()
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor
    dev = 'mps' if torch.backends.mps.is_available() else ('cuda' if torch.cuda.is_available() else 'cpu')
    model = CLIPModel.from_pretrained('openai/clip-vit-base-patch16').to(dev).eval()
    proc = CLIPProcessor.from_pretrained('openai/clip-vit-base-patch16')
    neg = a.neg or NEG
    txt = proc(text=a.pos + neg, return_tensors='pt', padding=True).to(dev)
    rows = []
    for path in files(a.paths):
        p = probe(path)
        px = proxy_of(path)
        src = px or path
        segs = proxy_offset(path, px) if (px and a.align) else None
        fr = frames(path, src, a.fps, p['dur'] - 0.05 + (max(s[2] for s in segs) if segs else 0))
        probs = []
        for k in range(0, len(fr), 64):
            ims = [Image.fromarray(f) for f in fr[k:k + 64]]
            with torch.no_grad():
                x = proc(images=ims, return_tensors='pt').to(dev)
                out = model(input_ids=txt['input_ids'], attention_mask=txt['attention_mask'],
                            pixel_values=x['pixel_values'])
                probs += out.logits_per_image.softmax(-1)[:, :len(a.pos)].sum(-1).cpu().tolist()
        ts = [i / a.fps for i in range(len(probs))]
        if segs:
            ts = [proxy_to_main(segs, t) for t in ts]
        keep = [(t, q) for t, q in zip(ts, probs) if 0 <= t < p['dur'] - 0.05]   # never past the main file's end
        rows += [(path, round(t, 2), round(q, 4)) for t, q in keep]
        ws = windows([t for t, _ in keep], [q for _, q in keep], a.thresh)
        tag = ' (proxy times)' if px and not segs else ''
        print(f"{path}: {p['dur']:.0f}s, {len(keep)} frames, {len(ws)} windows >= {a.thresh}{tag}", flush=True)
        for t0, t1, pk, mn in ws[:a.top]:
            print(f'   {t0:7.1f}-{t1:7.1f}s  peak {pk:.2f}  mean {mn:.2f}')
    with open(a.out, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['clip', 't', 'p'])
        w.writerows(rows)
    print('wrote', a.out)


if __name__ == '__main__':
    main()
