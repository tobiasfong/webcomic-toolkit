"""
Character & Panel Generator — MCP Server
=========================================
A local Model Context Protocol server for writers who aren't artists (and artists
who'd rather not redraw six angles by hand): register or generate a character's
reference art, then generate consistent poses and composite them onto background
plates into finished comic panels — all against a local ComfyUI.

The character-domain sibling of webcomic-background-mcp's World Builder: same
philosophy (reference-driven, never generate-from-text-and-pray), same skeleton,
no code dependency between the two servers.

**FLUX 3 Image Klein only, since v2.0.0** (see CHANGELOG). FLUX.1 — its GGUF
models, the manhwa and turnaround LoRAs, ControlNet and Kontext — was removed
once both this server and the background server had moved to Klein. What that
means for a caller:

  * Identity comes from the character's PRIMARY REFERENCE on every render that
    draws them. Klein's multi-reference held two identities through a pose
    change with no attribute bleed on 3 of 3 seeds, so generate_scene puts
    several characters in one render.
  * When the asked-for pose is the one the reference already shows, Klein
    COPIES the reference, flaws and crop included. Pad a tight reference first.
  * There is no ControlNet and no LoRA. Describe a pose in words; the style is
    Klein's own, accepted by the author.
  * Renders take 18-90 s, not FLUX.1's minutes.

Klein runs on its own ComfyUI (v0.41, port 8189), started on first use by
klein_workflow. Matting still runs on the main ComfyUI (port 8188), so both are
up during character work. Measured behavior is in the repo's AGENTS.md.

Exposes: register_character, get_character, list_characters, forget_character,
list_projects, generate_character_concept, crop_reference,
generate_character_pose, generate_reference_sheet, generate_turnaround_sheet,
edit_character_image, generate_scene, generate_expression,
compose_reference_sheet, compose_full_reference_sheet,
apply_gradient_background, apply_vfx_overlay, compose_panel, check_status.

The bible, cropping and compositing tools are GPU-free. Runs locally over stdio.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp.server.fastmcp import FastMCP
import characters
import comfy
import klein_workflow


def _klein_pose_text(entry, pose, prompt, words=None):
    """The pose prompt, in one place: generate_expression's from-scratch candidate
    must repeat its base's prompt word for word, plus only the expression."""
    extra = (prompt.strip().rstrip(".") + ". ") if prompt and prompt.strip() else ""
    face = (", with " + words.rstrip(". ")) if words else ""
    return ("The character from image 1, " + pose.strip().rstrip(".") + ", full body from head to "
            "feet, on a plain flat pale gray backdrop, clear empty space above the head and below "
            "the feet. " + extra + "The character from image 1: "
            + entry["description"].rstrip(". ") + face + ". They keep the face, hair and costume "
            "of their reference image. Lit from the upper left.")


def _klein_pose(character, pose, prompt, project, width, height, seed, out_dir, matte):
    """generate_character_pose: identity from the PRIMARY REFERENCE. The
    description still goes in, resolved from the bible -- never retyped."""
    try:
        entry = characters.get_character(character, project)
        if entry is None:
            raise characters.CharacterError(f"'{character}' is not registered in '{project}'.")
        ref = characters.primary_ref_path(character, project)
    except characters.CharacterError as e:
        return f"Could not generate pose: {e}"
    text = _klein_pose_text(entry, pose, prompt)
    try:
        raw = klein_workflow.generate(text, out_dir, width, height, seed=seed, refs=[ref], stem="pose")
    except klein_workflow.KleinError as e:
        return f"Generation failed: {e}"
    if not matte:
        return f"Pose generated (not matted): {raw}\nCurate before use."
    try:
        matted = klein_workflow.clean_matte(raw, comfy.matte(raw))
    except Exception as e:
        # Deliberately broad: whatever goes wrong, the caller must be TOLD the
        # image is not matted, or an RGB render is only discovered at composite.
        return (f"Pose generated but MATTING FAILED -- this image is RGB, not RGBA, and is NOT "
                f"ready for compose_panel: {type(e).__name__}: {e}\n  raw render: {raw}")
    return (f"Pose generated: {matted}\n  raw render (with backdrop): {raw}\n"
            f"Curate before compose_panel. Feed this to compose_panel as character_layer_path.")


def _matte_or_note(raw):
    """(path, note): the matted cutout, or the raw render and why it is not one."""
    try:
        return klein_workflow.clean_matte(raw, comfy.matte(raw)), ""
    except Exception as e:
        return raw, f" (MATTING FAILED, still RGB: {type(e).__name__}: {e})"


from tools.compose_panel import compose_panel as _compose_panel
from tools.crop_reference import crop_reference as _crop_reference
from tools.compose_sheet import compose_sheet as _compose_sheet
from tools.compose_sheet import compose_concept_sheet as _compose_concept_sheet
from tools.compose_sheet import compose_full_reference_sheet as _compose_full_reference_sheet
from tools.bg_composite import composite_on_gradient as _composite_on_gradient
from tools.bg_composite import screen_blend as _screen_blend

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
    profile: str = "",
    abilities: str = "",
    project: str = characters.DEFAULT_PROJECT,
) -> str:
    """Add (or grow) a character's reference set in the Character Bible.

    Copies each image into the bible and records/updates metadata. Input-format
    agnostic — a ChatGPT/Midjourney sheet is as valid as commissioned art.
    Calling again on an existing character_id APPENDS new images (turnarounds/
    expression sheets accumulate over time); only overwrites a field if passed
    — omitted fields keep their existing value.

    Args:
        image_paths: One or more reference images to add.
        character_id: Short id to reference later (e.g. "aria"). Auto-slugged
            from name/first filename if omitted.
        name: Human name (e.g. "Aria Solstice").
        description: Hair/eye color, build, costume, signature elements. Free
            text, be specific — the ONLY field that feeds generation prompts,
            and also becomes the reference sheet's "Appearance" block, so it
            does both jobs. If an artist already has appearance notes written,
            pass that text through directly.
        tags: Optional labels, e.g. ["protagonist", "mage"].
        notes: Anything that keeps the character on-model (e.g. "always
            barefoot indoors"). Internal reminder, not shown on the sheet.
        profile: Role in the story, standing/affiliation, personality,
            including (if relevant) Japanese speech patterns: register (丁寧語
            vs 普通語, shifts by listener) and self-referential pronoun (僕/俺/
            私/あたし/わし/吾輩/etc). E.g. "Exiled court mage. Guarded, dry
            wit; 丁寧語 with strangers, 普通語 with her sister; refers to
            herself as 私, never うち." Reference-sheet text, not a model prompt.
        abilities: Free text on powers/skills/equipment for the reference sheet.
        project: Which comic this character belongs to. Defaults to "default".

    Returns:
        A summary of the registered entry (id, reference count, auto-extracted palette).
    """
    try:
        entry = characters.register_character(
            image_paths=image_paths, character_id=character_id, name=name,
            description=description, tags=tags, notes=notes,
            profile=profile, abilities=abilities,
            project=project,
        )
        return (f"Registered '{entry['id']}' in project '{entry['project']}' — {entry['name']}\n"
                f"  references: {len(entry['refs'])}\n"
                f"  palette:    {', '.join(entry['palette']) or '(none)'}\n"
                f"Generate poses of them with generate_character_pose(character='{entry['id']}', "
                f"project='{entry['project']}', pose=...).")
    except characters.CharacterError as e:
        return f"Could not register character: {e}"


@mcp.tool()
def get_character(character: str, project: str = characters.DEFAULT_PROJECT) -> str:
    """Fetch one character's canon: description, reference image paths and the
    finished panels that establish each detail.

    CALL THIS BEFORE WRITING ANY PROMPT THAT INVOLVES THIS CHARACTER, and paste
    the returned description verbatim rather than describing them from memory or
    from looking at a panel. Until this tool existed there was no way to obtain a
    character's reference path through the MCP interface, so prompts got
    hand-written and drifted — a panel shipped with the wrong hair color and the
    wrong eye color, both of which the bible had recorded correctly all along.

    `primary_ref` is the image every render of this character conditions on.
    """
    entry = characters.get_character(character, project)
    if not entry:
        return (f"No character '{character}' in project '{project}'. "
                f"Use list_characters(project='{project}') to see what exists.")

    refs = entry.get("refs", [])
    sources = entry.get("ref_sources", {})
    out = [f"# {entry.get('name', character)}  (id: {character}, project: {project})",
           "", "## Description — use this text verbatim in prompts",
           entry.get("description", "(EMPTY — do not invent one; ask first)"), ""]

    if refs:
        out.append("## Reference images")
        for i, rel in enumerate(refs):
            path = characters.primary_ref_path(character, project) if i == 0 else \
                os.path.join(characters.CHAR_ROOT, rel.replace("/", os.sep))
            src = sources.get(os.path.basename(rel), "UNRECORDED ORIGIN")
            label = "primary — condition on this" if i == 0 else "alternate"
            out.append(f"- [{label}] {path}\n    from: {src}")
        out.append("")

    canon = entry.get("canon_panels", {})
    if canon:
        out.append("## Approved panels — canon, consult before redrawing a detail")
        for panel, what in canon.items():
            out.append(f"- {panel}\n    establishes: {what}")
        out.append("")

    for field in ("profile", "abilities", "notes"):
        if entry.get(field):
            out.append(f"## {field.title()}\n{entry[field]}\n")
    if entry.get("palette"):
        out.append("## Palette\n" + ", ".join(entry["palette"]))
    return "\n".join(out)


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
def generate_character_concept(
    description: str,
    style_prompt: str = "",
    n: int = 1,
    label: str | None = None,
    project: str = characters.DEFAULT_PROJECT,
    width: int = 832,
    height: int = 1216,
    seed: int | None = None,
) -> str:
    """Generate character-concept candidates for a character who doesn't exist in
    the bible yet — Concept Genesis on-ramp 1 (ARCHITECTURE.md §8b.6): a writer
    with a story but no reference art. Text-to-image on FLUX 3 Klein, one seed
    per candidate, on a plain pale gray backdrop.

    Output is RGB, NOT matted, and deliberately so: concepts are candidates to
    look at and choose between, and the chosen one gets cropped into a reference
    (`crop_reference`), which wants the backdrop intact.

    Does NOT register anything. Look at the candidate, then
    register_character(image_paths=['<the winner>'], ...) to make it canon.
    The author asks for a reroll when he wants one; n defaults to 1.

    Args:
        description: Visually renderable identity facts ONLY — build, face,
            hair, costume, signature elements, palette. Not quotes/backstory/
            stats. Leave out "tall" (it fills the canvas and clips the figure)
            and build words on a clothed character (muscle came back as skin).
        style_prompt: Extra detail, appended after the description.
        n: How many candidates (default 1). Each costs one render.
        label: Optional output-folder name; defaults to a slug of description.
        project: Which comic this is for.
        width / height: Default 832x1216, a full figure in portrait.
        seed: If set, candidates use seed, seed+1, seed+2… (reproducible batch).

    Returns:
        The filesystem paths to the candidates.
    """
    label_slug = characters._slug(label or description[:40])
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), "_concepts", label_slug)
    full_prompt = f"{description}, {style_prompt}" if style_prompt else description
    text = ("A single full-body figure of " + full_prompt.rstrip(". ") + ", standing "
            "facing the viewer, on a plain flat pale gray backdrop, clear empty space "
            "above the head and below the feet. Lit from the upper left.")
    try:
        paths = [klein_workflow.generate(text, out_dir, width, height,
                                         seed=(seed + i) if seed is not None else None,
                                         stem="concept")
                 for i in range(n)]
    except klein_workflow.KleinError as e:
        return f"Generation failed: {e}"
    lines = "\n".join(f"  {i + 1}. {p}" for i, p in enumerate(paths))
    return (f"{len(paths)} concept candidate(s) generated:\n{lines}\n"
            f"Nothing is registered yet — look at these, pick the one that's your "
            f"character, then register_character(image_paths=['<winner path>'], "
            f"character_id=..., name=..., project='{project}').")


@mcp.tool()
def generate_character_pose(
    character: str,
    pose: str,
    prompt: str = "",
    project: str = characters.DEFAULT_PROJECT,
    width: int = 832,
    height: int = 1216,
    seed: int | None = None,
    matte: bool = True,
) -> str:
    """Render a registered character alone, in a new pose, on a clean backdrop.

    FLUX 3 Klein, with the character's PRIMARY REFERENCE as image 1 and the
    bible description in the prompt: identity holds through the pose change.
    Describe the pose in words -- there is no ControlNet on Klein.

    ⚠ If the pose asked for is the one the reference already shows, Klein
    COPIES the reference, flaws and crop included (a tight crop came back cut
    off at the head or feet 17 times in 40). Pad the reference ~18% on its own
    backdrop color before a same-pose request.

    Output is matted to RGBA by default, ready for compose_panel.

    Args:
        character: A character_id already in the bible.
        pose: The pose/action to render (e.g. "arms crossed, looking over shoulder").
            Keep expression words out of a body meant as an expression base.
        prompt: Extra scene-agnostic detail (lighting, angle).
        project: Which comic's bible/output to use.
        width / height / seed: Default 832x1216.
        matte: Remove the backdrop to RGBA (default True). False keeps the raw
            render, e.g. to eyeball the pose first.

    Returns:
        The filesystem path to the matted (or raw) pose PNG.
    """
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character), "poses")
    return _klein_pose(character, pose, prompt, project, width, height, seed, out_dir, matte)


def _hex_to_rgb(hex_color: str | None) -> tuple[int, int, int] | None:
    if not hex_color:
        return None
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


# Avery's template (2026-07-19, per Tobias): a frontal view, a back view, and a
# few 3/4 close-ups with different expressions — not a full angle survey.
# "close-up portrait, head and shoulders only" makes the framing an
# instruction; "face close-up" alone once came back as a 3/4 BODY shot.
DEFAULT_SHEET_VIEWS = [
    "full body, front view",
    "full body, back view",
    "close-up portrait, head and shoulders only, head turned three-quarters, neutral expression",
    "close-up portrait, head and shoulders only, head turned three-quarters, a small closed-mouth smile",
    "close-up portrait, head and shoulders only, head turned three-quarters, a determined expression",
]


@mcp.tool()
def generate_reference_sheet(
    character: str,
    views: list[str] | None = None,
    project: str = characters.DEFAULT_PROJECT,
    width: int = 832,
    height: int = 1216,
    seed: int | None = None,
    matte: bool = False,
    combine: bool = True,
) -> str:
    """Grow a registered character's reference set toward the Avery-style
    checklist — front, back, and a few 3/4 expression close-ups — one FLUX 3
    Klein render per view, each from the character's primary reference
    (ARCHITECTURE.md §8b.6).

    For the four body angles, generate_turnaround_sheet is the better tool: one
    render, each view in its own layout box, a genuine profile included. This
    one is for the close-ups and the poster.

    ⚠ The front view usually comes back close to a copy of the reference --
    Klein copies when the pose asked for is the pose it was shown.

    combine=True (default) lays every view onto one poster-style sheet: title,
    large front hero pose, back panel, labeled expression row, and text blocks
    from the bible's profile/abilities/description — set those before calling.
    Needs a front view for the poster; falls back to a plain grid otherwise.

    Nothing auto-registers. Look at each view, then register_character
    (image_paths=[<keepers>], character_id=<character>, project=...).

    Args:
        character: A character_id already in the bible.
        views: Which views to render. Defaults to front, back and three 3/4
            close-ups. Pass a single view to redo just one. Keep expressions
            small: big ones came back cartoonish.
        project: Which comic's bible/output to use.
        width / height: Default 832x1216.
        seed: If set, views use seed, seed+1, seed+2… in order.
        matte: Remove the backdrop to RGBA. Default False — sheet views are
            reference material, not compositing layers.
        combine: Also build the poster-style sheet. Default True.

    Returns:
        The path for each view, plus the combined sheet path if requested. A
        single view's failure is reported inline, not fatal.
    """
    view_list = views if views else DEFAULT_SHEET_VIEWS
    if not view_list:
        return "generate_reference_sheet needs at least one view."
    try:
        entry = characters.get_character(character, project)
        if entry is None:
            raise characters.CharacterError(f"'{character}' is not registered in '{project}'.")
        ref = characters.primary_ref_path(character, project)
    except characters.CharacterError as e:
        return f"Could not generate reference sheet: {e}"

    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character),
                           "_concepts", "sheet")
    lines, ok_paths, ok_labels, expr_items = [], [], [], []
    front_path = back_path = None
    for i, view in enumerate(view_list):
        text = ("The character from image 1, " + view.strip().rstrip(".") + ", on a plain flat "
                "pale gray backdrop. The character from image 1: " + entry["description"].rstrip(". ")
                + ". They keep the face, hair and costume of their reference image. "
                "Lit from the upper left.")
        try:
            raw = klein_workflow.generate(text, out_dir, width, height,
                                          seed=(seed + i) if seed is not None else None,
                                          refs=[ref], stem="view")
        except klein_workflow.KleinError as e:
            lines.append(f"• {view}: FAILED — {e}")
            continue
        path, note = _matte_or_note(raw) if matte else (raw, "")
        lines.append(f"• {view}: {path}{note}")
        ok_paths.append(path)
        ok_labels.append(view)
        vl = view.lower()
        if "front" in vl and front_path is None:
            front_path = raw
        elif "back" in vl and back_path is None:
            back_path = raw
        elif "front" not in vl and "back" not in vl:
            expr_items.append((raw, view.split(",")[-1].strip() or view))

    combined_note = ""
    if combine and front_path:
        try:
            sheet_path = _compose_concept_sheet(
                front_path=front_path,
                back_path=back_path,
                expression_paths=[p for p, _ in expr_items],
                expression_labels=[lbl for _, lbl in expr_items],
                name=entry.get("name", character),
                profile=entry.get("profile", ""),
                abilities=entry.get("abilities", ""),
                appearance=entry.get("description", ""),
                accent_color=_hex_to_rgb((entry.get("palette") or [None])[0]),
                out=os.path.join(out_dir, "concept_sheet.png"),
            )
            combined_note = f"\nCombined sheet (Avery-style layout): {sheet_path}"
        except SystemExit as e:
            combined_note = f"\n(Could not build the combined sheet: {e})"
    elif combine and ok_paths:
        try:
            sheet_path = _compose_sheet(ok_paths, ok_labels,
                                        out=os.path.join(out_dir, "combined_sheet.png"))
            combined_note = (f"\nCombined sheet (plain grid — no front view this call, so the "
                             f"poster layout was skipped): {sheet_path}")
        except SystemExit as e:
            combined_note = f"\n(Could not build the combined sheet: {e})"

    return (f"Reference sheet for '{character}' ({len(view_list)} view(s)):\n"
            + "\n".join(lines) + combined_note +
            f"\nNothing appended to the bible yet — curate these, then "
            f"register_character(image_paths=[<keepers>], character_id='{character}', "
            f"project='{project}') to grow the reference set.")


@mcp.tool()
def generate_turnaround_sheet(
    character: str,
    project: str = characters.DEFAULT_PROJECT,
    seed: int | None = None,
    width: int = 2560,
    height: int = 1024,
    extra_prompt: str = "",
) -> str:
    """Front, three-quarter, profile and back in ONE FLUX 3 Klein render, from the
    character's primary reference, each view held in its own layout box and cut
    out EXACTLY by that box (no gap search). Measured 2026-10-17: four true
    views including a genuine profile, no strangers, 0.0% of figure pixels
    outside the boxes, ~86 s.

    The staged way to get a new character into the bible:

    1. generate_character_concept(description=...) — one candidate. Not right?
       Regenerate before the next step.
    2. register_character(image_paths=[<the approved concept>], ...) — make it
       canon; it becomes the reference this tool reads from.
    3. generate_turnaround_sheet(character=...) — this tool. Check each panel
       is the angle it claims, over the WHOLE figure (collar shape, hands, shoe
       orientation), and that the costume agrees across all four. Reroll with a
       new seed if one is wrong.
    4. compose_reference_sheet(character=..., front_path=..., back_path=...,
       expression_paths=[...], ...) — the final poster from those panels.

    Nothing is auto-registered or auto-composed.

    Args:
        character: A character_id already in the bible, with a primary
            reference image set.
        project: Which comic's bible to use.
        seed: Fixed seed for reproducibility; random if omitted.
        width / height: Default 2560x1024, four boxes of 640x1024.
        extra_prompt: Anything a view keeps losing (glasses, a full-length
            hem, an emblem on the back the front reference cannot show). The
            full bible description already goes in; this is IN ADDITION.

    Returns:
        The path to the sheet and to each cut panel.
    """
    try:
        ref_path = characters.primary_ref_path(character, project)
        entry = characters.get_character(character, project)
    except characters.CharacterError as e:
        return f"Could not generate turnaround sheet: {e}"
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character),
                           "_concepts", "turnaround")
    try:
        sheet_path, panels = klein_workflow.turnaround_sheet(
            ref_path, entry["description"], out_dir, width=width, height=height,
            seed=seed, extra_prompt=extra_prompt)
    except klein_workflow.KleinError as e:
        return f"Turnaround sheet generation failed: {e}"
    lines = "\n".join(f"  {k}: {v}" for k, v in panels.items())
    return (f"Turnaround sheet generated: {sheet_path}\n"
            f"Panels, cut exactly by their layout boxes:\n{lines}\n"
            f"Check each view is the angle it claims and that the costume agrees "
            f"across all four. extra_prompt carries anything a view keeps losing.")


@mcp.tool()
def edit_character_image(
    image_path: str,
    instruction: str,
    project: str = characters.DEFAULT_PROJECT,
    seed: int | None = None,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
    matte: bool = False,
    matte_tol: float | None = None,
    mask_box: tuple[int, int, int, int] | None = None,
) -> str:
    """Edit or re-pose an existing image with FLUX 3 Klein.

    WITHOUT mask_box, the image is a REFERENCE and the instruction describes
    the result. Every pixel is drawn fresh with the image's identity, so this
    is also how a character is re-posed from their own art, or a figure is
    re-framed on a taller canvas. Describe the whole result, not only the
    change.

    WITH mask_box (x0, y0, x1, y1, in the source's pixels), only that region is
    redrawn and pasted back: the change outside it is exactly zero, where the
    model on its own redraws the whole frame (18.5 of mean change outside a
    boxed edit). The box also sets the SIZE of what is drawn — an oversized box
    gave an oversized, swollen hand. Size it to the thing.

    ⚠ When a hand stays wrong, reroll the whole render rather than patching:
    six region repairs gave one clean hand; three fresh seeds of the full
    render gave one with both hands right.

    canvas_width / canvas_height: output size for an unmasked edit, e.g. a
    landscape panel from a portrait reference. Default: the image's own size.

    matte: key the result to a transparent RGBA cutout with tools/cutout.py's
    border-connected keying — for an edit rendered on a clean backdrop only.
    matte_tol: keying tolerance; omit to MEASURE it from this image. Watch for
    `pale_figure_risk` in the response (pale hair or costume near a pale
    backdrop) and lower matte_tol if the silhouette is bitten.

    Args:
        image_path: An existing image to edit.
        instruction: Plain-English instruction. Name what stays as well as what
            changes, and state things positively — a negation names what it
            forbids.
        project: Which comic's output folder to save under.
        seed: Fixed seed for reproducibility; random if omitted.

    Returns:
        The filesystem path to the edited image.
    """
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), "_edits")
    try:
        if mask_box:
            edited_path = klein_workflow.edit_region(
                image_path, instruction, out_dir, tuple(mask_box), seed=seed)
        else:
            w0, h0 = klein_workflow.size_of(image_path)
            edited_path = klein_workflow.generate(
                instruction, out_dir, canvas_width or w0, canvas_height or h0, seed=seed,
                refs=[image_path], megapixels=klein_workflow.megapixels_of(image_path),
                stem="edit")
    except klein_workflow.KleinError as e:
        return f"Edit failed: {e}"
    matte_note = ""
    if matte:
        try:
            from tools.cutout import key_cutout, measure_backdrop_tol
            if matte_tol is None:
                tol, stats = measure_backdrop_tol(edited_path)
            else:
                tol, stats = float(matte_tol), {"tolerance": float(matte_tol),
                                                "measured": False}
            cut = os.path.splitext(edited_path)[0] + "_cut.png"
            key_cutout(edited_path, cut, backdrop_tol=tol)
            matte_note = f"Matted cutout: {cut}\n  keying: {stats}\n"
            if stats.get("pale_figure_risk"):
                matte_note += ("  WARNING pale_figure_risk — part of the figure sits "
                               "close to the backdrop color; check the silhouette for "
                               "bites out of pale hair or costume, and re-run with a "
                               "lower matte_tol if so.\n")
            matte_note += "  Drop onto a plate with compose_panel.\n"
        except Exception as e:
            matte_note = f"Matting failed ({type(e).__name__}: {e}) — the raw edit above is fine.\n"

    return (f"Edited image: {edited_path}\n{matte_note}"
            f"Scan the WHOLE figure before trusting this — head, collar/"
            f"neckline, hands, legs, shoes — not just the region the "
            f"instruction targeted.")


@mcp.tool()
def generate_scene(
    characters_in_scene: list[str],
    scene: str,
    project: str = characters.DEFAULT_PROJECT,
    width: int = 1536,
    height: int = 864,
    seed: int | None = None,
) -> str:
    """FLUX 3 Klein: several registered characters in ONE render, each from their
    own primary reference -- a CG with its room and light in a single pass.

    Measured 2026-10-17: two characters re-posed together, each still themselves,
    with no attribute bleed, on 3 of 3 seeds. On FLUX.1 this needed a solo render
    per figure, a matte each, a plate and a composite by hand.

    scene: what happens, in plain words, referring to the characters as "the
        character from image 1", "image 2"... in the order given. Describe what
        their bodies DO. Two cautions from testing:
          - ask for poses the references do NOT already show; when the pose
            matches a reference, Klein copies that reference, flaws included.
          - describe states, not paint: "flushed deep red" came back as makeup,
            "sick with a fever, sleeping, perspiring" came back as a fever.
        Descriptions are appended from the bible automatically -- never retype them.
    characters_in_scene: character ids, in image order.
    width / height: 1536x864 is exact 16:9 and goes to 1920x1080 at a flat 1.25x.

    Hands are still the weak point: when one is wrong, REROLL the seed rather
    than patching -- three seeds beat six repairs in testing. To fix one region
    of a render you like, edit_character_image(mask_box=...) changes nothing
    outside the box.
    """
    refs, parts = [], []
    try:
        for i, cid in enumerate(characters_in_scene, 1):
            entry = characters.get_character(cid, project)
            if entry is None:
                return f"'{cid}' is not registered in '{project}'."
            refs.append(characters.primary_ref_path(cid, project))
            parts.append(f"The character from image {i}: " + entry["description"].rstrip(". ") + ".")
    except characters.CharacterError as e:
        return f"Could not build the scene: {e}"
    text = (scene.rstrip().rstrip(".") + ". " + " ".join(parts) + " Each keeps the face, hair and "
            "costume of their own reference image.")
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), "_scenes")
    try:
        p = klein_workflow.generate(text, out_dir, width, height, seed=seed, refs=refs, stem="scene")
    except klein_workflow.KleinError as e:
        return f"Scene generation failed: {e}"
    order = ", ".join(f"image {i} = {c}" for i, c in enumerate(characters_in_scene, 1))
    return (f"Scene rendered (FLUX 3 Klein, {order}): {p}\n"
            f"Check every hand at full size before keeping it; reroll the seed if one is wrong.")


@mcp.tool()
def generate_expression(
    character: str,
    expression: str,
    pose: str,
    seed: int,
    project: str = characters.DEFAULT_PROJECT,
    prompt: str = "",
) -> str:
    """FLUX 3 Klein: an expression as a WHOLE new body, rendered from scratch and matted.

    The author's rule, 2026-10-17: "Body can move." Body language and posture
    follow the mood, and a pose that shifts with the face makes the change easier
    to read -- so an expression is its own full body, never a face pasted onto
    the base. It is rendered from the character's reference with the base body's
    pose and prompt plus the expression, on a seed DIFFERENT from the base's.
    Reusing the base's own seed froze the posture -- the body came back with a
    mean change of 0.5 of 255 -- which reads as static; the expressions the
    author approved used the base's seed + 5000, and the posture moved with them.

    Not done, and why: pasting the new face onto the base (built on the idea that
    the body must not move) broke on bodies rendered from text alone -- the faces
    lost the hair strands crossing them; and a candidate "copied" from the base
    picture was rejected on sight as "bad and unnatural". From scratch was
    "excellent and more natural".

    expression: "smile", "anger" or "laugh" -- the names the game already uses,
        with deliberately small wordings (bigger ones came back cartoonish).
        Anything else is used as plain words, but the game wires expressions BY
        NAME: do not invent new ones without the author.
    pose / prompt: the ones the base body was made with by
        generate_character_pose. Keep expression words out of the base's pose
        ("a calm neutral expression"), or this render is asked for two at once.
    seed: the seed for THIS render, used as given. Pass a different one from
        the base's -- the base's seed + 5000 is what the approved ones used.
    """
    words = klein_workflow.EXPRESSIONS.get(expression, expression)
    name = expression if expression in klein_workflow.EXPRESSIONS else "custom"
    try:
        entry = characters.get_character(character, project)
        if entry is None:
            raise characters.CharacterError(f"'{character}' is not registered in '{project}'.")
        ref = characters.primary_ref_path(character, project)
    except characters.CharacterError as e:
        return f"Could not make the expression: {e}"
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character), "expressions")
    try:
        raw = klein_workflow.generate(_klein_pose_text(entry, pose, prompt, words=words), out_dir,
                                      832, 1216, seed=seed, refs=[ref], stem=f"body_{name}")
    except klein_workflow.KleinError as e:
        return f"Expression failed: {e}"
    try:
        matted = klein_workflow.clean_matte(raw, comfy.matte(raw))
    except Exception as e:
        return (f"Expression rendered but MATTING FAILED -- RGB, not RGBA: {type(e).__name__}: {e}\n"
                f"  raw render: {raw}")
    return (f"'{name}' body for {character} (seed {seed}): {matted}\n  raw render: {raw}\n"
            f"A whole new body -- the posture may differ from the base. Check every hand.")

@mcp.tool()
def compose_reference_sheet(
    character: str,
    front_path: str,
    back_path: str | None = None,
    expression_paths: list[str] | None = None,
    expression_labels: list[str] | None = None,
    project: str = characters.DEFAULT_PROJECT,
) -> str:
    """Assemble the Avery-style poster sheet (same layout as
    generate_reference_sheet's combine=True path) from images that already
    exist — e.g. panels sliced out of generate_turnaround_sheet's output via
    crop_reference, or any other curated set of views — instead of generating
    fresh views the way generate_reference_sheet does. Pulls the character's
    name/profile/abilities/description text from the bible automatically, same
    as generate_reference_sheet.

    Args:
        character: A character_id already in the bible.
        front_path: The full-body front view — the large hero image, center of
            the sheet.
        back_path: The full-body back view, its own labeled panel.
        expression_paths / expression_labels: Parallel lists — face/angle
            close-ups and their captions (e.g. "3/4 left", "profile"). Crop
            tighter to head-and-shoulders if the source panel is full-body.
        project: Which comic's bible to use.

    Returns:
        The filesystem path to the composed sheet.
    """
    try:
        entry = characters.get_character(character, project)
    except characters.CharacterError as e:
        return f"Could not compose reference sheet: {e}"
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character),
                           "_concepts", "sheet")
    os.makedirs(out_dir, exist_ok=True)
    try:
        sheet_path = _compose_concept_sheet(
            front_path=front_path,
            back_path=back_path,
            expression_paths=expression_paths or [],
            expression_labels=expression_labels or [],
            name=entry.get("name", character),
            profile=entry.get("profile", ""),
            abilities=entry.get("abilities", ""),
            appearance=entry.get("description", ""),
            accent_color=_hex_to_rgb((entry.get("palette") or [None])[0]),
            out=os.path.join(out_dir, "concept_sheet.png"),
        )
    except SystemExit as e:
        return f"Could not compose reference sheet: {e}"
    return (f"Composed reference sheet: {sheet_path}\n"
            f"Nothing auto-registered — register_character(image_paths=[<the "
            f"individual crops you used>], character_id='{character}', "
            f"project='{project}') to grow the reference set.")


@mcp.tool()
def compose_full_reference_sheet(
    character: str,
    front_path: str,
    back_path: str | None = None,
    expression_paths: list[str] | None = None,
    expression_labels: list[str] | None = None,
    subtitle: str = "",
    functions: list[str] | None = None,
    notes: list[str] | None = None,
    prop_path: str | None = None,
    prop_label: str = "",
    prop_caption: str = "",
    diagram_path: str | None = None,
    action_paths: list[str] | None = None,
    action_labels: list[str] | None = None,
    project: str = characters.DEFAULT_PROJECT,
) -> str:
    """A denser Avery-template-style poster than compose_reference_sheet:
    bordered boxes across left/center/right columns (not one stacked text
    column), front+back side by side in one box, plus optional FUNCTIONS/FILE
    NOTES bullet boxes, a boxed prop illustration, an ability-mechanism
    diagram box, and an "IN ACTION" pose row. Same staging discipline as
    compose_reference_sheet: nothing auto-registered.

    Do NOT invent content for functions/notes/prop/diagram — these need real
    text/images the caller has. Leave a param unset rather than filling it
    with placeholder content; the layout skips any section left empty.

    Args:
        character: A character_id already in the bible (pulls name/profile/
            abilities/description/palette from it).
        front_path / back_path: full-body views, shown side by side.
        expression_paths / expression_labels: face/angle close-ups shown as a
            row of same-height crops (full aspect preserved, not square-
            cropped — a square top-anchored crop can cut off the chin on a
            taller-than-wide source).
        subtitle: one line under the character's name.
        functions: bullet list for a "FUNCTIONS" box, from the bible's real
            abilities text.
        notes: bullet list for a "FILE NOTES" box, from the bible's real
            profile text.
        prop_path / prop_label / prop_caption: one boxed illustration (a
            signature item/artifact).
        diagram_path: one boxed illustration explaining the ability mechanism
            — render separately (e.g. PIL boxes+arrows), this tool just embeds it.
        action_paths / action_labels: a labeled row of action/combat poses, at
            full aspect ratio (not square-cropped, since the prop/effect can
            be anywhere in frame).
        project: Which comic's bible to use.

    Returns:
        The filesystem path to the composed sheet.
    """
    try:
        entry = characters.get_character(character, project)
    except characters.CharacterError as e:
        return f"Could not compose reference sheet: {e}"
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character),
                           "_concepts", "sheet")
    os.makedirs(out_dir, exist_ok=True)
    try:
        sheet_path = _compose_full_reference_sheet(
            front_path=front_path,
            back_path=back_path,
            expression_paths=expression_paths or [],
            expression_labels=expression_labels or [],
            name=entry.get("name", character),
            subtitle=subtitle,
            profile=entry.get("profile", ""),
            abilities=entry.get("abilities", ""),
            appearance=entry.get("description", ""),
            functions=functions or [],
            notes=notes or [],
            prop_path=prop_path,
            prop_label=prop_label,
            prop_caption=prop_caption,
            diagram_path=diagram_path,
            action_paths=action_paths or [],
            action_labels=action_labels or [],
            accent_color=_hex_to_rgb((entry.get("palette") or [None])[0]),
            out=os.path.join(out_dir, "full_sheet.png"),
        )
    except SystemExit as e:
        return f"Could not compose reference sheet: {e}"
    return (f"Composed full reference sheet: {sheet_path}\n"
            f"Nothing auto-registered — register_character(image_paths=[<the "
            f"individual crops you used>], character_id='{character}', "
            f"project='{project}') to grow the reference set.")


@mcp.tool()
def apply_gradient_background(
    image_path: str,
    top_color: list[int],
    bottom_color: list[int],
    project: str = characters.DEFAULT_PROJECT,
    out: str | None = None,
) -> str:
    """Cut a character image's white background out and place it over a
    fresh vertical two-color gradient — a lightweight alternative to
    compositing onto a full illustrated background (ARCHITECTURE.md §8b.11:
    illustrated scenes were tried and abandoned for reference-sheet use — a
    glowing VFX pose, e.g. a spell effect, renders with a soft fade to white
    with no hard edge, and no cutout fix removed the resulting halo cleanly
    against a high-contrast illustrated scene). Gradients sidestep that: for
    a pose with a glow effect, pick a LIGHT-toned pair (close to white near
    where the glow sits) and the leftover fade becomes invisible — this was
    never really a "background vs. no background" problem, only contrast
    between the glow's white fade and whatever's behind it.

    Args:
        image_path: A character image with a plain white background (any
            generate_character_pose / edit_character_image / turnaround-sheet
            crop output).
        top_color / bottom_color: [r, g, b] triples, 0-255. E.g. a dusk
            gradient: top_color=[120,90,140], bottom_color=[40,30,60].
        project: Which comic's output folder to save under.
        out: Output path. Auto-derived next to image_path if omitted.

    Returns:
        The filesystem path to the composited image.
    """
    if not os.path.isfile(image_path):
        return f"Could not read image: {image_path}"
    if out is None:
        root, ext = os.path.splitext(image_path)
        out = f"{root}_gradient{ext or '.png'}"
    try:
        result = _composite_on_gradient(image_path, out, tuple(top_color), tuple(bottom_color))
    except Exception as e:
        return f"Could not apply gradient background: {e}"
    return f"Composited onto gradient background: {result}"


@mcp.tool()
def apply_vfx_overlay(
    base_path: str,
    vfx_path: str,
    x: int,
    y: int,
    project: str = characters.DEFAULT_PROJECT,
    out: str | None = None,
) -> str:
    """Add a glow/spell-effect layer onto an already-composited image via
    screen blend — the fix for the glow-halo problem (ARCHITECTURE.md
    §8b.11/§8b.12): generate the character pose WITHOUT the effect baked in
    (cuts out cleanly, no halo risk), generate the effect separately on a
    plain BLACK background (e.g. "glowing blue-white ice crystals bursting in
    the air, plain solid black background, no character"), then layer it on
    with this tool. Screen blend is the correct math for light-on-black
    source material: a black vfx pixel leaves the base unchanged, white
    saturates to white, everything between adds light proportionally — no
    background-removal step needed, so there's no fringe to leave.

    Args:
        base_path: The already-composited scene (character placed on its
            background/gradient via apply_gradient_background or similar).
        vfx_path: The effect image, rendered on a plain black backdrop.
        x / y: Top-left pixel position where the vfx layer lands on base_path.
            Pick by eye from the pose (e.g. where a raised hand sits) — no
            auto-alignment, since effect and pose were generated independently.
        project: Which comic's output folder to save under.
        out: Output path. Auto-derived next to base_path if omitted.

    Returns:
        The filesystem path to the composited image.
    """
    if not os.path.isfile(base_path):
        return f"Could not read base image: {base_path}"
    if not os.path.isfile(vfx_path):
        return f"Could not read VFX image: {vfx_path}"
    if out is None:
        root, ext = os.path.splitext(base_path)
        out = f"{root}_vfx{ext or '.png'}"
    try:
        result = _screen_blend(base_path, vfx_path, position=(x, y))
        result.save(out)
    except Exception as e:
        return f"Could not apply VFX overlay: {e}"
    return f"Composited VFX overlay: {out}"


@mcp.tool()
def crop_reference(
    image_path: str,
    boxes: list[list[int]],
    out_dir: str | None = None,
) -> str:
    """Slice a composite character-concept sheet into clean single-view crops,
    ready for register_character — Concept Genesis on-ramp 2 (ARCHITECTURE.md
    §8b.6): a composite sheet from a ChatGPT/Midjourney sheet generator (hero
    pose + expressions strip + text overlay, all in one image) is NOT usable as
    a direct img2img/IP-Adapter reference. The model would condition on the
    layout — text blocks, panel borders — not the person.

    Crop boxes are pixel coordinates [x0, y0, x1, y1], top-left origin. Get them
    by eyeballing the sheet yourself, or by looking at it once (vision — opt-in,
    don't do this automatically for every sheet, it costs tokens) and proposing
    boxes for the user's approval before cropping.

    Args:
        image_path: The composite sheet to slice.
        boxes: One or more [x0, y0, x1, y1] pixel boxes, one per view to extract.
        out_dir: Where to save the crops. Defaults to <image>_crops/ next to the source.

    Returns:
        The filesystem paths to each crop, ready to pass to
        register_character(image_paths=[...]).
    """
    try:
        paths = _crop_reference(image_path, boxes, out_dir)
    except SystemExit as e:
        return f"Could not crop reference sheet: {e}"
    lines = "\n".join(f"  {i + 1}. {p}" for i, p in enumerate(paths))
    return (f"{len(paths)} crop(s) saved:\n{lines}\n"
            f"Register the good ones with register_character(image_paths=[...]).")


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
    """Check whether both ComfyUIs are reachable: Klein's (rendering) and the
    main one (matting). The bible and compose_panel work without either."""
    import requests
    lines = []
    for label, url in (("Klein (rendering)", klein_workflow.KLEIN_URL),
                       ("main (matting)", comfy.COMFY_URL)):
        try:
            r = requests.get(f"{url}/system_stats", timeout=10)
            lines.append(f"{label}: up at {url}" if r.status_code == 200
                         else f"{label}: HTTP {r.status_code} at {url}")
        except Exception as e:
            lines.append(f"{label}: not reachable at {url} ({type(e).__name__}) -- "
                         f"it auto-starts on the first job that needs it")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
