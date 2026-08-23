"""
Webcomic Background Generator — MCP Server
==========================================
A local Model Context Protocol server that generates stylised background
art for comic panels in any aesthetic the user references, wrapping a local
ComfyUI + FLUX.1-dev pipeline (GGUF unet + ControlNet + Kontext editing).

FLUX ONLY as of v2.0.0 — the SD1.5 pipeline was removed. See CHANGELOG for
why: the sibling character-panel server generates figures with FLUX, and
SD1.5 plates under FLUX characters read as a composite.

Requires a running ComfyUI instance (default http://127.0.0.1:8188).
Runs locally over stdio; the GPU work happens on this machine.
"""

import os
import sys
# Make imports work regardless of the working directory Claude Desktop launches us from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp.server.fastmcp import FastMCP
import comfy
import flux_workflow
import world
import citygen
import props

mcp = FastMCP("webcomic-background-generator")

# Where finished backgrounds are written
OUTPUT_DIR = os.environ.get("WEBCOMIC_BG_OUTPUT", os.path.join(os.path.dirname(__file__), "output"))

# FLUX.1-dev is the only pipeline. The SD1.5 "manhwa recipe" (ManhwaUltimate
# LoRA + "fantasy-style" trigger + painterly/cinematic suffix) was removed with
# the SD1.5 path: the LoRA cannot load on FLUX at all, and that suffix's
# mood/lighting wording is exactly what dragged FLUX toward semi-realism.
# FLUX's own terse suffix lives in flux_workflow.FLUX_PROMPT_SUFFIX.
DEFAULT_MODEL = os.environ.get("WEBCOMIC_BG_MODEL", "flux_manwha")


def _recipe(prompt: str, extra_negative: str | None) -> str:
    """Build the negative prompt. FLUX barely honours negatives at cfg=1.0 —
    steer with the POSITIVE prompt instead, and keep mood/lighting words out
    of it entirely (see flux_workflow.py's recipe notes)."""
    negative = flux_workflow.FLUX_NEGATIVE
    if extra_negative:
        negative = f"{negative}, {extra_negative}"
    return negative


@mcp.tool()
def generate_background(
    prompt: str,
    sketch_path: str | None = None,
    match_canvas_to: str | None = None,
    model: str = DEFAULT_MODEL,
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
    (e.g. "comic_a" vs "comic_b"). References (sketch library) are shared, not
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
        match_canvas_to: Path to a drawn character PNG. Sizes the plate to that
            image's canvas so the two line up 1:1 when you composite — the
            practical half of the old `character_path` mode, without the SD1.5
            inpaint. The character is NOT used to condition the render (FLUX has
            no equivalent path); it only sets the output dimensions, and the
            response reports the numbers to hand to `compose_panel`. Long side is
            capped for VRAM; dimensions are rounded to a multiple of 16.
        sketch_path: Optional rough perspective sketch (white lines on black) —
            ControlNet forces the output to match this composition/angle. Use an
            edge map of a reference (e.g. a Warhammer 40K hive photo via
            tools/make_sketch.py) to force a 40K structure instead of a generic one.
        model: Kept for forward compatibility; "flux_manwha" is the only
            pipeline. SD1.5 was removed in v2.0.0.
        width / height: Output size in px.
        seed: Fixed seed for reproducibility; omit for a random one.
        controlnet_strength: How strictly to follow the sketch, 0.0–1.0.
        extra_negative: Extra terms appended to the default negative prompt.
        project: Which comic's canon/output to use (e.g. "comic_a", "comic_b").
        lora: Style LoRA filename in models/loras. Known options: "ManhwaUltimate
            .safetensors" (trigger "fantasy-style" — gothic/western manhwa, the
            default aesthetic) or "NijiV5Style.safetensors" (trigger "midjourney"
            — strong East-Asian architectural bias, pagodas/lanterns; good for
            illustration-style settings, but it will override a gothic/western ControlNet
            sketch's composition, so don't use it for Starry Knight/hive scenes).
            Remember to include the trigger word in your prompt. Omit for the
            server default (WEBCOMIC_BG_LORA env); pass "" to force the LoRA off.
        lora_strength: LoRA strength (default 0.8 / WEBCOMIC_BG_LORA_STRENGTH).
        hires: After the base render, upscale 1.5x and re-detail with a light
            img2img pass — recommended for dense architectural panels that come
            out soft at native SD resolution.

    Returns:
        The filesystem path to the generated PNG.
    """
    negative = _recipe(prompt, extra_negative)

    canvas_note = ""
    if match_canvas_to:
        if not os.path.exists(match_canvas_to):
            return f"match_canvas_to image not found: {match_canvas_to}"
        from PIL import Image
        with Image.open(match_canvas_to) as im:
            cw, ch = im.size
        MAX_SIDE = 1024                      # 6 GB VRAM ceiling for FLUX
        k = min(1.0, MAX_SIDE / max(cw, ch))
        width = max(256, int(cw * k) // 16 * 16)
        height = max(256, int(ch * k) // 16 * 16)
        canvas_note = (f"  canvas matched to {os.path.basename(match_canvas_to)} "
                       f"({cw}x{ch}) -> {width}x{height}\n"
                       f"  to composite: character height_px={height}, "
                       f"feet_x={width // 2}, feet_y={height} "
                       f"(character-panel-mcp's compose_panel)\n")

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
        out_path = flux_workflow.generate(
            prompt=prompt,
            out_dir=out_dir,
            negative=negative,
            width=width,
            height=height,
            seed=seed,
            sketch_path=sketch_path,
            sketch_is_synthetic=False,   # user-supplied sketch may be hand-drawn
            location_ref_path=location_ref_path,
            location_denoise=location_denoise,
            lora=lora,
            lora_strength=lora_strength,
            hires=hires,
        )
        return f"Background generated: {out_path}\n" + canvas_note
    except comfy.ComfyUIError as e:
        return (f"Generation failed: {e}\n"
                f"Is ComfyUI running at {comfy.COMFY_URL}?")


@mcp.tool()
def generate_city_scene(
    prompt: str,
    camera: str = "vista",
    city_seed: int = 40001,
    model: str = DEFAULT_MODEL,
    width: int = 896,
    height: int = 488,
    seed: int | None = None,
    hires: bool = True,
    lora: str | None = None,

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
        lora: FLUX style LoRA; defaults to manwha_style. Pass "" to disable.
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

    negative = _recipe(prompt, extra_negative)

    try:
        out_path = flux_workflow.generate(
            prompt=prompt,
            out_dir=out_dir,
            negative=negative,
            width=width,
            height=height,
            seed=seed,
            sketch_path=sketch_path,
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
    except comfy.ComfyUIError as e:
        return (f"Generation failed: {e}\n"
                f"Is ComfyUI running at {comfy.COMFY_URL}?")


@mcp.tool()
def generate_prop_scene(
    prompt: str,
    objects: list[dict] | None = None,
    n_bikes: int = 4,
    setting: str = "shelter",
    camera_angle: float = 30.0,
    camera_elev: float = 10.0,
    model: str = DEFAULT_MODEL,
    width: int = 896,
    height: int = 672,
    seed: int | None = None,
    hires: bool = True,
    lora: str | None = None,
    controlnet_strength: float = 0.75,
    extra_negative: str | None = None,
    project: str = world.DEFAULT_PROJECT,
) -> str:
    """Generate a panel of repeated 3D OBJECTS (props) in a scene — the
    citygen treatment extended from buildings to objects.

    Diffusion models fuse/crop/mutate rows of repeated objects when asked to
    invent their structure (a bike rack, market stalls, carts). This tool
    builds real 3D prop meshes, places them in the scene with true occlusion,
    auto-frames a camera so nothing clips, renders a projection-correct sketch
    headlessly, and lets the checkpoint paint it — geometry from math, beauty
    from the model.

    Args:
        prompt: Scene mood/setting/palette (webtoon recipe wording appended).
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
        model / width / height / seed / hires / lora / extra_negative /
            project: As generate_city_scene. controlnet_strength default 0.75:
            props need a firmer hold on the sketch than city vistas (0.6), but
            0.85+ still causes the cel-outline look.

    Returns:
        Path to the generated PNG (plus the reusable sketch path).
    """
    out_dir = os.path.join(OUTPUT_DIR, world._slug(project))
    try:
        obs = objects if objects else props.bike_row(n=n_bikes)
        sw, sh = int(width * 1.5), int(height * 1.5)
        sketch_path, _ = props.prop_sketch(
            os.path.join(out_dir, "prop_sketches"), obs,
            setting=setting, width=sw, height=sh,
            angle_deg=camera_angle, elev_deg=camera_elev,
            tag=f"props_{len(obs)}",
        )
    except ValueError as e:
        return f"Prop render failed: {e}"

    negative = _recipe(prompt, extra_negative)

    try:
        out_path = flux_workflow.generate(
            prompt=prompt,
            out_dir=out_dir,
            negative=negative,
            width=width,
            height=height,
            seed=seed,
            sketch_path=sketch_path,
            lora=lora,
            hires=hires,
        )
        return (f"Prop scene generated: {out_path}\n"
                f"  objects: {len(obs)}  setting: {setting}  "
                f"camera: {camera_angle}°/{camera_elev}°\n"
                f"  sketch (reusable): {sketch_path}")
    except comfy.ComfyUIError as e:
        return (f"Generation failed: {e}\n"
                f"Is ComfyUI running at {comfy.COMFY_URL}?")


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
    """Check whether the ComfyUI backend is reachable and ready."""
    import requests
    try:
        r = requests.get(f"{comfy.COMFY_URL}/system_stats", timeout=10)
        if r.status_code == 200:
            return f"ComfyUI is up at {comfy.COMFY_URL}."
        return f"ComfyUI responded with HTTP {r.status_code}."
    except Exception as e:
        return f"ComfyUI not reachable at {comfy.COMFY_URL}: {e}"


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
    """Colour-grade a finished plate for mood, without touching the original.

    Use this INSTEAD of asking for mood in a prompt. Mood words ("grimdark",
    "dim lighting", "deep shadow", "muted palette") drag FLUX off the manhwa
    aesthetic into semi-realistic murk — measured, v1.9.0. Generate a clean,
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
    """Read a reference image's dominant colours as PROMPT LANGUAGE.

    References drive colour only if their palette gets into the prompt, and
    diffusion models can't consume hex — so this returns both the swatches and
    the words. Point it at anything in `references/` (or any approved plate)
    and paste the colour words straight into a generate_* prompt.

    Note the stronger option if you want a reference's *whole* look rather than
    just its colours: pass it as `location`/img2img instead, which inherits its
    style, palette and composition together (v1.9.0's best result).

    Args:
        image_path: Reference image or finished plate.
        n: How many dominant colours to extract.

    Returns:
        Hex swatches, colour words, and a ready-to-paste prompt fragment.
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
            f"NOTE: Add colour words only — do NOT add mood/lighting wording "
            f"(\"grimdark\", \"deep shadow\"); that pushes FLUX toward "
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
    """Edit an existing plate with a plain-English instruction (FLUX Kontext).

    Start from a plate you already approved and change one thing, instead of
    re-rolling a fresh generation and hoping the seed cooperates. Good for
    local changes: "add a hanging lantern on the left pillar", "make the stone
    wetter", "put rust on the ironwork".

    WARNING - two real limits, both learned the hard way on the sibling server:
      • Large structural change does NOT work as one edit. "Turn it around"
        plus "keep everything else the same" are contradictory and produce a
        chimera. Re-generate for big changes.
      • Without `mask_box` this re-renders the WHOLE canvas — no wording in the
        instruction protects anything. If part of the plate must survive
        untouched, fence it off with a mask instead of asking in the prompt.

    Args:
        image_path: The plate to edit.
        instruction: Plain English, describing the change.
        project: Which comic's output folder to write to.
        seed: Fixed seed for reproducibility.
        mask_box: [x0, y0, x1, y1] in the source's pixels — only this rectangle
            is edited. Strongly recommended when composition must be preserved.
        restyle: Load the manhwa style LoRA for a restyle pass rather than a
            structural edit.

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
        out = flux_workflow.edit_image(
            image_path=image_path, instruction=instruction, out_dir=out_dir,
            seed=seed, mask_box=box,
            lora=flux_workflow.FLUX_LORA if restyle else None,
        )
    except comfy.ComfyUIError as e:
        return (f"Edit failed: {e}\nIs ComfyUI running at {comfy.COMFY_URL}?")
    return (f"Edited: {out}\n"
            f"  instruction: {instruction}\n"
            f"  {'masked region only' if box else 'WHOLE canvas re-rendered (no mask_box)'}\n"
            f"  source untouched: {image_path}")


if __name__ == "__main__":
    mcp.run()
