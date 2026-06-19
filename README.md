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

## Prerequisites

- A running **ComfyUI** instance (default `http://127.0.0.1:8188`)
- These models installed in ComfyUI:
  - Checkpoint: `Counterfeit_V3.safetensors` (any SD1.5 checkpoint works — set `GRIMDARK_CHECKPOINT`)
  - ControlNet: `control_v11p_sd15_scribble_fp16.safetensors`
  - IP-Adapter (SD1.5) + `CLIP-ViT-H-14-laion2B-s32B-b79K` CLIP vision encoder
  - Custom nodes: `comfyui_controlnet_aux`, `ComfyUI_IPAdapter_plus`

## Install

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

## Run / connect

Register it with an MCP client (e.g. Claude Desktop) by adding to its config:

```json
{
  "mcpServers": {
    "grimdark-background": {
      "command": "C:/AI/grimdark-background-mcp/.venv/Scripts/python.exe",
      "args": ["C:/AI/grimdark-background-mcp/server.py"]
    }
  }
}
```

Then ask the client to generate a background, optionally pointing it at a sketch
and a style reference.

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI backend address |
| `GRIMDARK_CHECKPOINT` | `Counterfeit_V3.safetensors` | SD checkpoint to use |
| `GRIMDARK_OUTPUT` | `./output` | Where finished PNGs are written |

## Status

Working prototype. Generation pipeline (text-to-image, ControlNet composition
control, and IP-Adapter style transfer — individually and combined) is validated.
Built with [Claude Code](https://claude.com/claude-code).
