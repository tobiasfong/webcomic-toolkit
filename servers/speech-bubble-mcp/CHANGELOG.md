# Changelog — speech-bubble-mcp

## v0.1.0 — 2026-11-27

First build. Letters stills and video shots; no GPU, no network.

### What it does

- **Five bubble kinds**, all drawn in code: `speech` (ellipse, curved tapering
  tail), `thought` (cloud, trail of shrinking circles), `caption` (box for
  narration), `shout` (spiky burst, straight tail, type 15% larger), `whisper`
  (dashed outline). Every shape is a union of primitives drawn twice -- grown
  by the stroke in the outline color, then at size in the fill -- so the tail
  and the body share one seamless outline. Drawn at 3x and downsampled.
- **The bubble follows the text.** One type size per project (a fraction of
  the frame's short side, 0.034 by default: 37 px at 1080p). Line breaks try
  every line count and keep the one whose smallest enclosing ellipse is
  smallest, aimed at 1.7 wide with a small charge per line. On sample lines
  that gives "Is that / really him?" and "Wait. You think / I came here / for
  the money?" rather than one word per line.
- **Vertical Japanese** (tategaki): right-to-left columns, brackets, dashes
  and ー turned 90 degrees, 、。 in the upper right of their cell, small kana
  nudged. When the author breaks the columns himself they are kept whole: the
  first test split 吹き出し across two columns.
- **Kinsoku** for CJK line breaks: closing punctuation and small kana never
  start a line, opening brackets never end one.
- **Auto-placement** when a bubble has no position: a grid search on a map of
  local detail (calm art first), near and above the speaker, off the
  speaker, in reading order, and with no tail or thought trail crossing
  another bubble. The trail rule came from the first demo, where a thought's
  circles ran across the speech bubble beside it.
- **Video**: bubbles fade, slide or pop in one after another, each after the
  one before has had its reading time (about 3 English words or 7 CJK
  characters a second, plus a beat, clamped to 1.5-6 s), and stay until the
  shot ends. When the lines need longer than the motion, the last frame is
  held. A still image works as a source too. Encoding a 14.7 s 1080p shot
  took 17-19 s.
- **The preview is the encode.** `compose()` builds the frame at time t for
  both, so an approved preview is the render.
- **Specs are saved** (`state/lettering/<project>/<name>.json`), so a page is
  re-lettered in another language by name, with each language's own geometry.

### Why the video path composites in Python

The first version drew the animation with ffmpeg's `overlay` and `fade`
filters. The ffmpeg this toolkit runs on is a reduced build: 50 filters, none
of `overlay`, `fade`, `pad`, `tpad` or the test-pattern sources. So ffmpeg now
only decodes (raw RGB out over `image2pipe`) and encodes (PNG in over
`image2pipe`, the route anime-production's assembly already uses), and works
with any build.

### Not decided yet -- starting values only

No font, outline weight, tail style or reading speed has been chosen by the
author. The English default is Comic Sans Bold only because it ships with
Windows; no lettering font is licensed on record. Fonts are a per-project
setting.

### Setup note

On build day PyPI was unreachable from this machine (pip and curl both got
empty replies), so the venv was seeded from anime-production's, which runs
the same Python 3.12.10 and already holds every package this server needs.
`pip install -r requirements.txt` replaces it whenever PyPI is reachable.
