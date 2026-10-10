# Sound: score, natural sound, narration, mix

## Contents
- [The score (score.py)](#the-score-scorepy)
- [Natural sound](#natural-sound)
- [Narration in the user's cloned voice (narrate.py)](#narration-in-the-users-cloned-voice-narratepy)
- [The mix (mix.py) and its checks](#the-mix-mixpy-and-its-checks)
- [Cutting to an existing song](#cutting-to-an-existing-song)

## The score (score.py)

An original score synthesised in Python on the edit's own bar grid: no licence questions, every hit lands on a cut,
and each section gets the energy the story needs. Instruments: detuned-saw pads (low-passed), plucked arpeggio,
kalimba lead, sine bass, kick, clap, shaker; noise sweeps for risers and whooshes; convolution reverb (a long one for
ambient sections).

**Styles** (per section, in `music.sections.<sec>.style`):

| style | sounds like | default target |
|---|---|---|
| `intro` | pad swell, an arpeggio that grows and brightens | -19 LUFS |
| `groove` | full band: kick 1 & 3, clap 2 & 4, 16th shaker, pumping bass, arpeggio, kalimba tune | -14.5 |
| `light` | no kick: soft shaker, half-note bass, sparser tune - room for natural sound | -19 |
| `halftime` | kick on 1, clap on 3; tune and arpeggio an octave up (golden hour, slowing down) | -16.5 |
| `breath` | pad and a few notes: the quiet beat (留白) | -23 |
| `ambient` | pad, low bass, a few high notes, long reverb (night, awe) | -24.5 |
| `outro` | ambient + a slow arpeggio; the last chord rings with the picture's fade | -22.5 |

Targets are relative: after the sections are set, the whole score is normalised and the mix sets the final level.
Override any of them (`"lufs": -17`). `"ramp"`: seconds the loudness change takes going into the section (0.04 for a
hit, 1-1.6 s to sink into a breath). `"hit": true`: a riser in the bar before, then a boom and a crash on the downbeat
(automatic for a `groove` that follows an `intro`, `breath` or `ambient`).

**Under water** (`"uw": true` on a section): the same music heard from below - a steep zero-phase 480 Hz low-pass
(48 dB/oct), a +4 dB bump at 250 Hz, a 3.6 s wet reverb, slow pitch and level wobble, 3 dB down; exhaled-bubble
clusters, a plunge at the entry and a swish at the exit. A gentle 850 Hz low-pass does not read as under water.

**Harmony**: `"key"` (`"E"`, `"F#"`, `"Bb"`, `"Am"`) and per section `"chords"`, one per bar, cycled. Symbols: root
A-G with # or b, quality `''`, `m`, `7`, `maj7`, `m7`, `6`, `m6`, `sus2`, `sus4`, `add9`, `madd9`, `9`, `maj9`, `m9`,
`dim`, `aug`, `5`, `m7b5`, optional `/bass`. Without chords each style uses a default progression in the key.
Progressions that work (major key, degrees -> in E):

| mood | progression | in E |
|---|---|---|
| warm, open | I - V/7 - vi - IV | E - B/D# - C#m - A |
| wistful intro | vi9 - IVadd9 | C#m9 - Aadd9 |
| lifting | IV - V - iii - vi | A - B - G#m - C#m |
| golden hour | IV - I/3 - ii - V | A - E/G# - F#m - B |
| night, awe | vi - IV - V | C#m - A - B |
| ending | IVadd9 - I - I | Aadd9 - E - E |

Pick a key that sits well for the lead (D, E, F major are comfortable); 84-96 BPM for travel films, 76-84 for a
gentle, drum-less score (piano/strings feel).

**The tune**: without one, a melody is generated per section from the chords (seeded: change `"seed"` for another;
chord tones on strong beats, scale steps between, two-bar phrases, a long note on the root or third at the section's
end). Its notes drop 10 dB under narration. For the sections that matter, write it by hand:
`"tune": {"0": [[0, "E5", 1], [1, "D#5", 0.5], [1.5, "E5", 0.5], [2, "F#5", 1], [3, "G#5", 1]], "1": [...]}` -
bar (from the section start) -> [beat, note, length in beats]; notes as names or MIDI numbers.
`"tune_octave": 12` lifts a section.

**Sound design at the cuts** (automatic): a whoosh across the stereo field on whip pans, a sweep over a rot2fit
turn, a shimmer into a long dissolve that lands on an ambient/outro section. Add more with
`"fx": [{"type": "riser"|"boom"|"crash"|"whoosh"|"shimmer"|"sweep", "shot": "role", "at": 0.0, "dur": 2.0}]`.

**Ending**: the music fades with the last shot's `fade_out` (+0.3 s), the reverb rings; it swells in from silence
when the film opens on an intro.

score.py prints the loudness of every section: check the shape matches the plan before going on.

## Natural sound

The camera's own sound makes footage feel real - waves, wind in the dunes, a crowd at sunset, a laugh.

- Level it **per shot** (`"natural": -26`): devices differ wildly (a phone and an action camera were 17 dB apart).
  -24 to -31 LUFS sits under the music; louder for a moment that should be heard.
- Wind: `"hpf": 180`. Gusts and bumps are held 15 dB above the shot's level automatically.
- Under water the action camera records mostly rumble - leave it out (`natural` absent) and let the muffled score
  carry the scene.
- People talking on camera: `"speech": [[a, b], ...]` (seconds into the shot) sets their words to -20 LUFS, just
  under the narration, while the rest of the shot keeps its `natural` level; the music ducks 12 dB under them
  (`speech_duck_db`: on-camera speech is rougher than the narration and loses its consonants first). Add the words,
  `[a, b, "拍到了"]`, and `finish.py --verify` checks them in the final mix. Find those moments with `speech.py` - they
  are often the best sound in the film.
- Drone footage has no sound; a silent aerial under the score is normal.

## Narration in the user's cloned voice (narrate.py)

**Consent first.** Clone only the voice of the person asking, from a recording they made for this purpose. Never
clone a friend, a family member or a public figure from found audio. Platforms ask you to declare synthetic voices:
tick "AI-generated content" / "altered or synthetic content" when posting (platforms.md).

**The reference recording** - ask the user to:
- read 20-30 s of ordinary sentences in a quiet room, in their normal speaking voice, phone close to the mouth,
  natural pauses between sentences;
- send the file (m4a / wav).

Then `python scripts/narrate.py --prepare-ref recording.m4a --out voice/ref.wav --lang zh` cuts the longest stretch
of <= 11.5 s that starts and ends at a pause and prints Whisper's transcript. **Have the user confirm or correct the
transcript word for word** - Whisper mishears (it wrote 羊又哭了 for 杨柳枯了). F5-TTS clips the reference at ~12 s:
a longer reference no longer matches its transcript, and the output races and garbles.

**Writing the lines**: see editing.md (few, plain, for the ear). Show the script to the user before generating.
Put the words that must survive in `"must"` (place names, the animal, the key noun).

**Generation**: F5-TTS (`F5TTS_v1_Base`, zero-shot), speed 0.9 (calmer than the default), each line retried over
seeds until Whisper hears it right - in the clean take and again with music.wav playing under it, ducked as in the
mix. Run the score before the narration when you can, so that second check happens. Results go to
`narration/<lang>/lines.json` (seed, duration, what Whisper heard).

**When a line keeps failing**, the TTS is not going to get it: reword. Real cases:

| intended | heard | a rewording that avoids it |
|---|---|---|
| 鲸鱼 (whale) | 金鱼 (goldfish) | 喷水的鲸 / 一头鲸 |
| 镜头 (lens) | 尽头 (the end) | 相机 |
| 海是蓝绿色的 | 还是蓝绿色的 | 海水是蓝绿色的 |
| 径直走过来 | 静止走过来 | 直接走过来 |
| 刚上岸 | 刚上完 | 一上岛 |

Numbers: write them as words (九月, not 9月). English names a model may not know (quokka): try spellings in
`"tts"` (`"kwokka"`) and keep the real spelling in `"text"` for the subtitle.

**Other languages**: the same Chinese reference speaks English (and other languages) in the same voice - give
`"text": {"zh": "...", "en": "..."}` and run with `--lang en`. Keep the English lines as plain as the Chinese.

**Licences**: F5-TTS code is MIT but the released weights are CC-BY-NC 4.0 - fine for personal and non-commercial
videos; for paid or sponsored work, use a commercially licensed TTS. Whisper, CLIP: MIT; OWLv2: Apache-2.0.

## The mix (mix.py) and its checks

- Bed = score + natural sound; narration on top at -18 LUFS (narrate.py levels each line).
- The music ducks 9 dB under narration and 12 dB under on-camera speech (120 ms early, smooth); natural sound ducks
  under narration only.
- Final: -16 LUFS integrated, true peak <= -1.5 dBFS (a 4x oversampled lookahead limiter): loud enough on a phone
  with headroom left for the dynamics. Platforms that normalise (YouTube plays at about -14) adjust it slightly.
- **The report**: loudness per section. The designed shape must survive: if all sections read within ~4 LU, it will
  sound flat - widen the score targets. A limiter working > 4 dB means one shot's natural sound is far too loud.
- **finish.py --verify**: Whisper transcribes every narration line from the final file. A line that is fine alone
  but lost in the mix means the music under it is too busy: deepen `duck_db` (12), move the line (`at`) off a hit,
  re-run narrate.py (it will pick a take that survives the music), or quieten that section. Whisper is at its
  margin on a two- or three-syllable exclamation (拍到了 heard as 开到了 after AAC encoding, though the WAV mix reads
  right): the check is lenient there - if it still flags one, compare with the clip's own sound before changing
  anything.

## Cutting to an existing song

When the user wants a particular song, the film is cut to that song's own bars:

1. **The file**: a DRM-free copy the user owns (bought from the iTunes Store / Amazon / Bandcamp, their own track).
   Streaming downloads (Apple Music, QQ 音乐 .mflac/.mgg, Spotify) are encrypted and will not decode - and never
   download songs from unofficial sites.
2. **Analyse it**: `python scripts/beats.py song.m4a` -> beats.json + beats.png. Beats and bar starts come from
   beat_this (`pip install beat_this`), each beat snapped to the start of its attack; a song recorded to a click
   gets a constant-tempo grid fitted to the beats (the printout says whether it held). Look at beats.png: bar
   numbers, loudness, sections (blue loud = chorus, brown quiet = verse / intro).
3. **Choose the stretch**: 45-90 s for short-video platforms - often the last chorus into the outro (the song's own
   ending is the best ending), or a verse into the first chorus. Put the strongest images on the chorus downbeats,
   the quiet beats (留白) on the verse; change shots on bar lines, big changes on phrase starts (every 4 or 8 bars).
4. **The EDL**: `"music": {"file": "song.m4a", "beats": "beats.json", "start_bar": 52}` (or `"start": seconds`;
   optional `"fade_in"`, `"fade_out"`). Shots then count the song's real bars and beats (`"bars": 2` runs to the
   second bar line after the cut), so the cuts stay on the music even where the tempo drifts. score.py is not used;
   mix.py plays the song from that bar under the natural sound (ducking under voices as usual) and fades it out
   with the picture. Narration over a song with vocals clashes: prefer none, or only over an instrumental stretch.
   **Cutting on the lyrics** (each new sung line brings the next shot - what people mean by "卡点" on a vocal song):
   `python scripts/lyrics.py song.wav --from <start s> --gap 0.35` writes lyrics/lines.json (Whisper word times in
   overlapping 12 s windows, each line start moved to the strongest vocal-band onset nearby, snapped to a beat within
   0.12 s; pickups sung before the beat keep their own onset). Treat it as a draft: Whisper word times drift by
   0.2-0.9 s and it merges lines sung without a breath. Where two passes disagree, decide on the vocal energy (HPSS
   harmonic part, 250-3000 Hz): the line starts where the level rises after a dip. Edit the file by hand, set
   `"music": {..., "lines": "lyrics/lines.json"}` and give shots `"lines": 1` (to the next line start); long lines
   need long clips (check source length / speed) and a tracked subject can walk out of a longer shot - re-run
   track.py and look at the sheet. Use hard cuts on lyric lines (`"trans_in": ["cut"]`): a zoom or dissolve is centred on the cut, so a 0.8 s one starts changing the picture 0.4 s before the singer does. Check the render with ffmpeg `scdet` against the expected cut times. Show the user line numbers and times, not the lyrics.
5. **Rights**: the user needs the right to use the song where they post. YouTube Content ID will claim a commercial
   song (ads go to the rights holder, some countries block it). On Xiaohongshu / Douyin / Instagram / TikTok the
   safe route is the platform's own music library: export a version without music (`mix.py edl.json --no-music
   --out mix_nomusic.wav`, then finish.py with `--audio mix_nomusic.wav --name ..._nomusic`) and add the same song
   in the app when posting, starting it at the song time where the film's cut starts. Keep the version with the
   song for the user's own archive.
