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

## [Unreleased] — Fixed: front/back hero images overflowing their box (2026-07-26)

### Fixed — `compose_full_reference_sheet()` scaled hero images by height only
`fb_scale` was computed purely as `HERO_MAX_H / max(front.height, back.height)`,
never checking the resulting combined width against `CENTER_W`. For tall source
images the pair overflowed the center box, and because the paste offset is
`cx0 + (CENTER_W - fb_w) // 2`, an oversized `fb_w` made that offset **negative**
— silently pasting the figures on top of the left-hand PROFILE/APPEARANCE text
column, truncating the last characters of every wrapped line. Found on a real
Trevor sheet rebuild (591x1248 front + 532x1248 back overflowed to 756px against
a 580px inner width). Now constrained by both height and inner width, whichever
binds first; figures coming out shorter than `HERO_MAX_H` is the correct outcome
when width binds. Ri Hwa's earlier sheet happened to fit under the old code, so
this was latent rather than previously visible.

## [Unreleased] — Investigated and reverted — FLUX Redux for multi-character panels (2026-07-26)

### The problem this was chasing
A real two-character crossover test (Namgoong Ri Hwa x Trevor, `murim_test`/`rxr`
projects) surfaced that `edit_image()` only accepts one reference image —
in a contact/action panel with both characters, the unanchored one drifts
(observed: eye-color drift on the anchored character, costume drift on the
unanchored one, and the requested contact choreography was ignored outright
on two separate attempts).

### Tried: FLUX Redux (`StyleModelLoader`/`CLIPVisionEncode`/`StyleModelApply`,
native ComfyUI-core, no custom node needed) — chain one `StyleModelApply` per
reference image onto the text conditioning, hypothesis being it'd hold both
characters' identity in one txt2img generation. Four staged tests (single
reference, strength 0.5/0.2/0.08, then a face-only crop at 0.4) all showed
the same failure: Redux reproduces the *entire composition* of whatever
reference image it's given — pose, framing, background — regardless of what
the text prompt asks for, and regardless of whether the reference is a
full-body shot or a tight face crop. Lower strength let the background start
following the prompt but never freed the pose. Higher strength also visibly
degraded output sharpness. **Not a tuning problem — StyleModelApply's global,
whole-image conditioning is structurally the wrong tool for "new pose/
composition, held identity."** `generate_with_redux()` and its model
constants have been removed from `flux_workflow.py`; the two downloaded
model files (`flux1-redux-dev.safetensors`,
`sigclip_vision_patch14_384.safetensors`, ~940MB combined) were deleted from
the ComfyUI install, and `setup_models_flux_redux.py` was deleted.

### Also researched, not yet tried: FLUX IP-Adapter
Checked both real options before writing any code. **Neither supports the
regional/spatial masking this problem actually needs** (confining each
character's identity to its own part of the frame) — confirmed by reading
source, not just docs:
- XLabs-AI/x-flux-comfyui: attention-mask support was requested in
  [issue #120](https://github.com/XLabs-AI/x-flux-comfyui/issues/120)
  (Sept 2024), a maintainer said "we are going to do this," never shipped;
  repo has had no commits since Oct 2024 — abandoned.
- Shakker-Labs/ComfyUI-IPAdapter-Flux (InstantX's model, more recently
  active): `ApplyIPAdapterFlux`'s actual `INPUT_TYPES` only exposes `weight`
  and temporal (`start_percent`/`end_percent`) controls — no mask input.

Without spatial masking, two IP-Adapter references would condition the whole
image at once, same failure class as Redux just via a different mechanism.

### Leading candidate for next attempt: per-character LoRA + regional
conditioning ("Latent Couple"-style canvas-region splitting during sampling),
not reference-image conditioning at all. This is how the commercial AI-comic
platforms that have actually solved this (Dashtoon, ComicsMaker.ai) do it,
and it's this project's own already-documented Tier 3 — the strongest
consistency tier — just never applied to a *multi*-character scene before.
Architecturally the right shape for this problem either way: identity (LoRA)
and spatial placement (regional conditioning) are independently controllable,
unlike Redux/IP-Adapter's single global reference-image conditioning.

## [Unreleased] — Token-budget optimization pass (2026-07-26)

### Changed — trimmed `@mcp.tool()` docstrings in `server.py`
Every tool docstring is sent as that tool's `description` in the MCP schema on
every request where this server is connected — a recurring per-request cost,
not a one-time read (the same lesson `novel-translation-mcp` already
documented for its own schema trim, ARCHITECTURE.md §8a). Light-trimmed 10 of
21 tools (biggest cuts: `generate_character_pose` ~84→~58 lines,
`generate_reference_sheet` ~104→~62 lines), cutting restated/redundant
phrasing while preserving every distinct number, date, failure mode, and
rationale. 1546→1452 lines. Left untouched: the module-level top docstring,
inline code comments, and non-`@mcp.tool()` private helpers (e.g.
`_render_pose`) — none of these are part of the schema sent per-request, so
trimming them wouldn't have saved anything. `webcomic-background-mcp` and
`novel-translation-mcp` were not touched in this pass.

## [Unreleased] — Real Stage-6 run on Trevor + full-template reference sheet (2026-07-23/24)

### Added — `compose_full_reference_sheet()` (`tools/compose_sheet.py`)
A denser, bordered-box poster layout modeled on a real hand-composed Avery
reference sheet, alongside the existing simpler `compose_concept_sheet`:
scattered left/center/right columns instead of one stacked text column,
front+back shown side by side in one box, an "IN ACTION" pose row, one boxed
prop illustration, and a small ability-mechanism diagram box. Not yet wired
into `server.py` as an MCP tool — called directly from a script so far.
Deliberately does not model a stat block, personal quote, or mission
statement — no real data for those fields; don't invent filler (see
ARCHITECTURE.md §8b.11).

### Fixed — three real bugs found live during the first full real-character run
- **Turnaround-sheet proportions**: a short/wide canvas (1536×768) biases
  Kontext toward a squat figure regardless of the reference image's own
  proportions. Fixed by using a taller canvas (1536×1280) plus explicit
  "maintain scale and proportion" language in the prompt itself, not just the
  reference image.
- **Glasses missing/faint in some panels**: patching a bad turnaround sheet
  after the fact (whole-sheet edit, per-panel crop-and-paste) reliably failed
  or introduced new regressions in untouched panels. Fix was to bake the
  requirement into the main generation prompt and reroll fresh, not patch.
- **Expression thumbnails cropped off the chin**: `row_box()`'s square,
  top-anchored crop assumed roughly-square source images; a taller-than-wide
  source lost the bottom of the face. Added a `square=False` mode that scales
  to one shared height instead, preserving full aspect with no cropping.

### Added — `tools/bg_composite.py`, `compose_full_reference_sheet`, `apply_gradient_background` MCP tools
Tried a flat-cutout-plus-separate-illustrated-background approach first:
connected-component background detection correctly told a shirt apart from
a same-colored pose-gap (e.g. between crossed legs), but any pose with a
glowing VFX element (ice-magic burst, glowing book) kept showing a visible
halo — the glow renders as a genuine soft fade to white in the source art
with no hard edge to cut along. Decided illustrated backgrounds weren't
worth the time: plain white/gradient is the actual convention for model
sheets, not a compromise. **Plain two-color gradients work cleanly**,
including for glow poses, as long as the gradient is light-toned at the
point the glow fades into — pairing the ice-magic/glowing-book poses with
pale (winter/sunset-toned) gradients made the halo invisible, since it was
never about background vs. no background, only contrast between the glow's
white fade and whatever's behind it. Shipped as `tools/bg_composite.py`
(`extract_alpha`, `make_gradient`, `composite_on_gradient` — the illustrated-
background path was deliberately NOT carried over, see its module
docstring) plus two new MCP tools: `compose_full_reference_sheet` (wraps
`compose_sheet.py`'s new bordered-box poster layout, §8b.11) and
`apply_gradient_background`. Trevor's sheet ships with gradient backgrounds
(front=dusk, back=night, expressions=dusk/night/winter, action
poses=sunset/winter). The illustrated-scene-compositing problem is
real and left for whenever panel generation (character composited into an
actual scene) is built properly, where it can be solved by generating the
effect within the conditioned scene directly rather than cutting it from a
white-background render. See ARCHITECTURE.md §8b.11 for the full
step-by-step recipe, meant to be repeated for Lumiere.

## [Unreleased] — VRM depth-map ControlNet: a more reliable direction fix (2026-07-22/23)

### Added — `generate_pose_depth_map`, `pose_control_type="depth"`
A second, more reliable direction-control mechanism alongside Stage 5's
mannequin-skeleton ControlNet path, built from a real posable VRM mesh
(`assets/Base_Male.vrm`) rendered in Blender rather than a line skeleton.
New `vrm_depth.py` drives a separate Blender install (portable Blender 5.2
LTS + the community VRM Add-on — NOT pip-installable for this project's
Python 3.12, since the `bpy` pip package skips 3.12 entirely) via subprocess,
producing a depth map that `generate_character_pose`/`flux_workflow.py` can
use via the new `pose_control_type="depth"` parameter (default remains
`"openpose"`, the mannequin skeleton — nothing existing changes). New
`generate_pose_depth_map` MCP tool wraps it, mirroring `generate_pose_map`'s
shape.

**Result: ~3/3-seed direction-lock reliability, up from ~2/3** — but only
after fixing a real calibration bug (the depth remap's near/far window was
~8x too wide, producing a near-flat, low-relief map that looked clean but
gave the ControlNet almost no real structural information — the actual cause
of a hallucinated second head and other artifacts in initial testing, not a
ControlNet-strength problem). `type="normal"` was tested head-to-head and
dropped — same direction reliability, markedly worse costume coherence (one
seed's entire garment derailed into an unrelated robe).

**A second, distinct bug found and fixed**: the VRM mesh wears a plain
t-shirt, not any character's actual costume — describing a different outfit
in the prompt while conditioning on this mesh's depth silhouette causes a
text-vs-geometry conflict (ragged texture-clash artifacts). Fix: this mode's
prompt automatically excludes the character bible's `description` (costume
text) — use it for pose/anatomy only, then apply the real costume afterward
via `edit_character_image` as a separate pass. Validated end-to-end,
including catching and fixing a real logical error along the way (a necktie
rendered on the back of a back-view figure — a tie is front-only and
shouldn't be visible from behind at all) with a second, precise
`edit_character_image` call. See ARCHITECTURE.md §8b.10 for the full,
occasionally painful story (a lot of undocumented Blender 5.2 API churn
along the way — `Scene.node_tree`, `CompositorNodeMapRange`/`Math`, and
`CompositorNodeOutputFile`'s format-override handling all changed shape
since most available documentation was written).

`generate_reference_sheet` deliberately does NOT get `pose_control_type` —
it has no `pose_ref_path` parameter to pair it with; this is a manual,
curated flow (`generate_character_pose` + `generate_pose_depth_map` +
`edit_character_image`), not the bulk sheet tool.

## [Unreleased] — FLUX exploration + Stage 5: wired into the live tool (2026-07-21/22/23)

Motivation: 1.1.0's SDXL hand-anatomy fixes (CharTurn + RPGTurn + ClearHandsXL
LoRA stacking) plateaued — hands kept coming back deformed even fully stacked.
Prototyped FLUX.1-dev instead, GGUF-quantized (`flux1-dev-Q3_K_S.gguf`, ~5.0 GB,
via `ComfyUI-GGUF`) to fit the same 6 GB VRAM budget.

### Added — Stage 5: `model="flux_manwha"` + a staged concept-to-sheet workflow
The validated scratch-script recipe below is now real, callable code, not just
standalone test scripts. New `flux_workflow.py` (mirrors `workflow.py`'s shape
for FLUX's distinct ComfyUI graph — GGUF unet loading, dual CLIP encoders,
flux-specific sampling/guidance nodes — kept as a separate module rather than
threading a third graph convention through `build_graph()`, which is already
dense with SD1.5/SDXL/Tier-2 branches). `model="flux_manwha"` works anywhere a
model name is accepted (`generate_character_concept`, `generate_character_pose`,
`generate_reference_sheet`), routed via `_render_pose`'s new FLUX branch;
`identity_mode`/IP-Adapter raises a clear error if requested with FLUX (that
combination has never been tested). Three new tools complete the staged
workflow the validated stages actually call for: `generate_turnaround_sheet`
(FLUX Kontext dev + the turnaround-sheet LoRA, reading a character's registered
reference), `edit_character_image` (FLUX Kontext dev as a general-purpose
plain-English editor — the validated local-anatomy-fix mechanism), and
`compose_reference_sheet` (assembles the Avery-style poster from
already-existing images — e.g. panels `crop_reference` sliced out of a
turnaround sheet — rather than generating fresh views the way
`generate_reference_sheet` does). SDXL/SD1.5 are completely untouched; this is
purely additive, same non-migration philosophy as the SDXL prototype.

Validated in standalone scratch scripts before being ported into the above:
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

Explicitly still deferred: deleting the ~12.5 GB of SDXL-era files (checkpoint,
LoRAs, IP-Adapter, ControlNet) — held until the live tool above gets real
end-to-end use, not just an import-time smoke test; tuning the turnaround-sheet
LoRA's reliability further (one confirmed clean seed, not yet a measured rate);
any FLUX/SDXL upgrade decision for the sibling `webcomic-background-mcp` server
(still SD1.5, no demonstrated problem there — a separate investigation).

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
