# The edit list (edl.json)

One JSON file per film drives every script. Paths inside it are relative to the file (or absolute, `~` allowed); all
outputs land next to it (`out/`, `narration/`, `music.wav`, `mix_<lang>.wav`, `tracks.json`). JSON has no comments:
put your reasoning in `"note"` fields, which the scripts ignore. Run `python scripts/common.py edl.json` after every
change - it prints the timeline and every problem that would spoil a render.

## Contents
- [Top level](#top-level)
- [Shots](#shots) - timing, framing, zoom and tracking, stills, grade, transitions, sound
- [Narration lines, captions, titles](#narration-lines-captions-titles)
- [Music](#music)
- [A complete example](#a-complete-example)

## Top level

| key | default | meaning |
|---|---|---|
| `name` | `"video"` | output file names |
| `fps` | `"30000/1001"` | output frame rate (29.97). Every cut is rounded to a whole frame |
| `bpm`, `beats_per_bar` | `90`, `4` | the music grid the cuts sit on (one bar at 90 BPM = 2.67 s) |
| `canvas` | V 2160x3840, H 3840x2160 | `{"V": [w, h], "H": [w, h]}` to render at another size |
| `sources` | | `{"key": "path"}` - shots name their source by key |
| `shots` | | the film, in order |
| `lines` | | narration (cloned voice) + its subtitles |
| `captions`, `titles` | | on-screen text that is not narration |
| `subs` | | subtitle style: `size` (px at 4K), `y` (V: centre as a fraction of the height, 0.72), `bottom` (H: px from the bottom, 140), `plate` (0-1: a soft dark plate behind the text for bright scenes), `off` |
| `voice` | | `{"ref": "voice/ref.wav", "ref_text": "exact words", "speed": 0.9}` for narrate.py |
| `music` | | how the score plays each section (below) |
| `mix` | | `{"lufs": -16, "duck_db": 9, "speech_duck_db": 12, "ceiling": -1.5}` |

## Shots

```json
{"role": "hook", "sec": "hook", "src": "camels", "t_in": 72.3, "speed": 0.5, "bars": 2,
 "v": "rot", "zoom": [2.0, 1.15], "centre": "track", "lock": true, "note": "train from straight above, pull out"}
```

**Identity and timing**

| key | meaning |
|---|---|
| `role` | unique name of the shot (lines, captions, tracks refer to it) |
| `sec` | section name. Consecutive shots with the same `sec` form a section: the score's arrangement and the loudness report follow sections |
| `src` | a key of `sources`, or a path. Images (jpg/png/tif/webp) are stills |
| `t_in` | source in-point, seconds. Read it off the **main** file, not a proxy (see ingest.md) |
| `speed` | playback speed; `0.5` on 60 fps footage = clean 2x slow motion (every frame used). On 30 fps footage anything below 1 repeats frames |
| `bars` / `beats` / `dur` | length: bars or beats on the grid, or seconds (`dur`) when a shot must break the grid. Off-grid shots push later cuts off the bar lines (score.py warns) |
| `tail` | last shot only: seconds after its grid end (the ring-out) |

**Framing** - per output format: `"v"` for the vertical render, `"h"` for the horizontal one.

| mode | what it does | use it for |
|---|---|---|
| `fit` (`box`) | whole frame in the middle, over a blurred, darkened copy of itself | landscape footage in V (the default), portrait footage in H |
| `fill` (`crop`) | scale to cover the canvas, crop the rest | footage whose shape matches the canvas (the default then). Landscape -> V `fill` crops two thirds away: only for a static, centred subject |
| `rot` | turned 90 deg so the long side runs down the screen | top-down (nadir) drone shots: no "up" in the picture, so the whole frame fills 9:16 with nothing cropped |
| `rot2fit` (`rot2box`) | starts as `rot`, turns upright into `fit` between `morph: [a, b]` - seconds from the shot's start on the output timeline (after `speed`) | a drone tilting up from nadir to the horizon |

`rot_dir`: `"ccw"` (default) or `"cw"` - pick the direction in which motion in the shot reads naturally (people
walking up the screen, the coast on the left).

**Zoom and centring**

| key | meaning |
|---|---|
| `zoom` | `[z0, z1]`, eased over the shot (1 = the framing mode's own scale). Push in on a reveal, pull out from a detail |
| `centre` | `[x, y]` in source pixels, or `"track"` (tracks.json from track.py) |
| `lock` | `true`: stay on the target at every zoom. Otherwise the centre eases from the frame centre to the target as the zoom grows |

Zooming in `fill` with a `centre` also crops strangers (and their children) out of a frame - do it rather than show
faces of people who did not agree to be filmed.

**Stills** (photos, astro images, posters)

| key | meaning |
|---|---|
| `fit` | `"cover"` (default), `"contain"`, or a number: the scale at 4K |
| `centre` | the image point that sits dead centre (the nebula, the face) |
| `zoom` | `[z0, z1]` as above |
| `spin` | deg/s, constant, clockwise if positive. One speed and one direction for the whole film |
| `angle` | starting rotation (deg) |
| `feather` | edge fade as a fraction of the size (0.07 when not covering), or `"round"`: a soft disc, so a spinning image shows no turning corners |

A still must move (a slow push, a constant spin); a plain zoom on a photo reads as a slideshow.

**Grade**

`"grade": "water"` - underwater footage: per-channel levels from the shot's own 0.5 / 99.5 percentiles (haze off, the
lost red partly back), saturation 1.3 (luma kept), a gentle S-curve. Decoded at 16 bit so it does not band.
A dict tunes it: `{"preset": "water", "sat": 1.2}`, or builds another: `levels` [lo%, hi%], `white_keep` (0-1, how
far the white point moves: 0.7 for water; 1 stretches fully and looks fake), `black_keep`, `sat`, `curve` (S-curve
amount, 0.032), `exposure` (stops), `wb` ([r, g, b] gains).

**Transitions** - on the incoming shot: `"trans_in": [...]`

| value | use |
|---|---|
| `["dissolve", 1.6]` | matching shapes (moon -> nebula), time passing |
| `["dip", 0.7]` | through black: going under water, falling asleep, a new day |
| `["whip", 0.4, "left"]` | a fast pan with motion blur: "turning around" (the score adds a whoosh) |

The transition straddles the cut (half before, half after), so both shots need frames beyond their edges; a shot
cannot be shorter than its two transitions. `fade_in` / `fade_out` (seconds) fade a shot from / to black - the last
shot's `fade_out` also sets how the music ends.

**Sound**

| key | meaning |
|---|---|
| `natural` | the shot's own sound at this level (LUFS, typically -24 to -31). Leave it out for silence (drones have none) |
| `hpf` | high-pass in Hz (180 for wind) |
| `speech` | `[[a, b], ...]` seconds into the shot where people talk on camera: the words go to -20 LUFS (just under the narration), the rest of the shot keeps its `natural` level, the music ducks 12 dB under them. `[a, b, "拍到了"]` also lets `finish.py --verify` check the words |

## Narration lines, captions, titles

```json
"lines": [{"id": "1", "shot": "a_eye", "at": 0.55, "text": "这里的土是红色的，海水是蓝绿色的。",
           "must": ["红色", "海水"]}],
"captions": [{"shot": "seal", "at": 1.8, "dur": 3.0, "text": "Sea lion · Neophoca cinerea"}],
"titles": [{"shot": "open", "at": 4.5, "dur": 3.4, "title": "The Red Coast", "sub": "12 · V · 2025"}]
```

- `lines`: `at` = seconds after the shot starts. `text` can be `{"zh": "...", "en": "..."}` for several language
  versions (`--lang` picks). `must`: words the Whisper check must hear (names, the key noun), per language if needed.
  `tts`: what to send to the TTS when the spelling should differ from the subtitle (a phonetic hint). Leave >= 0.3 s
  between lines; common.py warns.
- `captions`: subtitles that are not spoken - names, numbers, places. Factual, never lyrical.
- `titles`: Jura Light in capitals, wide tracking, with an optional DM Mono `sub` line (`y` fraction of the height,
  `size`, `fade`, `"case": "as-is"` to keep lower case). No title card unless the user wants one. The bundled fonts
  are Latin-only: Chinese titles fall back to the CJK font.

## Music

```json
"music": {"key": "E", "seed": 7,
          "sections": {"hook":  {"style": "intro",  "chords": ["C#m9", "Aadd9"], "lufs": -19},
                       "above": {"style": "groove", "chords": ["E", "B/D#", "C#m", "A"], "hit": true},
                       "water": {"style": "light", "uw": true},
                       "moon":  {"style": "ambient", "ramp": 0.5},
                       "end":   {"style": "outro", "chords": ["Aadd9", "E", "E"]}}}
```

Section keys are the shots' `sec` names. Styles, chords, tunes and fx are described in sound.md.

## A complete example

`examples/edl.example.json` - a 70 s travel film: a top-down hook with a tracked pull-out, a rotated aerial section,
a drone tilt-up turning into the letterbox, eye-level shots with natural sound, a sunset, a whip pan to the full moon
and a dissolve into an astro photo; three narration lines; a seven-section score.
