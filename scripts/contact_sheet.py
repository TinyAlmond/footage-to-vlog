"""Timestamped thumbnail sheets, to see what is in the footage before deciding anything.

Overview: every clip of a folder at one thumbnail per --step seconds (from the DJI .LRF proxy when there is one: much
faster to decode; its times are close to, not exactly, the main file's - see align_proxy.py).
Window: one clip between --t0 and --t1 at a finer --step, to pick exact in/out points.

usage: python contact_sheet.py CLIP_OR_FOLDER... [--step 2] [--cols 8] [--rows 9] [--t0 S --t1 S] [--main]
                               [--out sheets/]
  --main  decode the main file even if a proxy exists (exact times; slower for 4K/8K)
writes <out>/<clip>_<n>.jpg (several pages for long clips) and prints the list.
"""
import argparse
import os
import subprocess

import cv2
import numpy as np

from common import hwaccel, probe, proxy_of
from inventory import files

TW = 240                                              # thumbnail width (px)


def label(im, text):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    cv2.rectangle(im, (0, 0), (tw + 6, th + 8), (0, 0, 0), -1)
    cv2.putText(im, text, (3, th + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)


def sheet(path, step, cols, rows, t0, t1, outdir, use_main):
    main = probe(path)
    src = path if use_main else (proxy_of(path) or path)
    t1 = min(t1 if t1 is not None else main['dur'], main['dur'] - 0.05)  # never past the main file's end
    if t1 <= t0:
        return []
    th = int(round(TW * main['h'] / main['w'] / 2)) * 2
    cmd = ['ffmpeg', '-v', 'error'] + (hwaccel() if src == path else []) + \
          ['-ss', f'{t0:.3f}', '-i', src, '-t', f'{t1 - t0:.3f}',
           '-vf', f'fps=1/{step},scale={TW}:{th}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, th, TW, 3).copy()
    if not len(fr):
        return []
    tiles = []
    for i, im in enumerate(fr):
        t = t0 + (i + 0.5) * step                    # the fps filter picks the frame in the middle of each step
        label(im, f'{int(t // 60)}:{t % 60:05.2f}' if step < 0.5 else f'{int(t // 60)}:{t % 60:04.1f}')
        tiles.append(im)
    name = os.path.splitext(os.path.basename(path))[0]
    head = np.zeros((26, TW * cols, 3), np.uint8)
    cv2.putText(head, f'{name}  {main["dur"]:.1f}s  {main["w"]}x{main["h"]} {main["fps"]:.0f}fps'
                      f'{"  (proxy)" if src != path else ""}', (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 255, 255), 1, cv2.LINE_AA)
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    grid = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    out = []
    for k in range(0, len(grid), rows):
        p = os.path.join(outdir, f'{name}_{int(t0)}_{k // rows + 1}.jpg')
        cv2.imwrite(p, np.vstack([head] + grid[k:k + rows]), [cv2.IMWRITE_JPEG_QUALITY, 85])
        out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--step', type=float, default=2.0, help='seconds between thumbnails')
    ap.add_argument('--cols', type=int, default=8)
    ap.add_argument('--rows', type=int, default=9, help='rows per page')
    ap.add_argument('--t0', type=float, default=0.0)
    ap.add_argument('--t1', type=float, default=None)
    ap.add_argument('--main', action='store_true', help='decode the main file even if a proxy exists')
    ap.add_argument('--out', default='sheets')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for f in files(a.paths):
        for p in sheet(f, a.step, a.cols, a.rows, a.t0, a.t1, a.out, a.main):
            print(p)


if __name__ == '__main__':
    main()
