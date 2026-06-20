# Grimdark Background MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that generates
grimdark-industrial **background art for comic panels**, wrapping a local
ComfyUI + Stable Diffusion pipeline.

It exists to solve one concrete problem in making an illustrated webcomic:
drawing detailed environment backgrounds is slow. This tool lets the artist
sketch a rough perspective, hand it a style reference, and get back a finished
background to draw characters onto — keeping the human in charge of characters,
story, and composition while offloading the repetitive scenery work.

## What it does

One MCP tool, `generate_background`, takes:

- a **prompt** (the scene),
- an optional **perspective sketch** — ControlNet forces the output to match
  the drawn angle/composition,
- an optional **style reference** — IP-Adapter transfers its palette and mood.

and returns a finished PNG. A second tool, `check_status`, reports whether the
generation backend is up.

## Architecture

```
 MCP client (Claude)
        │  stdio
        ▼
   server.py  ──►  workflow.py  ──HTTP──►  ComfyUI (:8188)  ──►  GPU
 (FastMCP tool)   (builds graph)          (SD1.5 + ControlNet
                                            + IP-Adapter)
```

The generation graph is assembled conditionally: the ControlNet (composition)
and IP-Adapter (style) branches are only added when a sketch / style reference
is supplied, so the tool degrades gracefully from "full control" down to a
plain text-to-image background.

### Why it's a *local* server

Each call runs Stable Diffusion on a local GPU. That makes a hosted, multi-user
deployment fundamentally different from a typical data-wrapping MCP server: every
request burns GPU compute that somebody has to pay for. Running locally keeps it
free and private, at the cost of single-machine availability — the right trade
for a personal creative tool. A hosted version would swap the ComfyUI backend for
a paid inference API (e.g. Replicate) behind rate limiting; the MCP layer above
would be unchanged.

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

Drop each file into the matching folder under `ComfyUI/models/`:

| Role | File | → Folder | Source |
|------|------|----------|--------|
| **Checkpoint** (SD 1.5) | `Counterfeit-V3.0_fp16.safetensors` | `checkpoints/` | [gsdf/Counterfeit-V3.0](https://huggingface.co/gsdf/Counterfeit-V3.0) |
| ControlNet (scribble) | `control_v11p_sd15_scribble_fp16.safetensors` | `controlnet/` | [comfyanonymous/ControlNet-v1-1_fp16](https://huggingface.co/comfyanonymous/ControlNet-v1-1_fp16_safetensors) |
| ControlNet (lineart, depth — optional) | `control_v11p_sd15_lineart_fp16.safetensors`, `control_v11f1p_sd15_depth_fp16.safetensors` | `controlnet/` | same repo |
| IP-Adapter | `ip-adapter_sd15.safetensors`, `ip-adapter-plus_sd15.safetensors` | `ipadapter/` | [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter/tree/main/models) |
| CLIP vision encoder | `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | `clip_vision/` | [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter/tree/main/models/image_encoder) (the `image_encoder/model.safetensors` — **rename it to exactly this**) |

> Any SD 1.5 checkpoint works (DreamShaper 8 is another good pick) — set the
> `GRIMDARK_CHECKPOINT` env var to point at it. The pipeline is SD 1.5, so don't
> mix in SDXL models.

## Step 3 — Install the custom nodes

ComfyUI needs two community node packs (the ControlNet preprocessors and the
IP-Adapter implementation). From `ComfyUI/custom_nodes/`:

```bash
git clone https://github.com/Fannovel16/comfyui_controlnet_aux.git
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
```

Then install the preprocessor dependencies with ComfyUI's Python (for the
portable build, that's `python_embeded/python.exe`):

```bash
python_embeded/python.exe -m pip install -r custom_nodes/comfyui_controlnet_aux/requirements.txt
```

Restart ComfyUI so it loads the new nodes.

## Step 4 — Set up this MCP server

```bash
git clone https://github.com/tobiasfong/Warhammer40000-background-mcp.git
cd Warhammer40000-background-mcp
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Linux/Mac: .venv/bin/python)
```

## Step 5 — Wire it into your MCP client

**The config location depends on your client** — this is the step that varies most:

- **Classic Claude Desktop:** add to `claude_desktop_config.json`:
  ```json
  {
    "mcpServers": {
      "grimdark-background": {
        "command": "C:/path/to/.venv/Scripts/python.exe",
        "args": ["C:/path/to/server.py"]
      }
    }
  }
  ```
- **Claude Code:** `claude mcp add grimdark-background -- /path/to/.venv/bin/python /path/to/server.py`
- **Newer "Cowork"-style desktop builds:** these manage MCP servers through an
  **Extensions/Connectors UI** or per-project config rather than the classic key —
  check your client's MCP/Extensions settings.

After adding it, **fully quit and relaunch the client** (see Troubleshooting —
just closing the window often isn't enough).

## Step 6 — Use it

1. Start ComfyUI (and leave it running).
2. In your MCP client, ask it to generate a background — e.g. *"Generate a hive
   city corridor background."* Optionally point it at a perspective sketch
   (`sketch_path`) and a style reference (`style_ref_path`).

---

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI backend address |
| `GRIMDARK_CHECKPOINT` | `Counterfeit_V3.safetensors` | SD checkpoint to use |
| `GRIMDARK_OUTPUT` | `./output` | Where finished PNGs are written |

## Troubleshooting

These are the real snags hit while building it:

- **`check_status` says ComfyUI isn't reachable** — ComfyUI isn't running, or
  it's on a different port. Start it; set `COMFY_URL` if needed.
- **`"ClipVision model not found"`** — the IP-Adapter loader auto-detects the CLIP
  vision model by filename. The file **must** be named exactly
  `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`. Rename and restart ComfyUI.
- **CUDA "not available" / `cudaErrorNotSupported` (NVIDIA)** — your GPU driver is
  older than the CUDA version PyTorch was built for. **Update your GPU driver**
  (GeForce Experience / NVIDIA app) and reboot.
- **The tool never appears in your MCP client** — the client reads its config at
  startup, and "close window" on many desktop apps only minimises to the system
  tray (the process keeps running). **Fully quit** (tray icon → Quit, or end the
  process in Task Manager) and relaunch.

## Status

Working prototype. The full pipeline — text-to-image, ControlNet composition
control, and IP-Adapter style transfer, individually and combined — is validated,
and the server is confirmed callable natively from an MCP client.
Built with [Claude Code](https://claude.com/claude-code).
