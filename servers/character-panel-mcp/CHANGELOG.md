# Changelog

All notable changes to the Character & Panel Generator MCP server are documented
here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This server lives in the [`webcomic-toolkit`](https://github.com/tobiasfong/webcomic-toolkit)
monorepo (`servers/character-panel-mcp`) alongside its sibling servers from day one;
releases are tagged `character-panel-mcp@vX.Y.Z`.

> This is the first tagged release. Everything below was built and live-tested across
> one continuous development arc before anything was ever released or announced —
> the numbered stages are development history, kept for the honest record of what was
> tried, what broke, and what the fix actually was, not a chain of prior public releases.

## [Unreleased] — FLUX exploration (2026-07-21/22)

**Nothing in this section is wired into `workflow.py`/`server.py` yet — this is an
honest record of a still-open investigation, not a shipped feature.** Motivation:
1.1.0's SDXL hand-anatomy fixes (CharTurn + RPGTurn + ClearHandsXL LoRA stacking)
plateaued — hands kept coming back deformed even fully stacked. Prototyped
FLUX.1-dev instead, GGUF-quantized (`flux1-dev-Q3_K_S.gguf`, ~5.0 GB, via
`ComfyUI-GGUF`) to fit the same 6 GB VRAM budget.

Validated in standalone scratch scripts (not yet ported):
- Base FLUX txt2img + a manhwa-style LoRA (`manwha_style.safetensors`), no OOM,
  clearly better anatomy on first look than SDXL.
- Impact Pack `detail_fix` hand pass ported to FLUX — needs `denoise=0.7` (0.55 was
  insufficient), confirmed 5-finger hands vs. SDXL's persistent deformity.
- Mannequin-generated ControlNet back view (`flux_controlnet_union_alpha`, InstantX
  Union, same `mannequin.render_pose_map` used since 1.0.0): genuine back-facing
  views on 2 of 3 seeds across two separate rounds — real progress, but not reliable
  enough to ship unattended (the same seed missed the direction lock both times it
  was tried, so this is seed-dependent, not noise).
- FLUX Kontext dev installed (`flux1-kontext-dev-Q3_K_S.gguf`) as an image *editor*
  (not text-to-image): validated for **local anatomy fixes on an already-correctly-
  posed image** (took a genuine back view with hands hidden in sleeve cuffs,
  instructed a hand-exposure edit, got clean 5-finger hands with everything else
  unchanged). **Not validated** for full front→back rotation as a single edit — one
  test produced a chimera (back-facing head/hair/hands, but front-facing tank-top
  neckline and shoe orientation), because "turn around" and "keep everything else
  the same" are self-contradicting instructions for a full viewpoint change.
- Kontext turnaround-sheet LoRA (Civitai 1753109): first test (recommended prompt
  verbatim) produced 7 panels, none an actual back view. Traced to the recommended
  prompt inserting "exact" into the creator's required trigger substring ("create
  turnaround sheet of this character"), breaking it. **Retested same-session with
  only that word dropped — fixed it.** Panel 4 of 7 came back a genuine back view,
  verified whole-figure (correct back collar, back seam, rear pockets, no belt
  buckle, clean hands) not just glanced at. Single successful seed so far, not yet
  a reliability figure — needs a multi-seed re-run before comparing to
  ControlNet's ~2/3 rate.

Explicitly deferred: porting the validated recipe into `workflow.py` as a real
`model=` option; deleting the ~12.5 GB of SDXL-era files (checkpoint, LoRAs,
IP-Adapter, ControlNet); tuning the turnaround-sheet LoRA further; any FLUX/SDXL
upgrade decision for the sibling `webcomic-background-mcp` server (still SD1.5, no
demonstrated problem there).

## [1.1.0] — 2026-07-20

### Added — Avery-style poster sheet, restructured fields
`generate_reference_sheet`'s combined output is now a real designed sheet (title,
large front-view hero pose, back-view panel, labeled expression row, text blocks) —
`tools/compose_sheet.py`'s new `compose_concept_sheet()`, modeled directly on Tobias's
friend Avery's hand-composed character sheets, with deliberately far less text (no
bio, no quotes, no lore boxes). Uses Noto Sans JP so mixed English/Japanese text
renders correctly (needed for the personality field's speech-pattern notes). Character
Bible fields reworked per direct feedback on the first cut: `role`/`status`/
`personality` (three separate fields) consolidated into one `profile` field;
`abilities` unchanged; the sheet's third block, "Appearance," is NOT a new field — it's
`description` itself, shown on the sheet as well as fed to generation, so hair/eye/
costume notes (including ones pulled from an artist's own markdown notes when
ingesting their art) are only ever typed once, never duplicated between a
generation-facing field and a sheet-facing one.

### Added — disciplined sequential generation (scope corrected after live testing)
`generate_reference_sheet` generates in a fixed order regardless of how `views` is
passed: front view first, then back, then expressions. Once the front view succeeds,
it becomes the **back view's** identity anchor (img2img seed + IP-Adapter reference)
instead of the raw bible photo — chaining an already-in-style render should hold
costume/color continuity better than re-deriving it from a raw source photo.
**Expression/face close-ups deliberately do NOT chain off the front view** — the
first cut of this feature chained everything, and live testing caught it immediately:
a "face close-up, smiling" request came back as a repeat of the front view's full-body
action pose, because IP-Adapter conditions on the whole reference image, not just "this
person's face." Reverted that part; close-ups use the bible's own primary reference,
same as before this feature existed. Also reworded the close-up view prompts
("close-up portrait, head and shoulders only, head turned three-quarters, ...")
after live testing showed "face close-up, 3/4 view" alone was ambiguous enough to
render as a 3/4-angle body shot instead of a tight face crop.

### Investigated and reverted — automatic back-view ControlNet in generate_reference_sheet
Tried wiring the (already-shipped, already-validated as its own manual tool)
mannequin ControlNet pose map automatically into the back view here, forcing
`identity_mode="off"` to stop IP-Adapter from fighting the pose signal (confirmed
live that `identity_mode="plus"`, this tool's default, wins that fight and keeps the
render front-facing even at `pose_strength=1.45`). With identity_mode forced off,
genuine back-facing content DID start appearing — but **full-resolution scrutiny of
hands and feet, not just checking facing direction, found it came with a fused,
fingerless hand and hoof-like feet**, and retrying the same call reproduced the same
failure rather than a clean result. Reverted entirely rather than ship a mechanism
that trades one failure mode (wrong direction) for a worse one (deformed anatomy) on
an unattended, un-curated bulk call. **Back view remains an honest, open limitation
of this tool** — text + IP-Adapter alone still doesn't produce one reliably (matches
every prior finding in this project's history). The validated path when a real back
view is needed stays `generate_pose_map` + `generate_character_pose`, run and curated
by hand across a few seeds — a deliberately reviewed one-at-a-time flow, not
something safe to fire unattended inside a 5-view bulk sheet call.

### Added — `detail_fix`: the actual fix for hallucinated hands/faces
New opt-in pass on `generate_character_pose`/`generate_reference_sheet`
(`workflow.py`'s `build_graph`/`generate`), needing two new custom nodes
(`ComfyUI-Impact-Pack`, `ComfyUI-Impact-Subpack`) and two YOLOv8 detector models
(`face_yolov8m.pt`, `hand_yolov8s.pt` from `Bingsu/adetailer`). Detects the face and
hands, re-samples each region at a much higher effective resolution, composites back —
the standard fix for a resolution problem (a hand is a small fraction of a full-body
frame) that no amount of prompt/negative tuning was ever going to solve, which is what
every earlier hand-anatomy complaint in this project's history actually was. **Found
via live before/after comparison, not assumed:** the first tuning pass
(`denoise=0.45`) detected hands correctly but didn't give the sampler enough freedom
to redraw them — visually indistinguishable from doing nothing. `denoise=0.6` produced
a real, visible fix (individual finger separation instead of a featureless fist) on
the same seed; shipped as the default. Face pass stayed at `denoise=0.4`. Off by
default — extra install, roughly doubles generation time.

### Fixed
- Downloading the two YOLOv8 detector models hit the same SSL revocation-check
  failure documented in 1.0.0's OpenPose-annotator fix (`curl`/Python's own SSL stack
  both failed; `CRYPT_E_NO_REVOCATION_CHECK` / `unable to get local issuer
  certificate`) — worked around with PowerShell's `Invoke-WebRequest` (Windows
  certificate store, different validation path), not by disabling verification.
- Impact-Subpack's model whitelist (a PyTorch 2.6+ `weights_only` safety feature)
  blocks loading `.pt` files by default; documented adding the two detector filenames
  to `ComfyUI/user/default/ComfyUI-Impact-Subpack/model-whitelist.txt` in README.md's
  setup steps.

## [1.0.0] — 2026-07-19

### Added — the three consistency tiers
- **Character Bible** (`register_character`, `list_characters`, `forget_character`,
  `list_projects`) — the character-domain sibling of `webcomic-background-mcp`'s
  World Builder. Unlike a location's single canonical image, a character has a
  *set* of reference images (turnarounds, expression sheets); re-registering an
  existing character appends to the set instead of replacing it.
- **Tier 1 — `generate_character_pose`**: img2img seeded from the character's
  primary reference image onto a clean backdrop, auto-matted to RGBA via `rembg`.
  Always on; the baseline every other tier layers onto.
- **Tier 2 — IP-Adapter identity + ControlNet OpenPose**, opt-in params on
  `generate_character_pose` (`identity_mode="plus"`/`"plus_face"`, `pose_ref_path`)
  rather than a separate tool — additive on top of Tier 1's img2img, off by
  default. Uses `cubiq/ComfyUI_IPAdapter_plus` and the `OpenposePreprocessor`
  node from `comfyui_controlnet_aux`. Ships `"plus_face"` instead of true
  FaceID — avoids an InsightFace/`antelopev2` install, a known-fiddly Windows
  dependency; a deliberate, documented substitution, not a silent gap.
- **Tier 3 — per-character LoRA baking**, via `bake_character_lora`,
  `check_lora_training`, `cancel_lora_training` (kohya-ss/sd-scripts,
  `accelerate launch train_network.py`). Training takes 30-90 min, so this is
  **async by construction**: `bake_character_lora` preps a dataset and launches
  a detached background process, returning immediately; the other two poll/
  cancel it. A finished LoRA auto-installs into ComfyUI's `models/loras/` and
  is recorded on the character's bible entry — `generate_character_pose` uses
  it automatically from then on. **Bakes the Niji V5 Style LoRA into every
  character LoRA by default** (sd-scripts' `--base_weights`, merged into the
  checkpoint before training starts — distinct from `generate_character_pose`'s
  `lora=`, which applies a style LoRA at generation time); pass `style_lora=""`
  to bake against a plain checkpoint.
- **`compose_panel`** — deterministic CPU compositing of a matted character onto
  a background plate, feet-anchored (`feet_x`/`feet_y`/`height_px`) to match the
  exact shape `webcomic-background-mcp`'s `generate_city_scene` anchor tool
  already reports, so the two servers' outputs chain directly. Multi-character
  panels chain calls (`base=<previous output>`).
- **`check_status`** — ComfyUI reachability check, same as the background server.

### Added — Concept Genesis (ARCHITECTURE.md §8b.6)
Three on-ramps into the Character Bible for users who don't already have a full
reference set:
- **`generate_character_concept`** — batch txt2img candidates (n distinct seeds)
  for a character that doesn't exist in the bible yet, for writers with a story
  but no art. Nothing auto-registers; the human picks a winner and calls
  `register_character`.
- **`crop_reference`** — deterministic PIL slicer (`tools/crop_reference.py`)
  for composite concept sheets (ChatGPT/Midjourney sheet generators — hero pose
  + expressions + text overlay, all in one image). A composite sheet conditions
  img2img/IP-Adapter on its layout, not the person; it must be sliced into
  single-view crops first.
- **`generate_reference_sheet`** — grows a registered character toward a
  standard 7-view turnaround checklist (front/back/side/3-4 body views + 3
  expressions), one Tier-2 generation per view. Also the tool for on-ramp 3
  (an artist's own drawing) — that on-ramp needs zero new code, just
  `register_character` on the drawing directly, then this tool for the
  turnaround views. Defaults `combine=True`: all views are also laid out on
  one labeled grid image via `tools/compose_sheet.py` (deterministic PIL, no
  GPU) — real users expect one sheet like a traditional turnaround/concept
  sheet, not N separate files.

### Added — SDXL prototype: `model="mj_manga_sdxl"`
An additional, opt-in model family (SDXL 1.0 base +
[Midjourney Manga Art Style LoRA](https://civitai.com/models/185798)), **not**
a migration — all SD1.5 models remain untouched and are the default. Motivated
by live testing hitting the SD1.5 stack's ceiling: distorted full-body anatomy
and no genuine back views regardless of tuning. Verified live on the dev
machine (6 GB RTX 3060 Laptop): **anatomy fixed outright**, clean backdrops,
strong identity retention, ~30s warm / ~75s cold generations — far better than
the "multi-minute, maybe-won't-fit" expectation for a 6.94 GB checkpoint on
6 GB VRAM. `SDXL_MODELS` registry + `sdxl` branch in `build_graph()`
(`CLIPSetLastLayer` for the LoRA's clip-skip-2, SDXL OpenPose ControlNet
filename), automatic trigger-word injection, automatic 832×1216 resolution
when defaults are untouched. `setup_models_sdxl.py` downloads the stack, with
`--stage1-only` (~7.5 GB) vs full (~12 GB) staging.

### Added — the 3D mannequin: `generate_pose_map` (ARCHITECTURE.md §8b.7)
The back-view breakthrough. `mannequin.py` poses and rotates a low-poly 3D
COCO-18 skeleton to any yaw angle and projects it directly into an OpenPose
control map — the same mesh-to-ControlNet pattern as `webcomic-background-mcp`'s
`citygen.py`/`props.py`, applied to the character's body instead of a scene.
`generate_pose_map(preset, yaw)` synthesizes the map; feed it to
`generate_character_pose(pose_ref_path=..., pose_preprocess=False)` to pin the
pose without running `OpenposePreprocessor` (which would try, and fail, to
detect a human in a stick figure).

This exists because 2D-photo pose *extraction* fundamentally cannot produce an
unambiguous back view — see "the back-view campaign" below for why. The
mannequin sidesteps extraction entirely: at yaw=180 the left/right limb-color
assignment flips and the face keypoints vanish, exactly like a genuine
back-view annotation, because it's built from a real 3D angle instead of
guessed from a flat image. **Live-verified (2026-07-19)**: at `pose_strength=1.45`,
a synthesized yaw=180 map produced the project's first genuine clean
single-figure back view — back of head, jacket back-seam and vent, no face.
**Honest caveat: stochastic, not deterministic** — the identical settings with
a different seed produced a front-facing figure instead, in a two-seed sample.
Treat it like every other tier here: generate 2-3 seeds, curate the hit.
Identity retention (IP-Adapter) at this strength/angle combination is untested
beyond `identity_mode="off"`; Tier-3 LoRA baking remains the principled fix for
identity if `pose_strength` this high fights IP-Adapter.

### The back-view campaign (honest findings, folded into the mannequin's design)
~12 configurations tested across SD1.5 and SDXL before the mannequin —
prompt-only, img2img sweeps, IP-Adapter weights 0.25–0.8, pure text-to-image,
and OpenPose ControlNet (strengths 1.0–1.6, face/hand keypoints on and off,
direction-ambiguous and direction-distinctive pose references, identity on and
off) — established: **the checkpoints can paint back-view bodies, but never as
a clean single figure via 2D-extracted pose conditioning.** Back-body geometry
only ever appeared inside messy multi-figure compositions; every configuration
that forced a clean solo figure reverted to front/profile. A checkpoint-level
prior, not a tuning failure — the root cause being that `OpenposePreprocessor`
guesses left/right limb assignment from a 2D image's appearance and has no way
to encode "this person is facing away from camera." The mannequin above is the
fix that actually worked.

### Fixed (found via real-world testing, not synthetic tests)
- **`rembg` alone doesn't pull in a working inference backend.** `requirements.txt`
  now pins `onnxruntime` explicitly; without it, `matte()` fails at runtime with
  "No onnxruntime backend found" despite `rembg` itself installing cleanly.
- **`generate_reference_sheet`'s original tuning produced unusable output
  against a real, busy source illustration.** Every "view" came back as a
  near-identical re-roll of the source image's own pose and VFX (ice crystals,
  magic circles), ignoring both the requested angle and the clean-backdrop
  prompt — because `ref_denoise=0.7` still let the img2img branch anchor
  heavily on the source latent, and `ip_adapter_weight=0.8` conditioned on the
  reference's whole scene, not just the character. Fixed: `ref_denoise` now
  defaults to `1.0` (view text actually gets to steer composition) and
  `ip_adapter_weight` to `0.25` (identity without dragging the scene along —
  much more effective once `register_character`'s `description` field is
  actually populated with real visual detail). `workflow.py`'s
  `CLEAN_BACKDROP_NEGATIVE`/`CLEAN_BACKDROP_SUFFIX` gained explicit
  VFX-suppression terms and a `solo` tag (both apply globally, not just to
  sheets) — the `solo` tag also fixed SD1.5 occasionally rendering two figures
  side-by-side at full `ref_denoise`. Validated anti-duplicate/fusion negative
  terms (`2boys`, `fused body`, `conjoined`, etc.) were later promoted into
  `generate_reference_sheet`'s default negative during the SDXL/OpenPose
  campaign, eliminating fused-body/multi-figure artifacts entirely.
- **`IPAdapter`'s `weight_type` accepted `"linear"` in the code but ComfyUI
  rejects it.** Fixed to the actual valid enum value, `"standard"` — found via
  live `/prompt` HTTP validation, not guessed.
- **OpenPose annotator models documented + manual-install path** — the
  `OpenposePreprocessor` node's first-use download of its three `.pth`
  annotator models can fail in-process ("Cannot send a request, as the client
  has been closed"); README troubleshooting now documents placing them flat in
  `custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/`. (Found
  the hard way: the node's `subfolder="annotator/ckpts"` path only applies to
  the legacy `lllyasviel/ControlNet` repo id, not the default
  `lllyasviel/Annotators`.)

### Known limitations (documented, not silently dropped)
- **Hand/finger anatomy** is improved by SDXL vs SD1.5 but still imperfect —
  occasionally a thumb renders as a fifth "normal" finger. Out of scope for
  this release; no reliable fix found.
- **Back views need the mannequin + retries**, not a single deterministic
  call — see above. Front/side/3-4 views are reliable; back views specifically
  benefit from generating a couple of seeds and curating.
- **Multi-character interaction panels** (embraces, fights, physical contact)
  are the weakest spot of the layered compositing approach — layers don't
  interpenetrate.

### Verification note
Unit-tested: `build_graph`/dataset-prep/command-building/async-job-lifecycle
(Tier 1/2/3), `crop_reference`, `compose_sheet`, `generate_concepts`'
seed-stepping, `generate_reference_sheet`'s view-iteration/defaults/
unregistered-character guard, and the `_render_pose` refactor. **Live-tested
end-to-end** against real art (Trevor and Lumiere from Tobias's own
Reincarnator x Regressor project, not synthetic images) — this is what
surfaced the `ref_denoise`/`ip_adapter_weight` bug, the `rembg` dependency
bug, and drove the entire back-view campaign through to the mannequin's live
verification. Tier-3 training's async job lifecycle is verified with a stub
trainer; a real kohya-ss training run hasn't been exercised live yet.
