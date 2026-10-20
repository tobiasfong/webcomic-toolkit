# Changelog

## 2.2.0 — 2026-10-20

**New tool: `animate_shot_cloud`, paid image-to-video through BytePlus
ModelArk (Seedance 2.0).** For the shots the free local path cannot do: an
action that has to actually happen, and hands that have to survive it. LTX on
the local card stays the default for everything else.

- Takes land in the same shot library as LTX takes — an mp4, a 12 fps webp,
  and the clip's last frame — so `contact_sheet`, `approve_shot` and
  `assemble_video` need no changes.
- **One take per call by default, at most 3.** Seedance 2.0 accepts no seed,
  so takes cannot be reproduced and every one is billed. Each result carries a
  cost ESTIMATE from third-party pricing; the ModelArk console has the bill.
- `last_frame_path` enables the first-and-last-frame mode: render the pose an
  action should end on, and the model fills in the motion between.
- Reference images are refused alongside a first frame, because BytePlus
  documents them as a separate mode.
- Generated audio is switched off (the API defaults it on); the soundtrack
  comes from the music server.
- The 12 fps preview is resampled in Python because the ffmpeg build this
  machine uses (Remotion's) ships without the `fps` filter.
- `check_status` reports whether the `ARK_API_KEY` variable is set, never its
  value.

**Not yet verified against the live API** — no key existed when this was
written. The request format follows BytePlus's documentation, and the model ID
is the one in its examples; confirm it in the console before the first paid run.

## 2.1.0 — 2026-10-17

**`animate_shot` and `edit_frame` unload the other ComfyUI before they start.**
The busy check stopped two jobs running at once, but an IDLE ComfyUI still
holds its model in system RAM, and LTX streams ~24 GB of weights from there.
Measured on the 32 GB machine: an LTX take that started with Klein resident
and 3.7 GB free took **694 s**; with Klein unloaded it started at 22 GB free
and took **176 s** cold, **75 s** warm. The unload is sent only when the other
side is idle, so it never interrupts a job; the next job there loads its model
again. `klein_edit.py` does the same.

Also removed from `klein.py`'s docstring: a leftover of the Kontext claim
corrected in 2.0.0 ("every damaged frame rescued").

## 2.0.0 — 2026-10-17

**`edit_frame` runs FLUX 3 Image Klein; FLUX.1 Kontext is retired.** The
character and background servers had already moved to Klein, and this server
was the last thing loading FLUX.1. Moving it is what lets FLUX.1 be uninstalled.

**Breaking:** `edit_frame` loses `guidance` (Klein is step-distilled at cfg 1
and has no such dial) and gains `box`. `steps` now defaults to 16.
`check_status` drops `kontext_ready` and reports a `klein` block instead.

- **`klein.py` replaces `kontext_workflow.py`.** Klein runs on its own ComfyUI
  (v0.41, port 8189), shared with the other two servers and started on first
  use. The main ComfyUI stays on v0.25.1 for LTX.
- **`box`** tells Klein where to draw and how big, then pastes back only that
  region. Klein redraws the whole frame even for a boxed edit, so this is what
  keeps the rest of the frame untouched: measured change outside the box, 0.
  The full redrawn frame is still returned (`full`) for `composite_patch`.
- **Edits come back at the source's exact size**, so `composite_patch` no longer
  has to register a resized patch. Kontext's snapping to its own resolutions
  was why `register()` existed; it stays for any patch that arrives at another
  size.
- **`animate_shot` and `edit_frame` refuse to start while the other ComfyUI has
  a job.** With LTX and the edit model on one ComfyUI, its serial queue at least
  ordered them; across two, nothing does. A Kontext call during an LTX batch
  once hung for five hours.
- The skill's standalone `kontext_edit.py` is replaced by `klein_edit.py`, same
  behavior as the tool. Its seed-1 output on the test frame was pixel-identical
  to the server's.

**Measured on one damaged test frame** (a sword hand LTX had blurred,
1920x1088, boxed, three seeds): ~97 s a seed against Kontext Q6_K's ~233 s.
**0 usable by the artist's eye** — the closest had a bad thumb — and Klein's
crisp inking stood out against the soft LTX frames. (The instruction asked for
"crisp black outlines"; that wording is a confound.)

**Corrected: no machine repair of an LTX hand has ever shipped.** Earlier
docs here said Kontext Q6_K "repairs hands" and rescued every damaged frame it
was given. Its best takes were bases the artist still drew on, and every
repaired hand in the test scene's final video was finished by the artist's
hand, before the Q6 model was even downloaded — one over a Q3 Kontext base, the
rest drawn outright. Klein replaced Kontext because nothing working was
lost, not because it repairs hands better.

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
