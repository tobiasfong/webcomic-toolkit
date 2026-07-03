# Changelog

All notable changes to the Webcomic Background Generator MCP server are documented
here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] — 2026-06-30

The growable city: World Builder's persistent 3D model.

### Added
- **Persistent city plans** — each project can now own a *growable 3D city*:
  `world/<project>/city_plan.json`, a small human-readable list of districts
  (each with its own seed, position, and parameters). The plan — not a mesh
  file — is the editable master: meshes are rebuilt from it on every render,
  so the city can start as one neighborhood and grow district by district while
  every earlier district re-renders identically. The 2D locations registered in
  the bible are snapshots *of* the plan; the plan is the structural truth.
- **`add_city_district` tool** — grow the city by one district: `old_city`
  (flanked avenue converging on a cathedral + skyline; a good founding core) or
  `block` (rectangular building fill with size/tier/density/landmark knobs).
  Updating an existing district never re-rolls its seed.
- **`list_city` tool** — show a project's plan.
- **Plan rendering** — `generate_city_scene(use_plan=True, focus="<district>")`
  renders the persistent city instead of a one-shot seed, with the camera
  presets re-aimed at any district (or the whole-city centroid).

## [1.3.0] — 2026-06-30

"Metropolis mode": giant city establishing panels from a procedural 3D city,
plus the tuned manhwa render recipe as first-class parameters.

### Added
- **`generate_city_scene` tool** — builds a seeded, reproducible 3D gothic city
  (street canyon converging on a landmark cathedral, layered skyline), renders it
  **headless** (a small software rasterizer in `citygen.py` — no GPU, no browser,
  no 3D engine) to a flat lineart pass, extracts a Canny composition sketch, and
  paints it with the validated manhwa recipe. Same `city_seed` = same city from
  any `camera` (vista / high / canyon / street) — structurally consistent giant
  panels across a story. Best for wide establishing shots.
- **Per-call LoRA** — `lora` / `lora_strength` arguments on `generate_background`
  (and the workflow API), overriding the `WEBCOMIC_BG_LORA` env default. Pass
  `""` to force a LoRA off for one call.
- **Hi-res finishing pass** — `hires=True` upscales the base render 1.5× (lanczos)
  and re-details it with a light img2img pass (denoise 0.35). Fixes the softness
  of dense architectural panels at native SD1.5 resolution. Default-on for city
  scenes, opt-in elsewhere.

### Changed
- The tuned "manhwa background" recipe is baked into city scenes: manhwa LoRA +
  ControlNet 0.6 + webtoon prompt/negative language. (High ControlNet strength on
  hard synthetic edges was the cause of the flat "comic book" look.)

### Notes
- Palette guidance: derive prompt color language from reference images — the
  World Builder's palette extractor (`world._extract_palette`) reads dominant hex
  colours from any reference for the harness to translate into prompt words.
  Validated: one 3D city rendered in three completely different reference-derived
  moods while staying structurally identical.

## [1.2.0] — 2026-06-28

### Added
- **Multi-project support.** A `project` argument on `generate_background`,
  `register_location`, and `list_world` namespaces the World Builder canon and the
  output folder per comic, so the same location id (e.g. `academy`) in different
  comics never collides. Canon lives under `world/<project>/`, renders under
  `output/<project>/`. References (the shared sketch library) are NOT namespaced.
  New `list_projects` tool lists comics that have a bible. Default project is
  `WEBCOMIC_BG_PROJECT` or `"default"`.

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

[1.4.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.4.0
[1.3.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.3.0
[1.2.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.2.0
[1.1.1]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.1.1
[1.1.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.1.0
[1.0.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.0.0
