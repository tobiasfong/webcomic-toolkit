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
import citygen

mcp = FastMCP("webcomic-background-generator")

# Where finished backgrounds are written
OUTPUT_DIR = os.environ.get("WEBCOMIC_BG_OUTPUT", os.path.join(os.path.dirname(__file__), "output"))

# --- The validated "manhwa background" recipe (tuned 2026-06-30) -------------
# Used by generate_city_scene; fixes the flat comic-book/cel look that hard
# synthetic edges otherwise produce. See CHANGELOG v1.3.0.
RECIPE_LORA = "ManhwaUltimate.safetensors"        # trigger word: fantasy-style
RECIPE_PROMPT_SUFFIX = ("painterly soft lighting, atmospheric perspective, "
                        "korean webtoon background art, no outlines, soft gradients, "
                        "cinematic, masterpiece")
RECIPE_NEGATIVE = ("comic book, thick outlines, heavy linework, flat colors, "
                   "western cartoon, cel border")
RECIPE_CONTROLNET = 0.6                            # 0.85+ causes the cel-outline look


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
    lora: str | None = None,
    lora_strength: float | None = None,
    hires: bool = False,
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
        lora: Style LoRA filename in models/loras (e.g. "ManhwaUltimate.safetensors",
            trigger word "fantasy-style"). Omit for the server default
            (WEBCOMIC_BG_LORA env); pass "" to force the LoRA off.
        lora_strength: LoRA strength (default 0.8 / WEBCOMIC_BG_LORA_STRENGTH).
        hires: After the base render, upscale 1.5x and re-detail with a light
            img2img pass — recommended for dense architectural panels that come
            out soft at native SD resolution.

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
            lora=lora,
            lora_strength=lora_strength,
            hires=hires,
        )
        return f"Background generated: {out_path}"
    except workflow.ComfyUIError as e:
        return (f"Generation failed: {e}\n"
                f"Is ComfyUI running at {workflow.COMFY_URL}?")


@mcp.tool()
def generate_city_scene(
    prompt: str,
    camera: str = "vista",
    city_seed: int = 40001,
    model: str = workflow.DEFAULT_MODEL,
    width: int = 896,
    height: int = 488,
    seed: int | None = None,
    hires: bool = True,
    lora: str | None = RECIPE_LORA,
    controlnet_strength: float = RECIPE_CONTROLNET,
    extra_negative: str | None = None,
    project: str = world.DEFAULT_PROJECT,
    use_plan: bool = False,
    focus: str | None = None,
    anchor_x: float | None = None,
    anchor_z: float | None = None,
) -> str:
    """Generate a giant city establishing panel from a procedural 3D city
    ("Metropolis mode").

    Builds a 3D gothic city, renders it headless to a composition sketch, and
    paints it with the validated manhwa recipe (webtoon prompt language, manhwa
    LoRA, soft ControlNet, hi-res finishing pass). Two sources of geometry:

    • One-shot (`use_plan=False`, default): a self-contained city from
      `city_seed`. Same seed = same city, forever.
    • Persistent (`use_plan=True`): the project's GROWABLE city — the plan in
      world/<project>/city_plan.json built with add_city_district. Start with a
      neighborhood, keep appending districts as the story expands; every earlier
      district re-renders identically. Aim the camera with `focus` (a district
      id). This is the World Builder's structural canon: the 2D locations you
      register are snapshots of it.

    Best for wide vista/establishing shots — street-level close-ups tend to
    regress to a hard cel look (use a photo-reference sketch for those).

    Args:
        prompt: Scene mood + palette (e.g. "grimdark hive city at dusk, toxic
            amber smog, furnace-orange windows"). Derive color language from
            your reference images for the strongest palettes. The webtoon
            recipe wording is appended automatically.
        camera: "vista" (elevated 3/4, default), "high" (aerial establishing),
            "canyon" (looking up between buildings), or "street" (see caveat).
        city_seed: One-shot mode only: which city. Record it when you register
            the result as a World Builder location.
        model / width / height / seed: As generate_background.
        hires: Finish with the 1.5x upscale + re-detail pass (default True —
            these dense panels need it).
        lora: Defaults to the manhwa LoRA; pass "" to disable.
        controlnet_strength: Default 0.6 (higher causes a comic-book look).
        extra_negative: Extra negative terms.
        project: Which comic's plan/output to use.
        use_plan: Render the project's persistent city plan instead of a
            one-shot seeded city.
        focus: Plan mode: district id to aim the camera at (default: whole-city
            centroid).
        anchor_x / anchor_z: Optional character placement anchor — the world
            position where a character will stand. Also writes an occlusion-aware
            mask (white = where the character goes) and reports the on-screen
            pixel height and feet line, so the artist draws the character at
            exactly the right scale and perspective. The mask matches the hires
            output resolution. A human is ~4.6 world units tall; streets are
            ~26 units wide.

    Returns:
        The filesystem path to the generated PNG (plus the sketch path, for reuse).
    """
    out_dir = os.path.join(OUTPUT_DIR, world._slug(project))
    try:
        tag, cam, plan_note = None, camera, ""
        if use_plan:
            plan = world.load_city_plan(project)
            if plan is None:
                return (f"Project '{project}' has no city plan yet. Create one by "
                        f"adding a first district with add_city_district.")
            meshes = citygen.build_from_plan(plan)
            cam = citygen.camera_for(camera, citygen.plan_centroid(plan, focus))
            tag = f"plan_{world._slug(project)}"
            plan_note = (f"  persistent plan: {len(plan['districts'])} district(s)"
                         f"{', focus: ' + focus if focus else ''}\n")
        else:
            meshes = citygen.build_city(city_seed)
        # 3D city -> composition sketch, rendered at 1.5x the gen size
        sw, sh = int(width * 1.5), int(height * 1.5)
        sketch_path, _ = citygen.city_sketch(
            os.path.join(out_dir, "city_sketches"),
            city_seed=city_seed, camera=cam,
            width=sw, height=sh, meshes=meshes, tag=tag,
        )
        anchor_note = ""
        if anchor_x is not None and anchor_z is not None:
            import cv2
            mask, info = citygen.render_anchor(meshes, cam, anchor_x, anchor_z,
                                               width=sw, height=sh)
            mask_path = sketch_path.replace("_sketch.png", "_anchor.png")
            cv2.imwrite(mask_path, mask)
            if info is None:
                anchor_note = "  anchor: behind the camera — pick another spot\n"
            else:
                vis = "visible" if info["visible"] else "OCCLUDED by buildings"
                anchor_note = (f"  anchor mask: {mask_path}\n"
                               f"  character at ({anchor_x}, {anchor_z}): {vis}, "
                               f"~{info['height_px']:.0f}px tall, feet at "
                               f"y={info['feet_y_px']:.0f}px (at hires scale)\n")
    except (ValueError, world.WorldError) as e:
        return f"City render failed: {e}"

    full_prompt = f"fantasy-style, {prompt}, {RECIPE_PROMPT_SUFFIX}"
    negative = f"{workflow.DEFAULT_NEGATIVE}, {RECIPE_NEGATIVE}"
    if extra_negative:
        negative = f"{negative}, {extra_negative}"

    try:
        out_path = workflow.generate(
            prompt=full_prompt,
            out_dir=out_dir,
            negative=negative,
            width=width,
            height=height,
            seed=seed,
            sketch_path=sketch_path,
            model=model,
            controlnet_strength=controlnet_strength,
            lora=lora,
            hires=hires,
        )
        src = "plan" if use_plan else f"city_seed {city_seed}"
        return (f"City panel generated: {out_path}\n"
                f"  source: {src}  camera: {camera}\n"
                + plan_note + anchor_note +
                f"  sketch (reusable): {sketch_path}\n"
                f"Re-render the SAME city from another angle by keeping the source "
                f"({'the plan' if use_plan else 'city_seed'}) and changing camera/focus.")
    except workflow.ComfyUIError as e:
        return (f"Generation failed: {e}\n"
                f"Is ComfyUI running at {workflow.COMFY_URL}?")


@mcp.tool()
def add_city_district(
    district_id: str,
    x: float = 0,
    z: float = 0,
    type: str = "block",
    seed: int | None = None,
    size_w: float = 220,
    size_d: float = 220,
    tier: int = 0,
    density: float = 1.0,
    landmark: bool = False,
    rows: int = 26,
    project: str = world.DEFAULT_PROJECT,
) -> str:
    """Grow the project's persistent 3D city by one district.

    The city plan (world/<project>/city_plan.json) is the World Builder's
    growable 3D model: start with one neighborhood, keep appending districts as
    the story expands — a neighborhood, then a district, eventually a full city.
    Every earlier district re-renders identically (each has its own seed), so
    established panels stay canon. Render it with
    generate_city_scene(use_plan=True, focus="<district_id>").

    Args:
        district_id: Name to reference later (e.g. "old_town", "docks").
        x / z: Where the district sits on the city map (world units; a typical
            district is ~200-600 across; -z is "away from the default cameras").
        type: "old_city" (flanked avenue converging on a cathedral + skyline —
            good founding district) or "block" (rectangular fill of buildings —
            the growable unit).
        seed: District's own RNG seed (auto-assigned if omitted; an existing
            district KEEPS its seed on update so it never re-rolls).
        size_w / size_d: Block type: footprint in world units.
        tier: Block type: 0 low-rise ... 2 tall massing.
        density: Block type: building density (0.3 sparse ... 1.5 packed).
        landmark: Drop a cathedral in this district.
        rows: old_city type: avenue length in building rows.
        project: Which comic's city.

    Returns:
        The updated plan summary.
    """
    try:
        params = ({"rows": rows, "landmark": landmark} if type == "old_city"
                  else {"size": [size_w, size_d], "tier": tier,
                        "density": density, "landmark": landmark})
        plan = world.add_city_district(district_id, x, z, type=type, seed=seed,
                                       project=project, **params)
    except world.WorldError as e:
        return f"Could not add district: {e}"
    lines = [f"• {d['id']}: {d.get('type','block')} at {tuple(d.get('origin',(0,0)))}"
             f"{' [landmark]' if d.get('landmark') else ''}" for d in plan["districts"]]
    return (f"City plan for '{project}' now has {len(plan['districts'])} district(s):\n"
            + "\n".join(lines) +
            f"\nRender it: generate_city_scene(use_plan=True, focus='{world._slug(district_id)}', ...)")


@mcp.tool()
def list_city(project: str = world.DEFAULT_PROJECT) -> str:
    """Show the project's persistent 3D city plan (districts, positions, seeds)."""
    plan = world.load_city_plan(project)
    if plan is None:
        return (f"Project '{project}' has no city plan yet. "
                f"Found a city with add_city_district (type='old_city' makes a good core).")
    lines = [f"• {d['id']}: {d.get('type','block')} at {tuple(d.get('origin',(0,0)))}, "
             f"seed {d.get('seed')}"
             f"{' [landmark]' if d.get('landmark') else ''}" for d in plan["districts"]]
    return f"City plan '{plan.get('name', project)}' — {len(lines)} district(s):\n" + "\n".join(lines)


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
