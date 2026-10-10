"""Shared helpers for the footage-to-vlog scripts: the edit list (EDL) and its frame-exact timeline, ffprobe, fonts,
easing, proxy alignment.

Run it on an EDL to print the timeline and check every shot against its source before rendering anything:
    python common.py edl.json [--lang zh]
"""
import glob
import json
import os
import re
import subprocess
import sys
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
FONT_DIR = os.path.join(SKILL, 'assets', 'fonts')
STILL_EXT = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.bmp', '.heic'}
DARWIN = sys.platform == 'darwin'
SR = 48000


# ---- small things ---------------------------------------------------------------------------------------------------
def ease(x):
    """smoothstep 0..1"""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease5(x):
    """smootherstep 0..1 (zero velocity and acceleration at both ends)"""
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (x * (6 * x - 15) + 10)


def parse_fps(v):
    return float(Fraction(str(v))) if not isinstance(v, (int, float)) else float(v)


def hwaccel():
    """hardware decoding where it is reliable (macOS VideoToolbox); plain software decoding elsewhere"""
    return ['-hwaccel', 'videotoolbox'] if DARWIN else []


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def is_still(path):
    return os.path.splitext(path)[1].lower() in STILL_EXT


# ---- ffprobe --------------------------------------------------------------------------------------------------------
_probe_cache = {}


def utc_iso(v):
    """'2025-05-12T15:40:19+0800' / '...Z' -> '2025-05-12T07:40:19Z' (sortable across cameras)"""
    if not v:
        return None
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(v.replace('Z', '+00:00'))
    except ValueError:
        return v
    if t.tzinfo:
        t = t.astimezone(timezone.utc)
    return t.strftime('%Y-%m-%dT%H:%M:%S') + ('Z' if t.tzinfo else '')


def _fps(v):
    """frame rate: frames / duration when known (some phone files carry a wrong avg_frame_rate), else the average,
    else the nominal rate"""
    r = parse_fps(v.get('r_frame_rate', '0/1')) if v.get('r_frame_rate', '0/0') != '0/0' else 0.0
    try:
        n, d = int(v.get('nb_frames', 0)), float(v.get('duration', 0))
        if n > 1 and d > 0:
            return n / d
    except ValueError:
        pass
    avg = parse_fps(v['avg_frame_rate']) if v.get('avg_frame_rate', '0/0') != '0/0' else 0.0
    return avg if (avg and (not r or 0.5 * r <= avg <= 1.05 * r)) else (r or 30.0)


def probe(path):
    """the facts that matter for editing, from one ffprobe call (JSON, so no csv parsing surprises):
    w, h (display size, rotation applied), fps, dur, codec, pix_fmt, bits, transfer, hdr ('HLG'/'PQ'/None), audio,
    rotation, created, location"""
    if path in _probe_cache:
        return _probe_cache[path]
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path],
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f'ffprobe failed on {path}: {out.stderr.strip()}')
    j = json.loads(out.stdout)
    fmt = j.get('format', {})
    vs = [s for s in j.get('streams', []) if s.get('codec_type') == 'video' and
          not s.get('disposition', {}).get('attached_pic')]
    aus = [s for s in j.get('streams', []) if s.get('codec_type') == 'audio']
    d = dict(path=path, dur=float(fmt.get('duration', 0) or 0), audio=bool(aus),
             audio_ch=int(aus[0].get('channels', 0)) if aus else 0, created=None, location=None)
    tags = {k.lower(): v for k, v in fmt.get('tags', {}).items()}
    d['created'] = utc_iso(tags.get('creation_time') or tags.get('com.apple.quicktime.creationdate'))
    d['created_local'] = tags.get('com.apple.quicktime.creationdate')     # phones: local time with its offset
    d['location'] = tags.get('com.apple.quicktime.location.iso6709') or tags.get('location')
    if vs:
        v = vs[0]
        w, h = int(v.get('width', 0)), int(v.get('height', 0))
        rot = 0
        for sd in v.get('side_data_list', []):
            if 'rotation' in sd:
                rot = int(round(float(sd['rotation'])))
        if 'rotate' in v.get('tags', {}):
            rot = int(v['tags']['rotate'])
        if abs(rot) % 180 == 90:                      # ffmpeg auto-rotates on decode: frames come out turned
            w, h = h, w
        fps = _fps(v)
        trc = v.get('color_transfer', '') or ''
        pix = v.get('pix_fmt', '') or ''
        bits = 10 if ('10' in pix or 'p010' in pix) else (12 if '12' in pix else 8)
        d.update(w=w, h=h, fps=fps, codec=v.get('codec_name'), pix_fmt=pix, bits=bits, transfer=trc, rotation=rot,
                 hdr='HLG' if trc == 'arib-std-b67' else ('PQ' if trc == 'smpte2084' else None))
        if v.get('duration'):
            d['dur'] = float(v['duration'])        # the video stream's own length (audio can run longer)
    _probe_cache[path] = d
    return d


def load_still(path):
    """BGR uint8, EXIF orientation applied"""
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert('RGB')
        return np.ascontiguousarray(np.asarray(im)[..., ::-1])


# ---- DJI-style proxies ----------------------------------------------------------------------------------------------
def proxy_of(path):
    """the low-res proxy recorded next to a clip (DJI .LRF), or None"""
    stem = os.path.splitext(path)[0]
    for ext in ('.LRF', '.lrf'):
        if os.path.exists(stem + ext):
            return stem + ext
    return None


def _motion_frames(path, fps):
    """tiny grey frames -> normalised frame differences: a motion signature that still discriminates when the scene
    itself barely changes (a static shot correlates with itself at every offset)"""
    cmd = ['ffmpeg', '-v', 'error'] + hwaccel() + ['-i', path, '-vf', f'fps={fps},scale=96:54,format=gray',
                                                   '-f', 'rawvideo', '-']
    a = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.uint8).reshape(-1, 54 * 96)
    a = np.diff(a.astype(np.float32), axis=0)
    a -= a.mean(1, keepdims=True)
    return a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-6)


def proxy_offset(main, proxy, lo=-8.0, hi=16.0, fps=5, win=8.0):
    """proxy time = main time + offset. DJI proxies can start seconds earlier than the main file, run 4-13 s longer,
    and the offset can CHANGE inside one clip (0 s for the first half, +3.2 s later), so it is measured per window.
    Returns [(main t0, main t1, offset, corr)] for windows of `win` seconds (half overlapping)."""
    m, p = _motion_frames(main, fps), _motion_frames(proxy, fps)
    offs = np.arange(int(lo * fps), int(hi * fps) + 1)
    n, hop = int(win * fps), int(win * fps / 2)
    out = []
    for i0 in range(0, max(len(m) - n // 2, 1), hop):
        idx = np.arange(i0, min(i0 + n, len(m)))
        best = (-1.0, 0)
        for off in offs:
            j = idx + off
            ok = (j >= 0) & (j < len(p))
            if ok.sum() >= max(5, len(idx) // 2):
                c = float((m[idx[ok]] * p[j[ok]]).sum(1).mean())
                best = max(best, (c, int(off)))
        out.append((i0 / fps, (idx[-1] + 1) / fps, best[1] / fps, best[0]))
    return out


def proxy_to_main(segments, t_proxy):
    """map a time read off the proxy back to the main file, with the offset of the window it falls in"""
    best = min(segments, key=lambda s: 0 if s[0] <= t_proxy - s[2] <= s[1] else
               min(abs(t_proxy - s[2] - s[0]), abs(t_proxy - s[2] - s[1])))
    return t_proxy - best[2]


# ---- fonts ----------------------------------------------------------------------------------------------------------
BUNDLED = {'title': 'Jura-Light.ttf', 'mono': 'DMMono-Regular.ttf', 'latin': 'InstrumentSans-Regular.ttf'}
CJK_CANDIDATES = [  # (path glob, preferred family, preferred style)
    ('/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData/PingFang.ttc', 'PingFang SC', 'Regular'),
    ('/System/Library/Fonts/PingFang.ttc', 'PingFang SC', 'Regular'),
    ('/System/Library/Fonts/Hiragino Sans GB.ttc', 'Hiragino Sans GB', 'W3'),
    ('/System/Library/Fonts/STHeiti Light.ttc', None, None),
    ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 'Noto Sans CJK SC', 'Regular'),
    ('/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc', 'Noto Sans CJK SC', 'Regular'),
    ('/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc', 'Noto Sans CJK SC', 'Regular'),
    ('C:/Windows/Fonts/msyh.ttc', None, None),
]
LATIN_FALLBACK = ['/System/Library/Fonts/Helvetica.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                  'C:/Windows/Fonts/arial.ttf']
_font_cache = {}


def font_file(kind):
    """(path, ttc index) for 'title' (Jura Light), 'mono' (DM Mono), 'latin' (Instrument Sans) or 'cjk'
    (PingFang SC / Hiragino / Noto Sans CJK SC). Override with FTV_FONT_<KIND>=path[:index]."""
    env = os.environ.get(f'FTV_FONT_{kind.upper()}')
    if env:
        p, sep, i = env.rpartition(':')
        if not sep or not i.isdigit():
            p, i = env, '0'
        return p, int(i)
    if kind in BUNDLED:
        p = os.path.join(FONT_DIR, BUNDLED[kind])
        if os.path.exists(p):
            return p, 0
        kind = 'latin_fallback'
    if kind == 'latin_fallback':
        for p in LATIN_FALLBACK:
            if os.path.exists(p):
                return p, 0
        raise FileNotFoundError('no Latin font found: set FTV_FONT_LATIN')
    from PIL import ImageFont
    for pat, fam, sty in CJK_CANDIDATES:
        for p in sorted(glob.glob(pat)):
            best = 0
            if fam:
                for i in range(40):
                    try:
                        name = ImageFont.truetype(p, 20, index=i).getname()
                    except OSError:
                        break
                    if name[0] == fam and (sty is None or name[1] == sty):
                        best = i
                        break
            return p, best
    raise FileNotFoundError('no CJK font found (PingFang / Hiragino / Noto Sans CJK): set FTV_FONT_CJK=path[:index]')


def load_font(kind, size):
    from PIL import ImageFont
    key = (kind, int(size))
    if key not in _font_cache:
        p, i = font_file(kind)
        _font_cache[key] = ImageFont.truetype(p, int(size), index=i)
    return _font_cache[key]


CJK_RE = re.compile(r'[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]')


def has_cjk(text):
    return bool(CJK_RE.search(text))


def missing_glyphs(font, text):
    """characters of `text` the font has no glyph for (they would render as tofu boxes)"""
    try:
        from fontTools.ttLib import TTFont
        path, idx = font.path, getattr(font, 'index', 0)
        key = ('cmap', path, idx)
        if key not in _font_cache:
            _font_cache[key] = set(TTFont(path, fontNumber=idx, lazy=True).getBestCmap())
        cmap = _font_cache[key]
        return sorted({c for c in text if not c.isspace() and ord(c) not in cmap})
    except Exception:
        notdef = bytes(font.getmask('\U0010fffd'))           # what an unmapped character draws
        return sorted({c for c in text if not c.isspace() and bytes(font.getmask(c)) == notdef})


# ---- the edit list --------------------------------------------------------------------------------------------------
DEFAULTS = dict(fps='30000/1001', bpm=90, beats_per_bar=4)


def load_edl(path):
    edl = json.load(open(path))
    for k, v in DEFAULTS.items():
        edl.setdefault(k, v)
    edl['_dir'] = os.path.dirname(os.path.abspath(path))
    edl['_path'] = os.path.abspath(path)
    return edl


def out_path(edl, *parts):
    p = os.path.join(edl['_dir'], *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def source_path(edl, src):
    """a shot's `src`: a key of edl['sources'] or a path; relative paths are relative to the EDL file"""
    p = edl.get('sources', {}).get(src, src)
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(edl['_dir'], p)


def bar_seconds(edl):
    return edl['beats_per_bar'] * 60.0 / edl['bpm']


def song(edl):
    """the existing song the film is cut to, or None: dict(path, start (s into the song), beats, bars (song times))"""
    m = edl.get('music', {})
    if not m.get('file'):
        return None
    path = source_path(edl, m['file'])
    bp = source_path(edl, m.get('beats', 'beats.json'))
    if not os.path.exists(bp):
        raise SystemExit(f'music.file is set but {bp} does not exist: run beats.py on the song first')
    b = json.load(open(bp))
    g = b.get('grid', {})
    beats = g['beats'] if g.get('use') else b['beats']
    bars = [x['t'] for x in b['bars']]
    if 'start_bar' in m:
        start = bars[int(m['start_bar'])]
    else:
        start = float(m.get('start', bars[0]))
    lines = []
    if m.get('lines'):                                       # lyric line cut times (song seconds), see lyrics.py
        lp = source_path(edl, m['lines'])
        lines = sorted(x['cut'] if isinstance(x, dict) else float(x) for x in json.load(open(lp)))
    return dict(path=path, start=start, beats=np.array(beats), bars=np.array(bars), duration=b.get('duration'),
                meter=b.get('meter', 4), lines=np.array(lines))


def _next_on(times, pos, n, step):
    """the n-th time in `times` strictly after pos (extrapolated past the end with `step`)"""
    later = times[times > pos + 1e-3]
    if len(later) >= n:
        return float(later[n - 1])
    last = float(later[-1]) if len(later) else pos
    return last + step * (n - len(later))


def timeline(edl):
    """shots with frame-exact start/length: each cut is its grid position rounded to the nearest output frame.
    Length per shot: `bars` or `beats` (on the music grid) or `dur` (seconds); `tail` adds seconds after the last
    shot's grid end (a ring-out that is not on the grid). With an existing song ("music": {"file": ...}), the grid is
    the song's own bars and beats from beats.json: `bars: n` runs to the n-th bar line after the cut, `beats: n` to
    the n-th beat, and `lines: n` to the start of the n-th lyric line (music.lines, written by lyrics.py)."""
    sg = song(edl)
    if sg is not None:
        return _song_timeline(edl, sg)
    fps = parse_fps(edl['fps'])
    beat = 60.0 / edl['bpm']
    out, t = [], 0.0
    shots = edl['shots']
    for i, s in enumerate(shots):
        if 'bars' in s:
            d = s['bars'] * edl['beats_per_bar'] * beat
        elif 'beats' in s:
            d = s['beats'] * beat
        elif 'dur' in s:
            d = float(s['dur'])
        else:
            raise ValueError(f"shot {s.get('role', i)}: give 'bars', 'beats' or 'dur'")
        a = round(t * fps)
        t += d
        tail = s.get('tail', 0) if i == len(shots) - 1 else 0
        b = round(t * fps) + round(tail * fps)
        out.append(dict(s, role=s.get('role', f'shot{i}'), sec=s.get('sec', 'main'), start_f=a, len_f=b - a,
                        start=a / fps, dur=(b - a) / fps, index=i))
    return out


def _song_timeline(edl, sg):
    fps = parse_fps(edl['fps'])
    bar_step = float(np.median(np.diff(sg['bars']))) if len(sg['bars']) > 1 else 2.0
    beat_step = float(np.median(np.diff(sg['beats']))) if len(sg['beats']) > 1 else 0.5
    pos = sg['start']
    out = []
    shots = edl['shots']
    for i, s in enumerate(shots):
        if 'bars' in s:
            end = _next_on(sg['bars'], pos, int(s['bars']), bar_step)
        elif 'beats' in s:
            end = _next_on(sg['beats'], pos, int(s['beats']), beat_step)
        elif 'lines' in s:
            if not len(sg['lines']) or int(s['lines']) > int(np.sum(sg['lines'] > pos + 1e-3)):
                raise ValueError(f"shot {s.get('role', i)}: 'lines' needs music.lines with {s['lines']} line(s) "
                                 f"after {pos:.2f}s")
            end = _next_on(sg['lines'], pos, int(s['lines']), 0)
        elif 'dur' in s:
            end = pos + float(s['dur'])
        else:
            raise ValueError(f"shot {s.get('role', i)}: give 'bars', 'beats', 'lines' or 'dur'")
        a = round((pos - sg['start']) * fps)
        tail = s.get('tail', 0) if i == len(shots) - 1 else 0
        b = round((end - sg['start']) * fps) + round(tail * fps)
        out.append(dict(s, role=s.get('role', f'shot{i}'), sec=s.get('sec', 'main'), start_f=a, len_f=b - a,
                        start=a / fps, dur=(b - a) / fps, index=i, song_t=round(pos, 3)))
        pos = end
    return out


def total_frames(tl):
    return tl[-1]['start_f'] + tl[-1]['len_f']


def sections(tl):
    """[(name, t0, t1)] for runs of consecutive shots with the same `sec`"""
    out = []
    for s in tl:
        if out and out[-1][0] == s['sec']:
            out[-1][2] = s['start'] + s['dur']
        else:
            out.append([s['sec'], s['start'], s['start'] + s['dur']])
    return [tuple(x) for x in out]


def trans_frames(edl, tl):
    """shot index -> (type, frames on each side of the cut, extra) for shots with a `trans_in` other than a cut"""
    fps = parse_fps(edl['fps'])
    out = {}
    for i, s in enumerate(tl):
        tr = s.get('trans_in')
        if i == 0 or not tr or tr[0] == 'cut':
            continue
        out[i] = (tr[0], max(1, int(round(float(tr[1]) / 2 * fps))), tr[2] if len(tr) > 2 else None)
    return out


def pre_post(edl, tl):
    """frames each shot must provide before its start / after its end for transitions"""
    tr = trans_frames(edl, tl)
    return [(tr[i][1] if i in tr else 0, tr[i + 1][1] if i + 1 in tr else 0) for i in range(len(tl))]


def line_text(line, lang):
    t = line['text']
    if isinstance(t, dict):
        return t.get(lang) or next(iter(t.values()))
    return t


def line_lang(edl, lang=None):
    if lang:
        return lang
    for ln in edl.get('lines', []):
        if isinstance(ln['text'], dict):
            return next(iter(ln['text']))
        return 'zh' if has_cjk(ln['text']) else 'en'
    return 'zh'


def narration_info(edl, lang):
    p = os.path.join(edl['_dir'], 'narration', lang, 'lines.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def estimate_dur(text, speed=0.9):
    """spoken length before the narration exists (Mandarin ~4.3 chars/s, English ~14 chars/s at F5 speed 0.9)"""
    n = len(re.sub(r'[\s，。、！？：；,.!?]', '', text))
    return (n / 4.3 if has_cjk(text) else len(text) / 14.0) * 0.9 / speed


def line_events(edl, tl, lang):
    """[(id, t0, t1, text, measured)] for the narration lines (durations from narration/<lang>/lines.json)"""
    info = narration_info(edl, lang)
    starts = {s['role']: s['start'] for s in tl}
    ev = []
    for ln in edl.get('lines', []):
        text = line_text(ln, lang)
        if ln['shot'] not in starts:
            raise ValueError(f"line {ln['id']}: no shot '{ln['shot']}'")
        a = starts[ln['shot']] + ln.get('at', 0.0)
        got = info.get(str(ln['id']))
        d = got['dur'] if got else estimate_dur(text)
        ev.append((str(ln['id']), a, a + d, text, bool(got)))
    return sorted(ev, key=lambda e: e[1])


# ---- checks ---------------------------------------------------------------------------------------------------------
def check(edl, lang=None, quiet=False):
    """print the timeline and every problem that would spoil a render; returns the list of problems"""
    tl = timeline(edl)
    fps = parse_fps(edl['fps'])
    pp = pre_post(edl, tl)
    problems, warnings = [], []
    if not quiet:
        print(f"{'role':14s} {'sec':8s} {'start':>7s} {'dur':>6s}  {'src':12s} {'in':>7s} {'speed':>5s}  modes")
    for s, (pre, post) in zip(tl, pp):
        path = source_path(edl, s['src'])
        sp = s.get('speed', 1.0)
        if not quiet:
            modes = ' '.join(f"{k}={s[k]}" for k in ('v', 'h') if k in s)
            print(f"{s['role']:14s} {s['sec']:8s} {s['start']:7.2f} {s['dur']:6.2f}  {s['src'][:12]:12s} "
                  f"{s.get('t_in', 0):7.2f} {sp:5.2f}  {modes}")
        if not os.path.exists(path):
            problems.append(f"{s['role']}: source not found: {path}")
            continue
        if is_still(path):
            continue
        p = probe(path)
        t0 = s.get('t_in', 0.0) - pre / fps * sp
        t1 = s.get('t_in', 0.0) + (s['len_f'] + post) / fps * sp
        if s.get('t_in', 0.0) < 0:
            problems.append(f"{s['role']}: t_in < 0")
        if t0 < 0:
            warnings.append(f"{s['role']}: the transition needs {-t0:.2f}s before the clip starts (first frame held)")
        if t1 > p['dur'] - 0.03:
            problems.append(f"{s['role']}: needs source up to {t1:.2f}s but {os.path.basename(path)} is "
                            f"{p['dur']:.2f}s long (proxy times past the main file's end?)")
        if p.get('hdr'):
            problems.append(f"{s['role']}: {p['hdr']} HDR source - convert to SDR first (hdr_to_sdr.py), "
                            f"or it renders flat and grey next to SDR shots")
        if sp < 1 and p.get('fps', 30) * sp < fps * 0.95:
            warnings.append(f"{s['role']}: {sp}x on a {p['fps']:.0f} fps source repeats frames (judder); "
                            f"slow motion wants >= {fps / sp:.0f} fps")
        if 'v' in s and s['v'] in ('rot', 'rot2fit', 'rot2box') and p['w'] < p['h']:
            warnings.append(f"{s['role']}: 'rot' on a portrait source")
        if s.get('centre') == 'track':
            tp = os.path.join(edl['_dir'], 'tracks.json')
            if not os.path.exists(tp) or s['role'] not in json.load(open(tp)):
                problems.append(f"{s['role']}: centre='track' but tracks.json has no '{s['role']}' (run track.py)")
    tail = [s for s in tl[:-1] if s.get('tail')]
    for s in tail:
        warnings.append(f"{s['role']}: 'tail' only applies to the last shot")
    T = tl[-1]['start'] + tl[-1]['dur']
    if edl.get('lines'):
        lang = line_lang(edl, lang)
        ev = line_events(edl, tl, lang)
        for k, (i, a, b, text, measured) in enumerate(ev):
            if not quiet:
                print(f"  line {i:>3s} {a:6.2f}-{b:6.2f}s {'' if measured else '(est.) '}{text}")
            if k + 1 < len(ev) and b > ev[k + 1][1] - 0.3:
                problems.append(f"line {i} ends {b:.2f}s, line {ev[k + 1][0]} starts {ev[k + 1][1]:.2f}s: "
                                f"less than 0.3 s apart")
            if b > T - 0.5:
                problems.append(f"line {i} ends {b:.2f}s, the video ends {T:.2f}s")
    sg = song(edl)
    if sg is not None and not quiet:
        end = sg['start'] + T
        print(f"song {os.path.basename(sg['path'])}: from {sg['start']:.2f}s to {end:.2f}s"
              + (f" of {sg['duration']:.1f}s" if sg.get('duration') else ''))
        if sg.get('duration') and end > sg['duration'] + 0.5:
            problems.append(f"the film runs {end - sg['duration']:.1f}s past the end of the song")
        if not os.path.exists(sg['path']):
            problems.append(f"song not found: {sg['path']}")
    if not quiet:
        print(f'total {T:.2f}s, {total_frames(tl)} frames at {fps:.3f} fps; {len(tl)} shots; '
              f'sections: ' + ', '.join(f'{n} {a:.1f}-{b:.1f}' for n, a, b in sections(tl)))
        for w in warnings:
            print('WARNING', w)
        for p in problems:
            print('PROBLEM', p)
    return problems


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edl')
    ap.add_argument('--lang', help='narration language to check when lines have several')
    a = ap.parse_args()
    sys.exit(1 if check(load_edl(a.edl), a.lang) else 0)
