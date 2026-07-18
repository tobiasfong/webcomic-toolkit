"""
Character & Panel Generator — MCP Server
=========================================
A local Model Context Protocol server for writers who aren't artists: register a
character's existing reference art (commissioned or AI-generated concept sheets),
then generate consistent poses and composite them onto background plates into
finished comic panels — all against a local ComfyUI + Stable Diffusion pipeline.

The character-domain sibling of webcomic-background-mcp's World Builder: same
philosophy (reference-driven, never generate-from-text-and-pray), same skeleton,
no code dependency between the two servers.

Ships Tier 1 of a three-tier consistency design (see README.md): img2img from a
character's reference image. Tier 2 (IP-Adapter + OpenPose) and Tier 3 (per-
character LoRA baking) are designed but not yet built — see the README's
"Consistency tiers" section for the honest state.

Exposes: register_character, list_characters, forget_character, list_projects,
generate_character_pose, compose_panel, check_status.

Requires a running ComfyUI instance (default http://127.0.0.1:8188) for
generate_character_pose only — the bible and compositing tools are GPU-free.
Runs locally over stdio.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp.server.fastmcp import FastMCP
import characters
import workflow
from tools.compose_panel import compose_panel as _compose_panel

mcp = FastMCP("character-panel-generator")

OUTPUT_DIR = os.environ.get("WEBCOMIC_CHAR_OUTPUT", os.path.join(os.path.dirname(__file__), "output"))


@mcp.tool()
def register_character(
    image_paths: list[str],
    character_id: str | None = None,
    name: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
    notes: str = "",
    project: str = characters.DEFAULT_PROJECT,
) -> str:
    """Add (or grow) a character's reference set in the Character Bible.

    Copies each image into the bible and records/updates the character's metadata.
    References are input-format agnostic — a ChatGPT/Midjourney character sheet is
    as valid as commissioned art; this tool never judges provenance. Calling this
    again on an existing character_id APPENDS the new images to the reference set
    rather than replacing it (turnarounds and expression sheets accumulate over
    time), and only overwrites name/description/tags/notes if you pass them.

    Args:
        image_paths: One or more reference images to add (concept art, turnarounds,
            expression sheets — whatever exists for this character).
        character_id: Short id to reference later (e.g. "aria"). Auto-slugged from
            name/first filename if omitted.
        name: Human name (e.g. "Aria Solstice").
        description: What defines this character's look — age, build, signature
            costume elements. Free text; be specific, this is authorial canon.
        tags: Optional labels, e.g. ["protagonist", "mage"].
        notes: Anything that helps keep the character on-model (e.g. "always
            barefoot indoors", "never smiles fully").
        project: Which comic this character belongs to. Defaults to "default".

    Returns:
        A summary of the registered entry (id, reference count, auto-extracted palette).
    """
    try:
        entry = characters.register_character(
            image_paths=image_paths, character_id=character_id, name=name,
            description=description, tags=tags, notes=notes, project=project,
        )
        return (f"Registered '{entry['id']}' in project '{entry['project']}' — {entry['name']}\n"
                f"  references: {len(entry['refs'])}\n"
                f"  palette:    {', '.join(entry['palette']) or '(none)'}\n"
                f"Generate poses of them with generate_character_pose(character='{entry['id']}', "
                f"project='{entry['project']}', pose=...).")
    except characters.CharacterError as e:
        return f"Could not register character: {e}"


@mcp.tool()
def list_characters(project: str = characters.DEFAULT_PROJECT) -> str:
    """List the characters registered in a project's Character Bible."""
    chars = characters.list_characters(project)
    if not chars:
        return (f"The character bible for project '{project}' is empty. "
                f"Register one with register_character.")
    lines = []
    for cid, e in chars.items():
        tags = f" [{', '.join(e.get('tags', []))}]" if e.get("tags") else ""
        desc = f" — {e['description']}" if e.get("description") else ""
        lines.append(f"• {cid}: {e['name']}{tags}{desc} ({len(e.get('refs', []))} ref image(s))")
    return f"Characters in '{project}':\n" + "\n".join(lines)


@mcp.tool()
def forget_character(
    character_id: str,
    delete_images: bool = False,
    project: str = characters.DEFAULT_PROJECT,
) -> str:
    """Remove a character from a project's Character Bible.

    By default only the manifest entry is removed; pass delete_images=True to also
    delete their reference images from disk."""
    existed = characters.forget_character(character_id, delete_images=delete_images, project=project)
    if not existed:
        return f"No character '{character_id}' in project '{project}'."
    return f"Removed '{character_id}' from project '{project}'" + (" (images deleted)." if delete_images else " (images kept on disk).")


@mcp.tool()
def list_projects() -> str:
    """List the comic projects that have a Character Bible."""
    projs = characters.list_projects()
    if not projs:
        return "No projects yet. Register a character with register_character (set `project`)."
    return "Projects with a character bible:\n" + "\n".join(f"• {p}" for p in projs)


@mcp.tool()
def generate_character_pose(
    character: str,
    pose: str,
    prompt: str = "",
    negative: str | None = None,
    project: str = characters.DEFAULT_PROJECT,
    model: str = workflow.DEFAULT_MODEL,
    width: int = 640,
    height: int = 896,
    seed: int | None = None,
    ref_denoise: float = 0.55,
    lora: str | None = None,
    lora_strength: float | None = None,
    matte: bool = True,
) -> str:
    """Render a registered character alone, in a new pose, on a clean backdrop.

    Tier 1 of this server's consistency design (see README.md): img2img seeded
    from the character's primary reference image, so the render stays recognizably
    them — "same character, slightly different angle" territory. Drifts on
    ambitious poses; curate the result before compositing. Output is auto-matted
    to an RGBA cutout by default, ready for compose_panel.

    Args:
        character: A character_id already in the bible (register_character first).
        pose: The pose/action to render (e.g. "arms crossed, looking over shoulder").
        prompt: Extra scene-agnostic detail (lighting, angle). The character's own
            name/description from the bible is prepended automatically.
        negative: Extra negative terms (appended to sane defaults).
        project: Which comic's bible/output to use.
        model / width / height / seed: As webcomic-background-mcp's generate_background.
        ref_denoise: How much of the reference survives (0-1). Lower = closer to
            the reference (safer, less pose range); higher = more prompt-driven
            (more pose range, more drift risk). Default 0.55.
        lora / lora_strength: Optional style LoRA — same pool as the background
            server's (e.g. the Niji V5 Style LoRA), so character and background
            style can match.
        matte: Auto-remove the clean backdrop to RGBA (default True). Set False to
            keep the raw render with its backdrop, e.g. to eyeball the pose first.

    Returns:
        The filesystem path to the matted (or raw) pose PNG.
    """
    try:
        ref_path = characters.primary_ref_path(character, project)
    except characters.CharacterError as e:
        return f"Could not generate pose: {e}"

    entry = characters.get_character(character, project)
    full_prompt = f"{entry['name']}, {pose}"
    if prompt:
        full_prompt = f"{full_prompt}, {prompt}"
    if entry.get("description"):
        full_prompt = f"{full_prompt}, {entry['description']}"

    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character), "poses")
    try:
        raw_path = workflow.generate(
            prompt=full_prompt,
            out_dir=out_dir,
            negative=negative if negative is not None else workflow.DEFAULT_NEGATIVE,
            width=width,
            height=height,
            seed=seed,
            ref_path=ref_path,
            ref_denoise=ref_denoise,
            model=model,
            lora=lora,
            lora_strength=lora_strength,
        )
    except workflow.ComfyUIError as e:
        return f"Generation failed: {e}\nIs ComfyUI running at {workflow.COMFY_URL}?"

    if not matte:
        return (f"Pose generated (not matted): {raw_path}\n"
                f"Tier 1 (img2img from reference, ref_denoise={ref_denoise}) — "
                f"drifts on ambitious poses; curate before use.")
    try:
        matted_path = workflow.matte(raw_path)
    except workflow.ComfyUIError as e:
        return f"Pose generated but matting failed: {e}\n  raw render: {raw_path}"
    return (f"Pose generated: {matted_path}\n"
            f"  raw render (with backdrop): {raw_path}\n"
            f"Tier 1 (img2img from reference, ref_denoise={ref_denoise}) — drifts on "
            f"ambitious poses; curate before compose_panel. Feed this to compose_panel "
            f"as character_layer_path.")


@mcp.tool()
def compose_panel(
    character_layer_path: str,
    feet_x: float,
    feet_y: float,
    height_px: float,
    background: str | None = None,
    base: str | None = None,
    out: str | None = None,
) -> str:
    """Composite a matted character cutout onto a background plate — deterministic,
    GPU-free, instant to iterate.

    Positioning is feet-anchored: the character is scaled to `height_px` tall and
    placed so its feet land at (feet_x, feet_y). This is exactly the shape
    webcomic-background-mcp's generate_city_scene(anchor_x=..., anchor_z=...)
    reports back (height_px / feet_y_px) — pass that output straight through.

    For multiple characters in one panel, call this once per character: start with
    `background` for the first, then pass the previous call's output back in as
    `base` for each additional character. "Redo panel 7 with a sadder expression"
    is re-rendering one layer and re-compositing, not regenerating the whole panel.

    Args:
        character_layer_path: A matted (RGBA) character pose, e.g. from
            generate_character_pose.
        feet_x / feet_y: Pixel position for the character's feet on the panel.
        height_px: The character's on-screen height in pixels.
        background: Start a new panel from this plate. Mutually exclusive with `base`.
        base: Add a layer to this existing panel (chaining). Mutually exclusive
            with `background`.
        out: Output path. Auto-derived (collision-safe) if omitted.

    Returns:
        The filesystem path to the composited panel.
    """
    try:
        out_path = _compose_panel(character_layer_path, feet_x, feet_y, height_px,
                                  background=background, base=base, out=out)
    except SystemExit as e:
        return f"Could not compose panel: {e}"
    return (f"Panel composited: {out_path}\n"
            f"Add another character with compose_panel(base='{out_path}', ...).")


@mcp.tool()
def check_status() -> str:
    """Check whether the ComfyUI backend is reachable and ready (only needed for
    generate_character_pose — the bible and compose_panel work without it)."""
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
