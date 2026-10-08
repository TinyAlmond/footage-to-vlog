"""Cover / thumbnail from a frame of the film: one strong picture, a restrained title, data in a monospace line.

Default type is quiet and editorial rather than YouTube-loud: title in Jura Light, capitals, wide tracking; a short
thin rule; the facts (place, date, gear, numbers) in DM Mono; warm white with a soft shadow, over a gentle dark
gradient instead of a box. Offer 2-3 variants (frames / text positions) and let the user pick; titles are theirs to
write. Also writes <out>_feed.png: the cover at feed size next to the full one, to check it still reads small.

usage: python cover.py (--video FILE --t SEC | --image FILE) --title "THE RED COAST" [--sub "12 · V · 2025"]
                       [--data "LINE" ...] [--size xhs|youtube|square|WxH] [--focus X,Y] [--zoom 1.0]
                       [--pos top|centre|bottom] [--out cover.jpg]
sizes: xhs 1242x1660 (3:4, Xiaohongshu feed), youtube 1280x720 (< 2 MB), square 1080x1080, or WxH
"""
import argparse
import io
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from common import has_cjk, load_font, load_still, missing_glyphs

SIZES = {'xhs': (1242, 1660), 'youtube': (1280, 720), 'square': (1080, 1080), 'xhs43': (1440, 1080)}
WHITE = (250, 248, 242)


def frame(a):
    if a.image:
        return Image.fromarray(load_still(a.image)[..., ::-1])
    png = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{a.t:.3f}', '-i', a.video, '-frames:v', '1',
                          '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(png)).convert('RGB')


def crop_to(im, W, H, focus, zoom):
    """cover-crop to W:H around the focus point (source px)"""
    w, h = im.size
    s = max(W / w, H / h) * zoom
    fx, fy = focus if focus else (w / 2, h / 2)
    cw, ch = W / s, H / s
    x0 = min(max(fx - cw / 2, 0), w - cw)
    y0 = min(max(fy - ch / 2, 0), h - ch)
    return im.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch))


def tracked(draw, xy, text, font, track, fill, anchor_x='c'):
    widths = [font.getlength(c) for c in text]
    total = sum(widths) + track * font.size * (len(text) - 1)
    x = xy[0] - (total / 2 if anchor_x == 'c' else 0)
    for c, cw in zip(text, widths):
        draw.text((x, xy[1]), c, font=font, fill=fill, anchor='lm')
        x += cw + track * font.size
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--video')
    src.add_argument('--image')
    ap.add_argument('--t', type=float, default=0.0)
    ap.add_argument('--title', required=True)
    ap.add_argument('--sub', default='')
    ap.add_argument('--data', action='append', default=[], help='extra monospace lines (repeat)')
    ap.add_argument('--size', default='xhs')
    ap.add_argument('--focus')
    ap.add_argument('--zoom', type=float, default=1.0)
    ap.add_argument('--pos', default='bottom', choices=['top', 'centre', 'bottom'])
    ap.add_argument('--out', default='cover.jpg')
    a = ap.parse_args()
    W, H = SIZES[a.size] if a.size in SIZES else tuple(int(v) for v in a.size.lower().split('x'))
    im = crop_to(frame(a), W, H, tuple(float(v) for v in a.focus.split(',')) if a.focus else None, a.zoom)
    # gentle gradient where the text sits (legibility without a box)
    g = np.linspace(0, 1, H)
    if a.pos == 'bottom':
        g = np.clip((g - 0.45) / 0.55, 0, 1) ** 1.6
    elif a.pos == 'top':
        g = np.clip((0.55 - g) / 0.55, 0, 1) ** 1.6
    else:
        g = np.exp(-((g - 0.5) / 0.22) ** 2)
    arr = np.asarray(im).astype(np.float32) * (1 - 0.55 * g)[:, None, None]
    im = Image.fromarray(arr.clip(0, 255).astype(np.uint8)).convert('RGBA')
    title = a.title if has_cjk(a.title) else a.title.upper()
    tfont = load_font('cjk' if has_cjk(title) else 'title', int(W * 0.085))
    while tfont.getlength(title) * (1.0 if has_cjk(title) else 1.3) > W * 0.86 and tfont.size > 12:
        tfont = load_font('cjk' if has_cjk(title) else 'title', int(tfont.size * 0.94))
    mfont = load_font('cjk' if has_cjk(a.sub + ''.join(a.data)) else 'mono', max(12, int(tfont.size * 0.30)))
    for f, s in ((tfont, title), (mfont, a.sub), *((mfont, d) for d in a.data)):
        miss = missing_glyphs(f, s)
        if miss:
            print(f'WARNING: no glyph for {"".join(miss)!r} in {s!r} (tofu); use plain ASCII (\' " -) or another font')
    lines = [a.sub] + a.data if a.sub else a.data
    block = tfont.size * 1.2 + (tfont.size * 0.45 if lines else 0) + len(lines) * mfont.size * 1.6
    y0 = {'top': H * 0.11, 'centre': (H - block) / 2, 'bottom': H * 0.89 - block}[a.pos] + tfont.size * 0.6
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    for d_, fill, off in ((ImageDraw.Draw(shadow), (0, 0, 0, 130), 3), (ImageDraw.Draw(layer), WHITE + (255,), 0)):
        y = y0
        tracked(d_, (W / 2 + off, y + off), title, tfont, 0.0 if has_cjk(title) else 0.30, fill)
        y += tfont.size * 0.95
        if lines:
            rw = W * 0.06
            d_.line([(W / 2 - rw / 2 + off, y + off), (W / 2 + rw / 2 + off, y + off)], fill=fill,
                    width=max(1, W // 900))
            y += tfont.size * 0.45
        for k, s in enumerate(lines):
            tracked(d_, (W / 2 + off, y + off), s, mfont, 0.0 if has_cjk(s) else 0.28,
                    fill if k == 0 else fill[:3] + (int(fill[3] * 0.82),))
            y += mfont.size * 1.6
    im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(max(2, W // 250))))
    im = Image.alpha_composite(im, layer).convert('RGB')
    q = 93
    im.save(a.out, quality=q)
    while a.size == 'youtube' and os.path.getsize(a.out) > 2 * 1024 * 1024 and q > 60:
        q -= 6
        im.save(a.out, quality=q)
    feed = im.resize((180, int(180 * H / W)) if H >= W else (320, int(320 * H / W)), Image.LANCZOS)
    sheet = Image.new('RGB', (im.width // 3 + feed.width + 30, max(im.height // 3, feed.height) + 20), (24, 24, 24))
    sheet.paste(im.resize((im.width // 3, im.height // 3), Image.LANCZOS), (10, 10))
    sheet.paste(feed, (im.width // 3 + 20, 10))
    sp = os.path.splitext(a.out)[0] + '_feed.png'
    sheet.save(sp)
    print(f'wrote {a.out} ({W}x{H}, {os.path.getsize(a.out) / 1024:.0f} KB) and {sp}')


if __name__ == '__main__':
    main()
