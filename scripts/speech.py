"""What people say (and laugh) on camera: Whisper over each clip's own sound, with times.

The camera sound of people - a laugh, a gasp at the whale, "so cute!" - is the most human part of a travel film.
Whisper transcribes each clip's sound with times; segments where the sound is no
louder than the clip's own background, and the stock phrases Whisper invents over silence and wind ("subtitles
by ...", "thanks for watching", 字幕志愿者), are dropped; looping repeats are shortened. What is left is listed with
times. Each hit is re-transcribed from two shifted windows: a real voice comes back the same ("stable"), noise
turns into different words each time ("UNSTABLE" - drop it unless the picture shows people talking). Keep the
best as "speech" windows on the shots (mix.py lifts them; [a, b, "words"] lets finish.py --verify check them).

usage: python speech.py CLIP_OR_FOLDER... [--lang auto|zh|en|...] [--out speech.json]
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import tempfile

import numpy as np
from scipy.io import wavfile

from common import probe
from inventory import files

SR = 16000
INVENTED = re.compile(r'(中文)?字幕(由|志愿者|提供|制作|by)[^。，,.!?]*|请不吝[^。]*|(点赞|订阅|打赏)[^。]*(频道|栏目)[^。]*|'
                      r'明镜与点点栏目|thank(s| you) for watching[.!]?|see you next time[.!]?|subtitles? by[^.]*\.?|'
                      r'amara\.org[^.]*|please subscribe[.!]?|like and subscribe[.!]?', re.I)


def loud_fraction(db, hop, t0, t1, thr):
    a, b = int(t0 * SR / hop), max(int(t1 * SR / hop), int(t0 * SR / hop) + 1)
    seg = db[a:b]
    return float((seg > thr).mean()) if len(seg) else 0.0


def tidy(text):
    """'oh, oh, oh, oh, oh, ...' -> 'oh, oh, oh…' (Whisper loops on laughter and noise)"""
    return re.sub(r'((\S+?)[,，]?\s?)(\2[,，]?\s?){3,}', r'\1\1\1… ', text).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--lang', default='auto')
    ap.add_argument('--out', default='speech.json')
    a = ap.parse_args()
    from narrate import asr
    pipe = asr()
    kw = {'task': 'transcribe'}
    if a.lang != 'auto':
        kw['language'] = a.lang
    out = {}
    with tempfile.TemporaryDirectory() as td:
        for f in files(a.paths):
            p = probe(f)
            if not p['audio']:
                continue
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', f, '-vn', '-ac', '1', '-ar', str(SR),
                                  '-f', 'f32le', '-'], capture_output=True, check=True).stdout
            x = np.frombuffer(raw, np.float32)
            hop = int(0.03 * SR)
            n = len(x) // hop
            db = 20 * np.log10(np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
            thr = max(np.percentile(db, 20) + 6, -55)        # louder than the clip's own background (wind, engine)
            w = os.path.join(td, 'a.wav')
            wavfile.write(w, SR, x)
            r = pipe(w, generate_kwargs=kw, return_timestamps=True, chunk_length_s=30, batch_size=8)
            segs, last = [], None
            for c in r.get('chunks', []):
                t0, t1 = c['timestamp']
                t0 = t0 or 0.0
                t1 = t1 if (t1 is not None and t1 > t0) else t0 + 2.0
                text = tidy(INVENTED.sub('', c['text']).strip(' ,.，。'))
                if not text or text == last or loud_fraction(db, hop, t0, t1, thr) < 0.05:
                    continue
                last = text
                segs.append([round(t0, 1), round(t1, 1), text])
            # a real voice transcribes the same from slightly shifted windows; noise turns into different words
            for sg in segs:
                alts = []
                for d0, d1 in ((-0.3, 0.3), (0.2, 0.6)):
                    a0, a1 = max(sg[0] + d0, 0), min(sg[1] + d1, len(x) / SR)
                    wavfile.write(w, SR, x[int(a0 * SR):int(a1 * SR)])
                    alts.append(tidy(INVENTED.sub('', pipe(w, generate_kwargs=kw)['text']).strip(' ,.，。')))
                n = lambda t: re.sub(r'[\W_]+', '', t.lower())
                agree = np.mean([difflib.SequenceMatcher(None, n(sg[2]), n(t)).ratio() for t in alts])
                sg += [round(float(agree), 2), alts]
            out[f] = segs
            print(f'{f} ({p["dur"]:.0f}s): {len(segs)} stretches with speech', flush=True)
            for t0, t1, text, agree, alts in segs:
                flag = 'stable  ' if agree >= 0.6 else 'UNSTABLE'
                also = '' if agree >= 0.6 else f'   (also heard: {" / ".join(alts)})'
                print(f'   {t0:7.1f}-{t1:7.1f}s  {flag} {text}{also}')
    json.dump(out, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print('wrote', a.out)


if __name__ == '__main__':
    main()
