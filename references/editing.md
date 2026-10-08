# Editing: what makes a short film work

These principles come from real review rounds - a professional's critique and the owner's own notes on several
travel and astrophotography films. The quoted feedback is what people actually said; the rule after it is what
changed. Read this before planning the story, and again before showing a cut.

## Contents
- [The six that matter most](#the-six-that-matter-most)
- [Structure and pacing](#structure-and-pacing)
- [Picture](#picture)
- [Vertical (9:16) from landscape footage](#vertical-916-from-landscape-footage)
- [Text and narration](#text-and-narration)
- [Feedback that changed the rules](#feedback-that-changed-the-rules)
- [Self-review before showing a cut](#self-review-before-showing-a-cut)

## The six that matter most

1. **Open on the rarest thing you have.** The first 1-3 seconds decide whether anyone stays. Rare footage is the
   asset ("胜在稀有" - its strength is rarity): a whale blowing, a camel train from straight above, a nebula building
   up out of noise. A transformation (a pull-out, a reveal, a stack growing) beats a static beauty shot. Never open on
   a selfie or on "we got on the ferry".
2. **A theme, not a diary.** Chronological order ("then we..., then we...") is the default failure ("流水账"). Order
   by point of view (from above -> eye level -> turn around), by element (above water -> under water -> on land),
   or by a motif. Use the clock only when the day itself has an arc.
3. **Dynamics.** Plan loud and quiet sections in picture and sound: a full-band section, a thinner one with natural
   sound, a quiet beat, a lift for the ending. "太平了" (too flat) means every section had the same energy. Measure
   it: the mix report should show a spread of 5+ LU between sections.
4. **Room to breathe (留白).** A held shot with the music thinned to a pad and no narration, eased in over 1-2 s.
   Never a hard cut to black with the music chopped ("太突兀" - too abrupt): fade picture and music together and let
   the reverb ring.
5. **People.** Faces, hands, laughter - the people who were there. A film of scenery alone feels empty; the owner
   noticed at once that "our faces" were missing. Real sound of people (a laugh, a "wow", "so cute!") is gold:
   find it with Whisper on the clips' audio and keep it (`speech` windows).
6. **Subjects dead centre and steady.** One framing per moment: cutting between three reframes of the same scene
   reads as chaos. Zoom on a tracked target, never let a subject drift to the edge, never jitter.

## Structure and pacing

- **Length**: 45-90 s for short-video platforms; 2-4 min only when there is that much strong material. A short
  brief (15-30 s) is hook + one idea + the ending: 2-3 sections, 6-10 shots, no quiet beat longer than a bar.
- **Grid**: cut on bar lines of the score (90 BPM: a bar is 2.67 s). Most shots 1-2 bars; the hook and the ending
  2-3 bars; a slow-motion moment as long as it stays interesting. The beat makes even simple cuts feel intended.
- **Sections**: 4-7, each with one job (hook, establish, the main event, people, a quiet beat, the payoff, the end).
- **Ending**: land on an image that means something - the result, the people, a callback to the opening. The last
  shot holds longest; the last chord rings out under a fade.
- **Cut subject-less footage**: transit, getting ready, empty water between fish. If a shot has no subject, it
  needs a reason (a breath, a reveal of scale).
- **Vary consecutive shots**: two similar shots in a row (same angle, same subject, same scale) read as a
  repeat. Alternate wide and close, high and low, still and moving.
- **Sound from the first frame**: a near-silent first second loses viewers before the hook lands; the score
  starts audible, and the first picture should read at phone size within a second (a tight start on a small
  subject, then pull out).
- **Celebrate**: don't narrate failures or obstacles ("叙事不用讲失败的东西") unless the user wants that story.

## Picture

- **Transitions are motivated by the action**: a whip pan when the story turns around; a dissolve between matching
  shapes (the round moon into a round nebula); a dip to black for going under water, night falling, a time jump.
  Avoid gimmicks: kaleidoscopes, blink cuts, wipes and plain slideshow dissolves between stills were all rejected
  ("太生硬", "太像PPT了").
- **Stills must move**: a slow push, a constant spin for astro images, parallax. A plain zoom on a photo is a slide.
  Between photos prefer a continuous motion (a shared centre, a spiral) over any cut.
- **Motion is constant and one-directional**: a rotation runs at one deg/s, one direction, for the whole film.
  Eased spins and reversals feel wrong ("有点难受").
- **Slow motion**: from high-frame-rate footage only (60 fps at 0.5x). 30 fps slowed down judders.
- **Colour**: convert phone HDR to SDR before anything (it looks grey next to SDR footage); grade underwater shots
  (they are grey-blue straight out of the camera - "水下太灰了"); keep the grade believable (partial levels).
- **Show nothing twice**: the same photo or the same moment repeated cheapens both.
- **Privacy**: crop or cut strangers' faces (children especially) and anything that shows a rule broken (touching
  or feeding wildlife).

## Vertical (9:16) from landscape footage

Cropping landscape footage to 9:16 keeps a third of the width: the fish swims out, the animal turns its head out of
frame, even with a subject tracker. The owner rejected tracked crops outright. Instead:

| shot | V framing |
|---|---|
| horizon / eye-level landscape | `fit`: the whole 16:9 picture in the middle, its own blur above and below; subtitles in the band below |
| top-down drone (nadir) | `rot`: turn it 90 deg - it has no "up", and the whole frame fills the screen |
| drone tilting up from nadir | `rot2fit`: the turn is animated as the camera tilts |
| portrait phone clip | `fill` |
| static subject, dead centre, nothing else important | `fill` with `centre` (rarely) |

Render both formats from the same EDL; the horizontal one is the 16:9 master for YouTube. If the footage is
vertical-native and the user wants 16:9, the same logic runs the other way (`fit` = pillarbox).

## Text and narration

- **No title card unless asked.** If wanted: Jura Light capitals with wide tracking, a DM Mono data line, over the
  picture, fading in and out.
- **Captions are facts**: names, places, numbers, dates, counters. No lyrical or sentimental lines ("不要抒情文案").
- **Narration only if wanted, and little of it**: 3-8 lines for a minute, one idea each, in plain spoken words - what
  you see and one feeling, like telling a friend. Lines that sound written by an AI ("那天，我好像也是。" -
  "that day, I think I was too") were rejected outright; the plain earlier lines were kept.
- **Write for the ear**: short sentences; avoid near-homophones (鲸鱼/金鱼, 镜头/尽头, 静止/径直), rare names at the start
  of a line, digits. Whisper checks every line; when a line keeps failing, reword it.
- **Glyphs**: a Latin font cannot draw Chinese (it renders tofu boxes); Jura and DM Mono also lack ′ ″ (use ' ").
  The scripts warn about missing glyphs - read the warnings.

## Feedback that changed the rules

| what the reviewer said | what changed |
|---|---|
| "开幕雷击 + 流水账" (a cringe opening + a diary) | open on the rarest moment; structure by theme |
| "要有共鸣和留白 ... 太平了" (needs resonance and breathing room; too flat) | planned dynamics, measured per section; quiet beats; people |
| "多放一些动物/鱼，减少无焦点的过场" (more animals, fewer subject-less transitions) | CLIP scan for subjects; cut empty footage |
| "水下太灰了"; "变闷的感觉不够明显" (underwater too grey; the muffled sound not obvious enough) | the water grade; a steep 480 Hz low-pass, not a gentle 850 Hz one |
| "竖屏不行 ... 鱼、quokka 的脸都会跑出屏幕外" (vertical crop loses the subjects) | fit / rot / rot2fit, never a crop |
| "第4秒突兀，咔嚓黑屏后接标题" (a snap to black then a title) | the title over moving footage, dissolving in |
| "没有我们的脸了" (our faces are missing) | people shots back in |
| "别来这种太AI的话" (no AI-sounding lines) | plain narration |
| "18-30 s 很乱" (three framings of one scene) | one framing per moment |
| "像PPT" (stills that only zoom; blink cuts) | living stills, continuous hand-overs |
| "有点难受" (a spin that sped up and reversed) | constant speed, one direction |
| "太突兀" (hard cut to black, music chopped) | fade picture and music together |

## Self-review before showing a cut

Look at the frame-check sheet and the preview as the viewer would, then answer honestly:

- [ ] Would a stranger keep watching after 2 seconds? Is the opening the rarest thing in the footage?
- [ ] Is there a theme or arc, or is it a diary?
- [ ] Where are the quiet beats? Does the loudness report show real dynamics (5+ LU spread)?
- [ ] Are the people in it? Their faces, their voices?
- [ ] Is every subject centred and steady in both formats? Nothing important cropped in 9:16?
- [ ] Is every transition motivated? Any hard cut to black or chopped music?
- [ ] Any shot without a subject, any repeated moment, any stranger's face?
- [ ] Narration: few, plain, true lines; all heard correctly in the final mix (finish.py --verify)?
- [ ] Text: no tofu boxes, readable on the brightest background, nothing lyrical, no unrequested title card?
