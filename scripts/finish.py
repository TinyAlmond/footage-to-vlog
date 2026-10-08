"""Deliverables from the composed picture and the mix, plus the checks that catch the embarrassing mistakes.

  <name>.mp4         master: the picture as rendered (stream copy) + AAC 384k; metadata stripped (no GPS, no
                     device names), +faststart. 4K vertical for Xiaohongshu / Douyin / Reels / Shorts; 4K
                     horizontal for YouTube.
  <name>.srt         the narration as a caption file (YouTube CC; burned subtitles stay in the picture)
  <name>_phone.mp4   small preview (< 28 MB) to send to a phone for review
  <name>_x.mp4       X/Twitter: 1080p, AAC 192k (X caps length at 2:20 for most accounts and size at 512 MB)
Checks: duration and frame count against the EDL, integrated loudness / true peak / loudness range of the master
(ffmpeg ebur128), and with --verify Whisper transcribes every narration line FROM THE FINAL MIX (music and
natural sound must not bury a word), plus on-camera speech tagged with its words ("speech": [[a, b, "words"]]).
A preview input (half-size render) gets '_preview' in every output name, so it never overwrites a master.
--chapters prints a YouTube chapter skeleton from the sections (YouTube needs >= 3 chapters, the first at 0:00,
each >= 10 s; name them yourself).

usage: python finish.py edl.json VIDEO [--audio mix_zh.wav] [--lang zh] [--name NAME] [--targets master,phone,x]
                        [--verify] [--chapters]
"""
import argparse
import difflib
import os
import re
import subprocess

from common import (has_cjk, line_events, line_lang, load_edl, out_path, parse_fps, probe, sections, timeline,
                    total_frames)

COMMON = ['-map_metadata', '-1', '-map_chapters', '-1', '-movflags', '+faststart']


def ts(t):
    h, m = int(t // 3600), int(t % 3600 // 60)
    s = t % 60
    return f'{h:02d}:{m:02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}'


def srt_events(edl, tl, lang):
    """sentence-level caption events: a long line is split at sentence ends, timed by character count"""
    ev = []
    for _, a, b, text, _ in line_events(edl, tl, lang):
        a, b = a - 0.05, b + 0.35
        parts = [p for p in re.split(r'(?<=[。！？!?])\s*|(?<=\.)\s+', text) if p.strip()]
        n = sum(len(p) for p in parts)
        t = a
        for p in parts:
            d = (b - a) * len(p) / n
            cjk = re.search(r'[一-鿿]', p)
            ev.append((t, t + d, p.rstrip('。！？').replace('，', ' ') if cjk else p))
            t += d
    return ev


def run(cmd):
    subprocess.run(cmd, check=True)


def ebur128(path):
    err = subprocess.run(['ffmpeg', '-v', 'info', '-nostats', '-i', path, '-af', 'ebur128=peak=true',
                          '-f', 'null', '-'], capture_output=True, text=True).stderr
    summ = err[err.rfind('Summary:'):]
    get = lambda k: (re.search(k + r':\s*(-?[\d.]+)', summ) or [None, 'nan'])[1]
    return float(get('I')), float(get('LRA')), float(get('Peak'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edl')
    ap.add_argument('video')
    ap.add_argument('--audio', help='default: mix_<lang>.wav (or mix.wav) next to the EDL')
    ap.add_argument('--lang')
    ap.add_argument('--name')
    ap.add_argument('--targets', default='master,phone', help='comma separated: master, phone, x')
    ap.add_argument('--verify', action='store_true', help='Whisper-check every narration line in the final mix')
    ap.add_argument('--chapters', action='store_true')
    a = ap.parse_args()
    edl = load_edl(a.edl)
    tl = timeline(edl)
    lang = line_lang(edl, a.lang)
    T = tl[-1]['start'] + tl[-1]['dur']
    audio = a.audio or next((os.path.join(edl['_dir'], f) for f in (f'mix_{lang}.wav', 'mix.wav')
                             if os.path.exists(os.path.join(edl['_dir'], f))), None)
    if not audio:
        raise SystemExit('no mix found: run mix.py (or pass --audio)')
    v = probe(a.video)
    vert = v['h'] > v['w']
    full = edl.get('canvas', {}).get('V' if vert else 'H', (2160, 3840) if vert else (3840, 2160))
    preview = '_preview' in os.path.basename(a.video) or max(v['w'], v['h']) < max(full)
    name = a.name or (f"{edl.get('name', 'video')}{'_' + lang if edl.get('lines') else ''}_{'V' if vert else 'H'}"
                      f"{'_preview' if preview else ''}")
    targets = a.targets.split(',')
    master = out_path(edl, 'out', f'{name}.mp4')
    run(['ffmpeg', '-v', 'error', '-y', '-i', a.video, '-i', audio, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
         '-c:a', 'aac', '-b:a', '384k', '-ar', '48000', '-t', f'{T:.3f}'] + COMMON + [master])
    m = probe(master)
    fps = parse_fps(edl['fps'])
    print(f"{master}: {m['w']}x{m['h']} {m['fps']:.3f} fps, {m['dur']:.2f}s (EDL {T:.2f}s, "
          f"{total_frames(tl)} frames), {os.path.getsize(master) / 2 ** 20:.0f} MiB")
    if abs(m['dur'] - T) > 1.5 / fps:
        print(f'WARNING: the master is {m["dur"] - T:+.2f}s off the EDL')
    I, LRA, TP = ebur128(master)
    print(f'loudness {I:.1f} LUFS integrated, range {LRA:.1f} LU, true peak {TP:.1f} dBFS'
          + ('   <- expected about -16' if abs(I + 16) > 1 else ''))
    if edl.get('lines'):
        srt = out_path(edl, 'out', f'{name}.srt')
        with open(srt, 'w') as f:
            for k, (x0, x1, text) in enumerate(srt_events(edl, tl, lang), 1):
                f.write(f'{k}\n{ts(x0)} --> {ts(x1)}\n{text}\n\n')
        print('wrote', srt)
    if 'phone' in targets:
        p = out_path(edl, 'out', f'{name}_phone.mp4')
        kbps = int(min(2500, max(600, 27 * 8 * 1024 / max(T, 1) - 128)))
        size = '720:1280' if vert else '1280:720'
        run(['ffmpeg', '-v', 'error', '-y', '-i', master, '-vf', f'scale={size}:flags=lanczos', '-c:v', 'libx264',
             '-preset', 'slow', '-b:v', f'{kbps}k', '-maxrate', f'{int(kbps * 1.4)}k', '-bufsize', f'{kbps * 3}k',
             '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k'] + COMMON + [p])
        print(f'wrote {p} ({os.path.getsize(p) / 2 ** 20:.1f} MiB)')
    if 'x' in targets:
        p = out_path(edl, 'out', f'{name}_x.mp4')
        size = '1080:1920' if vert else '1920:1080'
        run(['ffmpeg', '-v', 'error', '-y', '-i', master, '-vf', f'scale={size}:flags=lanczos', '-c:v', 'libx264',
             '-preset', 'slow', '-crf', '20', '-profile:v', 'high', '-level', '4.2', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '192k', '-ar', '48000'] + COMMON + [p])
        mb = os.path.getsize(p) / 2 ** 20
        print(f'wrote {p} ({mb:.0f} MiB)' + ('   <- X limit is 2:20 for most accounts' if T > 140 else '')
              + ('   <- over 512 MB' if mb > 512 else ''))
    if a.chapters:
        print('YouTube chapters (rename; >= 3, first 0:00, each >= 10 s):')
        chs = []
        for n, x0, x1 in sections(tl):
            if chs and (x0 - chs[-1][0] < 10 or x1 - x0 < 10):
                continue
            chs.append((x0, n))
        if chs:
            chs[0] = (0.0, chs[0][1])
        for x0, n in chs:
            print(f'  {int(x0 // 60)}:{int(x0 % 60):02d} {n}')
        if len(chs) < 3:
            print('  (fewer than 3 chapters: YouTube will ignore them; fine for a short)')
    if a.verify and (edl.get('lines') or any(len(w) > 2 for s in tl for w in s.get('speech', []))):
        from narrate import norm, transcribe
        tmp = out_path(edl, 'out', '_verify.wav')
        print('heard in the final mix:')
        must = {str(ln['id']): ln.get('must', []) for ln in edl.get('lines', [])}
        checks = list(line_events(edl, tl, lang))
        for s in tl:                                      # on-camera speech tagged with what is said
            for w in s.get('speech', []):
                if len(w) > 2:
                    must[f"{s['role']}@{w[0]}"] = []
                    checks.append((f"{s['role']}@{w[0]}", s['start'] + w[0], s['start'] + w[1], w[2], True))
        for k, x0, x1, text, _ in checks:
            lg = lang if '@' not in k else ('zh' if has_cjk(text) else 'en')
            mw = must[k].get(lang, []) if isinstance(must[k], dict) else must[k]
            best = None
            for pa, pb in ((0.2, 0.3), (0.5, 0.6)):      # two windows: Whisper wavers on a borderline consonant
                run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{max(x0 - pa, 0):.3f}', '-i', master, '-t',
                     f'{x1 - x0 + pa + pb:.3f}', '-vn', '-ac', '1', '-ar', '16000', tmp])
                h = transcribe(tmp, lg)
                sm = difflib.SequenceMatcher(None, norm(h, lg), norm(text, lg)).ratio()
                ls = [w for w in mw if norm(w, lg) not in norm(h, lg)]
                if best is None or (not ls, sm) > (not best[2], best[1]):
                    best = (h, sm, ls)
            heard, sim, lost = best
            bad = sim < (0.6 if '@' in k else 0.85) or lost   # a 2-3 syllable exclamation: one sound off is fine
            fix = ('deeper speech_duck_db, or a cleaner moment' if '@' in k else
                   'deeper duck_db, move the line off a hit, re-run narrate.py, or quieten that section')
            print(f"  {k}: {sim:.2f}  {heard}" + (f"   <- {'/'.join(lost) + ' lost' if lost else 'garbled'}: {fix}"
                                                 if bad else ''))
        os.remove(tmp)


if __name__ == '__main__':
    main()
