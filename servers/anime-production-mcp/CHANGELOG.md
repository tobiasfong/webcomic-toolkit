# Changelog

## 3.4.0 — 2026-10-27

**Character references: `animate_shot_cloud(ref_images=...)` and the
`kling-o3-ref` model** (Kling O3 image reference). The panel goes in as the
first frame and the characters' sprites as reference images, so a character
the panel shows small, or one who enters the shot, is drawn from their own
design. It is the only workflow here that takes a first frame and references
together. A model without a reference field refuses sprites instead of
dropping them while the take is still billed.

## 3.3.0 — 2026-10-26

**New tool: `edit_shot_cloud`, paid video edit on Higgsfield.** For a take
whose motion is right but whose faces or hands smear: the take itself goes to
`seedance-2.5-edit` or `kling-o3-edit` with a prompt, and the panel as a
reference image, and comes back redrawn with the same motion and camera.

- LTX takes run about 2 s; Kling's edit needs 3 s and Seedance's 4 s.
  `fit="slow"` sends the same frames at a lower rate (the model sees the whole
  motion, slowed), `fit="pad"` holds the last frame; either way the result is
  put back to the take's own length. Tested end to end on a 49-frame clip.
- The clip as sent is kept beside the first take, for comparison.
- Same safeguards as `animate_shot_cloud`: model required, priced first,
  `max_usd`, `estimate_only`, one take by default, sound off.

## 3.2.0 — 2026-10-26

**`animate_shot_cloud` moves from BytePlus to Higgsfield.** One account now
reaches several paid video models through one request lifecycle, instead of
Seedance alone. The BytePlus client is gone; `cloud_video.py` is the
Higgsfield client.

- **The model is a required argument**, so a paid run always names what it
  spends on: `seedance-2.5`, `seedance-2.0`, `kling-3.0-std`, `kling-3.0-pro`,
  `kling-o3`. Each is mapped from its own documented schema, since the
  first- and last-frame fields are spelled differently per model (Kling O3's
  `first_frame_url` against Kling 3.0's `image_url`, Seedance's
  `end_image_url` against Kling's `last_image_url`).
- **Priced before submitting.** Higgsfield quotes the exact request
  (`/estimate`); `max_usd` refuses a run over budget, and `estimate_only`
  returns the price and spends nothing. The old third-party price table is
  gone.
- Local checks (prompt, duration, resolution, ffmpeg) run before anything is
  uploaded. A lost or 5xx submission is retried with the same
  Idempotency-Key, so a retry is never billed as a second take. Polling never
  cancels a request.
- Sound is switched off on every model (most default it on). The last frame
  is cut from the clip itself, since these endpoints return none.
- Keys come from `HF_API_KEY_ID` / `HF_API_KEY_SECRET` (or
  `HF_CREDENTIALS`); `check_status` reports whether they are set, never their
  values. The presigned upload URL never receives them.

**Not yet verified against the live API**: no key existed when this was
written. The request formats follow docs.higgsfield.ai as of 2026-10-26.

**New tools: `inspect_moment` and `repair_frames`.** Name a shot and a time;
`inspect_moment` returns a slowed clip of that moment with each frame's
number burned in, and borders red the drawings that dip against their
neighbors (a smear or a flash frame). `repair_frames` then replaces the
named frames with a hold of the clean frame before them. The red border is a hint,
not a verdict: measured on the OP1 cut, it cannot tell fast motion from a
smear. `mode="interp"` (in-betweens by RIFE) needs `rife-ncnn-vulkan`, which
is not installed.

## 3.1.0 — 2026-10-22

**First-and-last-frame mode: `animate_shot(last_frame_path=...)`.** Give the
picture a shot should END on, and LTX-2.5 only fills in the motion between two
pictures it must land on. A last resort for an action image-to-video keeps
refusing, with the end pose made by Klein. `lw.build25_flf()` follows ComfyUI's own `video_ltx2_5_flf2v` template:
one stage at full size, both pictures pinned with `LTXVAddGuide` at frame 0 and
the last frame (strength 0.7), `LTXVCropGuides` before decode, the prompt
enhancer off. Both pictures are fitted to the render size in Python; an end
frame of a different shape is refused rather than silently cropped. The
skill's `ltx_run.py` gains `--last`, building the identical graph.

**The workflow is written down** (README and SKILL.md): image-to-video for
every shot, generated or hand-drawn; reword before anything else when a shot
fails; and only then, for Klein-generated art, a Klein-rendered end pose with
first-and-last-frame. No one draws extra poses: for hand-drawn art Klein makes
the end pose with a BOXED edit first (only the moving part redrawn), and edits
the whole panel only as the last resort, since that re-inks the drawing. No
shot is left as a still — a still is a failed shot. Seedance stays a separate
paid option outside this chain.

**Docs stop presenting 2.3 findings as current.** The README's works/fails
table, the "feature-scale motion only arrives as a passenger" note (README,
server, SKILL.md) and the 17-frame retime example now say what 2.5 changed.
Recorded too: the 2.3 takes those findings came from were 25 frames at
0.5–0.8 MP in one pass, against 2.5's 49–97 frames at ~1.8 MP refined, so the
gain between them is part model, part settings, never separated.

Also: `build25`/`recipe25` default to 49 frames at 24 fps (they still said 17
at 48), and the recipe records the mode and end frame.

Tested once on a real shot, a top-down panel of one figure landing on another:
the graph ran end to end (~7 min, 49 frames) and landed on the end frame, but
the take was rejected for its START frame, which Klein drew with extra boots
and a deformed face. Klein also could not move the pose: told "falling toward
him", "a gap between their bodies" or "kneeling", with the panel as reference,
it redrew the panel's own pose on all seven seeds. The shot was made instead by
animating the figure pushing up off the other and playing it backward at 2x.
Show any Klein-made frame to the artist before animating from it.

## 3.0.0 — 2026-10-22

**LTX-2.3 is removed; `animate_shot` runs LTX-2.5 only.** On an eight-scene
teaser of hand-drawn panels the artist judged 2.5 much better and had 2.3
uninstalled.

**Breaking:** `animate_shot` loses `variant`. Defaults change to 2.5's own
settings: `length=49`, `fps=24`, `strength=0.7`. Its 12 fps preview keeps every
other frame of the 24 fps take, so it plays at true speed.

- `ltx_workflow.py` drops the 2.3 graph (`build`, `recipe`, `validate`, the
  GGUF `VARIANTS`, Gemma 3, the inert negative prompt). `pick_size` and the 2.5
  builder stay; the module notes keep the 2.3 lessons that are about pictures.
- `check_status` drops the ComfyUI-GGUF and 2.3 file checks. It reports the
  Klein ComfyUI (which now runs everything this server renders), the LTX-2.5
  and Klein files on it, and the main ComfyUI only as the thing the server
  unloads before rendering.
- The README's Models section describes 2.5 alone; ComfyUI-GGUF is no longer
  required.

The skill follows: `ltx_run.py` is rewritten for 2.5 (stdlib + Pillow, the same
graph as the server, sizes from the artwork, writes a 12 fps preview);
`fetch-ltx.sh` downloads the 2.5 files from the gated Lightricks repo;
`ltx_hybrid.py`, a 2.3-only two-variant trick, is removed; `ltx-setup.md`,
`SKILL.md` and the skill's `AGENTS.md` describe 2.5, including the wording that
fixed its blink and head-turn failures.

## 2.3.0 — 2026-10-21

**LTX-2.5 as an `animate_shot` variant (`variant="2.5"`).** It runs on the Klein
ComfyUI (v0.41), which hosts Lightricks' official INT8 files natively; the main
ComfyUI stays on v0.25.1 for LTX-2.3, music and matting. `lw.build25()` follows
ComfyUI's own `video_ltx2_5_i2v` template: two stages (half size, then a 2x
latent upscale and a short refine), the prompt enhancer left off, frames saved
as animated webp like 2.3's. `check_status` reports missing 2.5 files.

**Use 2.5's own settings: 24 fps, 49 or 97 frames.** Run at 2.3's 17 frames
and 48 fps, every take held still for frames 0-8, lurched at frame 9 (the
third and last latent frame) and tore faces on full-body action. At 24 fps and
49-97 frames, an eight-scene teaser of hand-drawn panels came back with clean
faces, and the artist judged 2.5 much better than 2.3 on them: a real punch
toward the viewer, a waltz turn, a prayer pose, two people talking. Measured on
the 6 GB card with 32 GB RAM: ~3.5 min for 49 frames, ~7 min for 97, at
1152x1728 — slower than 2.3 but not paging, despite 37 GB of weights.

Still weak in that run: asked to blink, it often closed the eyes for good; it
turned a profile head toward the camera unasked; asked to grow ice, it barely did.

`motion.retime()` gains `step`: 2.5 at 24 fps is real-time motion, so its
12 fps preview keeps every other frame. 2.3's 48 fps takes keep every frame
and play slowed, as before.

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
