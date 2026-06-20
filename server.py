"""
Webcomic Background Generator — MCP Server
==========================================
A local Model Context Protocol server that generates stylised background
art for comic panels in any aesthetic the user references, wrapping a local
ComfyUI + Stable Diffusion pipeline (checkpoint + ControlNet + IP-Adapter).

Exposes one tool:
  generate_background(prompt, sketch_path?, style_ref_path?, ...)

Requires a running ComfyUI instance (default http://127.0.0.1:8188).
Runs locally over stdio; the GPU work happens on this machine.
"""

import os
import sys
# Make imports work regardless of the working directory Claude Desktop launches us from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp.server.fastmcp import FastMCP
import workflow

mcp = FastMCP("webcomic-background-generator")

# Where finished backgrounds are written
OUTPUT_DIR = os.environ.get("WEBCOMIC_BG_OUTPUT", os.path.join(os.path.dirname(__file__), "output"))


@mcp.tool()
def generate_background(
    prompt: str,
    sketch_path: str | None = None,
    style_ref_path: str | None = None,
    width: int = 768,
    height: int = 512,
    seed: int | None = None,
    ipa_weight: float = 0.7,
    controlnet_strength: float = 1.0,
) -> str:
    """Generate a stylised background image for a comic panel, in any aesthetic.

    Args:
        prompt: Description of the scene (e.g. "medieval great hall", "cyberpunk
            neon alley", "hive city corridor"). Avoid describing characters —
            this tool makes empty backgrounds to draw over.
        sketch_path: Optional path to a rough perspective sketch (white lines
            on black). When given, ControlNet forces the output to match this
            composition/angle.
        style_ref_path: Optional path to a reference image whose visual style
            (palette, mood, grime) is transferred onto the result via IP-Adapter.
        width: Output width in px (default 768).
        height: Output height in px (default 512).
        seed: Fixed seed for reproducibility; omit for a random one.
        ipa_weight: Strength of the style transfer, 0.0–1.5 (default 0.7).
            Lower if the reference's colour bleeds in too strongly.
        controlnet_strength: How strictly to follow the sketch, 0.0–1.0
            (default 1.0).

    Returns:
        The filesystem path to the generated PNG.
    """
    try:
        out_path = workflow.generate(
            prompt=prompt,
            out_dir=OUTPUT_DIR,
            width=width,
            height=height,
            seed=seed,
            sketch_path=sketch_path,
            style_ref_path=style_ref_path,
            ipa_weight=ipa_weight,
            controlnet_strength=controlnet_strength,
        )
        return f"Background generated: {out_path}"
    except workflow.ComfyUIError as e:
        return (f"Generation failed: {e}\n"
                f"Is ComfyUI running at {workflow.COMFY_URL}?")


@mcp.tool()
def check_status() -> str:
    """Check whether the ComfyUI backend is reachable and ready."""
    import requests
    try:
        r = requests.get(f"{workflow.COMFY_URL}/system_stats", timeout=10)
        if r.status_code == 200:
            return f"ComfyUI is up at {workflow.COMFY_URL}."
        return f"ComfyUI responded with HTTP {r.status_code}."
    except Exception as e:
        return f"ComfyUI not reachable at {workflow.COMFY_URL}: {e}"


if __name__ == "__main__":
    mcp.run()
