# Character & Panel Generator — MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server for **writers
who aren't artists** — and for artists who'd rather not redraw the same character six
times before page one. Whether you already have reference art (commissioned, or a
ChatGPT/Midjourney character sheet), have a story and nothing else, or have one good
drawing of a character, this tool gets it into a **Character Bible**, generates new
poses and turnaround views that stay recognizably the same character, and composites
them onto background plates into finished panels — wrapping a local ComfyUI + FLUX
pipeline.

It's the character-domain sibling of
**[`webcomic-background-mcp`](../webcomic-background-mcp/README.md)**'s World Builder:
same philosophy (**reference-driven, never generate-from-text-and-pray** — the
references are the ground truth for who a character is), same skeleton, same README
standard. No code dependency between the two servers; they just point at the same
local ComfyUI by default.

## How identity works (read this first)

There is **one** generation path: FLUX. The SD1.5/SDXL stack and its three-tier
consistency design were retired (see CHANGELOG) — every panel of the first real
scene went through FLUX Kontext, and the tiers were being carried unused.

**Identity comes from conditioning on an image, not from a prompt.** FLUX Kontext
takes an approved reference sheet — or an already-finished panel — as a latent
input, so a new pose is generated *from* the existing art rather than from a
description of it. `edit_character_image` and `generate_turnaround_sheet` are the
tools that do this, and they are what keep a character on-model.

### The one trade-off that shapes everything

The two things you might want are mutually exclusive **in a single pass**:

| | conditions on the character's art | controls the camera angle |
|---|---|---|
| `edit_character_image` (Kontext) | **yes** — identity holds | no — framing and body angle are inherited from the reference and ignore instructions |
| `generate_character_pose` | no — identity is prompt text, and drifts | **yes** — ControlNet pins the pose, including genuine back views |

So you choose per generation: *this character's actual art*, or *this exact
camera angle*. In practice, for finished panels the reference-driven path wins,
and direction is handled by generating a turnaround sheet first
(`generate_turnaround_sheet`), then conditioning on whichever view you need.

`generate_character_pose` earns its place for the case nothing else reaches: a
pose pinned by a control map you supply via `pose_ref_path` — which is how
`tools/sketch_to_lineart.py` corrects hand-drawn anatomy. For a genuine back
view, use `generate_turnaround_sheet` instead: it keeps the likeness.

### Other things that surprise people

- **One reference binds to one generation.** There is no way to lock two
  characters' identities in a single image; attempting it produces attribute
  bleed. Multi-character panels are generated as solo figures and composited
  (`tools/cutout.py` + `tools/place_cutout.py`).
- **Kontext restyles, it does not restructure.** The reliable test: must the
  model invent what lies *underneath*? Raising arms into open air works;
  changing a pose beneath clothing does not.
- **Expression must be set at generation time.** It is not a safe edit.
- **Generation is minutes, not seconds.** Compositing is instant and GPU-free —
  that separation is deliberate, and it is why panel assembly is CPU-side.

See `../../CLAUDE.md` for the full set of rules this pipeline accumulated in
production.

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
- **`generate_character_pose`** — render the character in a new pose with optional
  ControlNet pose pinning, auto-matted to a clean RGBA cutout. No image identity
  input — see "How identity works" above.
- **`generate_turnaround_sheet`** / **`edit_character_image`** — **the identity
  tools** (Step 9 below): a multi-pose turnaround sheet from one reference image,
  and a plain-English image editor that conditions on real art. These are what
  keep a character on-model.
- **`compose_reference_sheet`** / **`compose_full_reference_sheet`** — poster
  composers that work from already-existing crops. GPU-free.
- **`compose_panel`** — deterministic CPU compositing: paste a matted character onto
  a background plate at a given feet position and height. Zero GPU, zero tokens,
  instant to iterate.
- **`check_status`** — is the ComfyUI backend up? (Only tools that generate pixels
  need it — the bible, `crop_reference`, and `compose_panel` are GPU-free.)

## Consistency: what actually holds a character together

Character consistency is *the* unsolved-in-general problem of AI comics. This
server's answer is **reference-latent conditioning via FLUX Kontext** — the
registered art is the ground truth, and generations condition on it directly
rather than on a description of it.

Earlier versions shipped a three-tier SD design (img2img seeding → IP-Adapter
identity → per-character LoRA baking). All three are gone. Kontext superseded the
first two, and the third was never used on a real character. The honest summary
is that the tiers were a way to approximate what Kontext does directly.

**Validation is the other half.** `tools/check_bible.py` exits non-zero if a
reference is missing, if an unregistered image is lurking in a character folder,
or if the primary reference can't be traced back to an approved sheet. That check
exists because a silently wrong reference once propagated a character's wrong
hair colour through a run of finished panels before anyone noticed. Provenance
that was searched for and genuinely lost is recorded as `"irrecoverable: <why>"`
and reported as a NOTE instead — the check is meant to catch provenance nobody
looked for, and a gate that can never go green is a gate nobody runs.

**Cross-cutting fix: `detail_fix`.** Hallucinated hands are a resolution problem
(too few pixels in a full-body frame), not a prompt problem — a detect-and-repair
pass at higher resolution is the fix, independent of how identity is handled.

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
for deformed. If you actually need a back view, use `generate_turnaround_sheet` +
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
staging discipline as never letting an unreviewed render become canon.
A human always picks the canon.

**Honest caveat:** genesis is bootstrapped, not solved. The very first image (or your
own drawing) is the only ground truth; every other view is Tier-2 *inference* from it,
which means back/side views of a character who only exists as one front-view image
will drift and need retries. This is exactly what curation is for — and once you've
accumulated ~10-20 curated views, the bible holds the strongest version
of what you approved.

**Real-world tuning note (2026-07-19, from an actual test against hand-drawn art):**
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

## Genuine back views

Reference sheets are almost always frontal, and a text prompt saying "back view"
does not work — the model can paint back-body geometry, but nothing in the
conditioning unambiguously says *this is the back*, so results relax toward
front or profile. (~12 tuning configurations confirmed this the hard way; see
CHANGELOG's "back-view campaign".)

**The answer is `generate_turnaround_sheet`** — FLUX Kontext plus a
turnaround-sheet LoRA, which produces a multi-pose sheet (typically 7 panels)
from one reference image, including a genuine back view, **with the character's
identity intact**. Crop the view you want and register it; every later
generation can then condition on it.

> **Retired:** earlier versions shipped `generate_pose_map` and
> `generate_pose_depth_map` — a 3D skeleton and a posable VRM mesh that forced
> direction structurally through ControlNet. They worked (~2/3 and ~3/3 seeds
> respectively), but they fed `generate_character_pose`, which has **no image
> identity input**. A structurally-correct back view of *nobody in particular*
> can't become a reference for a specific character, and Kontext cannot rotate a
> viewpoint to fix it afterward. The turnaround sheet solves the same problem
> without discarding the likeness, so the 3D machinery, its VRM assets and its
> Blender scripts were removed.
>
> ControlNet itself is **not** retired: `generate_character_pose` still accepts
> `pose_ref_path` with any control map you supply, which is how
> `tools/sketch_to_lineart.py` corrects hand-drawn anatomy
> (`pose_control_type="canny_auto"`).

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

FLUX only. Roughly 11 GB total, all of it fitting a 6 GB card via GGUF
quantisation and ComfyUI's model offloading.

⚠ **Q6_K, not a low quant.** The Q3_K_S files these used to name were deleted
2026-08-10. VRAM is not the reason to quantise low — ComfyUI streams weights
from system RAM, and this 6 GB card runs a 14.2 GB model routinely. Measured:
Kontext repair of a damaged hand went from 0-of-6 frames usable at Q3_K_S to
3-of-3 at Q6_K. Plain generation showed no difference either way, but Q6 was
also faster there (225 s vs 339 s) and used less VRAM, so there is no case for
the smaller file.

| Role | File | → Folder |
|------|------|----------|
| Base FLUX (txt2img) | `flux1-dev-Q6_K.gguf` | `unet/` |
| FLUX Kontext (identity/editing) | `flux1-kontext-dev-Q6_K.gguf` | `unet/` |
| Text encoder | `t5xxl_fp8_e4m3fn.safetensors` | `clip/` |
| Text encoder | `clip_l.safetensors` | `clip/` |
| VAE | `ae.safetensors` | `vae/` |
| Manhwa style LoRA | `manwha_style.safetensors` | `loras/` |
| Turnaround-sheet LoRA | `kontext-turnaround-sheet-v1.safetensors` | `loras/` |

> **Transparent figures need no extra weights here.** A FLUX LayerDiffuse route
> (`layerlora` + a `TransparentVAE` decoder, 1.6 GB) was built and measured on
> 2026-08-13 and then removed — it left a white edge and altered the drawing.
> See the CHANGELOG before re-downloading anything on that hunch. Transparency
> comes from `matte_image()` instead (Step 3).

See **Step 9** for where these come from and the settings that matter
(`manwha_style` at strength **1.5** — 1.0 loses the fight against ControlNet
conditioning).

**ControlNet (optional, for pose pinning)** — the Union Pro 2.0 model, via its
own downloader:

```bash
python setup_models_controlnet_pro.py --comfy "C:/AI/ComfyUI_windows_portable/ComfyUI"
```

> **Retired:** `setup_models.py` and `setup_models_sdxl.py` are gone along with the
> SD1.5/SDXL path. If you have IP-Adapter, CLIP-vision or SD1.5 ControlNets
> installed for an older version of this server, nothing here uses them any more —
> though `webcomic-background-mcp` may still need its own SD checkpoints.

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

**`matte_image()` needs ComfyUI-RMBG** (optional — only if you want transparent
figures; nothing else depends on it).

Clone it, and install only these dependencies, not
its full `requirements.txt` — the rest is SAM/SAM2/SAM3 and GroundingDINO
text-prompted segmentation, which this server never uses and which drags in
`groundingdino-py`, `onnxruntime-gpu` and `decord`:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/1038lab/ComfyUI-RMBG.git
<ComfyUI's python> -m pip install timm PyMatting
```

⚠ **RMBG's auto-downloader is broken against `huggingface_hub` 1.x** — it fails
with *"Cannot send a request, as the client has been closed"*, and that error
appears **only in ComfyUI's `/history`**, never to the client, which just reports
that no image was produced. Do **not** downgrade the hub; ComfyUI depends on it.
Place the weights by hand instead — for the default `RMBG-2.0`, four files from
[1038lab/RMBG-2.0](https://huggingface.co/1038lab/RMBG-2.0) (~885 MB) into
`ComfyUI/models/RMBG/RMBG-2.0/`:

| File | → Folder |
|------|----------|
| `config.json`, `model.safetensors`, `birefnet.py`, `BiRefNet_config.py` | `models/RMBG/RMBG-2.0/` |

Other models' repo ids and target folders are in
`custom_nodes/ComfyUI-RMBG/py/AILab_RMBG.py` (`AVAILABLE_MODELS`) and
`AILab_BiRefNet.py` (`MODEL_CONFIG`); all land under `models/RMBG/<cache_dir>/`.

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
   'hero' in project 'example_comic'."*

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

## Step 9 — FLUX: `model="flux_manwha"` + the staged concept-to-sheet workflow

> Added 2026-07-21/22 after SDXL's hand-anatomy fixes (Step 7/CHANGELOG's LoRA-
> stacking work) plateaued — hands kept coming back deformed even with every
> correction LoRA stacked at once. Prototyped FLUX.1-dev as SD1.5→SDXL's natural
> next step up, validated in scratch scripts, then wired into the live tool
> (`flux_workflow.py`, new — see ARCHITECTURE.md §8b.9 "Stage 5" for the full
> record of what was tried, what failed, and why, before this landed here).

**What's real:** `model="flux_manwha"` works anywhere a model name is accepted
(`generate_character_concept`, `generate_character_pose`, `generate_reference_sheet`)
— a GGUF-quantized FLUX.1-dev (`flux1-dev-Q6_K.gguf`, ~9.9 GB; ComfyUI streams it
from system RAM, so it runs fine on 6 GB VRAM) with a manhwa-style LoRA, genuinely better hand anatomy than SDXL once
`detail_fix=True` is on (hand-only pass, `denoise=0.7` — no face pass, that wasn't
tested for FLUX), and the same 3D-mannequin `pose_ref_path` mechanism for back
views, now ~2/3-seed reliable on FLUX's ControlNet too (an alpha-quality community
adapter — reroll on a miss, don't expect every seed to land it). **Not supported**:
IP-Adapter was never supported on FLUX and the SD tiers are retired.

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

Models involved: `flux1-dev-Q6_K.gguf` and `flux1-kontext-dev-Q6_K.gguf`
(both `models/unet/`, both from `QuantStack`/`city96`'s GGUF repos on
HuggingFace), `manwha_style.safetensors` and `kontext-turnaround-sheet-v1.safetensors`
(both `models/loras/`), and `flux_controlnet_union_alpha.safetensors`
(`models/controlnet/`, InstantX's community FLUX ControlNet). No setup script
for these yet — fetched by hand during the investigation; see `flux_workflow.py`'s
module docstring for the exact filenames each constant expects.

## Transparent figures

Panel figures come out on a transparent background so they never fight a plate
from the background server.

### Use `matte_image()` — this is the route

Generate the figure however you normally would, then cut it out:

```python
import flux_workflow as F

F.matte_image("output/<project>/_scene1/FINAL_p01_arrival.png",
              out_dir="output/<project>/_figures")
```

~5 s, works on **anything that already exists** — locked panels, approved
concept panels, hand-drawn art — and needs no change to how figures are made.

**It lands on the lineart**, which is what matters on cel-shaded art. Measured as
the brightness of the 2 px rim just inside the silhouette against the figure's
interior, RMBG scores **−28.7** — it keeps the dark line at the edge.

### Why there is no "generate with alpha directly" option

A full FLUX LayerDiffuse implementation was built and measured on 2026-08-13
(`layerlora` + a `TransparentVAE` decoder node, keeping Kontext identity
conditioning) and then **removed**. Do not rebuild it without reading the
CHANGELOG — it worked, and was still the wrong tool:

- It scored **−11.5** on that same rim measure against RMBG's −28.7: its alpha
  cuts *outside* the lineart, leaving a white fringe.
- `layerlora` is another LoRA competing with `manwha_style`, so it **changes the
  drawing** — mean abs diff 9.459 against strength 0.0 at a fixed seed.
- Its selling point ("identity *and* alpha in one pass") was never real. Matting
  is a post-process and does not compete with identity conditioning, so you can
  generate normally with full Kontext identity and matte afterwards.

`tools/cutout.py`'s colour keying is superseded for figures: it cannot separate
pale fabric from a pale backdrop by construction, which is why it carries a
`pale_figure_risk` flag and clamps tolerance at 110 when the measured value
wanted 173–187.

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

## Troubleshooting

- **`check_status` says ComfyUI isn't reachable** — same as `webcomic-background-mcp`:
  start it, or set `COMFY_URL`. If you already run the background server, ComfyUI is
  likely already up.
- **Matted cutout has ragged/incomplete edges** — Tier 1's clean-backdrop prompt isn't
  perfectly reliable; regenerate with a different seed, or lower `ref_denoise` to stay
  closer to the reference's own clean framing.
- **Pose looks like a different character** — `ref_denoise` is too high for how
  ambitious the pose is. Condition on real art with `edit_character_image` instead, or
  LoRA (Tier 3) if you need this character in many panels.
- **`generate_character_pose` fails with an unknown node / `IPAdapterUnifiedLoader`
  error** — the `ComfyUI_IPAdapter_plus` custom node (Step 3) isn't installed, or
  `setup_models.py` hasn't been run (Step 2). Only relevant when `identity_mode` is
  set — Tier 1 alone never touches these nodes.
- **`pose_ref_path` fails with "Generation produced no image" and the ComfyUI log
  shows an `OpenposePreprocessor` download error** — the preprocessor tries to
  fetch its three annotator models (`body_pose_model.pth`, `hand_pose_model.pth`,
  `facenet.pth` from `lllyasviel/Annotators` on Hugging Face) on first use, and
  that in-process download can fail on some setups. Fix: download those three
  files manually and place them FLAT (no subfolders) in
  `ComfyUI/custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/`.
- **Asked for a back view, got a profile/front view** — text prompts and 2D-photo
  `pose_ref_path` both hit this (see the SDXL section above). Use
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
real tuning bugs (see CHANGELOG). The since-retired SDXL prototype
(`model="mj_manga_sdxl"`) fixes anatomy/backdrop quality outright, verified
views after ~12 failed 2D-extraction configurations — live-verified, with an
honest stochastic caveat documented above and in CHANGELOG. **FLUX (Step 9,
`model="flux_manwha"`) is now wired in** — `flux_workflow.py`, plus
`generate_turnaround_sheet`/`edit_character_image`/`compose_reference_sheet`
for the staged concept-to-sheet workflow — but individual pieces carry the same
honest reliability caveats validated in scratch-script form: back views via
ControlNet are ~2/3-seed reliable, the turnaround-sheet LoRA has one confirmed
clean seed but no measured reliability rate yet, and IP-Adapter
is not supported with FLUX at all (untested combination, raises an error).
SDXL/SD1.5 remain fully intact and are still the default — FLUX is an
additional option, same non-migration philosophy as the SDXL prototype.
**A second, more reliable back-view path landed the same arc** (Step 10,
depth map, rendered via a separate Blender install, reaches ~3/3-seed
direction-lock reliability once properly calibrated — a real improvement
over the mannequin skeleton's ~2/3, validated live including a full
pose-then-costume-then-fix pipeline (see CHANGELOG/ARCHITECTURE §8b.10).
Built with [Claude Code](https://claude.com/claude-code).
