# Troubleshooting: problems already met, and their fixes

| symptom | cause | fix |
|---|---|---|
| A shot comes out short, or freezes on its last frame ("source ran out") | in/out points read off a proxy; the main file is 4-13 s shorter | `common.py edl.json` checks every window against the main file; read times from the main file |
| A cut lands seconds away from the moment picked on the sheets | proxy offset, which can change inside a clip | `align_proxy.py clip.MP4`; confirm with `contact_sheet.py clip --main --t0 --t1 --step 0.5` |
| Phone clips look flat and grey next to the rest | HLG HDR decoded as SDR | `hdr_to_sdr.py` before editing (inventory flags HDR) |
| Underwater shots are grey-blue and hazy | water absorbs red, scatters light | `"grade": "water"` (16-bit, per-shot levels) |
| Slow motion stutters | `speed` < 1 on 30 fps footage repeats frames | slow down only 60 fps+ footage (0.5x of 60 fps = every frame used) |
| The subject drifts to the edge during a zoom | fixed centre, or the camera itself drifted | `track.py` + `"centre": "track", "lock": true`; pick a window where the camera is steady |
| The tracker jumps to the wrong thing | seed too far away / colour range too wide; OWLv2 picking the other boat / person | `--sheet` and look; move the seed to the first frame's position; narrow the range; `--owl ... --seed X,Y` follows one object |
| A match transition lands side by side, not on top | the subject is not where you guessed (a bright rim biases a brightness peak) | measure the subject's centroid in a rendered frame and correct `centre`; `fill` needs zoom > 1 to move the centre at all |
| Black corners while a shot turns (rot2fit) | the turning frame does not cover the canvas | built in: the blurred fill sits behind; if you write your own, never leave black |
| Subtitles are boxes (tofu) | Latin font (DM Mono, Jura) used for CJK, or ′ ″ in Jura | the scripts pick a CJK font for CJK text and warn about missing glyphs - read the warnings |
| Subtitles hard to read over foam, snow, sky | white text on white | `"subs": {"plate": 0.3}` |
| A narration line is spoken wrong (鲸鱼 -> 金鱼) | TTS homophone, unknown name | reword (sound.md has real cases); `"tts"` spelling for names |
| Narration speeds up and garbles | reference > 12 s, or its transcript is not exact | `narrate.py --prepare-ref`; have the user confirm the transcript word for word |
| A line is fine alone but lost in the final mix | busy music under it (a hit, a melody note on a consonant) | narrate.py checks takes against music.wav (run the score first); finish.py --verify; deeper `duck_db`; move the line |
| Narration cut off in the middle | silence trimming that stops at the first pause | trim the ends only (narrate.py's level() does) |
| On-camera words buried under the music | the music only ducked as much as for narration | `speech` windows (music ducks 12 dB); tag the words for `finish.py --verify` |
| One shot's natural sound jumps out | devices record 10-20 dB apart; wind gusts | per-shot `natural` level; `hpf: 180`; the gust limiter is automatic |
| The film sounds flat | every section at the same loudness | score targets with a spread; check mix.py's per-section report (5+ LU) |
| Hard cut to black / chopped music at the end | picture and music ended separately | `fade_out` on the last shot: the score fades with it and rings out |
| Whisper hears "subtitles by ..." in silence | Whisper invents stock phrases over noise | speech.py filters them and marks unstable hits; keep only stable ones the picture supports |
| `ffprobe` value has a trailing comma / two lines | csv output of multiple streams | common.probe() parses JSON |
| transformers: `torch_dtype` deprecated; OWLv2 post-processing renamed | transformers 5 | the scripts use `dtype` (falling back) and `post_process_grounded_object_detection(..., text_labels=...)` |
| OpenCV 5: positional args rejected (`fastNlMeansDenoising`) | API change | keyword arguments |
| ffmpeg has no `subtitles`/`ass`/`drawtext` filter | Homebrew ffmpeg built without libass/freetype | the scripts draw text with PIL (better typography anyway) |
| `timeout: command not found`, `== not found` in zsh | macOS shell quirks | no `timeout` on macOS; quote strings that start with `=` in zsh; zsh does not word-split `$VAR` |
| A render was fine at half size, odd at 4K | preview hides detail; fonts and strokes scale | check one full-size frame (`--frames` without `--preview`) before the final |
| Out of disk mid-render | 4K intermediates are large | `df -h` before rendering; 4K masters are ~5 MB/s |
| Files vanished from /tmp | the system cleans it | keep projects in a permanent folder |
