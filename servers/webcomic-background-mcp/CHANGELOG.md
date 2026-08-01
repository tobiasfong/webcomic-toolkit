# Changelog

All notable changes to the Webcomic Background Generator MCP server are documented
here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> As of v1.7.0 this server lives in the [`webcomic-toolkit`](https://github.com/tobiasfong/webcomic-toolkit)
> monorepo (`servers/webcomic-background-mcp`) alongside its sibling servers; releases
> are tagged `webcomic-background-mcp@vX.Y.Z` there. v1.0.0–v1.6.0 were released from
> the standalone (now archived) repo.

## [1.9.0] — 2026-07-28

FLUX.1-dev as an optional second base model, and a real sketch-input bug fix.

### Added
- **`flux_workflow.py` + `model="flux_manwha"`** — FLUX.1-dev (GGUF Q3_K_S, to
  fit 6 GB VRAM) available anywhere a model name is accepted, across
  `generate_background`, `generate_city_scene` and `generate_prop_scene`.
  Purely additive: SD 1.5 is untouched and remains the default. FLUX's graph
  shares almost no node types with SD 1.5 (GGUF unet, dual CLIP encoders,
  flux sampling/guidance, `cfg=1.0`), so it is a separate module rather than
  more branches in `build_graph()` — same call the sibling character-panel
  server made. Uses Union Pro 2.0 ControlNet (`type="auto"` — Pro 2.0 dropped
  the alpha's per-type embedding, which also retires the old "scribble has no
  FLUX equivalent" problem).
- **Measured ControlNet window for FLUX** (8-render sweep, fixed seed, against
  a `props.py` bike-row sketch). The dominant variable is **`end_percent`, not
  strength** — FLUX keeps injecting the edge map's luminance through the
  colour phase, so releasing it early is what yields solid painted objects
  instead of glowing white outlines on near-black. Ships 0.95 strength /
  0.40 end for synthetic geometry. SD 1.5's tuned values (0.6 / 0.75) are
  deliberately **not** forwarded to FLUX — they produce ghosts.
- LoRA note: `ManhwaUltimate` is SD 1.5 and cannot load on FLUX at all; the
  FLUX path uses `manwha_style` at strength **1.5** (1.0 loses the fight
  against ControlNet conditioning and renders washed out).

### Fixed
- **`tools/make_sketch.py` doubled every stroke of a hand-drawn sketch.** Canny
  detects *both* sides of a pencil line, so one drawn stroke became two
  parallel control edges and the model painted the doubled hairlines literally
  (plus a desaturated frame). Photos and 3-D renders were never affected —
  their edges are single region boundaries — but hand-drawn input is squarely
  on the roadmap (mecha/kaiju), so this mattered. `make_sketch.py` now
  auto-detects line art and **binarizes** it instead (threshold 215, not a
  conventional 128 — hand sketches are faint), with `--mode photo|drawing` to
  override. Verified: Canny yields 2 control lines across one drawn stroke,
  binarize yields 1. Credit to the character-panel server, which diagnosed
  this first (`tools/sketch_to_lineart.py`).

### Notes / honest limits
- **FLUX composition hold is approximate, not exact.** SD 1.5 at 0.95 reproduces
  a `props.py` sketch near-exactly; FLUX lands close but drifts — a live
  `generate_prop_scene(n_bikes=4)` run painted one bicycle. Expect rerolls when
  exact count/placement matters. Same alpha-ecosystem limitation the character
  server measured for direction lock.
- **What FLUX clearly wins:** object geometry. Bicycles come out with correct
  frames, two wheels, spokes, saddles and baskets — the failure that consumed a
  whole session on SD 1.5 in v1.8.0.
- **`character_path` is SD 1.5 only** — that mode is a two-pass inpaint that has
  never been ported to FLUX; requesting it with a FLUX model raises rather than
  silently ignoring the argument.
- Speed: ~100–150 s per FLUX plate vs ~20–40 s on SD 1.5, on a 6 GB RTX 3060
  Laptop. Fine for finished plates, noticeable when iterating.

## [1.8.0] — 2026-07-18

Props: the citygen treatment, extended from buildings to objects.

### Added
- **`props.py`** — parametric 3D prop meshes placed in-scene and rendered
  headless to a ControlNet sketch, exactly like `citygen.py` does for
  buildings: real geometry, real camera, real occlusion (painter's algorithm),
  one coherent Canny sketch — SD only paints. World scale matches citygen
  (1 unit ≈ 0.37 m), so props drop into city scenes at correct size. First
  prop: **bicycle** (thin-tired, true diamond frame, straight T-bar above the
  saddle), plus a `shelter` setting (wall + posts + roof carport) and an
  **auto-framing camera** that fits every prop vertex in-frame — eyeballed
  cameras kept clipping wheels.
- **`generate_prop_scene` tool** — paint a prop scene with the manhwa recipe.
  `objects=[{type,x,z,yaw,scale}]` for explicit placement or `n_bikes=` for a
  realistic parked row (rack spacing, per-bike yaw jitter). ControlNet default
  0.75 (props need a firmer hold than city vistas' 0.6; 0.85+ still goes cel).

### Why (a war story)
A real panel — "character waving at a bicycle parking lot" — burned a whole
session proving that diffusion cannot be prompted into correct repeated-object
geometry: photo-edge sketches fused nine bikes into a tangle; img2img from the
photo made wheelchairs; hand-drawn 2D circle sketches made one-wheeled
half-bikes; sprite-cloning a good bike made a "bicycle train." Every failure
was geometry, and every geometry problem this server has ever solved was
solved the same way: build it in 3D, render it headless, let SD paint.
Lessons baked in: flat cutout props collapse edge-on (keep the camera ≥ ~25°
off their plane — enforced by yaw jitter + a documented camera floor);
per-mesh grey separation is what keeps neighbouring props Canny-separable; and
a straight T-bar reads as a handlebar where a curved drop-bar hook kept being
painted as a second saddle.

## [1.7.0] — 2026-07-10

### Added
- **Niji V5 Style LoRA** documented and added to `setup_models.py` as an
  optional style choice — `lora="NijiV5Style.safetensors"` (trigger word
  "midjourney"), for stories wanting a strong East-Asian architectural bias
  (pagodas, lanterns). Selectable per-call via the existing `lora` argument, no
  code changes needed — this release is documentation/installer only.
- Considered and **rejected**: Midjourney Manga Art Style LoRA (SDXL-only,
  incompatible with this server's SD 1.5 stack) and Vivid Midjourney Mimic
  (general Midjourney-photoreal mimic, not manga-specific; superseded by the
  already-tuned v1.3.0 recipe for the "picture-book" color problem).
- A/B tested against the existing ManhwaUltimate recipe on the same city
  sketch/seed: Niji V5 Style pulls architecture toward pagodas/lanterns even
  against a gothic ControlNet sketch — a poor fit for Starry Knight's grimdark
  hive city, but a good fit for Reincarnator x Regressor's setting.

## [1.6.0] — 2026-07-08

### Added
- **Character placement anchor** — `generate_city_scene(anchor_x=, anchor_z=)`
  places a human-scale (≈4.6 world units) box at that spot in the 3D city and
  writes an occlusion-aware mask (white = where the character stands; buildings
  in front hide it) alongside the sketch, plus reports the on-screen pixel
  height and feet line at the hires output resolution. The artist knows exactly
  how large to draw the character and where it sits in the scene's perspective —
  the inverse of the existing `character_path` mode.

## [1.5.1] — 2026-07-05

### Fixed
- **`tools/parallax.py` now encodes web-ready MP4s** — H.264 / yuv420p with
  `+faststart`, via `imageio-ffmpeg` (bundles its own ffmpeg). The previous
  OpenCV `mp4v` output played in desktop players but not in browsers. Frame
  dimensions are forced even (a yuv420p requirement).

## [1.5.0] — 2026-07-05

Parallax: still illustrations become subtle 2.5D motion clips for promo videos.

### Added
- **`tools/make_depth.py`** — estimate a depth map from any illustration or
  background plate via the Depth-Anything V2 preprocessor in the local ComfyUI
  install (no new Python dependencies; the model auto-downloads, or place
  `depth_anything_v2_vitl.pth` under the controlnet_aux `ckpts/` manually if the
  auto-download flakes).
- **`tools/parallax.py`** — render the illustration + depth map into a
  camera-drift clip: near pixels shift more than far ones, so flat art gains
  depth — the signature webnovel-promo-short look. Four motion presets
  (`push`, `pan`, `drift`, `lift`), tunable duration/fps/strength, MP4 output
  with an optional preview GIF. Clips are ingredients for a video pipeline
  (e.g. Remotion) to assemble with music and text.

### Fixed
- Unique per-call output prefixes when talking to ComfyUI — resubmitting an
  identical graph was served entirely from ComfyUI's cache, recording no output
  and failing the poll.

## [1.4.0] — 2026-07-03

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

## [1.3.0] — 2026-07-02

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

[1.9.0]: https://github.com/tobiasfong/webcomic-toolkit/releases/tag/webcomic-background-mcp%40v1.9.0
[1.8.0]: https://github.com/tobiasfong/webcomic-toolkit/releases/tag/webcomic-background-mcp%40v1.8.0
[1.7.0]: https://github.com/tobiasfong/webcomic-toolkit/releases/tag/webcomic-background-mcp%40v1.7.0
[1.6.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.6.0
[1.5.1]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.5.1
[1.5.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.5.0
[1.4.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.4.0
[1.3.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.3.0
[1.2.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.2.0
[1.1.1]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.1.1
[1.1.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.1.0
[1.0.0]: https://github.com/tobiasfong/webcomic-background-mcp/releases/tag/v1.0.0
