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
import world

mcp = FastMCP("webcomic-background-generator")

# Where finished backgrounds are written
OUTPUT_DIR = os.environ.get("WEBCOMIC_BG_OUTPUT", os.path.join(os.path.dirname(__file__), "output"))


@mcp.tool()
def generate_background(
    prompt: str,
    sketch_path: str | None = None,
    character_path: str | None = None,
    model: str = workflow.DEFAULT_MODEL,
    width: int = 768,
    height: int = 512,
    seed: int | None = None,
    controlnet_strength: float = 1.0,
    extra_negative: str | None = None,
    location: str | None = None,
    location_denoise: float = 0.65,
    project: str = world.DEFAULT_PROJECT,
) -> str:
    """Generate a manhwa/anime-style background plate for a comic panel.

    The aesthetic comes from the model itself (no IP-Adapter / style ref). Drive
    palette and content through the prompt; drive composition with an optional
    sketch.

    Projects: `project` namespaces the World Builder canon and the output folder so
    you can work on several comics from one server without their locations colliding
    (e.g. "starry_knight" vs "rxr"). References (sketch library) are shared, not
    namespaced. Defaults to WEBCOMIC_BG_PROJECT or "default".

    World Builder: pass `location` (an id registered via register_location in the
    SAME project) to generate a NEW panel of an ALREADY-established place. The
    location's canonical image seeds the render (img2img) so it stays recognisably
    the same scene from a new angle / time of day. Omit `location` for a brand-new
    place (then register the keeper afterwards).

    `location_denoise` tuning (validated against test panels):
      • 0.40–0.48 — subtle variation / relight; hugs the canon tightly
      • 0.52–0.58 — new lighting or time of day, structure well preserved
      • 0.65 (default) — new angle with richer variation; still on-location
      • ≥0.70 — drifts off the location AND the checkpoint's character bias
        returns (a stray figure appears); not recommended
    Figure suppression is automatically reinforced whenever a location is used.

    Args:
        prompt: Description of the scene (e.g. "hive city corridor at night, deep
            blue moonlight"). Avoid describing characters — this makes empty
            backgrounds to draw over. Put palette/mood in the prompt.
        sketch_path: Optional rough perspective sketch (white lines on black) —
            ControlNet forces the output to match this composition/angle. Use an
            edge map of a reference (e.g. a Warhammer 40K hive photo via
            tools/make_sketch.py) to force a 40K structure instead of a generic one.
        character_path: Optional drawn character PNG (transparent bg ideal; plain
            white works). The tool builds a BACKGROUND PLATE around it (using it
            only as a scale/perspective guide) with the character ABSENT, sized to
            the character canvas, to import as its own layer.
        model: Which checkpoint to render with — "solstice" (Korean manhwa,
            atmospheric; default), "counterfeit" (clean anime — pairs well with the
            manhwa LoRA), or "dreamshaper" (soft painterly). A LoRA, if set via
            WEBCOMIC_BG_LORA, applies on top of whichever model.
        width / height: Output size in px (ignored when character_path is given —
            then it matches the character canvas).
        seed: Fixed seed for reproducibility; omit for a random one.
        controlnet_strength: How strictly to follow the sketch, 0.0–1.0.
        extra_negative: Extra terms appended to the default negative prompt.
        project: Which comic's canon/output to use (e.g. "starry_knight", "rxr").

    Returns:
        The filesystem path to the generated PNG.
    """
    negative = workflow.DEFAULT_NEGATIVE
    if extra_negative:
        negative = f"{negative}, {extra_negative}"

    location_ref_path = None
    if location:
        loc = world.get_location(location, project=project)
        if loc is None:
            known = ", ".join(world.list_locations(project)) or "(none registered yet)"
            return (f"Unknown location '{location}' in project '{project}'. "
                    f"Registered: {known}. "
                    f"Generate it as a new place, then register the keeper.")
        location_ref_path = loc["canonical_path"]

    out_dir = os.path.join(OUTPUT_DIR, world._slug(project))
    try:
        out_path = workflow.generate(
            prompt=prompt,
            out_dir=out_dir,
            negative=negative,
            width=width,
            height=height,
            seed=seed,
            sketch_path=sketch_path,
            character_path=character_path,
            model=model,
            controlnet_strength=controlnet_strength,
            location_ref_path=location_ref_path,
            location_denoise=location_denoise,
        )
        return f"Background generated: {out_path}"
    except workflow.ComfyUIError as e:
        return (f"Generation failed: {e}\n"
                f"Is ComfyUI running at {workflow.COMFY_URL}?")


@mcp.tool()
def register_location(
    image_path: str,
    location_id: str | None = None,
    name: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
    panel: str = "",
    project: str = world.DEFAULT_PROJECT,
) -> str:
    """Add an approved background to the World Builder bible as canonical for a place.

    Once registered, future panels of this place can be generated consistently by
    passing its id as `location` to generate_background. Use this on the version you
    finally picked (after discarding the ones you didn't like).

    Args:
        image_path: The finished background PNG to canonise (copied into
            world/<project>/).
        location_id: Short id to reference later (e.g. "iron_cross_slum"). Auto-
            slugged from name/filename if omitted.
        name: Human name (e.g. "Iron Cross slum, Mikhail's first posting").
        description: What defines this place — landmarks, palette, mood. Free text;
            this is your authorial canon, so be specific.
        tags: Optional labels, e.g. ["exterior", "slum", "hive"].
        panel: Where it first appears, e.g. "ch1_p27" (free-form, for your records).
        project: Which comic this location belongs to (e.g. "starry_knight", "rxr").
            Ids only need to be unique within a project. Defaults to "default".

    Returns:
        A summary of the registered entry (id, canonical path, auto-extracted palette).
    """
    try:
        entry = world.register_location(
            image_path=image_path, location_id=location_id, name=name,
            description=description, tags=tags, panel=panel, project=project,
        )
        return (f"Registered '{entry['id']}' in project '{entry['project']}' — {entry['name']}\n"
                f"  canonical: {entry['canonical']}\n"
                f"  palette:   {', '.join(entry['palette']) or '(none)'}\n"
                f"Generate consistent panels of it with location='{entry['id']}', "
                f"project='{entry['project']}'.")
    except world.WorldError as e:
        return f"Could not register location: {e}"


@mcp.tool()
def list_world(project: str = world.DEFAULT_PROJECT) -> str:
    """List the established locations in a project's World Builder bible."""
    locs = world.list_locations(project)
    if not locs:
        return (f"The world bible for project '{project}' is empty. "
                f"Register an approved background with register_location.")
    lines = []
    for lid, e in locs.items():
        tags = f" [{', '.join(e.get('tags', []))}]" if e.get("tags") else ""
        desc = f" — {e['description']}" if e.get("description") else ""
        lines.append(f"• {lid}: {e['name']}{tags}{desc}")
    return f"Established locations in '{project}':\n" + "\n".join(lines)


@mcp.tool()
def list_projects() -> str:
    """List the comic projects that have a World Builder bible."""
    projs = world.list_projects()
    if not projs:
        return "No projects yet. Register a background with register_location (set `project`)."
    return "Projects with established canon:\n" + "\n".join(f"• {p}" for p in projs)


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
