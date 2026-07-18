# Changelog

All notable changes to the Character & Panel Generator MCP server are documented
here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This server lives in the [`webcomic-toolkit`](https://github.com/tobiasfong/webcomic-toolkit)
monorepo (`servers/character-panel-mcp`) alongside its sibling servers from day one;
releases are tagged `character-panel-mcp@vX.Y.Z`.

## [1.2.0] — 2026-07-18

### Added
- **`bake_character_lora` now bakes the Niji V5 Style LoRA into every character
  LoRA by default** (`style_lora` param, defaults to `NijiV5Style.safetensors`) —
  matches the ecosystem's existing per-project style pool
  (`webcomic-background-mcp` v1.7.0), so baked characters carry the project's
  usual style without needing `lora=` at every generation call. Mechanism:
  sd-scripts' `--base_weights`/`--base_weights_multiplier`, which merges an
  existing LoRA into the checkpoint *before* training starts (verified flag,
  distinct from `generate_character_pose`'s `lora=`, which applies a style LoRA
  at generation time instead). Pass `style_lora=""` to bake against a plain
  checkpoint. New env vars: `WEBCOMIC_CHAR_BAKE_STYLE_LORA`,
  `WEBCOMIC_CHAR_BAKE_STYLE_LORA_MULTIPLIER`.

## [1.1.0] — 2026-07-18

### Added
- **Tier 2 — IP-Adapter identity + OpenPose ControlNet**, layered onto
  `generate_character_pose` as opt-in params (`identity_mode="plus"`/`"plus_face"`,
  `pose_ref_path`) rather than a new tool — additive on top of Tier 1's existing
  img2img mechanism, off by default so existing callers are unaffected. Uses
  `cubiq/ComfyUI_IPAdapter_plus` (`IPAdapterUnifiedLoader`/`IPAdapter`) and the
  `OpenposePreprocessor` node from `comfyui_controlnet_aux` (already required by
  `webcomic-background-mcp`, so only the IP-Adapter node is a new custom-node
  install for anyone with both servers). Deliberately ships `"plus_face"` instead
  of true FaceID — avoids an InsightFace/`antelopev2` install, a known-fiddly
  dependency on Windows — documented as a conscious substitution.
- **`setup_models.py`** (new) — downloads the Tier-2 models (CLIP vision encoder,
  IP-Adapter Plus + Plus Face, ControlNet OpenPose), mirroring
  `webcomic-background-mcp`'s downloader.
- **Tier 3 — per-character LoRA baking**, via three new tools:
  `bake_character_lora`, `check_lora_training`, `cancel_lora_training`. Training
  (kohya-ss/sd-scripts, `accelerate launch train_network.py`) takes 30-90 min, so
  this is **async by construction**: `bake_character_lora` prepares a dataset and
  launches a detached background process, returning immediately; the other two
  poll/cancel it. A finished LoRA is auto-installed into ComfyUI's `models/loras/`
  and recorded on the character's bible entry — `generate_character_pose` uses it
  automatically from then on, with no new args needed at generation time (the
  concrete implementation of the "bootstrap loop" design: curated Tier-1/2 renders
  fed back via the existing `register_character` become training data for a re-bake).
- **`training.py`** (new module) — dataset prep (fixed trigger-token + class-word
  captions, not per-image auto-captioning — a deliberate scope decision, not a
  gap), command construction, and the async job lifecycle (`bake`/`status`/`cancel`),
  mirroring `workflow.py`'s detached-subprocess pattern for auto-launching ComfyUI.
- New env vars for Tier 3: `WEBCOMIC_CHAR_COMFY_MODELS`, `WEBCOMIC_CHAR_KOHYA_DIR`,
  `WEBCOMIC_CHAR_KOHYA_PYTHON`.

### Verification note
Tier-2 graph construction and Tier-3 dataset-prep/command-building/job-lifecycle
logic are unit-tested (including with a stub trainer standing in for kohya-ss).
Live IP-Adapter/OpenPose generation against a running ComfyUI, and a real kohya-ss
training run, were not exercised in this release — verify end-to-end on next real use.

## [1.0.0] — 2026-07-18

### Added
- **Character Bible** (`register_character`, `list_characters`, `forget_character`,
  `list_projects`) — the character-domain sibling of `webcomic-background-mcp`'s
  World Builder. Unlike a location's single canonical image, a character has a
  *set* of reference images (turnarounds, expression sheets); re-registering an
  existing character appends to the set instead of replacing it.
- **`generate_character_pose`** — Tier 1 of the three-tier consistency design
  (img2img seeded from the character's primary reference, onto a clean backdrop),
  auto-matted to RGBA via `rembg`.
- **`compose_panel`** — deterministic CPU compositing of a matted character onto a
  background plate, feet-anchored (`feet_x`/`feet_y`/`height_px`) to match the
  exact shape `webcomic-background-mcp`'s `generate_city_scene` anchor tool already
  reports, so the two servers' outputs chain directly. Supports multi-character
  panels by chaining calls (`base=<previous output>`).
- **`check_status`** — ComfyUI reachability check, same as the background server.
- Tier 2 (IP-Adapter + OpenPose ControlNet) and Tier 3 (per-character LoRA baking)
  are designed but deliberately not built this release — see README.md's
  "Consistency tiers" section.
