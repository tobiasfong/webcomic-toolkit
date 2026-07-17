# Webcomic Background Generator — MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that generates
**background art for comic panels** in any aesthetic you reference — grimdark sci-fi,
medieval fantasy, cyberpunk, you name it — wrapping a local ComfyUI + Stable Diffusion
pipeline.

It exists to solve one concrete problem in making an illustrated webcomic:
drawing detailed environment backgrounds is slow. This tool lets the artist
sketch a rough perspective, hand it a style reference, and get back a finished
background to draw characters onto — keeping the human in charge of characters,
story, and composition while offloading the repetitive scenery work.

## What it does

One MCP tool, `generate_background`, takes:

- a **prompt** (the scene + palette/mood),
- a **model** (`solstice` Korean-manhwa default, `counterfeit`, or `dreamshaper`) —
  the *aesthetic comes from the model itself*,
- an optional **perspective sketch** — ControlNet forces the output to match the
  drawn angle/composition (feed an edge map of a reference photo to lock structure),
- an optional **character** (`character_path`) — see below.

and returns a finished PNG. A second tool, `check_status`, reports whether the
generation backend is up.

> **Design note — no IP-Adapter.** Earlier versions used an IP-Adapter style
> reference to push a palette. In practice a model trained on the target look
> (e.g. the Solstice manhwa checkpoint) renders the aesthetic natively and more
> cleanly, so the IP-Adapter was removed. Steer palette/mood through the **prompt**
> and structure through the **sketch**.

### Generate a background *around your character* (`character_path`)

Instead of describing the camera angle, you can just **draw the character first**
and hand it over. The tool uses the character only as a *spatial guide* — for
scale, perspective, horizon and camera angle — and returns a **background plate
with the character absent**, so you import it as its own layer under your art and
keep painting (snow at the feet, etc.).

- Export the character as a **PNG with a transparent background** for the cleanest
  mask. A character on **plain white** also works (the backdrop is segmented out;
  white *inside* the character is preserved).
- It runs a **two-pass inpaint**: pass 1 generates the scene around the locked
  character (fixing scale/horizon to it); pass 2 fills the character's silhouette
  with matching background so there are no holes behind it.
- The character is **never in the output** — only the background plate is, sized
  to your canvas (capped to an SD-friendly resolution; upscale the soft result in
  your editor if you drew large).
- Style reference, sketch and prompt all still apply on top of this.

> Needs `pillow` and `numpy` in the server venv (they're in `requirements.txt`).

## Architecture

```
 MCP client (Claude)
        │  stdio
        ▼
   server.py  ──►  workflow.py  ──HTTP──►  ComfyUI (:8188)  ──►  GPU
 (FastMCP tool)   (builds graph)          (SD1.5 + ControlNet
                                            + IP-Adapter)
```

The generation graph is assembled conditionally: a LoRA, a ControlNet
(composition) branch, a standalone VAE, and the character-plate inpaint passes are
added only when relevant, so the tool degrades gracefully from "full control" down
to a plain text-to-image background.

### Why it's a *local* server

Each call runs Stable Diffusion on a local GPU. That makes a hosted, multi-user
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
| **Checkpoint** (default — Korean manhwa) | `solstice_manhwa_v10.safetensors` | `checkpoints/` | [Solstice (Civitai)](https://civitai.com/models/48797) |
| **VAE** (Solstice is "NoEMA" — ships no VAE) | `vae-ft-mse-840000-ema-pruned.safetensors` | `vae/` | [stabilityai/sd-vae-ft-mse-original](https://huggingface.co/stabilityai/sd-vae-ft-mse-original) |
| ControlNet (scribble) | `control_v11p_sd15_scribble_fp16.safetensors` | `controlnet/` | [comfyanonymous/ControlNet-v1-1_fp16](https://huggingface.co/comfyanonymous/ControlNet-v1-1_fp16_safetensors) |
| Manhwa LoRA (optional) | `ManhwaUltimate.safetensors` | `loras/` | [Manhwa 4-in-1 (Civitai)](https://civitai.com/models/5086) |
| Niji V5 style LoRA (optional) | `NijiV5Style.safetensors` | `loras/` | [Niji V5 Style (Civitai)](https://civitai.com/models/131644/nijiyuanniji-v5-style-lora) |
| Alt checkpoints (optional) | `Counterfeit_V3.safetensors`, `DreamShaper_8.safetensors` | `checkpoints/` | [Counterfeit-V3.0](https://huggingface.co/gsdf/Counterfeit-V3.0), [DreamShaper](https://huggingface.co/Lykon/DreamShaper) |

> **Style LoRAs are per-call, not fixed at install.** Pass `lora="ManhwaUltimate.safetensors"`
> (trigger word `fantasy-style`) for the gothic/western manhwa look, or
> `lora="NijiV5Style.safetensors"` (trigger word `midjourney`) for a strong East-Asian
> architectural bias (pagodas, lanterns) — great for stories with that setting, but it
> will fight a gothic/western ControlNet sketch, so it's not the default. Remember to
> include the trigger word in your prompt when you pick a LoRA.

> SD 1.5 only — don't mix in SDXL models. Pick the render model per call with the
> `model` arg (`solstice`/`counterfeit`/`dreamshaper`) or set `WEBCOMIC_BG_MODEL`.
> The **IP-Adapter and CLIP-vision models are no longer needed** — the aesthetic
> comes from the checkpoint.

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
   - **`model`** — `solstice` (default), `counterfeit`, or `dreamshaper`.
   - **`sketch_path`** — an edge map (e.g. of a Warhammer 40K hive photo, via
     `tools/make_sketch.py`) to force that composition/structure.
   - **`character_path`** — a drawn character PNG to build the background *around*
     (returns a plate with the character absent, sized to your canvas).

### Helper scripts (`tools/`)

- **`make_sketch.py`** — turn a reference photo into a ControlNet sketch (white
  lines on black) for `sketch_path`. Tune `--low/--high/--blur` for line density.
- **`inpaint_region.py`** — paint a rectangular region back into scenery, e.g. to
  remove a stray figure a character-trained model (Solstice) dropped in:
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
| `WEBCOMIC_BG_MODEL` | `solstice` | Default render model (`solstice` / `counterfeit` / `dreamshaper`) |
| `WEBCOMIC_BG_LORA` | *(empty)* | Optional style LoRA filename in `models/loras` (e.g. `ManhwaUltimate.safetensors`) |
| `WEBCOMIC_BG_LORA_STRENGTH` | `0.8` | LoRA strength when one is set |
| `WEBCOMIC_BG_OUTPUT` | `./output` | Where finished PNGs are written |
| `WEBCOMIC_BG_COMFY_DIR` / `WEBCOMIC_BG_COMFY_LAUNCH` | `C:\AI\ComfyUI_windows_portable` / `run_nvidia_gpu.bat` | Auto-launch location/script for ComfyUI |
| `WEBCOMIC_BG_AUTOLAUNCH` | `1` | Set `0` to require a manually-started ComfyUI |

> Model→checkpoint/VAE pairings live in `MODELS` in `workflow.py` (Solstice maps to
> its standalone VAE automatically). Add your own entries there to register more models.

## Troubleshooting

These are the real snags hit while building it:

- **`check_status` says ComfyUI isn't reachable** — ComfyUI isn't running, or
  it's on a different port. Start it; set `COMFY_URL` if needed.
- **`"VAE is invalid: None"`** — a "NoEMA" checkpoint (e.g. Solstice) has no built-in
  VAE. Make sure the standalone VAE is installed and the model's `MODELS` entry in
  `workflow.py` points at it (the `solstice` entry already does).
- **Stray people/figures in open scenes** — manhwa checkpoints are character-trained.
  The default negative suppresses this; add more via `extra_negative` if needed.
- **CUDA "not available" / `cudaErrorNotSupported` (NVIDIA)** — your GPU driver is
  older than the CUDA version PyTorch was built for. **Update your GPU driver**
  (GeForce Experience / NVIDIA app) and reboot.
- **The tool never appears in your MCP client** — the client reads its config at
  startup, and "close window" on many desktop apps only minimises to the system
  tray (the process keeps running). **Fully quit** (tray icon → Quit, or end the
  process in Task Manager) and relaunch.

## Status

Working prototype. The pipeline — model-native manhwa/anime rendering (Solstice /
Counterfeit / DreamShaper, with optional LoRA), ControlNet composition control, and
the character-plate inpaint mode — is validated, and the server is confirmed
callable natively from an MCP client.
Built with [Claude Code](https://claude.com/claude-code).
