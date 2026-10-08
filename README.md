# footage-to-vlog

A [Claude Code](https://claude.com/claude-code) skill that edits raw footage into a finished short film - with
ffmpeg and Python, no editing app. Hand Claude a folder of clips (an SD card, a drone, a phone, the Photos library)
and it plans the story with you, cuts on a musical grid, renders vertical and horizontal versions, grades, scores,
narrates in your own cloned voice, subtitles, mixes, and prepares covers and exports for each platform. You review
at every step.

[中文说明](#中文说明)

## What it does

- **Looks at everything first**: inventory of every clip (HDR, frame rate, sound, proxy traps), timestamped contact
  sheets, CLIP search for subjects ("a fish", "a quokka") second by second, Whisper search for people talking and
  laughing on camera.
- **Plans a story, not a diary**: the rarest moment as the hook, sections by theme or point of view, quiet beats,
  people's faces - principles distilled from real review rounds (`references/editing.md`).
- **Vertical without cropping**: landscape shots sit whole in the 9:16 frame over their own blur; top-down drone
  shots are turned 90 degrees to fill it; a drone tilting up animates from one to the other. Zooms stay locked on a
  tracked subject.
- **Picture**: underwater grade (haze off, red back, 16-bit), phone HDR to SDR, whip pans, dissolves, dips, living
  stills, titles and captions in a quiet editorial type.
- **An original score** synthesised on the edit's bar grid: per-section styles (intro, groove, light, half-time,
  breath, ambient, outro), designed loudness per section, hits on the cuts, whooshes on whip pans, and a muffled
  "heard from under water" version for diving scenes. No licence questions.
- **Narration in your own voice** (F5-TTS, zero-shot from a 10 s recording), every line checked by Whisper - alone
  and with the music under it - so a homophone or a buried word never reaches the final cut. Chinese and English
  from the same voice.
- **A measured mix**: each shot's natural sound levelled, music ducking under voices, -16 LUFS, a per-section
  loudness report, and a final Whisper check of every line in the finished file.
- **Deliverables**: 4K vertical and horizontal masters, phone previews, an X version, .srt captions, YouTube chapter
  skeletons, covers and thumbnails, platform notes for Xiaohongshu, Douyin, YouTube, X, Reels.

## Install

```bash
git clone https://github.com/TinyAlmond/footage-to-vlog ~/.claude/skills/footage-to-vlog
brew install ffmpeg                       # or your platform's ffmpeg
python3 -m venv ~/.venvs/vlog && ~/.venvs/vlog/bin/pip install -r ~/.claude/skills/footage-to-vlog/requirements.txt
```

The core (picture, score, mix, exports) needs only numpy, scipy, opencv-python and pillow. Scanning, tracking and
narration add torch, transformers and f5-tts; their models (~3 GB) download on first use. Works best on a Mac with
Apple silicon (Photos export, VideoToolbox decoding, avconvert, PingFang); on Linux install Noto Sans CJK for
Chinese text and an ffmpeg with zscale for HDR footage.

## Use

Just ask, in your own words:

> Edit the clips on the SD card into a one-minute vertical vlog for Xiaohongshu, with my voice as narration.

> 把相册里 9 月 26 日以后的横屏视频剪成一条视频，4K 竖屏和横屏各一版。

> Make a YouTube version of this edit in English and write the description.

Claude follows `SKILL.md`: ingest -> look at everything -> plan (you approve) -> edit list -> framing check ->
score -> narration script (you approve) -> mix -> phone preview (you review) -> 4K masters -> covers and copy (you
publish).

Everything is driven by one JSON edit list per film (`references/edl.md`, example in `examples/`), so changes are
cheap: a different hook, a slower section or another language is an edit and a re-run, not a re-edit.

## Responsible use

- **Clone only your own voice**, from a recording made for this purpose. Declare AI-generated voice where the
  platform asks (YouTube "altered or synthetic content", Xiaohongshu / Douyin content declarations).
- **Privacy**: deliverables are stripped of metadata (GPS, device); crop or cut strangers' faces, especially
  children's.
- **Licences**: this repository is MIT. Bundled fonts (Jura, DM Mono, Instrument Sans) are SIL OFL 1.1 - licences in
  `assets/fonts/`. Models are downloaded separately under their own terms: F5-TTS code MIT, **weights CC-BY-NC 4.0
  (non-commercial)** - use a commercially licensed TTS for paid work; Whisper and CLIP MIT; OWLv2 Apache-2.0.

## Layout

```
SKILL.md                  the workflow Claude follows
references/               editing principles, edit-list format, ingest, sound, platforms, troubleshooting
scripts/                  the tools (each has -h): inventory, contact_sheet, align_proxy, scan, speech, track,
                          compose, score, narrate, mix, finish, cover, hdr_to_sdr, photos_export, common, synth
examples/edl.example.json a complete 70 s film
assets/fonts/             OFL fonts for titles, data lines and Latin subtitles
```

Built from real edits made with Claude Code: travel films from an action camera, a drone and a phone, and an
astrophotography short. Every rule in `references/editing.md` comes from feedback on those cuts.

---

## 中文说明

一个 Claude Code 技能：用 ffmpeg 和 Python 把原始素材剪成成片，不需要剪辑软件。把一个文件夹的素材（SD 卡、无人机、手机、
照片图库）交给 Claude，它会和你一起定故事，按音乐小节剪辑，出竖屏和横屏两版，调色，配原创音乐，用你本人的克隆声音解说，
加字幕，混音，并为各平台准备封面和导出文件。每一步都先给你看，再继续。

**它做什么**

- **先看完全部素材**：每个片段的清单（HDR、帧率、声音、代理文件的坑）、带时间码的缩略图、用 CLIP 逐秒找主体（鱼、动物），
  用 Whisper 找镜头里有人说话和笑的地方。
- **讲故事而不是记流水账**：最稀有的画面开场，按主题或视角分段，留白，拍到人的脸 —— 这些原则来自真实的修改意见
  （`references/editing.md`）。
- **竖屏不裁画面**：横屏镜头完整放在 9:16 中间，上下是它自己的模糊放大；俯拍的无人机镜头旋转 90° 铺满全屏；无人机抬头的
  镜头从旋转平滑过渡到居中。推拉镜头锁定跟踪的主体，始终居中。
- **画面**：水下调色（去灰、补红、16 位处理）、手机 HDR 转 SDR、甩镜、叠化、黑场过渡、会动的照片、克制的标题和信息字幕。
- **原创配乐**：按剪辑的小节网格用代码合成，每段有自己的风格和设计好的响度，转场处有重音和音效，水下段落是“闷”的声音。
  没有版权问题。
- **你本人声音的解说**（F5-TTS，用 10 秒录音零样本克隆），每一句都用 Whisper 反向核对 —— 单独听一遍，叠上音乐再听一遍，
  读错或被音乐盖住的词不会进成片。同一个声音可以说中文和英文。
- **可量化的混音**：每个镜头的现场声单独统一响度，人声出现时音乐自动让位，成片 -16 LUFS，按段落输出响度报告，最后再用
  Whisper 从成片里核对每一句解说。
- **交付**：4K 竖屏和横屏母版、手机预览版、X 版本、.srt 字幕、YouTube 章节草稿、封面和缩略图，以及小红书、抖音、YouTube、
  X、Reels 的平台说明。

**安装**

```bash
git clone https://github.com/TinyAlmond/footage-to-vlog ~/.claude/skills/footage-to-vlog
brew install ffmpeg
python3 -m venv ~/.venvs/vlog && ~/.venvs/vlog/bin/pip install -r ~/.claude/skills/footage-to-vlog/requirements.txt
```

然后直接用你自己的话提要求，例如：“把 SD 卡里的素材剪成一分钟的小红书竖屏 vlog，用我的声音配解说。”

**负责任地使用**：只克隆你本人的声音；发布时按平台要求声明含 AI 生成内容；成片会去掉 GPS 等元数据；陌生人（尤其是小孩）的
脸要裁掉或剪掉。F5-TTS 的模型权重是 CC-BY-NC 4.0（非商业），商业用途请换用可商用的 TTS。代码 MIT 许可，字体 SIL OFL 1.1。
