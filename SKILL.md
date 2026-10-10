---
name: footage-to-vlog
description: >-
  Edit raw footage into a finished short video with code, no editing app: story and hook, cuts on a musical bar
  grid, vertical 9:16 and horizontal 16:9 renders that never crop the subject (letterbox over blur, rotated top-down
  drone shots), underwater and phone-HDR colour fixes, an original synthesised score that goes muffled under water,
  narration in the user's own cloned voice checked word by word with Whisper, burned subtitles, a loudness-checked
  mix, covers and exports for Xiaohongshu, Douyin, YouTube, X and Reels. Use it whenever someone wants a video made
  from their clips or photos (剪辑, 剪视频, 做个vlog, 出片, "edit my travel footage", "make a reel or short from
  these", a trip, dive, drone flight or astrophotography night turned into a film), wants a vertical cut of a
  landscape edit, wants music, voice-over or subtitles added, or wants a video readied for posting, even if they
  never say "vlog".
---

# Footage to vlog

You are the editor; the user is the director. You turn a folder of clips into a finished film with ffmpeg and the
Python scripts in this skill's `scripts/` folder, all driven by one edit list, `edl.json` (format:
references/edl.md). The user judges at four checkpoints - plan, narration script, preview, final - so show something
cheap at each one and change course on their word rather than after the whole film is rendered.

## What good looks like

Read references/editing.md before planning; these six decide most of the result:

1. **Open on the rarest thing in the footage**, ideally a transformation (a pull-out, a reveal). Never a selfie or
   "we got on the ferry".
2. **A theme, not a diary**: from above -> eye level -> turn around; above water -> under water -> on land.
3. **Dynamics and breathing room (留白)**: loud and quiet sections in picture and sound; quiet beats eased in, never a
   hard cut to black with the music chopped. Measured per section, not guessed.
4. **People**: their faces, their laughter, their real voices from the clips.
5. **Subjects dead centre and steady**, in both formats. A landscape shot is never cropped to 9:16.
6. **Little, plain narration** in the user's own voice, only with their consent; on-screen text is facts.

## Setup

- ffmpeg on PATH. Python 3.10+ with `numpy scipy opencv-python pillow fonttools`; for scanning, tracking and
  narration also `torch transformers f5-tts` (models download on first use, ~3 GB in all). Use the user's existing
  environment if it has these; otherwise make a venv in their home folder.
- macOS gets the most: Photos library export, HDR conversion (avconvert), VideoToolbox decoding, PingFang for
  Chinese. Elsewhere: install Noto Sans CJK for Chinese text and an ffmpeg with zscale for HDR.
- Bundled fonts (OFL): Jura Light (titles), DM Mono (data lines), Instrument Sans (Latin subtitles).
- Keep the project in a permanent folder, not /tmp: `project/src/` (originals, never modified), `project/sdr/`,
  `project/sheets/`, `project/edit/edl.json` - every script writes next to the EDL.

## Scripts

`S=<this skill's directory>/scripts`; run them with that Python. Each prints its usage with `-h`.

| step | script | does |
|---|---|---|
| ingest | `photos_export.py` | macOS Photos: list a date range, export originals |
| | `hdr_to_sdr.py` | phone HLG/PQ -> SDR BT.709 |
| | `inventory.py` | one line per clip: length, fps, HDR, sound, proxy traps |
| look | `contact_sheet.py` | timestamped thumbnail sheets (overview, or a fine strip of a window) |
| | `align_proxy.py` | DJI .LRF proxy offset, per window |
| | `scan.py` | CLIP: where the subject is, second by second |
| | `speech.py` | Whisper: who says / laughs what on camera, when |
| | `track.py` | per-frame target position (colour, brightness or OWLv2) for centred zooms |
| check | `common.py edl.json` | the timeline + every problem that would spoil a render |
| picture | `compose.py edl.json V\|H` | renders the film (`--frames`: framing sheet; `--preview`: half size) |
| sound | `score.py` | original score on the bar grid, per-section styles and loudness |
| | `beats.py` | an existing song: beats, bar starts, sections -> cut on its real bars |
| | `lyrics.py` | an existing song: lyric line start times -> cut on each sung line (`"lines": 1`) |
| | `narrate.py` | cloned-voice lines, each verified by Whisper (alone and over the music) |
| | `mix.py` | natural sound + narration + score, ducking, -16 LUFS, per-section report |
| deliver | `finish.py edl.json VIDEO` | masters, phone preview, X version, .srt, loudness, `--verify` |
| | `cover.py` | cover / thumbnail from a frame, quiet editorial type |

## Workflow

### 1. Ingest
Copy cards completely (main files and proxies), verify counts and sizes, tell the user when the card can come out.
From Photos: `photos_export.py list ...`, agree the selection, `export`. Convert HDR phone clips
(`hdr_to_sdr.py`). Run `inventory.py src/ sdr/ --json inventory.json`. Details and traps: references/ingest.md.

### 2. Look at everything
`contact_sheet.py src/ sdr/ --step 2 --out sheets/`, then read every sheet. For long footage, scan first
(`scan.py --pos ...`), and find people's voices (`speech.py`). Keep a log: clip, time, what happens, how rare,
who is in it, usable sound. Confirm in/out points on the main file, not the proxy.

### 3. Plan the story - checkpoint 1
Choose the hook (the rarest moment) and a theme; group the footage into 4-7 sections, each with one job; decide
where the quiet beat is and what the ending lands on; pick a tempo (84-96 BPM) and the length (45-90 s for
short-video platforms). Show the user a compact plan:

```
Hook (2 bars)    camels from straight above, 0.5x slow motion, pull out      intro swell
From above (8)   red cliffs, the 'eye', rock pools with you two, drone tilts up   full band, hit
Eye level (4)    waves on the rocks, the dog                                light, natural sound
...
Narration: 3 short lines (draft below) - or none?
```

Ask what to change. Ask whether they want narration, a title, which formats (vertical, horizontal, both) and which
platforms - unless they already said.

### 4. Write the EDL and check it
Shots on the bar grid, framing per format (`v` / `h`), zooms, grades, transitions, natural sound levels, sections,
music styles, lines. Then `python $S/common.py edl.json` until it reports no problems. For tracked zooms run
`track.py ... --sheet` and look at the sheet.

### 5. Framing check
`compose.py edl.json V --preview --frames` (and `H`): first / middle / last frame of every shot, with subtitles.
Read the sheet: subject centred? nothing important cropped? text readable? Fix the EDL and repeat (`--only ROLE`
re-checks one shot). It is quick - seconds for 4K sources, a minute or two for 8K.

### 6. Score - or the user's song
`score.py edl.json` - prints the loudness of each section; the shape must match the plan (references/sound.md:
styles, chords, writing a tune, under water, fx). Run it before the narration so narrate.py can test each take
over the music. If the user wants a particular song, cut to it instead: get a DRM-free file from them,
`beats.py song.m4a`, choose the stretch, and set `"music": {"file", "start_bar"}` in the EDL so every cut lands on
the song's own bar lines (sound.md, "Cutting to an existing song" - including the rights question).

### 7. Narration (only if wanted) - checkpoint 2
Consent: clone only the voice of the person asking, from their own recording. Get a 20-30 s recording, then
`narrate.py --prepare-ref rec.m4a --out voice/ref.wav` and have them confirm the transcript word for word. Write
3-8 plain lines (one idea each, for the ear), show them, wait for an OK, then `narrate.py edl.json --lang zh`.
Lines that never come back right get reworded (sound.md lists real homophone traps).

### 8. Mix
If narration was generated, re-run `score.py` first (it then thins the melody under the real line lengths). Then
`mix.py edl.json --lang zh` (no narration: no `--lang`; it writes mix.wav). Read the report: per-section loudness
spread 5+ LU, limiter under ~4 dB.

### 9. Preview - checkpoint 3
`compose.py edl.json V --preview` prints the file it wrote; pass that to `finish.py edl.json <file> --verify`. It
writes `*_preview.mp4` and `*_preview_phone.mp4` (under 28 MB) - preview names never overwrite a master - and
Whisper-checks every narration line, and every on-camera speech window tagged with its words, in the final mix.
Run the self-review below, then send the phone file to the user (use the host's file-sending tool if there is one)
with two or three sentences on what you did and what you are unsure about. Iterate on their notes.

### 10. Final
Full-size renders (`compose.py edl.json V`, `H`; minutes at 4K - run them in the background), then
`finish.py ... --targets master,phone,x --verify --chapters`. Check one full-size frame per format by eye.

### 11. Cover, copy, posting - checkpoint 4
`cover.py` variants (2-3), title options only if asked (the user usually writes the title), body text and topics,
the AI disclosure (cloned voice). Specs and conventions: references/platforms.md. Never publish or click a publish
button without the user's explicit OK.

## Iterating on feedback

Feedback arrives as feelings ("太平了", "有点突兀", "faces are missing"). Translate it into the principle behind it
(references/editing.md has a table of real cases), change the EDL, re-run only what depends on the change
(picture-only: compose + finish; timing: score + narrate check + mix too), keep the previous version's files
(`name` -> `name_v2`), and say in one line what changed and why. Note durable preferences (style, pacing, type) for
the next film.

## Before you show anything

- [ ] Would a stranger keep watching after 2 seconds?
- [ ] Theme or diary? Where is the quiet beat? Section spread 5+ LU in the mix report?
- [ ] People's faces and voices in it?
- [ ] Every subject centred and steady, nothing cropped in 9:16, no stranger's face, no repeated moment?
- [ ] Every transition motivated; no hard cut to black; the ending fades picture and music together?
- [ ] `finish.py --verify`: every narration line (and tagged on-camera speech) heard right in the final mix?
- [ ] Sound from the first frame; no two near-identical shots back to back?
- [ ] No glyph warnings; subtitles readable on the brightest frame; captions factual; no unrequested title card?

## Reference files

| file | read it when |
|---|---|
| references/editing.md | planning the story; reviewing a cut; translating feedback |
| references/edl.md | writing or changing edl.json (every field, with examples) |
| references/ingest.md | copying cards, Photos, HDR, proxies, scanning, tracking, finding speech |
| references/sound.md | score styles and harmony, under water, natural sound, voice cloning, mix targets |
| references/platforms.md | exports per platform, covers, titles and copy, AI disclosure, posting |
| references/troubleshooting.md | something looks or sounds wrong |
| examples/edl.example.json | a complete 70 s film to start from (its in-points belong to its own footage: pick yours from the sheets) |
