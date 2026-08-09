# Changelog

## 1.2.0 — 2026-08-09

**Breaking default change: `animate_shot` now renders at 1920x1088**, up from
832x576. `lw.PRIMARY` / `lw.FALLBACK` name the two sizes an artist reviewed
frame-by-frame and approved; 832x576 is retired.

A ceiling sweep on the 6 GB RTX 3060 Laptop found **no out-of-memory point at
any resolution tested**, up to and including 1920x1088 at length 17, with
steady-state cost of ~90-140 s a take across the whole range once the model is
resident. The old default's speed advantage was largely the first-take model
load being misattributed. Resolution is close to free on this card and buys the
only thing that mattered: hands that survive motion.

Also corrected from the same sweep, both by the artist's eye against the
scanner's numbers:
- **"The tail degrades" is a length-17 observation, not a law.** At length 33
  the bad window was frames 12-17 and the clip recovered afterwards, tail
  included. The scanner had reported failure at frame 3. Find the bad window;
  do not blind-truncate.
- **Height may need to be divisible by 64, not 32** (unconfirmed). 1408x800 was
  the only size tested whose height fails 64, and the only one that grew an
  extra finger. `validate()` still enforces 32; prefer 704/832/896/1088.
- Length 25 and 33 misbehaved at 1216x832 and have not been re-run at the new
  default. 17 remains the only length verified clean.

## 1.1.0 — 2026-08-09

Documentation correction, driven by a 15-panel scene that needed **65 of 221
frames hand-repaired**. No default changed — the defaults still fit a 6 GB card
— but they are no longer described as "the settled recipe", because they aren't
a good recipe, they're a cheap one.

**Corrected**
- `832x576` is now documented as a VRAM ceiling, not a target. Lightricks
  recommend 1280x720 minimum; at 832x576 a hand is ~5 latent pixels after the
  VAE's 8x compression and cannot be rendered while moving. `1216x832` produced
  the only take the artist accepted from a full comparison set. A later ceiling
  sweep found no OOM point on the 6 GB card at all (1920x1088 / length 17
  completes) and steady-state cost of ~90-140 s a take across the range, so the
  low default was never buying much. `RECOMMENDED_MIN` added alongside the existing `MIN_DIM` floor
  so the two are not confused.
- The negative prompt is documented as **inert on `distilled`**: cfg 1.0
  discards the negative branch, verified by pixel-identical output with and
  without it (mean abs difference 0.000, against ~67 between two seeds). It is
  retained because `dev` runs at cfg 3.0.
- Prompt length (4–8 sentences, not one), frame count (121/257, not the 8n+1
  floor of 17) and motion density (fewer readable beats, not stacked
  simultaneous actions) documented against upstream guidance. Steps at 8 on
  `distilled` was the one original choice that held up.
- The motion score and the artifact scanner are now documented as *sort orders*,
  not verdicts, with their measured blind spots: a face melting inside hair, a
  sword outside the face box, eyes at 0.2% of frame — and ranking the only
  acceptable take last, because it had the most motion.

**Added to the working notes**
- Never interleave LTX and Kontext on a small card; one such call cost five
  hours and two finished takes.
- Kontext repairs a *grip* (2/2) but cannot rebuild an *open hand* from a blur
  (0/7) — same invent-vs-relocate boundary as LTX.
- When LTX is worth using at all, stated honestly: ambient motion over existing
  pixels, not a way to avoid drawing keys.

**Changed**
- `assemble_video` takes `shortest` (default `True`). `-shortest` truncates the
  video to the audio, which is wrong whenever the music was written against the
  cut.

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
