"""
Webcomic Background Generator — MCP Server
==========================================
A local Model Context Protocol server that generates manhwa-style background
plates for comic panels, wrapping FLUX 3 Image Klein on a local ComfyUI.

KLEIN ONLY as of v3.0.0. FLUX.1-dev, and with it the manhwa LoRA, ControlNet
and Kontext, was removed as SD1.5 was in v2.0.0 and for the same reason: the
sibling character-panel server renders figures with Klein, and a plate from a
different model under them reads as a composite. klein.py records what
replaced each FLUX.1 part and the measurements behind it.

Requires the Klein ComfyUI (v0.41+, default http://127.0.0.1:8189), which the
server starts on first use. Runs locally over stdio; the GPU work happens on
this machine.
"""

import os
import sys
# Make imports work regardless of the working directory Claude Desktop launches us from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp.server.fastmcp import FastMCP
import klein
import world
import citygen
import props

mcp = FastMCP("webcomic-background-generator")

# Where finished backgrounds are written
OUTPUT_DIR = os.environ.get("WEBCOMIC_BG_OUTPUT", os.path.join(os.path.dirname(__file__), "output"))


def _fail(e: Exception) -> str:
    return (f"Generation failed: {e}\n"
            f"Is the Klein ComfyUI installed at {klein.KLEIN_DIR} (port {klein.KLEIN_PORT})? "
            f"See setup_models.py.")


@mcp.tool()
def generate_background(
    prompt: str,
    sketch_path: str | None = None,
    match_canvas_to: str | None = None,
    width: int | None = None,
    height: int | None = None,
    seed: int | None = None,
    location: str | None = None,
    project: str = world.DEFAULT_PROJECT,
) -> str:
    """Generate a manhwa-style background plate for a comic panel (FLUX 3 Klein).

    PROMPTING -- rules measured on FLUX.1 and kept for Klein (the far-distance
    one has already recurred on Klein):
      • Name what the place IS, as a list of physical objects. No mood,
        lighting or "cinematic" wording; darken afterwards with grade_plate.
      • No negatives. There is no negative-prompt parameter, on purpose: the
        model draws what a prompt names, including what it is told to avoid.
      • Name whatever fills the far distance (forest, hills, a rampart), or the
        model fills it from photographs -- the modern-skyline failure.
      • Open with the period and place ("Ming dynasty ... in Anhui").
    The house style sentence is appended automatically.

    Projects: `project` namespaces the World Builder canon and the output folder,
    so several comics share one server without their locations colliding.

    World Builder: pass `location` (an id registered via register_location in
    the SAME project) to draw an ALREADY-established place. Its canonical plate
    is given to the model as a reference, so it stays recognizably the same
    place. Unlike the old img2img path this is not tied to the canon's framing:
    ask for a new angle, another part of the room, or another time of day in
    the prompt and it follows. Omit `location` for a brand-new place, then
    register the keeper.

    Args:
        prompt: The scene as physical objects (see rules above). Do not describe
            characters -- these are empty plates to composite figures onto.
        sketch_path: Optional composition sketch, white lines on black (a 3D
            render from citygen/props, or tools/make_sketch.py on a photo or
            drawing). It fixes the camera and where every object sits; the
            model draws the scene inside it.
        match_canvas_to: Path to a drawn character PNG. Sizes the plate to that
            image's canvas so the two line up 1:1 when composited, and reports
            the numbers to hand to compose_panel. The character does not
            condition the render; it only sets the size.
        width / height: Output size in px, rounded to a multiple of 16. Default
            1024x768; with `location`, the location image's own size. Wide
            interiors read bigger on a wide canvas (1152x704) -- aspect ratio
            conveys scale better than adjectives.
        seed: Fixed seed for reproducibility; omit for a random one.
        location: Registered location id to keep consistent with.
        project: Which comic's canon/output to use.

    Returns:
        The filesystem path to the generated PNG.
    """
    canvas_note = ""
    if match_canvas_to:
        if not os.path.exists(match_canvas_to):
            return f"match_canvas_to image not found: {match_canvas_to}"
        from PIL import Image
        with Image.open(match_canvas_to) as im:
            cw, ch = im.size
        # Capped at 1600 on the long side. VRAM is not what limits this card --
        # ComfyUI streams weights from system RAM -- but very large canvases
        # invite duplicated elements, and 1600x896 is a size plates have
        # rendered at cleanly.
        MAX_SIDE = 1600
        k = min(1.0, MAX_SIDE / max(cw, ch))
        width = max(256, int(cw * k) // 16 * 16)
        height = max(256, int(ch * k) // 16 * 16)
        canvas_note = (f"  canvas matched to {os.path.basename(match_canvas_to)} "
                       f"({cw}x{ch}) -> {width}x{height}\n"
                       f"  to composite: character height_px={height}, "
                       f"feet_x={width // 2}, feet_y={height} "
                       f"(character-panel-mcp's compose_panel)\n")

    refs, lead = [], ""
    if sketch_path:
        if not os.path.exists(sketch_path):
            return f"sketch_path not found: {sketch_path}"
        refs.append(sketch_path)
        lead = klein.SKETCH_LEAD
    if location:
        loc = world.get_location(location, project=project)
        if loc is None:
            known = ", ".join(world.list_locations(project)) or "(none registered yet)"
            return (f"Unknown location '{location}' in project '{project}'. "
                    f"Registered: {known}. "
                    f"Generate it as a new place, then register the keeper.")
        ref = loc["canonical_path"]
        refs.append(ref)
        name = loc.get("name") or location
        if sketch_path:
            # The sketch is image 1, so the location is image 2.
            lead += (f"Image 2 shows {name}, an established place in this story; "
                     f"draw it as that same place, with its architecture, materials "
                     f"and colors. ")
        else:
            lead = klein.location_lead(name)
        if width is None or height is None:
            from PIL import Image
            with Image.open(ref) as im:
                lw, lh = im.size
            width = width or lw
            height = height or lh
    width = width or 1024
    height = height or 768

    out_dir = os.path.join(OUTPUT_DIR, world._slug(project))
    try:
        out_path = klein.generate(lead + prompt, out_dir, width, height,
                                  seed=seed, refs=refs)
    except klein.KleinError as e:
        return _fail(e)
    return f"Background generated: {out_path}\n" + canvas_note


@mcp.tool()
def generate_city_scene(
    prompt: str,
    camera: str = "vista",
    city_seed: int = 40001,
    width: int = 1344,
    height: int = 732,
    seed: int | None = None,
    project: str = world.DEFAULT_PROJECT,
    use_plan: bool = False,
    focus: str | None = None,
    anchor_x: float | None = None,
    anchor_z: float | None = None,
) -> str:
    """Generate a giant city establishing panel from a procedural 3D city
    ("Metropolis mode").

    Builds a 3D gothic city, renders it headless to a composition sketch, and
    has Klein draw the city the sketch lays out -- geometry from math, the look
    from the model. Two sources of geometry:

    • One-shot (`use_plan=False`, default): a self-contained city from
      `city_seed`. Same seed = same city, forever.
    • Persistent (`use_plan=True`): the project's GROWABLE city -- the plan in
      world/<project>/city_plan.json built with add_city_district. Every
      earlier district re-renders identically; aim the camera with `focus`.

    Args:
        prompt: The city as physical objects -- towers, buttresses, rooftops --
            AND what stands around it: say where the ground is and what the sky
            is. The sketch's black areas are filled from the prompt; a prompt
            naming only buildings gave a city floating in a gray void.
        camera: "vista" (elevated 3/4, default), "high" (aerial establishing),
            "canyon" (looking up between buildings), or "street".
        city_seed: One-shot mode only: which city. Record it when you register
            the result as a World Builder location.
        width / height / seed: Output size and seed. The sketch is rendered at
            exactly this size, so an anchor mask lines up with the plate.
        project: Which comic's plan/output to use.
        use_plan: Render the project's persistent city plan instead of a
            one-shot seeded city.
        focus: Plan mode: district id to aim the camera at (default: whole-city
            centroid).
        anchor_x / anchor_z: Optional character placement anchor -- the world
            position where a character will stand. Writes an occlusion-aware
            mask (white = where the character goes) and reports the on-screen
            pixel height and feet line. A human is ~4.6 world units tall;
            streets are ~26 units wide.

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
        sketch_path, _ = citygen.city_sketch(
            os.path.join(out_dir, "city_sketches"),
            city_seed=city_seed, camera=cam,
            width=width, height=height, meshes=meshes, tag=tag,
        )
        anchor_note = ""
        if anchor_x is not None and anchor_z is not None:
            import cv2
            mask, info = citygen.render_anchor(meshes, cam, anchor_x, anchor_z,
                                               width=width, height=height)
            mask_path = sketch_path.replace("_sketch.png", "_anchor.png")
            cv2.imwrite(mask_path, mask)
            if info is None:
                anchor_note = "  anchor: behind the camera — pick another spot\n"
            else:
                vis = "visible" if info["visible"] else "OCCLUDED by buildings"
                anchor_note = (f"  anchor mask: {mask_path}\n"
                               f"  character at ({anchor_x}, {anchor_z}): {vis}, "
                               f"~{info['height_px']:.0f}px tall, feet at "
                               f"y={info['feet_y_px']:.0f}px\n")
    except (ValueError, world.WorldError) as e:
        return f"City render failed: {e}"

    try:
        out_path = klein.generate(klein.SKETCH_LEAD + prompt, out_dir, width, height,
                                  seed=seed, refs=[sketch_path], stem="city")
    except klein.KleinError as e:
        return _fail(e)
    src = "plan" if use_plan else f"city_seed {city_seed}"
    return (f"City panel generated: {out_path}\n"
            f"  source: {src}  camera: {camera}\n"
            + plan_note + anchor_note +
            f"  sketch (reusable): {sketch_path}\n"
            f"Re-render the SAME city from another angle by keeping the source "
            f"({'the plan' if use_plan else 'city_seed'}) and changing camera/focus.")


@mcp.tool()
def generate_prop_scene(
    prompt: str,
    objects: list[dict] | None = None,
    n_bikes: int = 4,
    setting: str = "shelter",
    camera_angle: float = 30.0,
    camera_elev: float = 10.0,
    width: int = 1344,
    height: int = 1008,
    seed: int | None = None,
    project: str = world.DEFAULT_PROJECT,
) -> str:
    """Generate a panel of repeated 3D OBJECTS (props) in a scene -- the
    citygen treatment extended from buildings to objects.

    Rows of repeated objects (a bike rack, market stalls, carts) fuse, crop or
    mutate when a model invents their structure. This tool builds real 3D prop
    meshes, places them with true occlusion, auto-frames a camera so nothing
    clips, renders a projection-correct sketch, and has Klein draw the scene
    inside it. On the bike-row sketch every bicycle and the bollard landed
    exactly where the sketch put them.

    Args:
        prompt: The setting around the props as physical objects (the ground,
            what stands behind them, the sky) -- the sketch only fixes the props.
        objects: Explicit placement: [{"type": "bicycle", "x": 0, "z": 0,
            "yaw": 0, "scale": 1}, ...]. World scale: 1 unit ≈ 0.37 m (a human
            is 4.6 units; a bike wheel is 0.92). Available types: "bicycle".
            Omit to get a parked row of `n_bikes` instead.
        n_bikes: Convenience when `objects` is omitted: a realistic parked row
            (rack spacing, slight per-bike yaw jitter).
        setting: "shelter" (back wall + posts + roof carport around the props)
            or "none" (props only on open ground).
        camera_angle: Yaw around the props, degrees. Keep ≥ ~25 — props are
            flat cutouts and collapse to a sliver seen edge-on.
        camera_elev: Camera elevation, degrees.
        width / height / seed / project: As generate_city_scene.

    Returns:
        Path to the generated PNG (plus the reusable sketch path).
    """
    out_dir = os.path.join(OUTPUT_DIR, world._slug(project))
    try:
        obs = objects if objects else props.bike_row(n=n_bikes)
        sketch_path, _ = props.prop_sketch(
            os.path.join(out_dir, "prop_sketches"), obs,
            setting=setting, width=width, height=height,
            angle_deg=camera_angle, elev_deg=camera_elev,
            tag=f"props_{len(obs)}",
        )
    except ValueError as e:
        return f"Prop render failed: {e}"

    try:
        out_path = klein.generate(klein.SKETCH_LEAD + prompt, out_dir, width, height,
                                  seed=seed, refs=[sketch_path], stem="props")
    except klein.KleinError as e:
        return _fail(e)
    return (f"Prop scene generated: {out_path}\n"
            f"  objects: {len(obs)}  setting: {setting}  "
            f"camera: {camera_angle}°/{camera_elev}°\n"
            f"  sketch (reusable): {sketch_path}")


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
        project: Which comic this location belongs to (e.g. "comic_a", "comic_b").
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
    """Check whether the Klein ComfyUI is up, and whether its model files are installed."""
    if klein.is_up():
        return f"Klein ComfyUI is up at {klein.KLEIN_URL}."
    if not os.path.isdir(klein.KLEIN_DIR):
        return (f"Klein ComfyUI is not installed at {klein.KLEIN_DIR}. "
                f"See setup_models.py.")
    models = os.path.join(klein.KLEIN_DIR, "ComfyUI", "models")
    want = {"diffusion_models": klein.MODEL, "text_encoders": klein.TEXT_ENCODER, "vae": klein.VAE}
    missing = [f"{d}/{f}" for d, f in want.items() if not os.path.isfile(os.path.join(models, d, f))]
    if missing:
        return (f"Klein ComfyUI is not running, and these model files are missing: "
                f"{', '.join(missing)}. See setup_models.py.")
    return (f"Klein ComfyUI is not running at {klein.KLEIN_URL}, but it is installed "
            f"with all three model files; the first render starts it.")


@mcp.tool()
def grade_plate(
    image_path: str,
    preset: str = "grimdark",
    exposure: float | None = None,
    contrast: float | None = None,
    temp: float | None = None,
    saturation: float | None = None,
    vignette: float | None = None,
    out_path: str | None = None,
) -> str:
    """Color-grade a finished plate for mood, without touching the original.

    Use this INSTEAD of asking for mood in a prompt. Mood words ("grimdark",
    "dim lighting", "deep shadow", "muted palette") dragged FLUX.1 off the
    manhwa aesthetic into semi-realistic murk (measured, v1.9.0), and the
    rule carries over to Klein, which takes color words literally. Generate a clean,
    bright, correctly-styled plate, then darken it here: deterministic, instant,
    CPU-only, and reversible because the master is never modified.

    Args:
        image_path: The plate to grade.
        preset: "grimdark" (Starry Knight hive interiors), "night", "dusk",
            "overcast", "warm_lamp", or "none" (measure without changing).
        exposure / contrast / temp / saturation / vignette: Override individual
            preset values. exposure <1 darkens; contrast >1 expands range; temp
            <0 cools toward blue and >0 warms; saturation <1 mutes; vignette
            0-1 adds corner falloff.
        out_path: Where to write. Defaults to `<name>_<preset>.png` alongside
            the source.

    Returns:
        The graded file's path plus before/after luminance, so you can check
        tone against a number. This server's approved SD1.5 plate sits at
        mean 0.138 / std 0.123.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    import grade as grade_mod
    try:
        before = grade_mod.luminance_stats(image_path)
        out, params = grade_mod.grade_file(
            image_path, out_path, preset, exposure=exposure, contrast=contrast,
            temp=temp, saturation=saturation, vignette=vignette)
        after = grade_mod.luminance_stats(out)
    except SystemExit as e:
        return f"Grade failed: {e}"
    return (f"Graded: {out}\n"
            f"  preset: {preset}  params: {params}\n"
            f"  luminance mean/std: {before[0]:.3f}/{before[1]:.3f} -> "
            f"{after[0]:.3f}/{after[1]:.3f}  (approved SD1.5 plate: 0.138/0.123)\n"
            f"  original untouched: {image_path}")


@mcp.tool()
def extract_palette(image_path: str, n: int = 5) -> str:
    """Read a reference image's dominant colors as PROMPT LANGUAGE.

    References drive color only if their palette gets into the prompt, and
    diffusion models can't consume hex — so this returns both the swatches and
    the words. Point it at anything in `references/` (or any approved plate)
    and paste the color words straight into a generate_* prompt.

    Note the stronger option if you want a reference's *whole* look rather than
    just its colors: pass it as `location`/img2img instead, which inherits its
    style, palette and composition together (v1.9.0's best result).

    Args:
        image_path: Reference image or finished plate.
        n: How many dominant colors to extract.

    Returns:
        Hex swatches, color words, and a ready-to-paste prompt fragment.
    """
    if not os.path.exists(image_path):
        return f"Image not found: {image_path}"
    hexes = world._extract_palette(image_path, n=n)
    if not hexes:
        return f"Could not extract a palette from {image_path} (is PIL installed?)"
    words = world.describe_palette(hexes)
    return (f"Palette of {os.path.basename(image_path)}:\n"
            f"  hex:   {', '.join(hexes)}\n"
            f"  words: {', '.join(words)}\n"
            f"  prompt fragment: \"{', '.join(words)}\"\n"
            f"NOTE: Add color words only — do NOT add mood/lighting wording "
            f"(\"grimdark\", \"deep shadow\"); that pushes the model toward "
            f"semi-realism. Darken with grade_plate afterwards instead.")


@mcp.tool()
def edit_background(
    image_path: str,
    instruction: str,
    project: str = world.DEFAULT_PROJECT,
    seed: int | None = None,
    mask_box: list[int] | None = None,
    restyle: bool = False,
) -> str:
    """Edit an existing plate with a plain-English instruction (FLUX 3 Klein).

    Start from a plate you already approved and change one thing, instead of
    re-rolling. Good for local changes: "remove the person on the bridge", "make
    the sign board a plain dark lacquered panel", "put rust on the ironwork".

    With `mask_box`, ONLY that rectangle changes -- Klein redraws the frame and
    just the box is composited back, so every pixel outside it is untouched.
    Without one, the whole redrawn frame is returned: fine for global changes,
    but nothing in the instruction protects the rest of the plate.

    Phrase removals as what to leave behind ("remove the sign completely, leave
    only bare stone masonry"), and keep large structural changes ("turn the
    causeway into a stair up the slope") for a fresh generation instead.

    Args:
        image_path: The plate to edit.
        instruction: Plain English, describing the change.
        project: Which comic's output folder to write to.
        seed: Fixed seed for reproducibility.
        mask_box: [x0, y0, x1, y1] in the source's pixels -- what to change, and
            how big the new thing should be (a box sets size as well as place).
        restyle: Redraw the plate in the house style -- for pulling an off-style
            plate (photoreal, painterly) back to the inked look.

    Returns:
        Path to the edited copy (the source is never modified).
    """
    out_dir = os.path.join(OUTPUT_DIR, world._slug(project))
    if not os.path.exists(image_path):
        return f"Image not found: {image_path}"
    box = tuple(mask_box) if mask_box else None
    if box and len(box) != 4:
        return "mask_box must be exactly [x0, y0, x1, y1]."
    try:
        out = klein.edit(image_path, instruction, out_dir, box=box, seed=seed, restyle=restyle)
    except klein.KleinError as e:
        return _fail(e)
    return (f"Edited: {out}\n"
            f"  instruction: {instruction}\n"
            f"  {'masked region only, nothing outside it changed' if box else 'WHOLE frame redrawn (no mask_box)'}\n"
            f"  source untouched: {image_path}")


if __name__ == "__main__":
    mcp.run()
