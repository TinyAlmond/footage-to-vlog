# Platforms: exports, covers, copy, posting

Limits change; when one matters (length, size), check the platform's current upload page. finish.py strips all
metadata from the deliverables (GPS position, device names) - keep it that way.

## Contents
- [Exports](#exports)
- [Covers and thumbnails](#covers-and-thumbnails)
- [Titles and copy](#titles-and-copy)
- [AI disclosure](#ai-disclosure)
- [Posting](#posting)

## Exports

| platform | file | notes |
|---|---|---|
| Xiaohongshu 小红书 | V master, 2160x3840 H.264 + AAC | upload the 4K: it looks visibly better in the feed than 1080p. Cover 3:4 |
| Douyin 抖音 / TikTok | V master (or 1080x1920) | keep subtitles above the bottom quarter and clear of the right-hand buttons |
| Instagram Reels | V, 1080x1920 is plenty | same safe zones as TikTok |
| YouTube | H master, 3840x2160, AAC 384k | upload the clean master + the .srt as captions (or the burned-in version without an srt). Shorts: the V master, up to 3 min |
| Bilibili B站 | H master (V accepted) | 4K is shown to members; AI declaration available |
| X / Twitter | `finish.py --targets x`: 1080p, AAC 192k | <= 2:20 for most accounts, <= 512 MB |
| review on a phone | `_phone.mp4` (< 28 MB) | send it for feedback before the final |

Burned-in subtitles are what most short-video viewers see (sound off). For YouTube, prefer the clean picture plus
the .srt: captions can be translated and switched off.

## Covers and thumbnails

`scripts/cover.py` makes a cover from a frame of the film. The default look is restrained and editorial - one strong
picture, a lot of quiet space, the title in Jura Light capitals with wide tracking, a short rule, the facts (place,
date in Roman-numeral month, gear, numbers) in DM Mono, warm white with a soft shadow. Big outlined text, red tags and
"1 VS 533"-style numbers read as cheap to many audiences ("很尬"); ask the user's taste before going loud.

- Offer 2-3 variants side by side (different frames or text positions); check each at feed size (`_feed.png`).
- Xiaohongshu: 3:4 (1242x1660). The cover is chosen in the post's cover editor, not taken from the first frame.
- YouTube: 1280x720, < 2 MB. "Test & compare" A/B-tests up to 3 thumbnails: give 3 genuinely different options
  (the subject close-up, the title frame, the people).
- Every character must exist in the font (Jura / DM Mono are Latin-only; no ′ ″ - use ' ").

## Titles and copy

- **The user writes the title** unless they ask for options. Offer 2-3 short, concrete options when asked; never
  clickbait ("you won't believe").
- Xiaohongshu: title <= 20 characters (ASCII counts as half). Body: what happened in 2-4 short lines, what is in the
  film, optionally how it was made; 5-10 topics - type `#name`, pick the exact match from the suggestions so it
  becomes a real topic.
- YouTube: title 50-70 characters with the concrete hook ("A Seal Swam Up and Looked Into My Camera"); description:
  the hook line, 2-3 sentences of story, chapters (first at 0:00, >= 3, each >= 10 s: `finish.py --chapters` gives
  a skeleton), how it was made, 3 hashtags.
- X: <= 280 weighted characters (CJK and emoji count double); one line of story + the film; a thread for "how it
  was made" if the user wants it.
- "Edited by AI" can be an honest angle that interests people. If the user wants it, say precisely what the AI did
  (selection, cut, grade, score, cloned narration) and what was theirs (the footage, the trip, the decisions).

## AI disclosure

When the narration is a cloned voice (or anything else synthetic looks or sounds real), declare it:
- YouTube: Details -> "Altered or synthetic content" -> Yes.
- Xiaohongshu / Douyin / Bilibili: the content declaration option for AI-generated content (内容含 AI 生成 / AI 合成).
- TikTok / Instagram: the "AI-generated" label toggle.
Mentioning it in the description as well costs nothing and builds trust.

## Posting

Publishing is the user's decision: prepare everything (file, cover, title options, body, topics, settings), then
let the user press publish - never click a publish / 发布 button without their explicit OK in the conversation.
With browser automation, large video files usually have to be chosen by the user in the file dialog (extensions
cap uploads around 10 MB); covers and text can be filled in for them. Do not work around upload limits.
