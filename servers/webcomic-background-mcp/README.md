# Webcomic Background Generator — MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that generates
**background art for comic panels** in any aesthetic you reference — grimdark sci-fi,
medieval fantasy, cyberpunk, you name it — wrapping a local ComfyUI + FLUX.1-dev
pipeline.

It exists to solve one concrete problem in making an illustrated webcomic:
drawing detailed environment backgrounds is slow. This tool lets the artist
sketch a rough perspective, hand it a style reference, and get back a finished
background to draw characters onto — keeping the human in charge of characters,
story, and composition while offloading the repetitive scenery work.

## What it does

One MCP tool, `generate_background`, takes:

- a **prompt** (the scene + palette/mood),
- an optional **perspective sketch** — ControlNet forces the output to match the
  drawn angle/composition (feed an edge map of a reference photo to lock structure),
- an optional **reference image** (`location`) — img2img from approved art, which
  inherits its style, palette *and* composition. The strongest way to get a
  consistent look.

and returns a finished PNG. A second tool, `check_status`, reports whether the
generation backend is up.

> **v2.0.0 — FLUX.1-dev only. Stable Diffusion 1.5 has been removed.**
> This server now renders exclusively with FLUX.1-dev (GGUF-quantised, so it
> fits a 6 GB card). The SD1.5 pipeline, its checkpoints, and the
> `character_path` mode are gone — see CHANGELOG for the reasoning, but in
> short: the sibling character-panel server generates figures with FLUX, and
> SD1.5 plates under FLUX figures look pasted together. **You will need FLUX**;
> `setup_models.py` fetches it. If VRAM is tight use a smaller GGUF quantisation
> (Q3_K_S is the default, Q2 exists) — there is deliberately no lower-quality
> fallback path. Note FLUX.1-dev's licence covers the *model* (non-commercial)
> but permits commercial use of generated *outputs*.
>
> **v1.8.0 — 3D props (`generate_prop_scene`).** Diffusion fuses, crops, or
> mutates rows of repeated objects (a bike rack, market stalls) when asked to
> invent their structure. This tool gives objects the same treatment buildings
> get from Metropolis mode: parametric 3D prop meshes (`props.py` — first prop:
> bicycle) placed in-scene with true occlusion, auto-framed, rendered headless
> to a projection-correct sketch, painted once by the checkpoint. Pass
> `objects=[{type,x,z,yaw,scale}]`, or just `n_bikes=4` for a realistic parked
> row under a carport (`setting="shelter"`).

> **Design note — where the look comes from.** There is no IP-Adapter style path.
> Steer structure with the **sketch**, and the look either through the **prompt**
> or — better — by pointing `location` at approved art and letting img2img inherit
> it. One hard-won rule: **keep mood and lighting words out of FLUX prompts**
> ("grimdark", "dim lighting", "deep shadow"). They drag it toward semi-realistic
> murk. Name the subject, let FLUX light it, then darken with `grade_plate`.

### Generate a background around your character

Still supported — the workflow survives v2.0.0, only the mechanism changed.
The old `character_path` mode was an SD1.5 two-pass inpaint and went with the
SD1.5 removal. What replaced it is three explicit steps instead of one implicit
one, and it works with **your own hand-drawn characters**, not just generated
ones:

1. **Size the plate to your character.** Pass `match_canvas_to=<character.png>`
   to `generate_background`. The plate comes back at your character's canvas
   size, and the response reports the exact `height_px` / `feet_x` / `feet_y` to
   composite with. (The character is not used to condition the render — FLUX has
   no equivalent to the old inpaint path — it only sets dimensions.)
2. **Cut your character out**, if it isn't already transparent.
   `character-panel-mcp`'s `tools/cutout.py` keys a figure off a flat backdrop,
   including a scan or a drawing on white paper.
3. **Composite**, with that server's `compose_panel` — it takes *any* RGBA PNG
   and pastes it bottom-centred at a given feet position and height. It does not
   care whether the figure was generated or drawn by hand.

For a plate from `generate_city_scene`, use `anchor_x`/`anchor_z` instead of
step 1: it reports the on-screen character height and feet line for a spot in
the 3D city, with occlusion accounted for, which is exactly what step 3 wants.

## Architecture

```
 MCP client (Claude)
        │  stdio
        ▼
   server.py  ──► flux_workflow.py ──HTTP──► ComfyUI (:8188) ──► GPU
 (FastMCP tool)   (builds graph)   comfy.py   (FLUX.1-dev GGUF
                                   (plumbing)  + ControlNet Union
                                                + Kontext editing)
```

The generation graph is assembled conditionally: a style LoRA, a ControlNet
(composition) branch, and an img2img seed for World Builder locations are added
only when relevant, so the tool degrades gracefully from "full control" down to
a plain text-to-image background.

### Why it's a *local* server

Each call runs FLUX.1-dev on a local GPU. That makes a hosted, multi-user
deployment fundamentally different from a typical data-wrapping MCP server: every
request burns GPU compute that somebody has to pay for. Running locally keeps it
free and private, at the cost of single-machine availability — the right trade
for a personal creative tool. A hosted version would swap the ComfyUI backend for
a paid inference API (e.g. Replicate) behind rate limiting; the MCP layer above
would be unchanged.

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

> **Heads-up — this is not click-and-go.** You need a reasonably capable GPU,
> ~15 GB of model downloads, and a working ComfyUI install. It's aimed at users
> comfortable with a terminal. Budget an hour for first-time setup.

## Hardware: will it run on *your* machine?

The generation runs on ComfyUI, so your GPU options are ComfyUI's options. Be
realistic about what you have — performance varies enormously:

| Hardware | Support | Reality |
|----------|---------|---------|
| **NVIDIA** (GTX 16-series / RTX 20-series and newer, ≥6 GB VRAM) | ✅ **Best** | Easiest path. Use the ComfyUI portable build (bundles CUDA). This project was developed on an RTX 3060 Laptop (6 GB). |
| **Apple Silicon** (M1–M4 Macs) | ✅ Good | ComfyUI supports the Metal (MPS) backend natively. Slower than a discrete NVIDIA card but very usable. |
| **AMD Radeon** | ⚠️ Workable | **Linux:** good via ROCm. **Windows:** harder — DirectML (slower) or ZLUDA (experimental). Doable, not effortless. |
| **Intel Arc** (discrete) | ⚠️ Experimental | Via Intel's IPEX or DirectML. Improving, but less mature than NVIDIA/Mac. |
| **Integrated graphics** (Intel UHD/Iris, AMD APU) | ❌ Impractical | Technically runs via DirectML but shares system RAM and is *painfully* slow. Not recommended. |
| **CPU only** | ❌ Last resort | Works, but minutes-per-image. Fine to test the plumbing, miserable for real use. |

If you're not on NVIDIA or Apple Silicon, follow ComfyUI's
[hardware-specific install instructions](https://github.com/comfyanonymous/ComfyUI#installing)
for your platform — the rest of this guide (models, nodes, this server) is identical.

## Step 1 — Install ComfyUI

- **NVIDIA (Windows):** download the [ComfyUI portable build](https://github.com/comfyanonymous/ComfyUI/releases) (`ComfyUI_windows_portable_nvidia.7z`), extract it. It bundles a CUDA-enabled PyTorch.
- **Everything else:** follow the [ComfyUI manual install](https://github.com/comfyanonymous/ComfyUI#manual-install-windows-linux) and install the PyTorch build for your hardware (ROCm / DirectML / IPEX / MPS / CPU).

Confirm it launches and reports your GPU before continuing.

## Step 2 — Download the models

**Easiest:** run the bundled downloader (no API token needed; skips files already
present). It pulls all three render checkpoints + VAE + ControlNet + LoRA — budget
**~10 GB**:

```bash
python setup_models.py --comfy "C:/AI/ComfyUI_windows_portable/ComfyUI"
```

That fetches the stack below. Or place them manually under `ComfyUI/models/`:

| Role | File | → Folder | Source |
|------|------|----------|--------|
| **FLUX.1-dev unet** (the renderer) | `flux1-dev-Q3_K_S.gguf` | `unet/` | [city96/FLUX.1-dev-gguf](https://huggingface.co/city96/FLUX.1-dev-gguf) |
| **Text encoders** (FLUX uses two) | `t5xxl_fp8_e4m3fn.safetensors`, `clip_l.safetensors` | `clip/` | [comfyanonymous/flux_text_encoders](https://huggingface.co/comfyanonymous/flux_text_encoders) |
| **VAE** | `ae.safetensors` | `vae/` | [black-forest-labs/FLUX.1-schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell) |
| **ControlNet** (composition / sketch) | `flux_controlnet_union_pro2.safetensors` | `controlnet/` | [Shakker-Labs Union Pro 2.0](https://huggingface.co/Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0) |
| **Style LoRA** (the manhwa look) | `manwha_style.safetensors` | `loras/` | [Civitai](https://civitai.com/models/793264) |
| FLUX Kontext (for `edit_background`) | `flux1-kontext-dev-Q3_K_S.gguf` | `unet/` | [QuantStack/FLUX.1-Kontext-dev-GGUF](https://huggingface.co/QuantStack/FLUX.1-Kontext-dev-GGUF) |

> **You need the [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) custom
> node** — ComfyUI's stock loader cannot read `.gguf`. Install it before running
> `setup_models.py`.

> **VRAM.** `Q3_K_S` (~5 GB) is chosen so FLUX fits a 6 GB card, and is what this
> project is developed on. On 8 GB+ substitute `Q4_K_S` from the same repo for
> better quality; below 6 GB, smaller quants (Q2) exist. **There is no SD1.5
> fallback** — see v2.0.0 in the CHANGELOG for why.

> **Style LoRA strength matters.** `manwha_style` is applied at **1.5**, not the
> usual 1.0 — below that it loses the fight against ControlNet conditioning and
> renders washed out. 2.0 goes muddy under a sketch, but in plain txt2img gives a
> more cinematic, painterly register if you want it.

## Step 3 — Install the custom nodes

The pipeline uses only **core** ComfyUI nodes (checkpoint, LoRA, ControlNet apply,
VAE, inpaint) — no IP-Adapter node pack required. The only optional extra is the
ControlNet **preprocessors**, if you want ComfyUI to make sketches for you (this
server ships its own `tools/make_sketch.py`, so it's optional). From
`ComfyUI/custom_nodes/`:

```bash
git clone https://github.com/Fannovel16/comfyui_controlnet_aux.git
```

Then install its dependencies with ComfyUI's Python (for the portable build,
that's `python_embeded/python.exe`):

```bash
python_embeded/python.exe -m pip install -r custom_nodes/comfyui_controlnet_aux/requirements.txt
```

Restart ComfyUI so it loads the new nodes.

## Step 4 — Set up this MCP server

This server lives in the `webcomic-toolkit` monorepo — clone the whole repo, but you
only need to install this one server's dependencies:

```bash
git clone https://github.com/tobiasfong/webcomic-toolkit.git
cd webcomic-toolkit/servers/webcomic-background-mcp
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Linux/Mac: .venv/bin/python)
```

## Step 5 — Wire it into your MCP client

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

## Step 6 — Use it

1. ComfyUI auto-launches on the first call (or start it yourself and leave it running).
2. In your MCP client, ask it to generate a background — e.g. *"Generate a hive
   city corridor at night, deep blue moonlight."* Options:
   - **`sketch_path`** — an edge map (e.g. of a Warhammer 40K hive photo, via
     `tools/make_sketch.py`) to force that composition/structure. Hand-drawn
     sketches are auto-detected and binarised rather than Canny-ed.
   - **`location`** — img2img from a registered reference, inheriting its style,
     palette and composition. The most reliable way to stay on-model.
   - **`hires`** — 1.5x upscale + light re-detail pass for dense panels.

### Helper scripts (`tools/`)

- **`make_sketch.py`** — turn a reference photo into a ControlNet sketch (white
  lines on black) for `sketch_path`. Tune `--low/--high/--blur` for line density.
- **`grade.py`** — colour-grade a finished plate for mood (`--preset grimdark`,
  `night`, `dusk`…). This is how you get a dark panel; don't ask the prompt for it.
- **`inpaint_region.py`** — paint a rectangular region back into scenery, e.g. to
  remove a stray figure the model dropped in:
  `python tools/inpaint_region.py <image> x0 y0 x1 y1`. Keeps your background layer
  figure-free. (Character-plate mode already returns a figure-free plate — this is
  for cleaning unexpected extras.)

### Your asset library (you provide this)

The repo ships the **code and the model downloader, but no reference images** — the
`references/` folder is git-ignored because such images are typically copyrighted
(game screenshots, manhwa panels) and shouldn't be redistributed. Curate your own:
drop environment photos / concept refs in `references/`, turn them into composition
sketches with `tools/make_sketch.py`, and pass them as `sketch_path`. The models
supply the *style*; your library supplies the *structure*.

---

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI backend address |
| `WEBCOMIC_BG_MODEL` | `flux_manwha` | Render model (FLUX only as of v2.0.0) |
| `WEBCOMIC_BG_FLUX_LORA` | `manwha_style.safetensors` | Style LoRA in `models/loras`; `""` disables |
| `WEBCOMIC_BG_FLUX_LORA_STRENGTH` | `1.5` | LoRA strength — see the note above; 1.0 renders washed out |
| `WEBCOMIC_BG_FLUX_CN_SYNTHETIC` / `_DRAWN` | `0.95` / `0.70` | ControlNet strength for generated vs hand-drawn sketches |
| `WEBCOMIC_BG_OUTPUT` | `./output` | Where finished PNGs are written |
| `WEBCOMIC_BG_COMFY_DIR` / `WEBCOMIC_BG_COMFY_LAUNCH` | `C:\AI\ComfyUI_windows_portable` / `run_nvidia_gpu.bat` | Auto-launch location/script for ComfyUI |
| `WEBCOMIC_BG_AUTOLAUNCH` | `1` | Set `0` to require a manually-started ComfyUI |

> Model definitions live in `FLUX_MODELS` in `flux_workflow.py`. Add entries there
> to register another FLUX quantisation (e.g. a Q4_K_S unet on a larger card).

## Troubleshooting

These are the real snags hit while building it:

- **`check_status` says ComfyUI isn't reachable** — ComfyUI isn't running, or
  it's on a different port. Start it; set `COMFY_URL` if needed.
- **`UnetLoaderGGUF` not found** — the [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF)
  custom node isn't installed. FLUX's `.gguf` files can't be read without it.
- **Out of memory** — drop to a smaller quantisation (Q2) or lower `width`/`height`.
  Q3_K_S at 896x672 is about the ceiling on a 6 GB card.
- **Stray people/figures in open scenes** — FLUX barely honours negative prompts at
  `cfg=1.0`, so `extra_negative` helps less than you'd expect. Describe the scene so
  completely there's no room for a figure (e.g. fill the floor with pews) — that
  works where negation doesn't.
- **Renders look murky / semi-realistic instead of manhwa** — check your prompt for
  mood words ("grimdark", "dim lighting", "deep shadow"). Remove them, then darken
  with `grade_plate` afterwards.
- **CUDA "not available" / `cudaErrorNotSupported` (NVIDIA)** — your GPU driver is
  older than the CUDA version PyTorch was built for. **Update your GPU driver**
  (GeForce Experience / NVIDIA app) and reboot.
- **The tool never appears in your MCP client** — the client reads its config at
  startup, and "close window" on many desktop apps only minimises to the system
  tray (the process keeps running). **Fully quit** (tray icon → Quit, or end the
  process in Task Manager) and relaunch.

## Status

Working. The pipeline — FLUX.1-dev rendering with the manhwa style LoRA, ControlNet
composition control from generated or hand-drawn sketches, World Builder img2img for
location consistency, 3D city and prop geometry, Kontext editing, and post-hoc mood
grading — is validated, and the server is confirmed callable natively from an MCP
client.
Built with [Claude Code](https://claude.com/claude-code).
