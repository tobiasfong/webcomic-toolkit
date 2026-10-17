# Character & Panel Generator — MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server for **writers
who aren't artists** — and for artists who'd rather not redraw the same character six
times before page one. Whether you already have reference art, have a story and
nothing else, or have one good drawing of a character, this tool gets it into a
**Character Bible**, generates new poses and turnaround views that stay recognizably
the same character, and composites them onto background plates into finished panels
— rendering with [FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy)
on a local ComfyUI.

> **v2.0.0 — FLUX 3 Klein only. FLUX.1 has been removed.** Its GGUF models, the
> manhwa and turnaround LoRAs, ControlNet and Kontext are gone, along with every
> `model=`, `lora=`, `negative=` and `pose_ref_path=` parameter that reached them.
> The sibling [`webcomic-background-mcp`](../webcomic-background-mcp/README.md) made
> the same move in its v3.0.0, so plates and figures come from one model. See the
> CHANGELOG for what replaced each part.

It's the character-domain sibling of the background server's World Builder: same
philosophy (**reference-driven, never generate-from-text-and-pray** — the references
are the ground truth for who a character is), same skeleton. No code dependency
between the two servers.

## How identity works (read this first)

**Every render of a character conditions on their PRIMARY REFERENCE** — the image
registered first in the bible, cropped from their approved sheet. The bible's
`description` goes into the prompt as well, resolved in code, never retyped.

What Klein does with that, measured 2026-10-17 (the repo's `AGENTS.md` has the
detail):

- **Identity holds through a pose change.** A new pose is drawn *from* the art, not
  from a description of it.
- **Several characters in one render work.** Two characters' references in one
  render held both identities, re-posed, with no attribute bleed, on 3 of 3 seeds.
  `generate_scene` does this; a full CG comes back with its room and light in one
  render.
- **⚠ When the asked-for pose is the one the reference already shows, Klein COPIES
  the reference** — its flaws and its crop. Tight sheet crops came back cut off at
  the head or feet 17 times in 40; padding the reference ~18% on its own backdrop
  color fixed all 9 retried.
- **There is no ControlNet and no LoRA.** Describe a pose in words. Klein's own
  style was accepted in place of the old manhwa LoRA, which cannot load (0 of its
  494 layers exist in Klein).
- **Even a boxed edit redraws the whole frame**, so `edit_character_image` with a
  `mask_box` pastes back only the box: the change outside it is exactly zero.
- **Hands are still the weak point.** Reroll the whole render before patching one.
- **Renders take 18–90 s** on a 6 GB card. Compositing is instant and GPU-free.

## What it does

- **`register_character`** — add (or grow) a character's reference set in the bible.
  Calling it again on the same character **appends** references.
- **`get_character`** / **`list_characters`** / **`forget_character`** /
  **`list_projects`** — browse and curate the bible. Call `get_character` before
  writing any prompt that involves a character.
- **`generate_character_concept`** / **`crop_reference`** — **Concept Genesis**: get a
  character into the bible in the first place (see below).
- **`generate_character_pose`** — the character alone in a new pose, matted to RGBA.
- **`generate_turnaround_sheet`** — front, three-quarter, profile and back in ONE
  render, each view in its own layout box and cut out exactly by it. Measured: four
  true views, no strangers, 0.0% of figure pixels outside the boxes.
- **`generate_reference_sheet`** — one render per view (front, back, 3/4 expression
  close-ups) plus an Avery-style poster.
- **`generate_expression`** — an expression as a WHOLE new body, rendered from
  scratch on a different seed from its base and matted. The body moves with the
  mood; a face is never pasted onto the base.
- **`generate_scene`** — several registered characters in one render.
- **`edit_character_image`** — re-pose or re-frame from an image (no box), or redraw
  one region of it (with a box).
- **`compose_reference_sheet`** / **`compose_full_reference_sheet`** — poster
  composers from images you already have. GPU-free.
- **`apply_gradient_background`** / **`apply_vfx_overlay`** — GPU-free finishing.
- **`compose_panel`** — paste a matted character onto a plate at a feet position and
  height. Zero GPU, zero tokens, instant to iterate.
- **`check_status`** — are both ComfyUIs up?

**Validation is the other half.** `tools/check_bible.py --all` exits non-zero if a
reference is missing, if an unregistered image is lurking in a character folder, or
if the primary reference can't be traced back to an approved sheet. That check
exists because a silently wrong reference once propagated a character's wrong hair
color through a run of finished panels.

## Concept Genesis: getting a character into the bible

| You have... | Use | Then |
|---|---|---|
| A story, no art at all | `generate_character_concept` — a text-to-image candidate | Pick the winner, `register_character` it |
| A composite concept sheet (hero pose + expressions + text, one image) | `crop_reference` — slice it into clean single views | `register_character` the crops |
| One finished drawing of your own character | `register_character` the drawing directly | Straight to the turnaround |

Then `generate_turnaround_sheet` for the four angles, and `compose_reference_sheet`
for the poster. `generate_reference_sheet` adds expression close-ups and builds the
poster in one call.

**Three text fields, shown on the sheet**, deliberately short — this server
generates panels, it doesn't write your story:

| Field | What goes here |
|---|---|
| `profile` | Who they are — role, standing, personality, and (if relevant) Japanese speech patterns: register (丁寧語 vs 普通語) and self-referential pronoun (僕/俺/私/あたし/わし/吾輩/etc.) |
| `abilities` | Powers, skills, equipment |
| *(shown as "Appearance")* | `description` itself — hair and eye color, build, costume. It drives the prompts too, so it is written once. |

**Write a real `description` before generating.** Without visual detail the prompt
has nothing to anchor identity with, and a detail that exists only in the art is
lost on every render made from the words. Leave out "tall" (it fills the canvas and
clips the figure — relative height belongs in the sprite manifest) and build words on
a clothed character (muscle came back as bare skin).

**For artists specifically**: register your one drawing, then the turnaround sheet
answers the rotational questions — the back of the outfit, the silhouette from the
side — as **reference to draw from**, the way you'd use a 3D turntable. Feed it a
clean full-body drawing on a plain background.

**Nothing auto-registers, ever.** A human always picks the canon.

## How a panel gets made

On Klein the first thing to try is **one render**: `generate_scene` with every
character's reference and the room described. Klein holds identities and draws the
light, which a composite has to fake.

When something genuinely cannot be generated together, panels are **composited
layers**:

1. **Background plate** — `webcomic-background-mcp` (World Builder keeps the
   *location* consistent).
2. **Character layer** — `generate_character_pose`, alone on a clean backdrop,
   matted to RGBA.
3. **Composition** — `compose_panel` pastes the layer onto the plate at a feet
   position/height. Chain each call's output back in as `base` for several
   characters.

`compose_panel`'s `feet_x`/`feet_y`/`height_px` are exactly what the background
server's `generate_city_scene(anchor_x=, anchor_z=)` reports back — the two servers
meet at that seam with no code dependency.

## Transparent figures

Every pose and expression is matted by `comfy.matte()`, and anything that already
exists — a locked panel, a hand-drawn figure — by `comfy.matte_image()`:

```python
import comfy
comfy.matte_image("output/<project>/_scene1/FINAL_p01_arrival.png",
                  out_dir="output/<project>/_figures")
```

Both use **BiRefNet-general** through ComfyUI-RMBG, ~4–8 s. **That choice is a
license decision**: RMBG-2.0's downloadable weights are for non-commercial use only,
and BiRefNet (the model RMBG-2.0 is a fine-tune of) is MIT. A learned matte lands
ON the lineart, keeps white garments a brightness key would delete, and removes
backdrop trapped inside the silhouette.

Klein renders then go through `klein_workflow.clean_matte()`, which removes the pale
fringe a learned matte leaves between hair strands by flood-filling the backdrop from
the frame edge — it stops dead at Klein's black outline.

## Architecture

```
 MCP client (Claude)
        │  stdio
        ▼
   server.py  ──►  characters.py      (bible: pure data/IO, no GPU)
                   klein_workflow.py  ──HTTP──►  Klein ComfyUI (:8189, v0.41+)  ──►  GPU
                   comfy.py           ──HTTP──►  main ComfyUI (:8188) — matting only
                   tools/             (compositing, cropping, sheets: pure PIL, no GPU)
```

Two ComfyUIs on purpose: the main install runs LTX, the music model and matting
through add-ons never tested on v0.41, and upgrading it in place would risk all three
to gain nothing Klein needs.

### Why it's a *local* server

Each render runs on a local GPU, so a hosted multi-user deployment would mean paying
for everyone's GPU compute. Running locally keeps it free and private — the right
trade for a personal creative tool.

## Part of a wider webcomic/animation toolkit

This server generates characters and composites panels — it doesn't paint
backgrounds (see `webcomic-background-mcp`) or make videos (see the
**[Anime Production Skill](../anime-production-skill/README.md)**). More tools in the
same ecosystem are listed on [tobiasfong.github.io](https://tobiasfong.github.io).

---

# Setup Guide

> **Already have `webcomic-background-mcp` set up?** One Klein ComfyUI serves both
> servers — skip to **Step 3** (matting) here.

## Hardware: will it run on *your* machine?

Same as `webcomic-background-mcp` — see its
[hardware table](../webcomic-background-mcp/README.md#hardware-will-it-run-on-your-machine).
Measured on a 6 GB RTX 3060 Laptop: VRAM is not the constraint, because ComfyUI
streams weights from system RAM.

## Step 1 — Install ComfyUI v0.41 or later, and Klein

Follow the background server's
[Step 1 and Step 2](../webcomic-background-mcp/README.md#step-1--install-comfyui-v041-or-later):
a ComfyUI 0.41+ (this project keeps it separate, at `C:/AI/ComfyUI_flux3` on port
**8189**), and three files from BFL's gated `flux-3-image-klein-comfy` repo — each BFL
repo needs its own license click.

| Role | File | → Folder |
|------|------|----------|
| Diffusion model (step-distilled, INT8) | `flux3_image_klein_sd_int8_convrot.safetensors` | `diffusion_models/` |
| Text encoder | `qwen3vl_4b_int8_convrot.safetensors` | `text_encoders/` |
| VAE | `flux2-vae.safetensors` | `vae/` |

**INT8, not FP8**: an Ampere card has INT8 tensor cores and no native FP8; NVFP4 needs
Blackwell. The 9B prompt upsampler in the same repo is left off on purpose — it
rewrites the prompt, and every prompting rule here assumes the prompt the model sees
is the one that was written.

> **License: FLUX Kommunity License v1.0.** Commercial use of generated *outputs* is
> permitted for users under US$5M gross annual revenue, with content filtering or
> human review of outputs, and AI disclosure where the law requires it. Outputs may
> not be used to train models for commercial use. Read it on the repo page.

## Step 2 — The main ComfyUI, for matting

Any ComfyUI install works (default `C:/AI/ComfyUI_windows_portable`, port 8188). It
needs no diffusion model — only the matting node in Step 3.

## Step 3 — ComfyUI-RMBG and BiRefNet

Clone it into the main ComfyUI and install only these dependencies, not its full
`requirements.txt` — the rest is SAM and GroundingDINO segmentation, which this
server never uses:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/1038lab/ComfyUI-RMBG.git
<ComfyUI's python> -m pip install timm PyMatting
```

⚠ **RMBG's auto-downloader is broken against `huggingface_hub` 1.x** — it fails with
*"Cannot send a request, as the client has been closed"*, and that error appears
**only in ComfyUI's `/history`**, never to the client. Do not downgrade the hub;
place the weights by hand. Repo ids and target folders are in
`custom_nodes/ComfyUI-RMBG/py/AILab_BiRefNet.py` (`MODEL_CONFIG`); everything lands
under `models/RMBG/<cache_dir>/`. Check each model's license at its ORIGINAL source
before using it.

Restart ComfyUI so it loads the node. Without it, matting falls back to `rembg` with
`isnet-anime` (`WEBCOMIC_CHAR_REMBG_MODEL`).

## Step 4 — Set up this MCP server

```bash
git clone https://github.com/tobiasfong/webcomic-toolkit.git
cd webcomic-toolkit/servers/character-panel-mcp
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Linux/Mac: .venv/bin/python)
```

## Step 5 — Wire it into your MCP client

- **Claude Desktop:** add to `claude_desktop_config.json`:
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

After adding it, **fully quit and relaunch the client**.

## Step 6 — Use it

**Already have reference art?** *"Register these three images of Aria as a character
named 'hero' in project 'example_comic'."*

**No art yet?** *"Generate a character concept: gaunt young man, long nose, manic
grin, purple-and-black military uniform, white gloves, gold pocket chain"* — pick it
or ask for a reroll, then register it.

**Have a composite concept sheet?** *"Crop this sheet into the hero pose and the three
expression panels"* (`crop_reference`), then register the crops.

**From here on, all paths converge:**

1. *"Generate a turnaround sheet for aria."* Check every panel over the whole figure.
2. *"Generate a pose of aria: arms crossed, looking over her shoulder."*
3. *"Put aria and the captain in one scene: a night market, both turned toward a
   lantern stall."* (`generate_scene`)

### Helper scripts (`tools/`)

- **`check_bible.py --all`** — run before generating; non-zero means the bible
  cannot be trusted yet.
- **`compose_panel.py`** / **`crop_reference.py`** / **`compose_sheet.py`** — the
  GPU-free tools, also runnable standalone from the CLI.
- **`repair_hand.py`** — a boxed Klein redraw of one hand. Reroll the whole render
  first; it is the better odds.
- **`complete_figure.py`** — re-frame a clipped figure: a fresh render with the
  clipped one, padded, as its reference, on a taller canvas.
- **`cutout.py`** / **`place_cutout.py`** — color keying and placement for
  composites.
- **`magic_circle.py`** — draws a spell circle to RGBA. Flat symbolic marks are
  drawn, never generated.

### Your asset library (you provide this)

The repo ships the code, but no character art — the `characters/` folder is
git-ignored: it's your personal, often commissioned art, and shouldn't be
redistributed.

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `WEBCOMIC_CHAR_KLEIN_URL` | `http://127.0.0.1:8189` | The Klein ComfyUI |
| `WEBCOMIC_CHAR_KLEIN_DIR` | `C:\AI\ComfyUI_flux3` | Where to start it from on first use |
| `WEBCOMIC_CHAR_KLEIN_MODEL` / `_TE` / `_VAE` | the three files above | Klein's model files |
| `COMFY_URL` | `http://127.0.0.1:8188` | The main ComfyUI, for matting |
| `WEBCOMIC_CHAR_COMFY_DIR` / `WEBCOMIC_CHAR_COMFY_LAUNCH` | `C:\AI\ComfyUI_windows_portable` / `run_nvidia_gpu.bat` | Auto-launch of the main ComfyUI |
| `WEBCOMIC_CHAR_AUTOLAUNCH` | `1` | Set `0` to require a manually started main ComfyUI |
| `WEBCOMIC_CHAR_MATTE_MODEL` | `BiRefNet-general` | Matting model; check its license before changing it |
| `WEBCOMIC_CHAR_REMBG_MODEL` | `isnet-anime` | Fallback matte when ComfyUI-RMBG is absent |
| `WEBCOMIC_CHAR_OUTPUT` | `./output` | Where renders are written |
| `WEBCOMIC_CHAR_ROOT` | `./characters` | Where the Character Bible is stored |
| `WEBCOMIC_CHAR_PROJECT` | `default` | Default project when none is specified |

## Troubleshooting

- **`check_status` says the Klein ComfyUI isn't reachable** — it starts on the first
  render; if that fails, read `comfy_klein.log` beside the Klein install. A crash
  otherwise leaves no trace.
- **Matting failed / "produced no image"** — ComfyUI-RMBG or its BiRefNet weights are
  missing (Step 3). The real error is in the main ComfyUI's `/history`.
- **A figure comes back cut off at the head or feet** — the reference is a tight crop
  and the pose matches it, so Klein copied the crop. Pad the reference
  (`complete_figure.py` does), and check the description for "tall".
- **A pale fringe round the figure** — the raw learned matte; run
  `klein_workflow.clean_matte()` on it. Every tool here already does.
- **The tool never appears in your MCP client** — fully quit (not just close the
  window) and relaunch.

## Status

**v2.0.0 — FLUX 3 Klein only.** Character art for the author's own visual novel was
regenerated on it from scratch in October 2026: every sprite, expression, mob,
creature, prop and CG. The older SD1.5, SDXL and FLUX.1 paths are recorded in the
CHANGELOG and ARCHITECTURE.md.

Built with [Claude Code](https://claude.com/claude-code).
