"""Frame compositor: renders the EDL to a silent video, vertical 9:16 (V) or horizontal 16:9 (H), 4K by default.

Framing per shot and format (keys "v" and "h"; defaults: the whole frame when the source matches the canvas, else fit):
  fill     scale to cover the canvas (a landscape source in V is cropped hard - only for static, centred subjects)
  fit      the whole frame in the middle over a soft, darkened blur of itself (letterbox / pillarbox)
  rot      turned 90 deg: a top-down (nadir) drone shot fills the 9:16 screen with the whole frame, nothing cropped
  rot2fit  'rot' that turns upright into 'fit' between morph=[a, b] seconds (the drone tilting up to the horizon)
Zoom [z0, z1] is eased over the shot about "centre": [x, y] (source px) or "track" (tracks.json from track.py);
"lock": true stays on the target at every zoom (else the centre eases in from the frame centre as the zoom grows).
Stills (jpg/png/tif): "fit": "cover" | "contain" | scale, "centre", "zoom", "spin" (deg/s, constant, clockwise > 0),
"feather": fraction of the edge or "round" (a soft disc - use it with spin).
Grades: "grade": "water" (haze off, red partly back, saturation, S-curve; read in 16 bit) or a dict of levels / sat /
curve / exposure / wb. Transitions ("trans_in" on the incoming shot): ["dissolve", s], ["dip", s] (through black),
["whip", s, "left"|"right"] (a fast pan with motion blur). "fade_in" / "fade_out" (s) fade a shot from / to black.
Subtitles from "lines" (+ narration/<lang>/lines.json timing), "captions", "titles" are drawn in the same pass;
EDL "subs": {"size", "y" (V, fraction of height), "bottom" (H, px), "plate" (0..1 dark plate for bright scenes)}.

usage: python compose.py edl.json V|H [--preview] [--scale 0.5] [--lang zh] [--frames] [--only ROLE,ROLE]
                         [--no-subs] [--out FILE]
  --preview  half size, fast encode;  --frames  a sheet of composed frames per shot (framing check, no render)
"""
import argparse
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from common import (ease, ease5, hwaccel, is_still, line_events, line_lang, load_edl, load_font, load_still,
                    missing_glyphs, out_path, parse_fps, pre_post, probe, source_path, timeline,
                    total_frames, trans_frames, has_cjk)

BASE = {'V': (2160, 3840), 'H': (3840, 2160)}
ALIASES = {'box': 'fit', 'h': 'fill', 'crop': 'fill', 'rot2box': 'rot2fit'}
GRADES = {'water': dict(levels=[0.5, 99.5], white_keep=0.7, black_keep=0.95, sat=1.3, curve=0.032)}
TEXT_RGB = (250, 248, 242)                           # warm white


class Ctx:
    """render settings shared by everything below"""

    def __init__(self, edl, fmt, q):
        self.edl, self.fmt, self.q = edl, fmt, q
        w, h = edl.get('canvas', {}).get(fmt, BASE[fmt])
        self.CW, self.CH = int(round(w * q / 2)) * 2, int(round(h * q / 2)) * 2
        self.fps = parse_fps(edl['fps'])
        self.tracks = {}
        p = os.path.join(edl['_dir'], 'tracks.json')
        if os.path.exists(p):
            self.tracks = json.load(open(p))


# ---- sources --------------------------------------------------------------------------------------------------------
class Reader:
    """frames of one shot at the output rate, local frames -pre .. len+post-1, BGR (uint8; graded shots are decoded
    in 16 bit and graded before the 8-bit conversion, so the grade does not band)"""

    def __init__(self, cx, shot, pre, post):
        self.cx, self.shot, self.pre, self.n = cx, shot, pre, pre + shot['len_f'] + post
        self.path = source_path(cx.edl, shot['src'])
        self.still = is_still(self.path)
        self.deep = bool(shot.get('grade')) and not self.still
        self.i, self.last, self.proc, self.hold, self.warned = -pre, None, None, 0, False
        self.grade = None
        if self.still:
            self.img = load_still(self.path)
            self.h, self.w = self.img.shape[:2]
            self.k = 1.0
            return
        p = probe(self.path)
        # decode no bigger than the canvas needs (an 8K clip in a 4K letterbox decodes at ~2.3K: much faster)
        s = needed_scale(cx, shot, p['w'], p['h'])
        k = max(1.0, 1.0 / (s * 1.05))
        self.w = int(round(p['w'] / k / 2)) * 2
        self.h = int(round(p['h'] / k / 2)) * 2
        self.k = p['w'] / self.w                     # source px per decoded px (centre / track coordinates)

    def _cmd(self, t0, frames, single=False):
        sp = self.shot.get('speed', 1.0)
        vf = [f'setpts=(PTS-STARTPTS)/{sp}', f"fps={self.cx.edl['fps']}"] if not single else []
        vf.append(f'scale={self.w}:{self.h}:flags=lanczos')
        return ['ffmpeg', '-v', 'error'] + hwaccel() + ['-ss', f'{t0:.4f}', '-i', self.path, '-vf', ','.join(vf),
                                                        '-frames:v', str(frames), '-f', 'rawvideo',
                                                        '-pix_fmt', 'bgr48le' if self.deep else 'bgr24', '-']

    def _nbytes(self):
        return self.w * self.h * 3 * (2 if self.deep else 1)

    def _decode(self, buf):
        if self.deep:
            f = np.frombuffer(buf, np.uint16).reshape(self.h, self.w, 3).astype(np.float32) / 65535.0
            return apply_grade(f, self.grade_params())
        return np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)

    def _read(self):
        buf = self.proc.stdout.read(self._nbytes())
        return self._decode(buf) if len(buf) == self._nbytes() else None

    def start(self):
        if self.still or self.proc:
            return
        sp = self.shot.get('speed', 1.0)
        t0 = self.shot.get('t_in', 0.0) - self.pre / self.cx.fps * sp
        n = self.n
        if t0 < 0:                                   # the transition wants frames from before the clip starts:
            pad = int(np.ceil(-t0 * self.cx.fps / sp))   # its first frame stands in for them
            t0, n, self.hold = 0.0, self.n - pad, pad + 1
        self.proc = subprocess.Popen(self._cmd(t0, n), stdout=subprocess.PIPE, bufsize=10 ** 8)
        if self.hold:
            self.last = self._read()

    def next(self):
        """(local frame index, frame)"""
        k = self.i
        self.i += 1
        if self.still:
            return k, self.img
        self.start()
        if self.hold > 0:
            self.hold -= 1
        else:
            f = self._read()
            if f is not None:
                self.last = f
            elif not self.warned:
                self.warned = True
                print(f"WARNING {self.shot['role']}: source ran out at local frame {k}, holding the last frame",
                      flush=True)
        if self.last is None:
            raise RuntimeError(f"{self.shot['role']}: no frames from {self.path}")
        return k, self.last

    def frame_at(self, k):
        """one frame at local index k (accurate seek), for checks"""
        if self.still:
            return self.img
        sp = self.shot.get('speed', 1.0)
        t = max(self.shot.get('t_in', 0.0) + k / self.cx.fps * sp, 0.0)
        buf = subprocess.run(self._cmd(t, 1, single=True), capture_output=True).stdout
        if len(buf) < self._nbytes():
            raise RuntimeError(f"{self.shot['role']}: no frame at {t:.2f}s of {self.path}")
        return self._decode(buf[:self._nbytes()])

    def grade_params(self):
        if self.grade is None:
            self.grade = grade_params(self)
        return self.grade

    def close(self):
        if self.proc:
            self.proc.stdout.close()
            self.proc.wait()
            self.proc = None


def needed_scale(cx, shot, w, h):
    """the largest output scale (canvas px per source px) the shot reaches"""
    zmax = max(shot.get('zoom', (1.0, 1.0)))
    m = mode_of(cx, shot, w, h)
    fill, fit, rot = max(cx.CW / w, cx.CH / h), min(cx.CW / w, cx.CH / h), max(cx.CW / h, cx.CH / w)
    return {'fill': fill * zmax, 'fit': fit * zmax, 'rot': rot * zmax, 'rot2fit': max(rot, fit)}.get(m, fill * zmax)


# ---- grade ----------------------------------------------------------------------------------------------------------
def grade_params(r):
    g = r.shot['grade']
    g = dict(GRADES[g]) if isinstance(g, str) else dict(GRADES.get(g.get('preset'), {}), **g)
    if 'levels' in g:
        # per-channel percentiles of the shot itself, from 8 frames across it
        lo_p, hi_p = g['levels']
        sp = r.shot.get('speed', 1.0)
        samples = []
        for u in np.linspace(0.05, 0.95, 8):
            t = r.shot.get('t_in', 0.0) + u * r.shot['len_f'] / r.cx.fps * sp
            cmd = ['ffmpeg', '-v', 'error'] + hwaccel() + ['-ss', f'{t:.3f}', '-i', r.path, '-vf', 'scale=480:-2',
                                                           '-frames:v', '1', '-f', 'rawvideo',
                                                           '-pix_fmt', 'bgr48le', '-']
            buf = subprocess.run(cmd, capture_output=True).stdout
            samples.append(np.frombuffer(buf, np.uint16).reshape(-1, 3).astype(np.float32) / 65535.0)
        px = np.concatenate(samples)
        lo, hi = np.percentile(px, lo_p, axis=0), np.percentile(px, hi_p, axis=0)
        g['lo'] = lo * g.get('black_keep', 1.0)                      # blacks: nearly all the way
        g['hi'] = 1 - g.get('white_keep', 1.0) * (1 - hi)            # whites: partly (a full stretch looks fake)
        print(f"  grade {r.shot['role']}: levels lo {np.round(g['lo'], 3)} hi {np.round(g['hi'], 3)} (BGR)", flush=True)
    s = g.get('sat', 1.0)
    wl = np.array([0.114, 0.587, 0.299], np.float32)                  # luma weights, BGR order
    g['M'] = (np.eye(3, dtype=np.float32) * s + (1 - s) * np.tile(wl, (3, 1))).astype(np.float32)
    if g.get('wb'):
        r_, g_, b_ = g['wb']
        g['M'] = g['M'] * np.array([b_, g_, r_], np.float32)[:, None]
    c = g.get('curve', 0.0)
    if c:
        from scipy.interpolate import PchipInterpolator
        f = PchipInterpolator([0, 0.25, 0.5, 0.75, 1], [0, 0.25 - c, 0.5, 0.75 + c, 1])
        g['lut'] = np.clip(f(np.linspace(0, 1, 4096)), 0, 1).astype(np.float32)
    return g


def apply_grade(f, g):
    """float32 BGR 0..1 in, uint8 BGR out"""
    if 'lo' in g:
        f = (f - g['lo'].astype(np.float32)) / (g['hi'] - g['lo']).astype(np.float32)
    if g.get('exposure'):
        f = f * np.float32(2 ** g['exposure'])
    f = cv2.transform(f, g['M'])
    np.clip(f, 0, 1, out=f)
    if 'lut' in g:
        f = g['lut'][(f * 4095).astype(np.uint16)]
    return (f * 255 + 0.5).astype(np.uint8)


# ---- framing --------------------------------------------------------------------------------------------------------
def affine(scale, src_pt, dst_pt, angle=0.0):
    """2x3 matrix: rotate by `angle` deg (counter-clockwise on screen) and scale about src_pt, placed at dst_pt"""
    a = np.radians(angle)
    R = np.array([[np.cos(a), np.sin(a), 0], [-np.sin(a), np.cos(a), 0], [0, 0, 1.]])
    T1 = np.array([[1, 0, -src_pt[0]], [0, 1, -src_pt[1]], [0, 0, 1.]])
    S = np.diag([scale, scale, 1.])
    T2 = np.array([[1, 0, dst_pt[0]], [0, 1, dst_pt[1]], [0, 0, 1.]])
    return (T2 @ S @ R @ T1)[:2]


def mode_of(cx, shot, w, h):
    m = shot.get(cx.fmt.lower())
    if m:
        return ALIASES.get(m, m)
    return 'fill' if (w >= h) == (cx.CW >= cx.CH) else 'fit'


def zoom_centre(cx, shot, k, w, h, kscale):
    """zoom factor and centre (decoded px) at local frame k"""
    z0, z1 = shot.get('zoom', (1.0, 1.0))
    u = ease(k / max(shot['len_f'] - 1, 1))
    z = z0 + (z1 - z0) * u
    c = shot.get('centre')
    fc = np.array([w / 2, h / 2])
    if c is None:
        return z, fc
    if c == 'track':
        t = cx.tracks[shot['role']]
        j = int(np.clip(k + t.get('pre_f', 0), 0, len(t['x']) - 1))
        tgt = np.array([t['x'][j], t['y'][j]]) / kscale
    else:
        tgt = np.array(c, float) / kscale
    if shot.get('lock') or max(z0, z1) <= 1.0:
        b = 1.0
    else:
        b = (z - 1.0) / (max(z0, z1) - 1.0)          # 1 = on target, 0 = frame centre (eases in with the zoom)
    return z, fc + b * (tgt - fc)


def clamp(c, half_w, half_h, w, h):
    return np.array([np.clip(c[0], half_w, max(half_w, w - half_w)), np.clip(c[1], half_h, max(half_h, h - half_h))])


def blur_fill(cx, frame):
    """the background behind a fitted frame: the part of it with the canvas's shape, tiny, blurred, darkened"""
    h, w = frame.shape[:2]
    if w / h > cx.CW / cx.CH:
        cw = int(h * cx.CW / cx.CH)
        band = frame[:, (w - cw) // 2:(w + cw) // 2]
    else:
        ch = int(w * cx.CH / cx.CW)
        band = frame[(h - ch) // 2:(h + ch) // 2]
    small = cv2.resize(band, (max(cx.CW // 60, 8), max(cx.CH // 60, 8)), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 3)
    return (cv2.resize(small, (cx.CW, cx.CH), interpolation=cv2.INTER_LINEAR) * 0.55).astype(np.uint8)


_feathered = {}


def still_canvas(cx, shot, k, img):
    """a photo: centre point dead centre, eased zoom, optional constant spin, feathered edges on black"""
    h, w = img.shape[:2]
    fit = shot.get('fit', 'cover')
    feather = shot.get('feather', 0.0 if fit == 'cover' else 0.07)
    key = (id(img), str(feather))
    if key not in _feathered:
        if feather == 'round':                       # a soft disc: a spinning photo shows no turning corners
            yy, xx = np.mgrid[0:h, 0:w]
            r = np.hypot(xx - w / 2, yy - h / 2) / (min(w, h) / 2)
            a = np.clip((1.0 - r) / 0.12, 0, 1) ** 1.5
            _feathered[key] = (img * a[..., None]).astype(np.uint8)
        elif feather > 0:
            ax = np.clip(np.minimum(np.arange(w), w - 1 - np.arange(w)) / (feather * w), 0, 1)
            ay = np.clip(np.minimum(np.arange(h), h - 1 - np.arange(h)) / (feather * h), 0, 1)
            _feathered[key] = (img * (np.outer(ay, ax) ** 1.5)[..., None]).astype(np.uint8)
        else:
            _feathered[key] = img
    z0, z1 = shot.get('zoom', (1.0, 1.0))
    z = z0 + (z1 - z0) * ease(k / max(shot['len_f'] - 1, 1))
    if fit == 'cover':
        s0 = max(cx.CW / w, cx.CH / h)
    elif fit == 'contain':
        s0 = min(cx.CW / w, cx.CH / h)
    else:
        s0 = float(fit) * cx.q
    c = shot.get('centre') or (w / 2, h / 2)
    angle = -shot.get('spin', 0.0) * k / cx.fps + shot.get('angle', 0.0)    # spin > 0: clockwise, constant speed
    M = affine(s0 * z, c, (cx.CW / 2, cx.CH / 2), angle)
    return cv2.warpAffine(_feathered[key], M, (cx.CW, cx.CH), flags=cv2.INTER_LINEAR, borderValue=0)


def canvas(cx, r, k, frame):
    """the output picture of shot r.shot at local frame k"""
    shot = r.shot
    if r.still:
        return still_canvas(cx, shot, k, frame)
    h, w = frame.shape[:2]
    z, c = zoom_centre(cx, shot, k, w, h, r.k)
    mode = mode_of(cx, shot, w, h)
    CW, CH = cx.CW, cx.CH
    if mode == 'fill':
        s = max(CW / w, CH / h) * z
        c = clamp(c, CW / 2 / s, CH / 2 / s, w, h)
        return cv2.warpAffine(frame, affine(s, c, (CW / 2, CH / 2)), (CW, CH), flags=cv2.INTER_LINEAR)
    sign = -1.0 if shot.get('rot_dir', 'ccw') == 'cw' else 1.0
    if mode == 'rot':
        s = max(CW / h, CH / w) * z                   # turned frame: width h, height w
        c = clamp(c, CH / 2 / s, CW / 2 / s, w, h)
        return cv2.warpAffine(frame, affine(s, c, (CW / 2, CH / 2), 90.0 * sign), (CW, CH), flags=cv2.INTER_LINEAR)
    if mode == 'fit':
        s0 = min(CW / w, CH / h)
        bw, bh = min(CW, int(round(w * s0 / 2)) * 2), min(CH, int(round(h * s0 / 2)) * 2)
        out = blur_fill(cx, frame)
        s = s0 * z
        c = clamp(c, bw / 2 / s, bh / 2 / s, w, h)
        x0, y0 = (CW - bw) // 2, (CH - bh) // 2
        out[y0:y0 + bh, x0:x0 + bw] = cv2.warpAffine(frame, affine(s, c, (bw / 2, bh / 2)), (bw, bh),
                                                     flags=cv2.INTER_LINEAR)
        return out
    if mode == 'rot2fit':
        a, b = shot['morph']
        u = ease5((k / cx.fps - a) / (b - a))
        s = max(CW / h, CH / w) ** (1 - u) * min(CW / w, CH / h) ** u
        out = blur_fill(cx, frame)                   # corners uncovered mid-turn show the soft fill, not black
        M = affine(s, (w / 2, h / 2), (CW / 2, CH / 2), 90.0 * sign * (1 - u))
        cv2.warpAffine(frame, M, (CW, CH), dst=out, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)
        return out
    raise ValueError(f"{shot['role']}: unknown framing {mode!r}")


def fade_gain(cx, shot, k):
    g = 1.0
    if shot.get('fade_in'):
        g *= ease(k / (shot['fade_in'] * cx.fps))
    if shot.get('fade_out'):
        g *= ease((shot['len_f'] - 1 - k) / (shot['fade_out'] * cx.fps))
    return g


# ---- text -----------------------------------------------------------------------------------------------------------
class Overlay:
    def __init__(self, rgba, x, y, a, b, fin=0.15, fout=0.2):
        im = np.asarray(rgba).astype(np.float32)
        self.rgb, self.alpha = im[..., 2::-1].copy(), im[..., 3:] / 255.0
        self.x, self.y, self.a, self.b, self.fin, self.fout = int(x), int(y), a, b, fin, fout

    def draw(self, img, t):
        if not (self.a <= t <= self.b):
            return
        f = min(1.0, (t - self.a) / self.fin, (self.b - t) / self.fout)
        h, w = self.rgb.shape[:2]
        H, W = img.shape[:2]
        x0, y0, x1, y1 = max(self.x, 0), max(self.y, 0), min(self.x + w, W), min(self.y + h, H)
        if x1 <= x0 or y1 <= y0:
            return
        sl = (slice(y0 - self.y, y1 - self.y), slice(x0 - self.x, x1 - self.x))
        roi = img[y0:y1, x0:x1].astype(np.float32)
        al = self.alpha[sl] * f
        img[y0:y1, x0:x1] = (roi * (1 - al) + self.rgb[sl] * al).astype(np.uint8)


def wrap(text, font, maxw):
    """one line, or two balanced lines: CJK breaks at the full-width spaces that stand in for commas, Latin at word
    boundaries (preferring a comma)"""
    if font.getlength(text) <= maxw:
        return [text]
    sep = '　' if '　' in text else ' '
    parts = text.split(sep)
    if len(parts) < 2 and has_cjk(text):
        n = len(text) // 2
        return [text[:n], text[n:]]
    best = None
    for k in range(1, len(parts)):
        a, b = sep.join(parts[:k]), sep.join(parts[k:])
        score = max(font.getlength(a), font.getlength(b)) - (0.08 * maxw if a.endswith(',') else 0)
        if best is None or score < best[0]:
            best = (score, [a, b])
    return best[1]


def text_image(lines, font, q, stroke=4, shadow=8, tracking=0.0, shadow_alpha=195, plate=0.0):
    lh = int(font.size * (1.45 if any(has_cjk(l) for l in lines) else 1.3))
    widths = [font.getlength(l) + tracking * font.size * (len(l) - 1) for l in lines]
    pad = int(50 * q) + 10
    tw, th = int(max(widths)) + 2 * pad, lh * len(lines) + 2 * pad
    txt = Image.new('RGBA', (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    for j, (l, lw) in enumerate(zip(lines, widths)):
        x, y = (tw - lw) / 2, pad + lh * j + lh / 2
        if tracking:
            for ch in l:
                d.text((x, y), ch, font=font, fill=TEXT_RGB + (255,), anchor='lm')
                x += font.getlength(ch) + tracking * font.size
        else:
            d.text((tw / 2, y), l, font=font, fill=TEXT_RGB + (255,), anchor='mm',
                   stroke_width=max(1, int(stroke * q)), stroke_fill=(0, 0, 0, 115))
    sh = Image.new('RGBA', (tw, th), (0, 0, 0, 0))
    sh.paste((0, 0, 0, shadow_alpha), (0, int(4 * q)), txt.split()[3])
    sh = sh.filter(ImageFilter.GaussianBlur(max(1, shadow * q)))
    if plate:                                        # a soft dark plate: legible over foam, snow, bright sky
        pl = Image.new('RGBA', (tw, th), (0, 0, 0, 0))
        box = [pad * 0.6, pad * 0.6, tw - pad * 0.6, th - pad * 0.6]
        ImageDraw.Draw(pl).rounded_rectangle(box, radius=int(pad * 0.8), fill=(0, 0, 0, int(255 * plate)))
        sh = Image.alpha_composite(pl.filter(ImageFilter.GaussianBlur(pad * 0.35)), sh)
    return Image.alpha_composite(sh, txt)


def display_text(text):
    """subtitle form of a narration line: no full stops at the end; CJK commas become spaces"""
    text = text.strip()
    if has_cjk(text):
        return text.rstrip('。！？!?.').replace('，', '　').replace('、', '　')
    return text


def overlays(cx, tl, lang, subs=True):
    out, edl, q = [], cx.edl, cx.q
    starts = {s['role']: s['start'] for s in tl}
    cfg = edl.get('subs', {})
    V = cx.fmt == 'V'
    maxw = cx.CW - int((240 if V else 600) * q)

    def sub_overlay(text, a, b):
        cjk = has_cjk(text)
        size = int(cfg.get('size', 112 if V else 120) * q * (1.0 if cjk else 0.95))
        font = load_font('cjk' if cjk else 'latin', size)
        miss = missing_glyphs(font, text)
        if miss:
            print(f'WARNING: font has no glyph for {"".join(miss)!r} in {text!r} (would show as boxes)')
        im = text_image(wrap(display_text(text), font, maxw), font, q, plate=cfg.get('plate', 0.0))
        if V:
            cy = int(cfg.get('y', 0.72) * cx.CH)
            y = cy - im.height // 2
        else:
            y = cx.CH - int(cfg.get('bottom', 140) * q) - im.height + int(50 * q) + 10
        return Overlay(im, (cx.CW - im.width) // 2, y, a, b)

    if subs and edl.get('lines') and not cfg.get('off'):
        for _, a, b, text, _ in line_events(edl, tl, lang):
            out.append(sub_overlay(text, a - 0.05, b + 0.35))
    for c in edl.get('captions', []):
        a = starts[c['shot']] + c.get('at', 0.0)
        text = c['text'] if isinstance(c['text'], str) else c['text'].get(lang, next(iter(c['text'].values())))
        out.append(sub_overlay(text, a, a + c.get('dur', 3.0)))
    for ti in edl.get('titles', []):
        a = starts[ti['shot']] + ti.get('at', 0.7)
        b = a + ti.get('dur', 3.0)
        title, sub = ti.get('title', ''), ti.get('sub', '')
        if ti.get('case', 'upper') == 'upper' and not has_cjk(title):
            title = title.upper()                    # Jura in capitals with wide tracking: the quiet, premium look
        size = int(ti.get('size', 190 if not V else 150) * q)
        kind, track = ('cjk', 0.12) if has_cjk(title) else ('title', 0.32)   # Jura has no Chinese glyphs
        font = load_font(kind, size)
        while font.getlength(title) * (1 + track) > 0.84 * cx.CW and size > 20:
            size = int(size * 0.94)
            font = load_font(kind, size)
        im_t = text_image([title], font, q, tracking=track, shadow=10, shadow_alpha=120)
        sfont = load_font('cjk' if has_cjk(sub) else 'mono', int(size * 0.34))
        im_s = text_image([sub], sfont, q, tracking=0.30, shadow=10, shadow_alpha=120) if sub else None
        y = int(ti.get('y', 0.33 if not V else 0.30) * cx.CH)
        fade = ti.get('fade', 0.9)
        out.append(Overlay(im_t, (cx.CW - im_t.width) // 2, y - im_t.height // 2, a, b, fade, fade))
        if im_s:
            out.append(Overlay(im_s, (cx.CW - im_s.width) // 2, y + int(size * 0.62), a + 0.2, b, fade, fade))
        for f_, s_ in ((font, title), (sfont, sub)):
            miss = missing_glyphs(f_, s_) if s_ else []
            if miss:
                print(f'WARNING: no glyph for {"".join(miss)!r} in {s_!r} (tofu): Jura / DM Mono are Latin-only')
    return out


# ---- transitions ----------------------------------------------------------------------------------------------------
def hblur(cx, img, length):
    """horizontal motion blur of `length` px (done small: the picture is a smear anyway)"""
    if length < 2:
        return img
    f = 4
    small = cv2.resize(img, (cx.CW // f, cx.CH // f), interpolation=cv2.INTER_AREA)
    small = cv2.blur(small, (max(1, int(length / f)), 1))
    return cv2.resize(small, (cx.CW, cx.CH), interpolation=cv2.INTER_LINEAR)


def whip(cx, A, B, p, direction='left'):
    """one continuous fast pan: A leaves, B follows (direction = where the picture moves); p in [0, 1)"""
    if direction == 'right':
        return whip(cx, A[:, ::-1], B[:, ::-1], p)[:, ::-1].copy()
    e, v = ease(p), 6 * p * (1 - p)                  # position and speed of the pan
    A, B = hblur(cx, A, v * 0.35 * cx.CW), hblur(cx, B, v * 0.35 * cx.CW)
    out = np.zeros_like(A)
    CW = cx.CW
    xa = int(round(-e * CW))
    xb = xa + CW
    if xa > -CW:
        out[:, max(xa, 0):CW + min(xa, 0)] = A[:, max(-xa, 0):CW - max(xa, 0)]
    if xb < CW:
        out[:, max(xb, 0):] = B[:, :CW - max(xb, 0)]
    return out


def blend(cx, typ, A, B, p, extra):
    if typ == 'whip':
        return whip(cx, A, B, p, extra or 'left')
    if typ == 'dip':
        return (A * (1 - ease(2 * p))).astype(np.uint8) if p < 0.5 else (B * ease(2 * p - 1)).astype(np.uint8)
    return cv2.addWeighted(A, 1 - ease(p), B, ease(p), 0)


# ---- main -----------------------------------------------------------------------------------------------------------
def check_overlaps(edl, tl, tr):
    for i, s in enumerate(tl):
        a = tr[i][1] if i in tr else 0
        b = tr[i + 1][1] if i + 1 in tr else 0
        if a + b > s['len_f']:
            raise SystemExit(f"{s['role']}: its transitions ({a} + {b} frames) are longer than the shot "
                             f"({s['len_f']} frames): shorten them or lengthen the shot")


def frame_sheet(cx, tl, readers, ovs, path, only):
    tiles = []
    for i, s in enumerate(tl):
        if only and s['role'] not in only:
            continue
        r = readers[i]
        ks = [0, s['len_f'] // 2, s['len_f'] - 1]
        if s.get('morph') and mode_of(cx, s, r.w, r.h) == 'rot2fit':
            a, b = s['morph']
            ks = sorted(set(ks + [int(a * cx.fps), int((a + b) / 2 * cx.fps), int(b * cx.fps)]))
        for k in ks:
            img = canvas(cx, r, k, r.frame_at(k))
            img = (img * fade_gain(cx, s, k)).astype(np.uint8)
            for o in ovs:
                o.draw(img, s['start'] + k / cx.fps)
            th = 480 if cx.fmt == 'V' else 270
            im = cv2.resize(img, (int(img.shape[1] * th / img.shape[0]), th), interpolation=cv2.INTER_AREA)
            cv2.putText(im, f"{s['role']} {k}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
            tiles.append(cv2.copyMakeBorder(im, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(255, 255, 255)))
    cols = 9 if cx.fmt == 'V' else 6
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(path, np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    print('wrote', path, len(tiles), 'frames')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edl')
    ap.add_argument('fmt', choices=['V', 'H'])
    ap.add_argument('--preview', action='store_true', help='half size, fast encode')
    ap.add_argument('--scale', type=float, help='canvas scale (default 1, preview 0.5)')
    ap.add_argument('--lang', help='subtitle language when lines have several')
    ap.add_argument('--frames', action='store_true', help='framing check sheet instead of a render')
    ap.add_argument('--only', help='--frames: these roles only (comma separated)')
    ap.add_argument('--no-subs', action='store_true', help='no narration subtitles (captions/titles stay)')
    ap.add_argument('--out')
    a = ap.parse_args()
    edl = load_edl(a.edl)
    q = a.scale or (0.5 if a.preview else 1.0)
    cx = Ctx(edl, a.fmt, q)
    tl = timeline(edl)
    tr = trans_frames(edl, tl)
    check_overlaps(edl, tl, tr)
    pp = pre_post(edl, tl)
    readers = [Reader(cx, s, pre, post) for s, (pre, post) in zip(tl, pp)]
    lang = line_lang(edl, a.lang)
    ovs = overlays(cx, tl, lang, subs=not a.no_subs)
    name = edl.get('name', 'video')
    tag = f"{a.fmt}{'_' + lang if edl.get('lines') and not a.no_subs else ''}{'_preview' if q < 1 else ''}"
    if a.frames:
        only = set(a.only.split(',')) if a.only else None
        suffix = ('_' + '-'.join(sorted(only))) if only else ''
        frame_sheet(cx, tl, readers, ovs, out_path(edl, 'out', f'framecheck_{tag}{suffix}.jpg'), only)
        return
    out = a.out or out_path(edl, 'out', f'{name}_{tag}_video.mp4')
    total = total_frames(tl)
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                            '-s', f'{cx.CW}x{cx.CH}', '-r', str(edl['fps']), '-i', '-', '-c:v', 'libx264',
                            '-preset', 'medium' if q >= 1 else 'veryfast', '-crf', '18', '-profile:v', 'high',
                            '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709',
                            '-colorspace', 'bt709', '-movflags', '+faststart', out], stdin=subprocess.PIPE)
    t_start = time.time()
    span = [(s['start_f'] - pre, s['start_f'] + s['len_f'] + post) for s, (pre, post) in zip(tl, pp)]
    for n in range(total):
        active = [i for i, (lo, hi) in enumerate(span) if lo <= n < hi]
        pics = []
        for i in active:
            k, f = readers[i].next()
            pic = canvas(cx, readers[i], k, f)
            if tl[i].get('fade_in') or tl[i].get('fade_out'):
                pic = (pic * fade_gain(cx, tl[i], k)).astype(np.uint8)
            pics.append((i, pic))
        if len(pics) == 1:
            img = pics[0][1]
        else:
            (_, A), (i1, B) = pics[0], pics[1]
            typ, half, extra = tr[i1]
            p = (n - (tl[i1]['start_f'] - half)) / (2 * half)
            img = blend(cx, typ, A, B, p, extra)
        for i, (_, hi) in enumerate(span):
            if readers[i].proc and n >= hi - 1:
                readers[i].close()
        img = np.ascontiguousarray(img)
        for o in ovs:
            o.draw(img, n / cx.fps)
        enc.stdin.write(img.tobytes())
        if n % 150 == 0:
            el = time.time() - t_start
            eta = el / max(n, 1) * (total - n)
            print(f'{tag}: frame {n}/{total}  ({el:.0f}s, ~{eta:.0f}s left)', flush=True)
    enc.stdin.close()
    enc.wait()
    for r in readers:
        r.close()
    print('wrote', out, total, 'frames', f'{cx.CW}x{cx.CH}')


if __name__ == '__main__':
    sys.exit(main())
