# Character & Panel Generator — MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server for **writers
who aren't artists** — and for artists who'd rather not redraw the same character six
times before page one. Whether you already have reference art (commissioned, or a
ChatGPT/Midjourney character sheet), have a story and nothing else, or have one good
drawing of a character, this tool gets it into a **Character Bible**, generates new
poses and turnaround views that stay recognizably the same character, and composites
them onto background plates into finished panels — wrapping a local ComfyUI + Stable
Diffusion pipeline.

It's the character-domain sibling of
**[`webcomic-background-mcp`](../webcomic-background-mcp/README.md)**'s World Builder:
same philosophy (**reference-driven, never generate-from-text-and-pray** — the
references are the ground truth for who a character is), same skeleton, same README
standard. No code dependency between the two servers; they just point at the same
local ComfyUI by default.

## What it does

Seventeen tools:

- **`register_character`** — add (or grow) a character's reference set in the bible.
  Accepts one or more images at once; calling it again on the same character
  **appends** more references rather than replacing them.
- **`list_characters`** / **`forget_character`** / **`list_projects`** — browse and
  curate the bible. Projects namespace characters per-comic, same as World Builder.
- **`generate_character_concept`** / **`crop_reference`** / **`generate_reference_sheet`**
  — **Concept Genesis**: get a character into the bible in the first place (see
  below), whether you're starting from nothing, a composite sheet, or one drawing.
- **`generate_pose_map`** — synthesize an OpenPose control map from a posable 3D
  skeleton at any angle (front, side, **genuine back view**), for when a text
  prompt or a 2D reference photo can't force the direction (see below).
- **`generate_character_pose`** — render the character in a new pose, layering all
  three consistency tiers (see below), auto-matted to a clean RGBA cutout.
- **`generate_turnaround_sheet`** / **`edit_character_image`** / **`compose_reference_sheet`**
  — FLUX-only staged workflow (Step 9 below): a multi-pose turnaround sheet from
  one reference image, a plain-English image editor for surgical anatomy fixes,
  and a poster composer that works from already-existing crops.
- **`bake_character_lora`** / **`check_lora_training`** / **`cancel_lora_training`**
  — Tier 3: kick off, poll, and cancel per-character LoRA training (async — a bake
  takes 30-90 min, so these don't block).
- **`compose_panel`** — deterministic CPU compositing: paste a matted character onto
  a background plate at a given feet position and height. Zero GPU, zero tokens,
  instant to iterate.
- **`check_status`** — is the ComfyUI backend up? (Only tools that generate pixels
  need it — the bible, `crop_reference`, and `compose_panel` are GPU-free.)

## Consistency tiers

Character consistency is *the* unsolved-in-general problem of AI comics. This server
is designed around three tiers, shipped in order of cost/complexity, and they
**stack** — Tier 1 is always on, Tier 2 is opt-in per call, Tier 3 (once baked) is
used automatically:

| Tier | Mechanism | Status |
|------|-----------|--------|
| **1 — img2img from a reference** | Seed the render with the character's primary reference image (like World Builder's `location_denoise` mode). Good for "same character, slightly different angle." Drifts on anything ambitious. | ✅ **Shipped** |
| **2 — IP-Adapter identity + ControlNet OpenPose** | IP-Adapter conditions generation on the reference images' *identity* (`identity_mode="plus"` or `"plus_face"`); an OpenPose ControlNet pins the *pose* from a supplied photo, or a synthesized map from `generate_pose_map` (`pose_ref_path`). | ✅ **Shipped** — needs the Tier-2 models (`setup_models.py`) + the `ComfyUI_IPAdapter_plus` custom node |
| **3 — per-character LoRA baking** | Train a small SD 1.5 LoRA on the character's reference set (`bake_character_lora`, via kohya-ss/sd-scripts). Strongest, one-time cost per character (~30-90 min on a 3060-class GPU). Once baked, used automatically by `generate_character_pose`. **Bakes in the Niji V5 Style LoRA by default** (merged into the checkpoint before training via sd-scripts' `--base_weights`) — pass `style_lora=""` to train against a plain checkpoint instead. | ✅ **Shipped** — needs a separate kohya-ss install, the heaviest setup step |

**Not built: true FaceID.** Tier 2's `"plus_face"` preset (from `h94/IP-Adapter`
directly) covers face-focused portraits without extra install burden. True FaceID
models need InsightFace + the `antelopev2` face-embedding model — a notoriously
fiddly Windows install with its own distribution terms. Deliberately substituted,
not silently dropped; revisit if `"plus_face"` proves insufficient in practice.

**"Consistent enough for a webtoon with curation," not pixel-perfect** — even the
strongest tier drifts on extreme angles, complex hand poses, and costume details. The
writer curates; the tool narrows the drift, it doesn't eliminate it.

**Cross-cutting fix, not a tier: `detail_fix`.** Hallucinated hands (missing/extra
fingers) and mangled faces aren't a consistency problem — they're a *resolution*
problem: a face or hand is a small fraction of a full-body frame, too few pixels for
the checkpoint to render correctly, no matter how good the prompt or which tier is
active. `detail_fix=True` on `generate_character_pose`/`generate_reference_sheet`
detects the face and hands (ComfyUI-Impact-Pack's `FaceDetailer` + the YOLOv8
detector models) and re-samples just that region at a much higher effective
resolution before compositing it back — the standard fix for this class of failure.
Verified live (2026-07-20): a closed-fist hand that rendered as a featureless blob
came out with real finger separation after this pass, at `denoise=0.6` (0.45 detected
the hand but didn't give the sampler enough freedom to fix it — this took an actual
before/after comparison to find, not assumed). Off by default — needs the extra
custom nodes (see Step 3) and roughly doubles generation time.

## Concept Genesis: getting a character into the bible

Everything above assumes a character is already registered. Concept Genesis is the
on-ramp — **three starting points, all converging on the same reference-growth tool**:

| You have... | Use | Then |
|---|---|---|
| A story, no art at all | `generate_character_concept` — batch txt2img candidates from a text description | Pick the winner, `register_character` it |
| A composite concept sheet (ChatGPT/Midjourney sheet generator — hero pose + expressions + text overlay, all one image) | `crop_reference` — slice it into clean single-view crops | `register_character` the crops |
| One finished drawing of your own character | Nothing — `register_character` the drawing directly | Straight to `generate_reference_sheet` |

All three land in the same place: `generate_reference_sheet` grows a registered
character's reference set toward a standard turnaround checklist (front view, back
view, a few 3/4 expression close-ups — modeled on Tobias's friend Avery's own
hand-composed character sheets), one Tier-2 identity-locked generation per view.

**Generation is a disciplined sequence, not N independent dice rolls.** Regardless of
the order views are requested in, the front view always renders first, then the back
view, then expressions. Once the front view succeeds, the **back view** (only) is
anchored (img2img seed + IP-Adapter identity) to that freshly-generated, already-in-
style image instead of the bible's raw source photo, for costume/color continuity.
Expression/face close-ups deliberately do NOT chain off the front view — an early cut
of this feature chained everything, and live testing caught it fast: a "smiling
close-up" request came back as a repeat of the front view's full-body pose, because
IP-Adapter conditions on the whole reference image, not just "this person's face."
Close-ups use the bible's own primary reference instead. If the front view fails, the
back view falls back to that too.

**Honest limitation, found and NOT solved despite trying:** genuine back views remain
unreliable here. Automatically wiring in the 3D mannequin's ControlNet pose map for
the back view was tried and reverted — forcing `identity_mode="off"` to stop
IP-Adapter fighting the pose did get back-facing content into frame, but
full-resolution review (hands and feet specifically, not just "does it face
backward") found it came with a fused hand and hoof-like feet, and retrying reproduced
the same failure. Reverted rather than ship a mechanism that trades wrong-direction
for deformed. If you actually need a back view, use `generate_pose_map` +
`generate_character_pose` directly and curate across a few seeds by hand (see below)
— a reviewed one-at-a-time flow, not something safe to fire unattended in bulk.

By default all views are also laid out on one poster-style reference sheet (title,
large front-view hero pose, back-view panel, a labeled row of expression close-ups,
and short text blocks — see below) via `compose_sheet.py`'s `compose_concept_sheet`
(zero GPU, deterministic PIL, Noto Sans JP so Japanese text renders correctly) — the
individual files are still what you pass to `register_character`. You curate the
keepers and register them in — the same append-on-reregister behavior every tier
already relies on.

**Three text fields, shown on the sheet, deliberately far shorter than Avery's own
sheets** (no bio paragraphs, no quotes, no lore boxes — this server generates panels,
it doesn't write your story):

| Field | What goes here |
|---|---|
| `profile` | Who they are — role in the story, standing/affiliation, personality, and (if relevant) Japanese speech patterns: register (丁寧語 vs 普通語) and self-referential pronoun (僕/俺/私/あたし/わし/吾輩/etc.) |
| `abilities` | Powers/skills/equipment, as much or as little as you want |
| *(shown as "Appearance")* | This is `description` itself, not a separate field — hair/eye color, build, costume. It already drives generation prompts; showing it on the sheet too means it's written once, not twice. If you're ingesting an artist's own drawing and they already wrote appearance notes somewhere (a markdown file, a caption), pass that text straight into `description` rather than asking them to retype it. |

**Write a real `description` before generating a sheet.** This turned out to matter
more than expected: without visual detail in the character's bible entry (hair/eye/skin
color, build, costume colors — see `register_character`'s docstring), the text prompt
has nothing to anchor identity with, and the tool leans entirely on the reference
image — dragging its *exact* pose and background along too, not just the character.
`register_character(..., description="...")` fixes this at essentially zero cost.

**For artists specifically** (this tool started life solving Tobias's own "I need to find
a more efficient way of drawing the same character multiple times in several different angles"
problem): register your one drawing, then `generate_reference_sheet` answers the
rotational questions — what does the back of the outfit look like, how does the
silhouette read from the side — as **reference to draw from**, not final art. The
output renders in the checkpoint/LoRA's style, not yours, so treat it the way you'd
treat a 3D model turntable: a spatial answer key, not the page art itself. Pass
`lora=""` if you don't want the Niji V5 style fighting your own art direction, and
feed in a clean full-body drawing on a plain background — it conditions far better
than a busy illustration.

**Nothing auto-registers, ever.** `generate_character_concept` and
`generate_reference_sheet` only ever produce candidates for you to look at — the same
staging discipline as `bake_character_lora` never auto-training on garbage refs.
A human always picks the canon.

**Honest caveat:** genesis is bootstrapped, not solved. The very first image (or your
own drawing) is the only ground truth; every other view is Tier-2 *inference* from it,
which means back/side views of a character who only exists as one front-view image
will drift and need retries. This is exactly what curation is for — and once you've
accumulated ~10-20 curated views, `bake_character_lora` locks in the strongest version
of what you approved.

**Real-world tuning note (2026-07-19, from an actual test against RxR art):**
`generate_reference_sheet`'s original defaults (`ip_adapter_weight=0.8`,
`ref_denoise=0.7`) let a busy source illustration (dynamic pose, VFX) dominate every
view regardless of the requested angle or the clean-backdrop prompt — every "view"
came back as a near-identical re-roll of the source composition, VFX and all, and
two people occasionally appeared in one frame. Fixed in three steps: `ref_denoise=1.0`
and `ip_adapter_weight=0.25` (much lower — identity now leans on a real `description`
instead of the reference's whole scene), explicit VFX-suppression terms and a `solo`
tag added to `workflow.py`'s clean-backdrop prompt/negative globally (not just for
sheets), which also fixed the two-people artifact. Backdrop cleanliness and identity
consistency are now solid — but **genuine back-view turnarounds remain unreliable**
even with all of this fixed: "back view" reliably renders a different 3/4-ish angle,
not an actual view from behind. This looks like a real limitation of this SD1.5
checkpoint for non-front angles, separate from the composition-anchoring bug above
and not solved by further prompt/weight tuning. For a back view you actually need,
`generate_character_pose`'s `pose_ref_path` (an actual back-facing photo, via
OpenPose) forces the angle structurally instead of hoping the prompt gets there.

## Genuine back views: the 3D mannequin

A text prompt saying "back view" and a real photo fed through OpenPose both hit
the same wall: the checkpoint can paint back-body geometry, but the *pose
conditioning itself* never unambiguously says "this is the back" — a 2D photo's
skeleton is *extracted* by guessing left/right limb assignment from appearance,
which has no way to encode facing-away-from-camera, so every clean single-figure
result relaxes back toward front/profile. (~12 tuning configurations confirmed
this the hard way — see CHANGELOG's "back-view campaign.")

`generate_pose_map(preset, yaw)` sidesteps extraction entirely: it poses and
rotates a 3D skeleton, then projects it straight into an OpenPose-format map.
At `yaw=180` the left/right limb colors flip and the face keypoints vanish —
exactly like a real back-view annotation, because it's built from an actual 3D
angle instead of guessed from a flat image. Feed the result to
`generate_character_pose(pose_ref_path=<map>, pose_preprocess=False, pose_strength=1.4)`.

**It works, but it's a curate-a-few-seeds tool, not a one-shot button** —
identical settings with a different seed can still come back front-facing.
Generate 2-3 seeds at `pose_strength≈1.4-1.5` for yaw≥135° and pick the hit,
same discipline as everything else in this server. `identity_mode="off"` (or a
low `ip_adapter_weight`) is recommended at this strength until identity
retention on strongly-rotated poses gets its own testing pass.

## How a panel gets made

Panels are **composited layers**, not one-shot generations — trying to generate a
finished panel (characters + background + composition) in a single diffusion pass is
where consistency dies:

1. **Background plate** — use `webcomic-background-mcp`'s existing tools (World
   Builder keeps the *location* consistent; that problem is already solved there).
2. **Character layer** — `generate_character_pose` renders the character alone on a
   clean backdrop (optionally with IP-Adapter identity locking and/or OpenPose
   pose pinning, and automatically using a baked LoRA if one exists), then
   auto-mattes it to RGBA.
3. **Composition** — `compose_panel` pastes the layer onto the plate at a feet
   position/height. Call it once per character, chaining each call's output back in
   as `base` for multi-character panels.

`compose_panel`'s `feet_x`/`feet_y`/`height_px` arguments are exactly what
`webcomic-background-mcp`'s `generate_city_scene(anchor_x=, anchor_z=)` reports back —
the two servers were designed to meet at that seam. No code dependency; just a
compatible shape.

> **Caveats set up front:** multi-character interaction panels (embraces, fights,
> physical contact) are the weakest spot of the layered approach — layers don't
> interpenetrate. SD 1.5 faces/hands at a distance are rough. References generated by
> ChatGPT/Midjourney are fine as *identity* references; if you plan commercial
> publication, checking your source tool's ToS on that art is on you, not this tool.
> This server doesn't write the story, choose panel flow, or replace a storyboard eye —
> it proposes; you direct.

## Architecture

```
 MCP client (Claude)
        │  stdio
        ▼
   server.py  ──►  characters.py  (bible: pure data/IO, no ComfyUI)
                    workflow.py   ──HTTP──►  ComfyUI (:8188)  ──►  GPU
                    (Tier-1/2)                (shared with
                                               webcomic-background-mcp)
                    training.py   ──subprocess──►  kohya-ss/sd-scripts  ──►  GPU
                    (Tier-3, async)                (separate install/venv)
                    tools/compose_panel.py    (pure PIL, no GPU)
                    tools/crop_reference.py  (pure PIL, no GPU)
                    tools/compose_sheet.py   (pure PIL, no GPU)
                    mannequin.py             (3D pose synthesis, pure numpy+PIL, no GPU)
```

### Why it's a *local* server

Same reasoning as `webcomic-background-mcp`: each pose generation runs Stable
Diffusion on a local GPU, so a hosted multi-user deployment would mean paying for
everyone's GPU compute. Running locally keeps it free and private, at the cost of
single-machine availability — the right trade for a personal creative tool.

## Part of a wider webcomic/animation toolkit

This server generates character poses and composites panels — it doesn't paint
backgrounds (see `webcomic-background-mcp`) or make videos (see the
**[Anime Production Skill](../anime-production-skill/README.md)**). More tools in the
same ecosystem, including a novel/comic translation server, are listed on
[tobiasfong.github.io](https://tobiasfong.github.io).

---

# Setup Guide

> **Already have `webcomic-background-mcp` set up?** You already have ComfyUI and a
> checkpoint installed and configured — skip straight to **Step 4**; this server
> reuses that same local ComfyUI instance by default (same `COMFY_URL`).

## Hardware: will it run on *your* machine?

Same requirements as `webcomic-background-mcp` — see its
[hardware table](../webcomic-background-mcp/README.md#hardware-will-it-run-on-your-machine).
Tier 1 needs nothing extra beyond a working ComfyUI + SD 1.5 checkpoint.

## Step 1 — Install ComfyUI

See `webcomic-background-mcp`'s [Step 1](../webcomic-background-mcp/README.md#step-1--install-comfyui).
If you already run that server, this step is done.

## Step 2 — Models

**Tier 1 needs no new models** — it reuses whatever SD 1.5 checkpoint you already
installed for `webcomic-background-mcp` (default `solstice`; see that server's
[model table](../webcomic-background-mcp/README.md#step-2--download-the-models)
if you're installing this server standalone).

**Tier 2 needs ~3.5 GB more** (IP-Adapter + OpenPose ControlNet). Run the bundled
downloader:

```bash
python setup_models.py --comfy "C:/AI/ComfyUI_windows_portable/ComfyUI"
```

Or place manually:

| Role | File | → Folder | Source |
|------|------|----------|--------|
| CLIP vision encoder | `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | `clip_vision/` | [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors) |
| IP-Adapter Plus (identity) | `ip-adapter-plus_sd15.safetensors` | `ipadapter/` | [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter/resolve/main/models/ip-adapter-plus_sd15.safetensors) |
| IP-Adapter Plus Face (portraits) | `ip-adapter-plus-face_sd15.safetensors` | `ipadapter/` | [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter/resolve/main/models/ip-adapter-plus-face_sd15.safetensors) |
| ControlNet OpenPose | `control_v11p_sd15_openpose_fp16.safetensors` | `controlnet/` | [comfyanonymous/ControlNet-v1-1_fp16](https://huggingface.co/comfyanonymous/ControlNet-v1-1_fp16_safetensors/resolve/main/control_v11p_sd15_openpose_fp16.safetensors) |

**Tier 3 needs no new ComfyUI models** — it trains against the same checkpoint
Tier 1/2 already use. See Step 7 for its (separate) install.

## Step 3 — Custom nodes

**Tier 1 needs none** — only core ComfyUI nodes (checkpoint, LoRA, VAE, KSampler).

**Tier 2 needs `ComfyUI_IPAdapter_plus`** (the OpenPose *preprocessor* comes from
`comfyui_controlnet_aux`, which is already required by `webcomic-background-mcp`'s
Step 3 — if that server is installed, only the IP-Adapter node is new):

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus
```

**`detail_fix` needs `ComfyUI-Impact-Pack` + `ComfyUI-Impact-Subpack`** (optional —
only if you want the auto hand/face repair pass; nothing else depends on these):

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git
git clone https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git
<ComfyUI's python> -m pip install -r ComfyUI-Impact-Pack/requirements.txt
<ComfyUI's python> -m pip install -r ComfyUI-Impact-Subpack/requirements.txt
```

Then get the two YOLOv8 detector models (~75 MB total, from
[Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer) on Hugging Face) into
`ComfyUI/models/ultralytics/bbox/`:

| File | → Folder |
|------|----------|
| [`face_yolov8m.pt`](https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8m.pt) | `models/ultralytics/bbox/` |
| [`hand_yolov8s.pt`](https://huggingface.co/Bingsu/adetailer/resolve/main/hand_yolov8s.pt) | `models/ultralytics/bbox/` |

Impact-Subpack whitelists `.pt` files by base filename before loading them with
relaxed `weights_only` restrictions (a PyTorch 2.6+ safety feature) — add
`face_yolov8m.pt` and `hand_yolov8s.pt`, one per line, to
`ComfyUI/user/default/ComfyUI-Impact-Subpack/model-whitelist.txt` (create it if the
first ComfyUI launch after installing hasn't already created an empty one).

Restart ComfyUI so it loads the new nodes.

## Step 4 — Set up this MCP server

```bash
git clone https://github.com/tobiasfong/webcomic-toolkit.git
cd webcomic-toolkit/servers/character-panel-mcp
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Linux/Mac: .venv/bin/python)
```

`rembg` (matting) downloads its own model (~170 MB) to your home directory the first
time `generate_character_pose` runs with `matte=True` — no manual step needed.

## Step 5 — Wire it into your MCP client

- **Classic Claude Desktop:** add to `claude_desktop_config.json`:
  ```json
  {
    "mcpServers": {
      "character-panel-generator": {
        "command": "C:/path/to/.venv/Scripts/python.exe",
        "args": ["C:/path/to/server.py"]
      }
    }
  }
  ```
- **Claude Code:** `claude mcp add character-panel-generator -- /path/to/.venv/bin/python /path/to/server.py`
- **Newer "Cowork"-style desktop builds:** manage MCP servers through an
  Extensions/Connectors UI — check your client's settings.

After adding it, **fully quit and relaunch the client** (see Troubleshooting).

## Step 6 — Use it

**Already have reference art?**
1. Register a character: *"Register these three images of Aria as a character named
   'aria' in project 'starry_knight'."*

**No art yet?**
1. *"Generate 4 character concepts: gaunt young man, long nose, manic grin,
   purple-and-black military uniform, white gloves, gold pocket chain"*
   (`generate_character_concept`) — pick the one that's your character, then
   register it the same way as above.

**Have a composite concept sheet (ChatGPT/Midjourney-generated)?**
1. *"Crop this sheet into the hero pose and the three expression panels"*
   (`crop_reference` — give it the pixel boxes, or ask the harness to look once
   and propose them), then register the crops.

**From here on, all paths converge:**

2. Generate a pose: *"Generate a pose of aria: arms crossed, looking over her
   shoulder."* (Tier 1 only, always works once Step 4 is done.)
3. **Grow the reference set:** *"Generate a reference sheet for aria"*
   (`generate_reference_sheet`) — front/back/side/3-4 views + expressions, one
   generation each. Curate the keepers, `register_character` them in.
4. **Tier 2, optional:** *"Generate that pose again with identity_mode='plus' so
   it locks onto her reference more strongly"* — or pass `pose_ref_path` to a
   photo of someone in the target pose to pin it via OpenPose.
5. **Tier 3, optional:** *"Bake a LoRA for aria"* (`bake_character_lora`) once
   you have 10-20 good references — see Step 7 for its setup. Once it finishes
   (`check_lora_training`), every later `generate_character_pose` call for her
   uses it automatically.
6. Composite it: *"Composite that onto backgrounds/alley.png with her feet at
   (512, 780), 340px tall."*

### Helper scripts (`tools/`)

- **`compose_panel.py`** — also runnable standalone from the CLI:
  ```bash
  python tools/compose_panel.py character.png --feet-x 512 --feet-y 780 \
      --height-px 340 --background plate.png --out panel.png
  ```
- **`crop_reference.py`** — also runnable standalone from the CLI:
  ```bash
  python tools/crop_reference.py sheet.png --box 40,20,300,600 \
      --box 320,20,580,600 --out-dir crops/
  ```
- **`compose_sheet.py`** — the grid layout `generate_reference_sheet` builds
  automatically; also runnable standalone on any set of images:
  ```bash
  python tools/compose_sheet.py front.png back.png side.png \
      --label front --label back --label side --out sheet.png
  ```

### Your asset library (you provide this)

The repo ships the code, but no character art — the `characters/` folder is
git-ignored, same reasoning as `webcomic-background-mcp`'s `references/`: it's your
personal, often commissioned/licensed art, and shouldn't be redistributed.

---

## Step 7 — Tier 3 setup: kohya-ss/sd-scripts (optional, advanced)

> **Heads-up — this is the heaviest step in this whole server.** It's a separate
> ~5 GB ML training toolkit with its own venv, not a ComfyUI custom node. Skip
> this entirely if Tier 1/2 are enough for you; nothing else in this server
> depends on it.

```bash
git clone https://github.com/kohya-ss/sd-scripts.git C:/AI/sd-scripts
cd C:/AI/sd-scripts
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt
venv/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cu121
venv/Scripts/python -m accelerate.commands.config default
```

The last line runs `accelerate`'s one-time setup non-interactively with sane
single-GPU defaults; run `venv/Scripts/python -m accelerate.commands.config`
(without `default`) instead if you want to answer the prompts yourself (e.g. to
pick `bf16` over `fp16`, or if you have multiple GPUs).

Then point this server at it (defaults assume the path above — only needed if
yours differs):

```bash
export WEBCOMIC_CHAR_KOHYA_DIR="C:/AI/sd-scripts"          # Windows: set / setx
export WEBCOMIC_CHAR_COMFY_MODELS="C:/AI/ComfyUI_windows_portable/ComfyUI/models"
```

`bake_character_lora` reads the checkpoint straight off disk (unlike Tier 1/2,
which only ever talk to ComfyUI's HTTP API) and writes the trained LoRA into
`WEBCOMIC_CHAR_COMFY_MODELS/loras/` — set the latter if this server isn't sharing
`webcomic-background-mcp`'s ComfyUI install.

**One more file needed for baking to work with its defaults:** `bake_character_lora`
bakes the **Niji V5 Style LoRA** into every character LoRA by default (see
"Consistency tiers" above), which means `NijiV5Style.safetensors` must already be
in `WEBCOMIC_CHAR_COMFY_MODELS/loras/` — it's the same file
`webcomic-background-mcp`'s [model table](../webcomic-background-mcp/README.md#step-2--download-the-models)
documents as an optional style choice; if you haven't downloaded it there, do
that first, or pass `style_lora=""` to bake against a plain checkpoint instead.

---

## Step 8 — SDXL prototype (optional, experimental): `model="mj_manga_sdxl"`

> Added 2026-07-19 after live testing showed the SD1.5 stack's ceiling: distorted
> full-body anatomy ("spider legs") and no genuine back views, regardless of
> tuning. SDXL + the [Midjourney Manga Art Style LoRA](https://civitai.com/models/185798)
> **fixes the anatomy and art-quality problems outright** (verified live on a
> 6 GB RTX 3060 Laptop — ~30s warm generations, ~75s cold). It does NOT solve
> back views (see the honest limitation below).

```bash
python setup_models_sdxl.py --comfy "C:/AI/ComfyUI_windows_portable/ComfyUI" --stage1-only
```

`--stage1-only` fetches checkpoint + VAE + LoRA (~7.5 GB) — enough for Tier-1
generation. Run again without it for the SDXL IP-Adapter/CLIP-vision/OpenPose
models (~4.5 GB more) once you want Tier 2. Then just pass
`model="mj_manga_sdxl"` to any generation tool — the LoRA's `mj manga` trigger
word and SDXL-native resolution (832×1216 when you leave width/height at their
defaults) are applied automatically. Existing SD1.5 models are untouched; this
is an additional option, not a migration.

**Validated settings** (from the live tuning session): `ip_adapter_weight≈0.3`
for identity without scene-dragging, `ref_denoise=1.0` for pose freedom, and the
anti-duplicate negatives now baked into `generate_reference_sheet` by default.

**Genuine back views:** ~12 tuning configurations across SD1.5 and SDXL
(prompt-only, img2img, IP-Adapter sweeps, pure text, OpenPose ControlNet at
strengths 1.0–1.6 with face keypoints on/off) all failed to reach a clean
single-figure back view — a checkpoint-level prior in how 2D-extracted pose
conditioning works, not a tuning problem. This is what the **3D mannequin**
(`generate_pose_map`, see above) was built to solve, and does — see
CHANGELOG's "back-view campaign" for the full record and its honest
stochastic caveat.

## Step 9 — FLUX: `model="flux_manwha"` + the staged concept-to-sheet workflow

> Added 2026-07-21/22 after SDXL's hand-anatomy fixes (Step 7/CHANGELOG's LoRA-
> stacking work) plateaued — hands kept coming back deformed even with every
> correction LoRA stacked at once. Prototyped FLUX.1-dev as SD1.5→SDXL's natural
> next step up, validated in scratch scripts, then wired into the live tool
> (`flux_workflow.py`, new — see ARCHITECTURE.md §8b.9 "Stage 5" for the full
> record of what was tried, what failed, and why, before this landed here).

**What's real:** `model="flux_manwha"` works anywhere a model name is accepted
(`generate_character_concept`, `generate_character_pose`, `generate_reference_sheet`)
— a GGUF-quantized FLUX.1-dev (`flux1-dev-Q3_K_S.gguf`, ~5 GB, fits the same 6 GB
VRAM budget) with a manhwa-style LoRA, genuinely better hand anatomy than SDXL once
`detail_fix=True` is on (hand-only pass, `denoise=0.7` — no face pass, that wasn't
tested for FLUX), and the same 3D-mannequin `pose_ref_path` mechanism for back
views, now ~2/3-seed reliable on FLUX's ControlNet too (an alpha-quality community
adapter — reroll on a miss, don't expect every seed to land it). **Not supported**:
`identity_mode`/IP-Adapter with FLUX — never tested, raises an error if you try.

Two new FLUX-only tools plus one general-purpose composer round out a staged
workflow, designed specifically to catch mistakes early instead of discovering
them after a whole sheet is built:

1. **Intake** — `register_character` (unchanged) to save the character's
   Profile/Abilities/Appearance text, whether you already have art or not.
2. **One approved concept** — `generate_character_concept(description=...,
   model="flux_manwha", n=1)`. Look at it before spending time on the next step;
   regenerate if it's not right.
3. **Make it canon** — `register_character(image_paths=[<the approved one>], ...)`.
4. **`generate_turnaround_sheet`** (new) — FLUX Kontext dev + a dedicated
   turnaround-sheet LoRA, reads the character's just-registered reference and
   produces a multi-pose sheet (typically 7 panels: front/¾/profile repeats
   alongside one back view). Scan the **whole figure** on every panel you care
   about — collar shape, hands, shoe orientation — not just facing direction; a
   partial rotation can look right at a glance (see ARCHITECTURE.md §8b.9 for
   the chimera this exact mistake produced once).
5. **`crop_reference`** (existing, unchanged, already generic) — slice out the
   panels you want: front + back are mandatory, a profile/¾ view and 1-2
   close-ups (crop tighter if the source panel is full-body) round out the
   Avery template's three image slots.
6. **`compose_reference_sheet`** (new) — assembles the final poster from those
   crops (or any curated images), pulling Profile/Abilities/Appearance text from
   the bible automatically — same layout as `generate_reference_sheet`'s
   `combine=True` path, but composing from images you already have instead of
   generating fresh ones.
7. **`edit_character_image`** (new, optional) — FLUX Kontext dev as a plain-
   English image editor, for surgical anatomy fixes (e.g. "show both hands
   visible... keep everything else the same") on a pose that's already facing
   the right way. **Not** for viewpoint changes — that's what step 4 is for;
   asking this tool to rotate a figure produced a chimera in testing (see its
   docstring).

Models involved: `flux1-dev-Q3_K_S.gguf` and `flux1-kontext-dev-Q3_K_S.gguf`
(both `models/unet/`, both from `QuantStack`/`city96`'s GGUF repos on
HuggingFace), `manwha_style.safetensors` and `kontext-turnaround-sheet-v1.safetensors`
(both `models/loras/`), and `flux_controlnet_union_alpha.safetensors`
(`models/controlnet/`, InstantX's community FLUX ControlNet). No setup script
for these yet — fetched by hand during the investigation; see `flux_workflow.py`'s
module docstring for the exact filenames each constant expects.

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI backend address — shared with `webcomic-background-mcp` |
| `WEBCOMIC_CHAR_MODEL` | `solstice` | Default render model |
| `WEBCOMIC_CHAR_LORA` | *(empty)* | Optional style LoRA filename (same pool as the background server, e.g. `NijiV5Style.safetensors`) |
| `WEBCOMIC_CHAR_LORA_STRENGTH` | `0.8` | LoRA strength when one is set |
| `WEBCOMIC_CHAR_OUTPUT` | `./output` | Where generated poses/panels are written |
| `WEBCOMIC_CHAR_ROOT` | `./characters` | Where the Character Bible is stored |
| `WEBCOMIC_CHAR_PROJECT` | `default` | Default project when none is specified |
| `WEBCOMIC_CHAR_COMFY_DIR` / `WEBCOMIC_CHAR_COMFY_LAUNCH` | `C:\AI\ComfyUI_windows_portable` / `run_nvidia_gpu.bat` | Auto-launch location/script for ComfyUI |
| `WEBCOMIC_CHAR_AUTOLAUNCH` | `1` | Set `0` to require a manually-started ComfyUI (avoids two servers racing to launch it if you run both) |
| `WEBCOMIC_CHAR_COMFY_MODELS` | `<COMFY_DIR>/ComfyUI/models` | **Tier 3 only** — ComfyUI's `models/` folder as a real filesystem path (training reads the checkpoint off disk and writes the output LoRA here; Tier 1/2 never need this, they only talk to ComfyUI's HTTP API) |
| `WEBCOMIC_CHAR_KOHYA_DIR` | `C:\AI\sd-scripts` | **Tier 3 only** — where kohya-ss/sd-scripts is checked out |
| `WEBCOMIC_CHAR_KOHYA_PYTHON` | `<KOHYA_DIR>/venv/Scripts/python.exe` | **Tier 3 only** — the Python with sd-scripts' deps installed |
| `WEBCOMIC_CHAR_BAKE_STYLE_LORA` | `NijiV5Style.safetensors` | **Tier 3 only** — default `style_lora` for `bake_character_lora` (merged into the checkpoint before training); set empty to default to plain-checkpoint bakes |
| `WEBCOMIC_CHAR_BAKE_STYLE_LORA_MULTIPLIER` | `1.0` | **Tier 3 only** — default strength of that style merge |
| `WEBCOMIC_CHAR_SDXL_LORA` | `MJMangaSDXL.safetensors` | **SDXL prototype** — style LoRA auto-applied with `model="mj_manga_sdxl"` (trigger word added automatically) |
| `WEBCOMIC_CHAR_SDXL_LORA_STRENGTH` / `WEBCOMIC_CHAR_SDXL_CLIP_SKIP` | `0.8` / `2` | **SDXL prototype** — the LoRA author's recommended settings |

## Troubleshooting

- **`check_status` says ComfyUI isn't reachable** — same as `webcomic-background-mcp`:
  start it, or set `COMFY_URL`. If you already run the background server, ComfyUI is
  likely already up.
- **Matted cutout has ragged/incomplete edges** — Tier 1's clean-backdrop prompt isn't
  perfectly reliable; regenerate with a different seed, or lower `ref_denoise` to stay
  closer to the reference's own clean framing.
- **Pose looks like a different character** — `ref_denoise` is too high for how
  ambitious the pose is. Lower it, turn on `identity_mode="plus"` (Tier 2), or bake a
  LoRA (Tier 3) if you need this character in many panels.
- **`generate_character_pose` fails with an unknown node / `IPAdapterUnifiedLoader`
  error** — the `ComfyUI_IPAdapter_plus` custom node (Step 3) isn't installed, or
  `setup_models.py` hasn't been run (Step 2). Only relevant when `identity_mode` is
  set — Tier 1 alone never touches these nodes.
- **`bake_character_lora` fails with "kohya-ss Python not found"** — Step 7 hasn't
  been done, or `WEBCOMIC_CHAR_KOHYA_DIR`/`WEBCOMIC_CHAR_KOHYA_PYTHON` point at the
  wrong path.
- **`bake_character_lora` fails with "Checkpoint not found"** — `WEBCOMIC_CHAR_COMFY_MODELS`
  doesn't point at a real ComfyUI `models/` folder, or the checkpoint file for the
  chosen `model` isn't actually downloaded there.
- **`bake_character_lora` fails with "Style LoRA not found"** — `NijiV5Style.safetensors`
  (the default `style_lora`) isn't in `WEBCOMIC_CHAR_COMFY_MODELS/loras/`. Download it
  (see `webcomic-background-mcp`'s model table) or pass `style_lora=""` to skip it.
- **Training seems stuck / `check_lora_training` shows no new log lines for a long
  time** — the first few minutes are usually the base model loading into VRAM; if
  it's been 10+ minutes with zero progress, check the full log
  (`check_lora_training`'s response includes the path) for an out-of-memory error —
  a 3060 12GB is the assumed baseline; lower `resolution` or `network_dim` on a
  smaller GPU.
- **`pose_ref_path` fails with "Generation produced no image" and the ComfyUI log
  shows an `OpenposePreprocessor` download error** — the preprocessor tries to
  fetch its three annotator models (`body_pose_model.pth`, `hand_pose_model.pth`,
  `facenet.pth` from `lllyasviel/Annotators` on Hugging Face) on first use, and
  that in-process download can fail on some setups. Fix: download those three
  files manually and place them FLAT (no subfolders) in
  `ComfyUI/custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/`.
- **Asked for a back view, got a profile/front view** — text prompts and 2D-photo
  `pose_ref_path` both hit this (see the SDXL section above). Use
  `generate_pose_map(yaw=180)` + `pose_preprocess=False` + `pose_strength≈1.4-1.5`
  instead — and generate a couple of seeds, it's stochastic.
- **`detail_fix=True` fails with an unknown node / `FaceDetailer`/
  `UltralyticsDetectorProvider` error** — `ComfyUI-Impact-Pack`/`ComfyUI-Impact-Subpack`
  (Step 3) aren't installed, or their Python deps weren't installed into ComfyUI's own
  Python (not this server's venv — see Step 3's exact commands).
- **`detail_fix=True` runs but nothing looks different** — most likely the face/hand
  detector didn't confidently find a region to fix (small/occluded hands are the usual
  case) — this fails silently by design, not an error. Check the ComfyUI console for a
  line like `0: 640x448 1 hand, ...`; no such line means nothing was detected. Could
  also mean the two `.pt` files aren't in
  `ComfyUI/user/default/ComfyUI-Impact-Subpack/model-whitelist.txt` yet (Step 3) —
  check the console for a whitelist warning.
- **The tool never appears in your MCP client** — see
  `webcomic-background-mcp`'s note: fully quit (not just close the window) and relaunch.

## Status

**v1.0.0 — first release.** All three consistency tiers are implemented and
live-tested: Character Bible, Tier-1 img2img pose generation with auto-matting,
Tier-2 IP-Adapter/OpenPose, Tier-3 async LoRA baking (job lifecycle verified
with a stub trainer; a real kohya-ss training run hasn't been exercised live
yet), and deterministic panel compositing. Concept Genesis
(`generate_character_concept`, `crop_reference`, `generate_reference_sheet`)
is live-tested end-to-end against real character art, which surfaced and fixed
real tuning bugs (see CHANGELOG). The optional SDXL prototype
(`model="mj_manga_sdxl"`) fixes anatomy/backdrop quality outright, verified
live on a 6 GB GPU. The 3D mannequin (`generate_pose_map`) solves genuine back
views after ~12 failed 2D-extraction configurations — live-verified, with an
honest stochastic caveat documented above and in CHANGELOG. **FLUX (Step 9,
`model="flux_manwha"`) is now wired in** — `flux_workflow.py`, plus
`generate_turnaround_sheet`/`edit_character_image`/`compose_reference_sheet`
for the staged concept-to-sheet workflow — but individual pieces carry the same
honest reliability caveats validated in scratch-script form: back views via
ControlNet are ~2/3-seed reliable, the turnaround-sheet LoRA has one confirmed
clean seed but no measured reliability rate yet, and `identity_mode`/IP-Adapter
is not supported with FLUX at all (untested combination, raises an error).
SDXL/SD1.5 remain fully intact and are still the default — FLUX is an
additional option, same non-migration philosophy as the SDXL prototype.
Built with [Claude Code](https://claude.com/claude-code).
