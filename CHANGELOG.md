# Changelog

All notable changes to the Webcomic Background Generator MCP server are documented
here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] — 2026-06-27

World Builder tuning and two fixes found while validating it.

### Changed
- **Default `location_denoise` is now 0.65** (was 0.55), after sweeping 0.35–0.75
  against a test canon. Validated band: 0.40–0.48 relight / hugs the canon;
  0.52–0.58 new lighting or time of day; 0.65 a new angle with richer variation
  while staying on-location; ≥0.70 drifts off the location and the checkpoint's
  character bias returns. The tool docstring documents this band.

### Fixed
- **Output filename collision** — same-seed renders (e.g. a fixed-seed denoise
  sweep) overwrote each other at `background_{seed}.png`. A numeric suffix is now
  added when the name already exists.
- **Stray figures in World Builder mode** — partial img2img denoise let the manhwa
  checkpoint reassert its character training and drop a figure into the scene. A
  reinforced figure-suppression negative is now appended automatically whenever a
  location reference is used.

## [1.1.0] — 2026-06-25

The first major iteration since launch: a more authentic, model-native manhwa look,
and a "World Builder" layer that keeps backgrounds consistent across panels.

### Added
- **World Builder** — a persistent "bible" of established locations. Register an
  approved background as canon (`register_location`), then generate new panels of that
  place with `generate_background(location=...)`; the saved image seeds the render
  (img2img) so the same street stays the same street across the story. List the world
  with `list_world`. Storage is a `world/` folder of canonical PNGs plus a
  `world/world.json` manifest.
- **Selectable render models** — choose `solstice` (Korean manhwa), `counterfeit`
  (clean anime), or `dreamshaper` (soft painterly) per call via the `model` argument
  or the `WEBCOMIC_BG_MODEL` env var, each paired with the correct VAE.
- **Optional style LoRA** — apply a trained style (e.g. a manhwa LoRA) on top of any
  model via `WEBCOMIC_BG_LORA` / `WEBCOMIC_BG_LORA_STRENGTH`.
- **Auto-launch** — the server starts the local ComfyUI backend itself if it isn't
  already running, so any MCP client works without manual setup.
- **`setup_models.py`** — one-command downloader for all required checkpoints, VAE,
  ControlNet, and LoRA (~10 GB), skipping files already present.
- **`tools/inpaint_region.py`** — figure-removal utility to paint a stray character out
  of a finished plate (manhwa checkpoints are character-trained and sometimes add one).

### Changed
- **Model-native aesthetic** — removed the IP-Adapter style-reference path. A checkpoint
  trained on the target look renders the manhwa style more cleanly; palette and mood are
  now directed entirely through the prompt.
- **Character mode returns a true background plate** — the character workflow is now a
  two-pass inpaint that uses the drawn character only as a spatial guide (scale, horizon,
  camera angle) and returns the scene with the character **absent**, sized to the canvas,
  ready as its own layer.
- **Stronger default negative prompt** to suppress unwanted figures in open scenes.
- **Repository renamed** from `Warhammer40000-background-mcp` to reflect the broader,
  any-aesthetic scope (the tool is for all webcomic artists, not only Warhammer 40,000).

### Removed
- IP-Adapter and CLIP-vision dependencies, and the `style_ref_path` / `ipa_weight`
  arguments — no longer needed now that the aesthetic comes from the checkpoint.

### Roadmap
- Tune the World Builder consistency control (`location_denoise`) against real panels.
- A depth-map pass (Depth-Anything) for subtle parallax on finished plates.
- A possible "Asset Stylizer" mode: a photo of a physical miniature (tank, Imperial
  Knight) → stylized 2D render, for consistent mechanical subjects.
- The previously-planned 3D Blender tool was **dropped** — World Builder delivers the
  cross-panel consistency it promised, in 2D, without hand-building a 3D city.

## [1.0.0] — 2026

Initial release.

### Added
- MCP server (`generate_background`) wrapping a local ComfyUI + Stable Diffusion 1.5
  pipeline, running on the user's own GPU — no cloud, no per-image cost.
- ControlNet composition control from a perspective sketch.
- Character-conditioned generation to plan a background around a drawn character.
- `check_status` tool and a full setup guide in the README.

[1.1.1]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.1.1
[1.1.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.1.0
[1.0.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.0.0
