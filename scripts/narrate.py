"""Narration in the user's own cloned voice (F5-TTS, zero-shot), every line checked by ear - by Whisper.

Each line of the EDL's "lines" is synthesised with a seed, transcribed back with Whisper, and retried with other
seeds until the transcript matches the script and contains the line's "must" words (names, the key noun): TTS can
say a near-homophone (鲸鱼 -> 金鱼, 镜头 -> 尽头) and you would never notice by reading. When music.wav exists, each
take is also checked with the score playing under it (ducked as mix.py will): a take that is only intelligible on
its own (a place name heard as another word once the band plays) is rejected. When no seed gets a line right,
REWORD it (another word for the same thing) rather than trying more seeds. Lines are trimmed at both ends only
(never inside: a pause is not the end), high-passed and levelled to -18 LUFS.
-> narration/<lang>/line_<id>.wav (48 kHz mono) + narration/<lang>/lines.json (text, seed, duration, transcript, match)

The reference: the user reading 5-12 s of plain speech in a quiet room, and its EXACT transcript. F5-TTS clips the
reference at ~12 s; a longer one no longer matches its transcript and the output speeds up and garbles.
--prepare-ref cuts a <= 11.5 s piece that ends at a pause from a longer recording and prints Whisper's transcript
for the user to confirm. Clone only the voice of the person who asked (their consent, their recording), and label
the video as containing AI-generated voice where the platform asks.

usage: python narrate.py edl.json [--lang zh] [--ids 1,3] [--ref ref.wav --ref-text "..."] [--speed 0.9] [--no-context]
       python narrate.py --prepare-ref recording.wav [--out ref.wav] [--lang zh]
voice settings can live in the EDL: "voice": {"ref": "voice/ref.wav", "ref_text": "...", "speed": 0.9}
Models (download once): F5TTS_v1_Base (code MIT, weights CC-BY-NC 4.0: non-commercial), openai/whisper-large-v3-turbo.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import tempfile

os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')
import numpy as np
from scipy.io import wavfile

from common import SR, line_events, line_lang, line_text, load_edl, out_path, timeline

SEEDS = (7, 11, 23, 42, 3, 5, 99, 123, 1, 2, 13, 17, 31, 64, 77, 256)
ZH_PROMPT = '以下是普通话的句子，使用简体中文。'        # nudges Whisper to simplified characters
_pipe = None


def device():
    import torch
    return 'mps' if torch.backends.mps.is_available() else ('cuda' if torch.cuda.is_available() else 'cpu')


def asr():
    """the Whisper pipeline (whisper-large-v3-turbo), built once"""
    global _pipe
    if _pipe is None:
        import torch
        from transformers import pipeline
        dev = device()
        dt = torch.float16 if dev == 'cuda' else torch.float32
        name = 'openai/whisper-large-v3-turbo'
        try:
            _pipe = pipeline('automatic-speech-recognition', model=name, dtype=dt, device=dev)
        except TypeError:                                   # older transformers
            _pipe = pipeline('automatic-speech-recognition', model=name, torch_dtype=dt, device=dev)
    return _pipe


def transcribe(path, lang):
    """text of a short recording (< 30 s)"""
    _pipe = asr()
    kw = {'task': 'transcribe', 'language': lang}
    if lang == 'zh':
        try:
            kw['prompt_ids'] = _pipe.tokenizer.get_prompt_ids(ZH_PROMPT, return_tensors='pt').to(_pipe.device)
        except Exception:
            pass
    text = _pipe(path, generate_kwargs=kw, return_timestamps=False)['text'].strip()
    return text.replace(ZH_PROMPT, '').strip()


ZH_DIGITS = str.maketrans('〇零一二三四五六七八九', '00123456789')


def norm(s, lang):
    if lang == 'zh':
        return re.sub(r'[\W_]+', '', s).translate(ZH_DIGITS)
    return re.sub(r'\s+', ' ', re.sub(r"[^a-z0-9' ]", ' ', s.lower())).strip()


def level(x, sr):
    """trim silence at both ends only (the areverse trick: a stop-periods trim cuts at the first pause in the
    sentence), 80 Hz high-pass, -18 LUFS, 48 kHz mono"""
    with tempfile.TemporaryDirectory() as td:
        a, b = os.path.join(td, 'in.wav'), os.path.join(td, 'out.wav')
        wavfile.write(a, sr, np.asarray(x, np.float32))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', a, '-af',
                        'silenceremove=start_periods=1:start_threshold=-40dB,areverse,'
                        'silenceremove=start_periods=1:start_threshold=-40dB,areverse,'
                        'highpass=f=80,loudnorm=I=-18:TP=-2:LRA=7,aresample=48000',
                        '-ac', '1', '-c:a', 'pcm_f32le', b], check=True)
        return wavfile.read(b)[1].astype(np.float32)


def load_audio(path, sr=24000):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def prepare_ref(src, out, lang, max_len=11.5):
    """the longest stretch <= max_len s that starts and ends at a pause"""
    sr = 24000
    x = load_audio(src, sr)
    hop = int(0.02 * sr)
    rms = np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, 'same')[::hop] + 1e-12)
    db = 20 * np.log10(rms)
    floor = np.percentile(db, 10)                    # the room's noise floor
    quiet = db < min(max(floor + 6.0, db.max() - 40.0), db.max() - 15.0)
    # pause = >= 0.25 s of quiet; candidate cut points are the middles of pauses (+ start / end of the file)
    cuts, run = [0.0], 0
    for i, q in enumerate(quiet):
        run = run + 1 if q else 0
        if run == int(0.25 / 0.02):
            cuts.append((i - run / 2) * 0.02)
    cuts.append(len(x) / sr)
    best = None
    for i, a in enumerate(cuts):
        for b in cuts[i + 1:]:
            if b - a <= max_len and (best is None or b - a > best[1] - best[0]):
                best = (a, b)
    if best is None or best[1] - best[0] < 4.0:
        raise SystemExit('no stretch of 4-11.5 s between pauses: record again with natural pauses between sentences')
    a, b = best
    y = x[int(a * sr):int(b * sr)]
    y = y / max(np.abs(y).max(), 1e-6) * 0.7
    wavfile.write(out, sr, y.astype(np.float32))
    text = transcribe(out, lang)
    print(f'{out}: {b - a:.1f}s (from {a:.1f}s to {b:.1f}s of {src})')
    print(f'Whisper hears: {text}')
    print('Have the speaker confirm this word for word (fix it if not), '
          'then pass it as --ref-text or "voice.ref_text".')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edl', nargs='?')
    ap.add_argument('--lang')
    ap.add_argument('--ids', help='only these line ids (comma separated)')
    ap.add_argument('--ref')
    ap.add_argument('--ref-text')
    ap.add_argument('--speed', type=float)
    ap.add_argument('--seeds', help='comma separated')
    ap.add_argument('--no-context', action='store_true', help='do not check the takes against music.wav')
    ap.add_argument('--prepare-ref', metavar='RECORDING')
    ap.add_argument('--out', default='ref.wav')
    a = ap.parse_args()
    if a.prepare_ref:
        return prepare_ref(a.prepare_ref, a.out, a.lang or 'zh')
    if not a.edl:
        ap.error('give the EDL (or --prepare-ref)')
    edl = load_edl(a.edl)
    voice = edl.get('voice', {})
    ref = os.path.expanduser(a.ref or voice.get('ref', ''))
    if ref and not os.path.isabs(ref):
        ref = os.path.join(edl['_dir'], ref)
    ref_text = a.ref_text or voice.get('ref_text')
    speed = a.speed or voice.get('speed', 0.9)
    if not ref or not os.path.exists(ref) or not ref_text:
        ap.error('need the reference recording and its exact transcript (--ref/--ref-text or "voice" in the EDL)')
    rdur = len(load_audio(ref)) / 24000
    if rdur > 12.0:
        raise SystemExit(f'reference is {rdur:.1f}s: F5-TTS clips it at ~12 s and the transcript no longer matches; '
                         f'cut it with --prepare-ref')
    lang = line_lang(edl, a.lang)
    seeds = [int(s) for s in a.seeds.split(',')] if a.seeds else SEEDS
    lines = [ln for ln in edl.get('lines', []) if not a.ids or str(ln['id']) in a.ids.split(',')]
    from f5_tts.api import F5TTS
    tts = F5TTS(model='F5TTS_v1_Base', device=device())
    info_p = out_path(edl, 'narration', lang, 'lines.json')
    info = json.load(open(info_p)) if os.path.exists(info_p) else {}
    failed = []
    bed, starts = None, {}
    mp = os.path.join(edl['_dir'], 'music.wav')
    if os.path.exists(mp) and not a.no_context:
        bed = wavfile.read(mp)[1].astype(np.float32)
        bed = (bed.mean(1) if bed.ndim == 2 else bed) * 10 ** (-edl.get('mix', {}).get('duck_db', 9.0) / 20)
        starts = {k: x0 for k, x0, _, _, _ in line_events(edl, timeline(edl), lang)}
        print('checking every take with music.wav playing under it')
    for ln in lines:
        k = str(ln['id'])
        text = line_text(ln, lang)
        say = ln.get('tts')
        say = (say.get(lang) if isinstance(say, dict) else say) or text
        must = ln.get('must', [])
        must = must.get(lang, []) if isinstance(must, dict) else must
        best = None
        tmp = out_path(edl, 'narration', lang, f'line_{k}.tmp.wav')
        for seed in seeds:
            wav, sr, _ = tts.infer(ref_file=ref, ref_text=ref_text, gen_text=say, seed=seed, speed=speed,
                                   show_info=lambda *x: None)
            y = level(np.asarray(wav, np.float32), sr)
            wavfile.write(tmp, SR, y)
            asr = transcribe(tmp, lang)
            sim = difflib.SequenceMatcher(None, norm(asr, lang), norm(text, lang)).ratio()
            ok = all(norm(m, lang) in norm(asr, lang) for m in must)
            if bed is not None and k in starts and (sim >= 0.85 and ok):
                i0 = int(max(starts[k] - 0.2, 0) * SR)
                ctx = bed[i0:i0 + len(y) + int(0.5 * SR)].copy()
                ctx = np.pad(ctx, (0, max(0, len(y) + int(0.5 * SR) - len(ctx))))
                ctx[int(0.2 * SR):int(0.2 * SR) + len(y)] += y
                wavfile.write(tmp, SR, ctx.astype(np.float32))
                asr2 = transcribe(tmp, lang)
                sim2 = difflib.SequenceMatcher(None, norm(asr2, lang), norm(text, lang)).ratio()
                ok2 = all(norm(m, lang) in norm(asr2, lang) for m in must)
                if sim2 < sim or not ok2:
                    asr, sim, ok = asr2 + '  (with music)', min(sim, sim2), ok and ok2
            score = sim + (0.5 if ok else 0)
            if best is None or score > best[0]:
                best = (score, y, seed, asr, sim, ok)
            if sim >= 0.92 and ok:
                break
        os.remove(tmp)
        score, y, seed, asr, sim, ok = best
        wavfile.write(out_path(edl, 'narration', lang, f'line_{k}.wav'), SR, y)
        info[k] = dict(text=text, tts=say, seed=seed, dur=round(len(y) / SR, 3), asr=asr, match=round(sim, 3),
                       must_ok=ok)
        flag = '' if (ok and sim >= 0.85) else '   <- CHECK: reword this line'
        print(f"line {k}: {info[k]['dur']:.2f}s seed {seed} match {sim:.2f}"
              f"{'' if ok else ' MISSING ' + '/'.join(must)}  heard: {asr}{flag}", flush=True)
        if flag:
            failed.append(k)
        json.dump(info, open(info_p, 'w'), ensure_ascii=False, indent=1)
    if failed:
        print(f'lines {", ".join(failed)} never came back right: reword them (avoid near-homophones, unusual names '
              f'at the start, numbers), or put a phonetic spelling in "tts"')


if __name__ == '__main__':
    main()
