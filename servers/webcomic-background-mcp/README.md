# Webcomic Background Generator — MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that generates
**background art for comic panels** — Ming-dynasty cities, gothic hive cities, medieval
dungeons, whatever your story needs — in a crisp inked manhwa style, wrapping
[FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy)
on a local ComfyUI.

It exists to solve one concrete problem in making an illustrated webcomic:
drawing detailed environment backgrounds is slow. This tool lets the artist
describe a place (and optionally lay out its composition), and get back a
finished plate to put characters onto — keeping the human in charge of
characters, story and composition while offloading the repetitive scenery work.

> **v3.0.0 — FLUX 3 Klein only. FLUX.1-dev has been removed.**
> The server now renders exclusively with Klein, the model the sibling
> character-panel server already uses, so plates and figures come from one
> model and look like one drawing. With FLUX.1 went its manhwa LoRA (FLUX.1
> LoRAs cannot load in Klein), ControlNet (composition sketches are now passed
> to Klein as a reference image) and Kontext (edits now redraw only the box you
> give). It is also **~15x faster** — about 15 s per plate on a 6 GB laptop card,
> where FLUX.1 took ~225 s. See CHANGELOG for the measurements.
> **You will need Klein**; `setup_models.py` fetches it. There is no fallback model.

## What it does

The main tools:

- **`generate_background`** — a plate from a **prompt**, optionally with a
  composition **sketch** (white lines on black: it fixes the camera and where
  every object sits) and/or a registered **location** (the place's canonical
  plate, so a new view stays recognizably the same place — from any angle, not
  just the canon's own framing).
- **`generate_city_scene`** — a giant establishing panel from a procedural 3D
  gothic city, rendered to a sketch and drawn by Klein. Same seed = same city.
- **`generate_prop_scene`** — rows of repeated objects (first prop: bicycles)
  from real 3D meshes, so they don't fuse or crop the way invented rows do.
- **`edit_background`** — change one thing on an approved plate with a
  plain-English instruction; with a `mask_box`, nothing outside the box changes.
- **`register_location` / `list_world`** — the World Builder bible: register the
  plate you approved as a place's canon, then draw it again consistently.
- **`grade_plate`** — darken or color-grade a finished plate for mood (how you
  get a night or grimdark panel — never by asking the prompt for it).
- **`extract_palette`**, **`check_status`**, city-plan tools.

> **Prompting — rules measured on FLUX.1 and kept for Klein** (the far-distance
> one has already recurred on Klein; the others are carried over as standing rules).
> 1. **Name what the place IS, as physical objects.** No mood, lighting or
>    "cinematic" words; they drag the render toward semi-realistic murk. Darken
>    afterwards with `grade_plate`.
> 2. **No negatives.** There is no negative-prompt parameter, on purpose: the
>    model draws what a prompt names, including what it is told to avoid.
> 3. **Name what fills the far distance** — forest, hills, a rampart. Leave it
>    open and the model fills it from photographs: modern skylines behind a
>    Ming river port.
> 4. **Open with period and place** ("Ming dynasty … in Anhui"). It holds a
>    setting's architecture where a generic "ancient East Asian" invites drift.
>
> The house style sentence is appended automatically — the same one the
> character server uses.

### Generate a background around your character

Works with **your own hand-drawn characters**, not just generated ones:

1. **Size the plate to your character.** Pass `match_canvas_to=<character.png>`
   to `generate_background`. The plate comes back at your character's canvas
   size, and the response reports the exact `height_px` / `feet_x` / `feet_y` to
   composite with. (The character is not used to condition the render; it only
   sets dimensions.)
2. **Cut your character out**, if it isn't already transparent.
   `character-panel-mcp`'s `tools/cutout.py` keys a figure off a flat backdrop,
   including a scan or a drawing on white paper.
3. **Composite**, with that server's `compose_panel` — it takes *any* RGBA PNG
   and pastes it bottom-centered at a given feet position and height.

For a plate from `generate_city_scene`, use `anchor_x`/`anchor_z` instead of
step 1: it reports the on-screen character height and feet line for a spot in
the 3D city, with occlusion accounted for.

## Architecture

```
 MCP client (Claude)
        │  stdio
        ▼
   server.py  ──► klein.py ──HTTP──► Klein ComfyUI (:8189) ──► GPU
 (FastMCP tools)  (graphs,          (v0.41+, FLUX 3 Image Klein
                   plumbing)          INT8 + Qwen3-VL encoder)
        │
        ├─► citygen.py / props.py   3D geometry → composition sketches (CPU)
        ├─► world.py                the World Builder bible (JSON + canon PNGs)
        └─► tools/grade.py          mood grading (CPU)
```

Sketches and locations are both **reference images** to Klein, each introduced
by a lead sentence saying what it is for. The wording matters and is measured:
"render it as a finished scene" came back photoreal, and a sketch's black areas
were drawn as empty void until the lead said they are ground, walls and sky.
`klein.py` keeps the wording that passed.

### Why it's a *local* server

Each call runs a diffusion model on a local GPU. That makes a hosted, multi-user
deployment fundamentally different from a typical data-wrapping MCP server: every
request burns GPU compute that somebody has to pay for. Running locally keeps it
free and private, at the cost of single-machine availability — the right trade
for a personal creative tool. A hosted version would swap the ComfyUI backend for
a paid inference API behind rate limiting; the MCP layer above would be unchanged.

## Part of a wider webcomic/animation toolkit

This server produces still backgrounds and depth-parallax clips — it doesn't make videos.
For turning finished panels (including this tool's parallax clips) into a vertical promo
short or MV, see the companion
**[Anime Production Skill](https://github.com/tobiasfong/anime-production-skill)** — a
portable agent skill (works with Claude Code, Codex, Antigravity, and other AGENTS.md-aware
harnesses) built on Remotion. More tools in the same ecosystem — including a novel/comic
translation and lettering server — are listed on
[tobiasfong.github.io](https://tobiasfong.github.io).

---

# Setup Guide

> **Heads-up — this is not click-and-go.** You need an NVIDIA GPU, ~11 GB of
> model downloads, a Hugging Face account, and a ComfyUI install of v0.41 or
> later. It's aimed at users comfortable with a terminal. Budget an hour for
> first-time setup.

## Hardware: will it run on *your* machine?

| Hardware | Support | Reality |
|----------|---------|---------|
| **NVIDIA RTX 30/40-series** (≥6 GB VRAM) | ✅ **Tested** | The INT8 build this server defaults to. Developed on an RTX 3060 **Laptop** (6 GB): ~15 s per plate, 30–110 s with a sketch or location. |
| **NVIDIA RTX 50-series** | ✅ Expected | The repo's NVFP4 build is made for Blackwell; set `WEBCOMIC_BG_KLEIN_MODEL` to it. Untested here. |
| **Apple Silicon / AMD / Intel** | ⚠️ Untested | Depends on ComfyUI's Klein support for your backend. The INT8 and NVFP4 builds use NVIDIA tensor-core formats; the repo's bf16 build is the one to try. |
| **CPU only / integrated graphics** | ❌ Impractical | |

## Step 1 — Install ComfyUI v0.41 or later

Klein's nodes are core in **ComfyUI 0.41.0+** (or the 0.41.1 backport); older builds
show missing nodes. No custom node packs are needed.

- **NVIDIA (Windows):** download the [ComfyUI portable build](https://github.com/comfyanonymous/ComfyUI/releases) and extract it.
- **Already have an older ComfyUI with add-ons you rely on?** Install Klein's as a
  **separate** portable build rather than upgrading in place. This project does
  exactly that: Klein lives at `C:/AI/ComfyUI_flux3` on port **8189**, beside the main
  install, and the server starts it on first use. Point `WEBCOMIC_BG_KLEIN_DIR` /
  `WEBCOMIC_BG_KLEIN_URL` at yours.

## Step 2 — Download the models

The repo is **gated**: open
[black-forest-labs/flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy),
accept the license, then make a read token at
[huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). Each BFL repo
needs its own click — accepting the main Klein repo does not cover this one. Then:

```bash
python setup_models.py --comfy "C:/AI/ComfyUI_flux3/ComfyUI"
```

with `HF_TOKEN` set in the environment. It skips files already present. Or place them
by hand under `ComfyUI/models/`:

| Role | Saved as | → Folder | In the repo |
|------|----------|----------|-------------|
| **Diffusion model** (step-distilled, INT8) | `flux3_image_klein_sd_int8_convrot.safetensors` | `diffusion_models/` | `diffusion_models/flux3-image-klein-int8-convrot.safetensors` |
| **Text encoder** | `qwen3vl_4b_int8_convrot.safetensors` | `text_encoders/` | same name |
| **VAE** | `flux2-vae.safetensors` | `vae/` | same name |

> Use the **distilled** model, not the `-base-` file beside it: base is for
> fine-tuning and wants far more steps. The 9B **prompt upsampler** in the same repo
> is deliberately not used — it rewrites your prompt before generation, and the
> prompting rules above only hold for the prompt you wrote.

> **License: FLUX Kommunity License v1.0.** Commercial use of generated *outputs*
> is permitted for users under US$5M gross annual revenue; above that, BFL's
> self-hosted license or API applies. Outputs may not be used to train models for
> commercial use. Read it on the repo page before relying on it.

## Step 3 — Set up this MCP server

This server lives in the `webcomic-toolkit` monorepo — clone the whole repo, but you
only need to install this one server's dependencies:

```bash
git clone https://github.com/tobiasfong/webcomic-toolkit.git
cd webcomic-toolkit/servers/webcomic-background-mcp
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Linux/Mac: .venv/bin/python)
```

## Step 4 — Wire it into your MCP client

**The config location depends on your client** — this is the step that varies most:

- **Classic Claude Desktop:** add to `claude_desktop_config.json`:
  ```json
  {
    "mcpServers": {
      "webcomic-background-generator": {
        "command": "C:/path/to/.venv/Scripts/python.exe",
        "args": ["C:/path/to/server.py"]
      }
    }
  }
  ```
- **Claude Code:** `claude mcp add webcomic-background-generator -- /path/to/.venv/bin/python /path/to/server.py`
- **Newer "Cowork"-style desktop builds:** these manage MCP servers through an
  **Extensions/Connectors UI** or per-project config rather than the classic key —
  check your client's MCP/Extensions settings.

After adding it, **fully quit and relaunch the client** (see Troubleshooting —
just closing the window often isn't enough).

## Step 5 — Use it

1. Run `check_status` — it reports whether the Klein ComfyUI is up, and if not,
   whether it is installed with all three model files. The first render starts it.
2. Ask for a background, e.g. *"Ming dynasty Huizhou town lane in Anhui,
   whitewashed walls, black tile roofs, a stone arch bridge over a canal, green
   hills behind."* Then:
   - **`sketch_path`** — a composition sketch from `tools/make_sketch.py` (a photo
     or a drawing → white lines on black; hand-drawn sketches are detected and
     binarized rather than edge-detected).
   - **`location`** — a registered place, to stay on-model from a new angle.
   - Approve a keeper → `register_location` it → later panels pass `location`.

### Helper scripts (`tools/`)

- **`make_sketch.py`** — turn a reference photo or drawing into a composition
  sketch (white lines on black) for `sketch_path`. Tune `--low/--high/--blur` for
  line density.
- **`grade.py`** — color-grade a finished plate for mood (`--preset grimdark`,
  `night`, `dusk`…). The same thing `grade_plate` does from the MCP side.
- **`letter_plaque.py`** — set real hanzi onto a blank board or scroll. The model
  writes pseudo-characters, so ask for a plain board and letter it here: traditional
  forms, right to left as Ming horizontal inscriptions read (`--ltr` for modern
  order), `--vertical` for a hanging scroll, `--fill` to repaint a board that came
  back with marks on it. Uses SimSun, so it needs a font with traditional glyphs.

To remove a stray figure or a fake sign, use `edit_background` with a `mask_box`
and phrase it as what to leave behind ("remove the person completely, leave only
the empty paved lane").

### Your asset library (you provide this)

The repo ships the **code and the model downloader, but no reference images** — the
`references/` folder is git-ignored because such images are typically copyrighted
(game screenshots, manhwa panels) and shouldn't be redistributed. Curate your own:
drop environment photos / concept refs in `references/`, turn them into composition
sketches with `tools/make_sketch.py`, and pass them as `sketch_path`. The model
supplies the *style*; your library supplies the *structure*.

---

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `WEBCOMIC_BG_KLEIN_URL` | `http://127.0.0.1:8189` | The Klein ComfyUI's address |
| `WEBCOMIC_BG_KLEIN_DIR` | `C:\AI\ComfyUI_flux3` | Its portable install, for auto-launch |
| `WEBCOMIC_BG_AUTOLAUNCH` | `1` | Set `0` to require a manually started Klein ComfyUI |
| `WEBCOMIC_BG_KLEIN_LAUNCH_TIMEOUT` | `180` | Seconds to wait for it to come up |
| `WEBCOMIC_BG_KLEIN_MODEL` / `_TE` / `_VAE` | the INT8 files above | Swap in the FP8, NVFP4 or bf16 builds |
| `WEBCOMIC_BG_OUTPUT` | `./output` | Where finished PNGs are written |
| `WEBCOMIC_BG_PROJECT` | `default` | Default project (World Builder namespace) |

## Troubleshooting

- **`check_status` says the Klein ComfyUI isn't installed or files are missing** —
  see Steps 1–2. If it is installed but won't start, read `comfy_klein.log` in the
  install folder; a crash there leaves no other trace.
- **Missing node errors (`EmptyFlux2LatentImage`, `ReferenceMultiLatent`…)** — that
  ComfyUI is older than v0.41.
- **A download fails as "not a valid safetensors file"** — the license on that
  exact repo isn't accepted, or `HF_TOKEN` is missing.
- **Two servers, one queue** — the character-panel server shares this ComfyUI. A
  render waits behind the other server's job, and its timeout counts the wait.
- **Renders look murky / semi-realistic** — check the prompt for mood words
  ("grimdark", "dim lighting", "deep shadow"). Remove them; darken with `grade_plate`.
- **A modern skyline or tower appears in the distance** — the prompt left the far
  distance open. Name what fills it (forest, hills, a city wall).
- **Fake characters on signs and banners** — the model writes pseudo-text. Ask for
  a plain board, then letter the real characters yourself.
- **The tool never appears in your MCP client** — the client reads its config at
  startup, and "close window" on many desktop apps only minimizes to the system
  tray (the process keeps running). **Fully quit** and relaunch.

## Status

Working. Klein rendering with the house style, composition sketches and World
Builder locations as references, 3D city and prop geometry, region-exact editing,
and post-hoc mood grading — each verified end to end through the server's own tool
functions in the v3.0.0 port.
Built with [Claude Code](https://claude.com/claude-code).
