# Changelog

## 1.0.0 — 2026-08-07

First release. Extracted from the pipeline that produced a finished 1:47
landscape teaser, so every default here is a measured setting rather than a
guess.

**Generation**
- `animate_shot` — the seed hunt as one call: N LTX takes submitted serially,
  each retimed to 12 fps and motion-scored, all recorded, returned best-first.
  Defaults are the settled recipe (distilled / length 17 / strength 0.9 /
  fps 48, ~65 s a take).
- `edit_frame` + `composite_patch` — FLUX.1 Kontext keyframes for eye- and
  mouth-scale features LTX cannot move, with region-only compositing so a
  regenerated frame never ships wholesale.

**Judging** — `measure_motion` (reports `maxdev` and its peak frame, because
`span` is blind to round trips), `retime_clip`, `contact_sheet`.

**Drawn effects** — `add_impact`, `grow_layer`, `add_streaks`, `add_water`. All
masked; masks come from the caller as a painted PNG or polygons, since the
region is a property of the artwork.

**Framing** — `measure_frame_slot` (full-height columns, not the alpha bbox),
`frame_clip`.

**Assembly** — `assemble_video` with the four scene kinds (`loop`, `pong`,
`once`, `hold`), an animated end card, and burned-in bilingual captions;
`write_srt` from the same cue list.

**Library** — per-project shot registry with per-name approval, `FINAL_` publish
convention, and `forget_rejected` for bulk cleanup after a hunt.

Notes:
- Frames are piped as PNG over `image2pipe`, not rawvideo — some bundled ffmpeg
  builds are compiled without the rawvideo demuxer and fail with a bare
  "Invalid argument".
- A dedupe guard perturbs byte-identical consecutive frames by one pixel value:
  Pillow's animated-WebP writer drops them, which silently collapsed a 72-frame
  sequence to 23 and played it 2.7x too fast.
- `test_tools.py` covers the 13 GPU-free paths.
