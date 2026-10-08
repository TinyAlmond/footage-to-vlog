# Ingest and analysis: getting the footage, seeing everything, finding the moments

## Contents
- [Copying from cards and cameras](#copying-from-cards-and-cameras)
- [The macOS Photos library](#the-macos-photos-library)
- [Phone HDR](#phone-hdr)
- [Proxies (DJI .LRF) and their traps](#proxies-dji-lrf-and-their-traps)
- [Seeing everything: inventory and contact sheets](#seeing-everything-inventory-and-contact-sheets)
- [Finding subjects with CLIP](#finding-subjects-with-clip)
- [Tracking a subject](#tracking-a-subject)
- [Finding speech and laughter](#finding-speech-and-laughter)

## Copying from cards and cameras

1. Copy everything (main files and proxies) to a permanent local folder - not /tmp, which the system may clear.
   Check free space first: the footage plus about the same again for renders.
2. Verify: same file count and the same byte size for every file (`cmp` or sizes from `ls -l`).
3. Tell the user exactly when the card can be removed ("all 54 files copied and size-checked - you can unplug it").
4. Never delete anything from the card.

Eject-safe layout: `project/src/` (originals, never modified), `project/sdr/` (converted phone clips),
`project/edit/` (edl.json and everything generated).

## The macOS Photos library

`scripts/photos_export.py list --since YYYY-MM-DD [--until ...] --kind video --orient landscape --json list.json`
reads every item's name, date and size in a few bulk Apple events (fast even with 30,000 items). Review the list
with the user (which days, which trip), then `photos_export.py export --json list.json --to src/` exports the
originals. Items stored only in iCloud download first (slow). The first run asks the user to allow automation of
Photos (System Settings > Privacy & Security > Automation).

Photos dates are when the item was taken; a phone's clock and a drone's clock can disagree by hours (time zones):
group by place and content, not by timestamps alone.

## Phone HDR

iPhones record HLG HDR by default (`inventory.py` flags it). Edited as-is, those clips look flat and grey next to
SDR footage. Convert first: `scripts/hdr_to_sdr.py clips... --out sdr/` (macOS avconvert: Apple's own tone
mapping, same as Photos' export; elsewhere ffmpeg zscale + tonemap). Use the SDR copies in the EDL.

## Proxies (DJI .LRF) and their traps

DJI cameras and drones record a small proxy (.LRF) beside each clip. It decodes 20-50x faster than 4K/8K, so use it
for contact sheets and scans - but never trust its timing blindly:

- The main file can be **4-13 s shorter** than its proxy. In/out points read off a proxy past the main file's end
  silently produce short shots. `common.py` checks every shot against the main file's real length.
- The proxy can be **offset** by seconds, and the offset can **change inside a clip** (0 s for the first half,
  +3.2 s after a dropout). `scripts/align_proxy.py clip.MP4` measures it per window (motion signatures).
  `scan.py --align` maps proxy times back to main-file times.
- Before committing an in-point, confirm it on the main file: `contact_sheet.py clip.MP4 --main --t0 A --t1 B
  --step 0.5`.

## Seeing everything: inventory and contact sheets

```bash
python scripts/inventory.py src/ --json inventory.json      # one line per clip: length, size, fps, HDR, sound, notes
python scripts/contact_sheet.py src/ --step 2 --out sheets/ # one thumbnail every 2 s, per clip
```

Look at **every** sheet before planning (read the images; long clips have several pages). While looking, write a
short log: clip, time, what happens, how rare / how good, people visible, usable sound. The rare moments are often
seconds long inside long clips (a whale blow at 2 s of a 3 s phone clip; one fish crossing close to the lens in a
23-minute snorkel recording).

For a promising window, a fine strip: `contact_sheet.py clip --t0 60 --t1 75 --step 0.5`.

Inventory notes to act on:
- `60 fps`: 0.5x slow motion is clean (every frame used).
- `HLG HDR`: convert before editing.
- `proxy runs Ns longer`: check offsets before using proxy times.
- `portrait`: will `fill` the vertical canvas; in a horizontal film it is pillarboxed (`fit`).

## Finding subjects with CLIP

For long footage (snorkelling, safaris, dashcam-style walks), scan with CLIP before looking at sheets:

```bash
python scripts/scan.py src/ --pos "a photo of a fish underwater" --pos "a school of small fish" --fps 1 --align
```

- `--pos`: 2-4 phrasings of the subject ("a quokka", "a small furry animal on the ground"). `--neg`: what the
  footage mostly is (defaults cover sky, ground, water surface, blur, darkness); add scene-specific negatives
  ("seaweed underwater", "a sandy sea floor", "a person snorkeling") - they sharpen the scores a lot.
- It prints the best windows per clip (sustained runs first) and writes scan.csv. Look at those windows on fine
  strips; CLIP finds candidates, your eyes choose.
- Model: openai/clip-vit-base-patch16 (downloads once). 50 minutes of footage at 1 fps takes a few minutes on Apple
  silicon.

## Tracking a subject

A push-in or pull-out should keep the subject dead centre: `scripts/track.py edl.json ROLE ...` writes its path to
tracks.json, and the shot uses `"centre": "track"`.

| tracker | when | example |
|---|---|---|
| `--color H0-H1[,H0-H1]/SMIN/VMIN` | the subject has a colour nothing else has | red camel blankets on sand: `0-12,170-180/110/90` |
| `--bright X,Y` | a bright compact thing: moon, sun, a lamp | the full moon over a dusk beach, seed at its first-frame position |
| `--owl "query"` | anything nameable | `"a quokka"`, `"a dolphin"`, `"a person's face"` |

Always pass `--sheet` and look at track_ROLE.jpg: the yellow cross must sit on the subject in every sample. A seed
too far from the moon locks onto a building; a colour range too wide catches the sunset.

Pick windows where the camera itself is steady: no tracker rescues a shot where the drone drifts the subject out of
frame. A 0.5x slow-motion stretch of a steady moment usually beats a longer shaky one.

## Finding speech and laughter

The camera sound of people - a laugh, a gasp at a whale, "so cute!" - is the most human part of a film.

```bash
python scripts/speech.py src/ --lang auto      # every stretch Whisper hears as speech, per clip, with times
```

Whisper invents text over wind, engines and silence (stock phrases like "thanks for watching", 字幕志愿者, endless
"oh, oh, oh"). speech.py drops the known inventions, trims loops, and re-transcribes every hit from two shifted
windows: a real voice comes back the same (`stable`), noise turns into different words (`UNSTABLE` - "这只狗狗" in
one window, "真可惡" / "好酷哦" in the others). Keep stable hits that the picture supports (a fine contact sheet at that
time: people there, mouths moving, reacting); when a shot depends on one, ask the user to listen if they can. Mark
the keepers as `speech` windows on the shot, with their words for the final check.
