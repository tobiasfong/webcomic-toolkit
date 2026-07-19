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
