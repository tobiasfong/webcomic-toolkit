"""
Character & Panel Generator — MCP Server
=========================================
A local Model Context Protocol server for writers who aren't artists (and artists
who'd rather not redraw six angles by hand): register or generate a character's
reference art, then generate consistent poses and composite them onto background
plates into finished comic panels — all against a local ComfyUI + Stable
Diffusion pipeline.

The character-domain sibling of webcomic-background-mcp's World Builder: same
philosophy (reference-driven, never generate-from-text-and-pray), same skeleton,
no code dependency between the two servers.

Ships all three tiers of the consistency design (see README.md's "Consistency
tiers" section for the honest per-tier state): Tier 1 (img2img from a reference),
Tier 2 (IP-Adapter identity + OpenPose, opt-in via generate_character_pose's
identity_mode/pose_ref_path), and Tier 3 (per-character LoRA baking via
bake_character_lora/check_lora_training/cancel_lora_training).

Also ships Concept Genesis (ARCHITECTURE.md §8b.6) — three on-ramps into the
bible for users who don't already have a full reference set: no art at all
(generate_character_concept), a composite concept sheet from a sheet generator
(crop_reference), or one finished drawing that just needs turnaround views
(generate_reference_sheet — also the tool for on-ramp 3, an artist's own art;
that on-ramp needs no new tool, just register_character on the drawing itself).

Also ships the 3D mannequin (ARCHITECTURE.md §8b.7) — generate_pose_map
synthesizes an OpenPose control map from a posable 3D skeleton at any yaw
angle, feeding generate_character_pose's pose_ref_path directly. This is the
only reliable path to a genuine back view; 2D-photo pose extraction always
relaxes back toward front-facing (see generate_pose_map's docstring for the
validated recipe and its honest stochastic caveat).

Also ships FLUX (ARCHITECTURE.md §8b.9, Stage 5): `model="flux_manwha"` is a new
option on generate_character_concept/generate_character_pose/generate_reference_sheet,
alongside the existing SD1.5/SDXL models — better hand anatomy once detail_fix
is on, and pose_ref_path-driven back views via ControlNet, in two flavors
(pose_control_type): the mannequin's line-skeleton ("openpose", ~2/3-seed
reliable) or generate_pose_depth_map's real posable VRM mesh ("depth", ~3/3
once calibrated — ARCHITECTURE.md §8b.9). Three FLUX-only tools round out the
recommended staged workflow for avoiding hallucinations (see
generate_turnaround_sheet's and generate_pose_depth_map's docstrings for the
full sequences): generate_turnaround_sheet (FLUX Kontext dev + a turnaround-
sheet LoRA — multi-pose sheet from one reference image), generate_pose_depth_map
(VRM mesh depth map — pose/anatomy only, NOT costume; needs a separate Blender
install, see vrm_depth.py), and edit_character_image (FLUX Kontext dev as a
plain-English image editor — validated for local anatomy/costume fixes, NOT
for full viewpoint rotation, see its docstring). compose_reference_sheet
assembles the Avery-style poster from already-existing images (e.g. panels
cropped from a turnaround sheet), as opposed to generate_reference_sheet's own
fresh-generation-per-view path.

Exposes: register_character, list_characters, forget_character, list_projects,
generate_character_concept, crop_reference, generate_pose_map,
generate_pose_depth_map, generate_character_pose, generate_reference_sheet,
generate_turnaround_sheet, edit_character_image, compose_reference_sheet,
compose_panel, check_status, bake_character_lora, check_lora_training,
cancel_lora_training.

Requires a running ComfyUI instance (default http://127.0.0.1:8188) for anything
that generates pixels — the bible, cropping, and compositing tools are GPU-free.
bake_character_lora needs a separate kohya-ss/sd-scripts install (see README.md).
Runs locally over stdio.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp.server.fastmcp import FastMCP
import characters
import workflow
import flux_workflow
import vrm_depth
import training
import mannequin
from tools.compose_panel import compose_panel as _compose_panel
from tools.crop_reference import crop_reference as _crop_reference
from tools.compose_sheet import compose_sheet as _compose_sheet
from tools.compose_sheet import compose_concept_sheet as _compose_concept_sheet
from tools.compose_sheet import compose_full_reference_sheet as _compose_full_reference_sheet
from tools.bg_composite import composite_on_gradient as _composite_on_gradient

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

    Copies each image into the bible and records/updates the character's metadata.
    References are input-format agnostic — a ChatGPT/Midjourney character sheet is
    as valid as commissioned art; this tool never judges provenance. Calling this
    again on an existing character_id APPENDS the new images to the reference set
    rather than replacing it (turnarounds and expression sheets accumulate over
    time), and only overwrites a field if you pass it — omitted fields keep their
    existing value.

    Args:
        image_paths: One or more reference images to add (concept art, turnarounds,
            expression sheets — whatever exists for this character).
        character_id: Short id to reference later (e.g. "aria"). Auto-slugged from
            name/first filename if omitted.
        name: Human name (e.g. "Aria Solstice").
        description: Hair/eye color, build, costume, signature elements — what
            defines this character's look. Free text, be specific. This is the
            ONLY field that feeds generation prompts, and it also becomes the
            reference sheet's "Appearance" text block — write it once, it does
            both jobs. If you're ingesting an artist's existing drawing and they
            already wrote appearance notes in a markdown file, pass that text
            straight through here rather than asking them to retype it.
        tags: Optional labels, e.g. ["protagonist", "mage"].
        notes: Anything that helps keep the character on-model (e.g. "always
            barefoot indoors", "never smiles fully"). Internal reminder, not
            shown on the reference sheet.
        profile: Who they are — role in the story (e.g. "protagonist's rival,
            defects to the hero's side in act 2"), standing/affiliation, and
            personality, including (if relevant) Japanese speech patterns:
            register (丁寧語 vs 普通語, formal/casual shifts by listener) and
            self-referential pronoun (僕/俺/私/あたし/わし/吾輩/etc.). E.g.
            "Exiled court mage, wanted in three kingdoms. Guarded, dry wit;
            丁寧語 with strangers, 普通語 with her sister; refers to herself as
            私, never うち." Reference-sheet text only, not a generation prompt
            input — this is for you and your artist, not the model.
        abilities: Free text on powers/skills/equipment — as much or as little
            as you want on the reference sheet.
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
    negative: str | None = None,
    n: int = 4,
    label: str | None = None,
    project: str = characters.DEFAULT_PROJECT,
    model: str = workflow.DEFAULT_MODEL,
    width: int = 640,
    height: int = 896,
    seed: int | None = None,
    lora: str | None = None,
    lora_strength: float | None = None,
) -> str:
    """Generate a batch of character-concept candidates for a character who
    doesn't exist in the bible yet — Concept Genesis on-ramp 1 (ARCHITECTURE.md
    §8b.6): a writer with a story but no reference art at all. Pure txt2img, n
    distinct seeds, the same clean backdrop as every other tier (matting-ready).

    This does NOT register anything. Look at the candidates, pick the one that
    matches your character, then register_character(image_paths=['<the winner>'],
    ...) to make it canon — the other candidates are disposable drafts. This is
    the same staging discipline the bible already uses everywhere else (nothing
    auto-commits; a human always picks).

    Args:
        description: Visually renderable identity facts ONLY — build, face, hair,
            costume, signature elements, palette. NOT quotes, backstory, stats,
            or birthdays (those belong in your own story docs, not the bible —
            the bible is a generation asset). E.g. "gaunt young man, long nose,
            manic grin, purple-and-black military uniform, white gloves, gold
            pocket chain, slicked dark hair".
        style_prompt: Extra rendering-style detail (e.g. "anime style, dynamic
            lighting"). Appended after description.
        negative: Extra negative terms (appended to sane defaults).
        n: How many candidates to generate (default 4). Each costs one GPU render.
        label: Optional name to organize the output folder under (e.g. "aria").
            Defaults to a slug of description if omitted.
        project: Which comic this is for.
        model / width / height: As generate_character_pose.
        seed: If set, candidates use seed, seed+1, seed+2… (a reproducible
            batch); if omitted, each candidate gets its own random seed.
        lora / lora_strength: Optional style LoRA (same pool as generate_character_pose).

    Returns:
        The filesystem paths to all n candidates.
    """
    label_slug = characters._slug(label or description[:40])
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), "_concepts", label_slug)
    full_prompt = f"{description}, {style_prompt}" if style_prompt else description
    try:
        if model in flux_workflow.FLUX_MODELS:
            if (width, height) == (640, 896):
                width, height = 832, 1216
            paths = flux_workflow.generate_concepts(
                prompt=full_prompt,
                out_dir=out_dir,
                n=n,
                negative=negative if negative is not None else workflow.DEFAULT_NEGATIVE,
                width=width,
                height=height,
                seed=seed,
                model=model,
                lora=lora,
                lora_strength=lora_strength,
            )
        else:
            paths = workflow.generate_concepts(
                prompt=full_prompt,
                out_dir=out_dir,
                n=n,
                negative=negative if negative is not None else workflow.DEFAULT_NEGATIVE,
                width=width,
                height=height,
                seed=seed,
                model=model,
                lora=lora,
                lora_strength=lora_strength,
            )
    except workflow.ComfyUIError as e:
        return f"Generation failed: {e}\nIs ComfyUI running at {workflow.COMFY_URL}?"
    lines = "\n".join(f"  {i + 1}. {p}" for i, p in enumerate(paths))
    return (f"{len(paths)} concept candidate(s) generated:\n{lines}\n"
            f"Nothing is registered yet — look at these, pick the one that's your "
            f"character, then register_character(image_paths=['<winner path>'], "
            f"character_id=..., name=..., project='{project}').")


def _render_pose(
    character, pose, prompt, negative, project, model, width, height, seed,
    ref_denoise, identity_mode, ip_adapter_weight, pose_ref_path, pose_strength,
    lora, lora_strength, out_dir, pose_preprocess=True, ref_override=None,
    detail_fix=False, pose_control_type="openpose",
):
    """Core Tier 1/2/3 pose rendering, shared by generate_character_pose and
    generate_reference_sheet. Raises characters.CharacterError if the character
    isn't registered, workflow.ComfyUIError on generation failure. Returns
    (raw_path, tier_note) — matting is each caller's own responsibility (they
    want different messaging around a matting failure).

    ref_override: use this image as the img2img seed / IP-Adapter identity
    source instead of the bible's primary reference — generate_reference_sheet's
    sequential chaining (front view generated first, then reused as the anchor
    for back/expression views) passes the freshly-generated front view here,
    since it's already in the target render style, which should condition
    identity more reliably than jumping styles from a raw source photo.

    pose_control_type="depth" (FLUX + pose_ref_path only, ARCHITECTURE.md
    §8b.9): the character's bible `description` is deliberately EXCLUDED from
    the auto-built prompt here — the VRM depth mesh wears a plain t-shirt, and
    including a costume description (the usual case) causes a text-vs-geometry
    conflict that produces ragged texture-clash artifacts. Only the name and
    the explicit `pose`/`prompt` text are used; apply the character's actual
    costume afterward via edit_character_image, as its own separate pass."""
    ref_path = ref_override or characters.primary_ref_path(character, project)
    entry = characters.get_character(character, project)
    full_prompt = f"{entry['name']}, {pose}"
    if prompt:
        full_prompt = f"{full_prompt}, {prompt}"
    if entry.get("description") and pose_control_type != "depth":
        full_prompt = f"{full_prompt}, {entry['description']}"

    # Tier 3: auto-use the character's own baked LoRA unless the caller overrides.
    effective_lora = lora if lora is not None else entry.get("lora")

    if model in flux_workflow.FLUX_MODELS:
        # FLUX branch (Stage 5) — no img2img/identity_mode support (untested
        # combination; IP-Adapter has never been tried against FLUX). Identity
        # comes from the prompt/description text alone, same as this project's
        # plain-text-only path. pose_ref_path routes to FLUX's own ControlNet
        # (InstantX Union, ~2/3-seed reliable for back views — see
        # flux_workflow.py's docstring), independent of workflow.py's SD1.5/
        # SDXL OpenPose branch.
        if identity_mode != "off":
            raise workflow.ComfyUIError(
                "identity_mode is not supported with FLUX models — IP-Adapter + "
                "FLUX has never been tested. Drop identity_mode (or pass "
                "identity_mode='off') and rely on the prompt/description text "
                "for identity, same as this project's plain-text-only path."
            )
        if (width, height) == (640, 896):
            width, height = 832, 1216
        raw_path = flux_workflow.generate(
            prompt=full_prompt,
            out_dir=out_dir,
            negative=negative if negative is not None else workflow.DEFAULT_NEGATIVE,
            width=width,
            height=height,
            seed=seed,
            model=model,
            lora=effective_lora,
            lora_strength=lora_strength,
            pose_ref_path=pose_ref_path,
            pose_strength=pose_strength,
            pose_preprocess=pose_preprocess,
            pose_control_type=pose_control_type,
            detail_fix=detail_fix,
        )
        tier_note = "FLUX base generation"
        if effective_lora and effective_lora == entry.get("lora"):
            tier_note = f"Tier 3 (baked LoRA '{effective_lora}') + " + tier_note
        if pose_ref_path:
            if pose_control_type == "depth":
                tier_note += (" + ControlNet pose (VRM depth map, ~3/3-seed reliable "
                              "for back views once calibrated — see vrm_depth.py)")
            else:
                tier_note += (" + ControlNet pose (synthesized mannequin map, ~2/3-seed "
                              "reliable for back views — reroll on a miss)" if not pose_preprocess
                              else " + ControlNet pose (OpenPose)")
        if detail_fix:
            tier_note += " + hand detail fix (no face pass — untested for FLUX)"
        return raw_path, tier_note

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
        lora=effective_lora,
        lora_strength=lora_strength,
        identity_mode=identity_mode,
        ip_adapter_weight=ip_adapter_weight,
        pose_ref_path=pose_ref_path,
        pose_strength=pose_strength,
        pose_preprocess=pose_preprocess,
        detail_fix=detail_fix,
    )

    tier_note = "Tier 1 (img2img)"
    if effective_lora and effective_lora == entry.get("lora"):
        tier_note = f"Tier 3 (baked LoRA '{effective_lora}') + " + tier_note
    if identity_mode != "off":
        tier_note += f" + Tier 2 identity ({identity_mode})"
    if pose_ref_path:
        tier_note += (" + Tier 2 pose (synthesized mannequin map)" if not pose_preprocess
                      else " + Tier 2 pose (OpenPose)")
    if detail_fix:
        tier_note += " + face/hand detail fix"
    return raw_path, tier_note


@mcp.tool()
def generate_pose_map(
    preset: str = "standing",
    yaw: float = 0.0,
    width: int = 832,
    height: int = 1216,
    out: str | None = None,
) -> str:
    """Synthesize an OpenPose-format pose map from a 3D posable skeleton, at any
    viewing angle — the fix for back/angled views that no amount of prompt or
    reference-photo tuning could reach (ARCHITECTURE.md §8b.7). A real 2D photo
    fed to generate_character_pose's pose_ref_path gets its skeleton *extracted*
    by OpenposePreprocessor, which guesses left/right limb assignment from
    appearance and has no way to know the person is facing away from camera —
    so it always relaxes back toward a front-facing figure. This tool instead
    poses and rotates a 3D skeleton and projects it directly: at yaw=180 the
    left/right color assignment flips and the face keypoints vanish, exactly
    like a genuine back-view annotation, because it's built from an unambiguous
    3D angle rather than guessed from a flat image.

    Feed the output to generate_character_pose(pose_ref_path=<this path>,
    pose_preprocess=False, ...) — pose_preprocess=False is required, since
    running the human-detector preprocessor on an already-synthesized stick
    figure fails.

    Validated recipe for a genuine back view (2026-07-19 live test, after this
    took ~12 failed 2D-extraction configurations to reach): yaw=180,
    pose_strength=1.4-1.5 (1.0 pins the pose but drifts back to front-facing),
    identity_mode="off" or a low ip_adapter_weight (~0.3), and the sheet's
    anti-duplicate negative terms (SHEET_NEGATIVE, or add your own — "2boys",
    "duplicate character", "fused body" etc.). This is stochastic, not
    deterministic — in testing, identical settings with a different seed
    produced a front-facing figure instead. Generate 2-3 seeds and curate the
    hit, the same propose-then-curate discipline as every other tier here.

    Args:
        preset: A named pose — "standing", "t_pose", "hands_behind_back",
            "arms_crossed", or "walking". Add new presets in mannequin.py's
            POSES dict (hand-authored joint-coordinate overrides, no IK).
        yaw: Degrees around the vertical axis. 0 = facing the viewer, 90 = their
            left side toward the viewer, 180 = seen from behind. Any value works
            (e.g. 135 for a 3/4-back angle).
        width / height: Canvas size — match what you'll pass to
            generate_character_pose (defaults are SDXL-native portrait).
        out: Output path. Defaults to a scratch file named by preset/yaw.

    Returns:
        The filesystem path to the synthesized pose map PNG.
    """
    try:
        path = mannequin.render_pose_map(preset, yaw, width, height, out)
    except ValueError as e:
        return f"Could not generate pose map: {e}"
    return (f"Pose map generated: {path}\n"
            f"Feed to generate_character_pose(pose_ref_path='{path}', "
            f"pose_preprocess=False, pose_strength=1.4 for yaw>=~135, "
            f"identity_mode='off' or a low ip_adapter_weight). Stochastic — "
            f"try a couple of seeds and curate.")


@mcp.tool()
def generate_pose_depth_map(
    yaw: float = 180.0,
    width: int = 832,
    height: int = 1216,
    out: str | None = None,
) -> str:
    """FLUX-only (ARCHITECTURE.md §8b.9): render a depth map from a real,
    posable VRM mesh (assets/Base_Male.vrm), standing pose — validated
    2026-07-22/23 as MORE reliable than generate_pose_map's line-skeleton for
    genuine back views (~3/3 seeds vs. ~2/3), once the depth map's near/far
    window is properly calibrated (already done here — see vrm_depth.py).

    Requires a separate Blender install (not bundled — see vrm_depth.py's
    docstring for one-time setup: download Blender, install the community VRM
    Add-on, set WEBCOMIC_CHAR_BLENDER to the executable path).

    IMPORTANT — this is a pose/anatomy tool, not a costume tool. The VRM mesh
    wears a plain t-shirt. Feed the output to
    generate_character_pose(pose_ref_path=<this path>, pose_preprocess=False,
    model="flux_manwha", pose_control_type="depth") with a prompt that does
    NOT describe the character's actual costume (their bible `description` is
    automatically excluded from the prompt in this mode for exactly this
    reason) — otherwise the text and the plain-shirt geometry conflict,
    producing ragged texture-clash artifacts (confirmed live). Once you have
    a clean pose/anatomy result, dress it in the real costume via
    edit_character_image as a separate pass — validated end-to-end
    2026-07-23, including fixing a follow-up logical error (a necktie
    rendered on the back of a back-view figure) with a second, precise edit.

    Only the "standing" pose (arms at sides) is implemented.

    Args:
        yaw: Degrees around the vertical axis. 0 = facing the viewer, 180 =
            seen from behind — same convention as generate_pose_map.
        width / height: Canvas size — match what you'll pass to
            generate_character_pose (defaults are FLUX-native portrait).
        out: Output path. Defaults to a scratch file named by yaw.

    Returns:
        The filesystem path to the rendered depth map PNG.
    """
    try:
        path = vrm_depth.render_depth_map(yaw, width, height, out)
    except vrm_depth.VrmDepthError as e:
        return f"Could not generate depth map: {e}"
    return (f"Depth map generated: {path}\n"
            f"Feed to generate_character_pose(pose_ref_path='{path}', "
            f"pose_preprocess=False, model='flux_manwha', "
            f"pose_control_type='depth', pose_strength=0.8) with a "
            f"costume-neutral prompt — then edit_character_image to apply "
            f"the real costume afterward.")


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
    identity_mode: str = "off",
    ip_adapter_weight: float = 0.8,
    pose_ref_path: str | None = None,
    pose_strength: float = 1.0,
    pose_preprocess: bool = True,
    pose_control_type: str = "openpose",
    detail_fix: bool = False,
    lora: str | None = None,
    lora_strength: float | None = None,
    matte: bool = True,
) -> str:
    """Render a registered character alone, in a new pose, on a clean backdrop.

    Layers this server's three consistency tiers (see README.md), all available
    on this one tool:

    - Tier 1 (always on): img2img seeded from the character's primary reference
      image, so the render stays recognizably them. Drifts on ambitious poses.
    - Tier 2 (opt-in, identity_mode): IP-Adapter conditions the render on the
      reference's *identity* — stacks with Tier 1's img2img, or use
      ref_denoise=1.0 for pure txt2img + IP-Adapter (more pose range). Needs
      setup_models.py's Tier-2 models + the ComfyUI_IPAdapter_plus custom node.
      pose_ref_path (a photo of someone in the target pose, or a synthesized
      map from generate_pose_map) additionally pins the pose via OpenPose
      ControlNet, independent of identity_mode. generate_pose_map is the only
      reliable way to get a genuine back view — see its docstring.
    - Tier 3 (automatic once baked): if bake_character_lora has completed for
      this character, its LoRA is used automatically unless you pass your own
      `lora=`. Strongest consistency, no extra args needed here.

    detail_fix (opt-in, needs ComfyUI-Impact-Pack + ComfyUI-Impact-Subpack, see
    README.md): a detect-and-repair pass on the face and hands after the main
    render — the actual fix for hallucinated hands (missing/extra fingers) and
    mangled faces, which are a resolution problem (a face or hand is a small
    fraction of a full-body frame) that prompt/negative wording can't solve.
    Roughly doubles generation time; silently does nothing if a face/hand isn't
    confidently detected in frame (not an error, just nothing to fix there).

    Output is auto-matted to an RGBA cutout by default, ready for compose_panel.

    Args:
        character: A character_id already in the bible (register_character first).
        pose: The pose/action to render (e.g. "arms crossed, looking over shoulder").
        prompt: Extra scene-agnostic detail (lighting, angle). The character's own
            name/description from the bible is prepended automatically.
        negative: Extra negative terms (appended to sane defaults).
        project: Which comic's bible/output to use.
        model / width / height / seed: As webcomic-background-mcp's generate_background.
            model="flux_manwha" (Stage 5, ARCHITECTURE.md §8b.9) is a FLUX
            option alongside the SD1.5/SDXL models above — better hand anatomy
            with detail_fix=True, but identity_mode must stay "off" (IP-Adapter
            + FLUX is untested); use pose_ref_path for pose control instead.
        ref_denoise: How much of the reference survives (0-1) for Tier 1's
            img2img seeding. Lower = closer to the reference (safer, less pose
            range); higher = more prompt-driven (more pose range, more drift
            risk unless identity_mode compensates). Default 0.55.
        identity_mode: "off" (default), "plus" (body/identity, the Tier-2
            default), or "plus_face" (portraits — NOT true FaceID, see README).
        ip_adapter_weight: IP-Adapter strength when identity_mode is set. Default 0.8.
        pose_ref_path: A pose reference — either a photo of someone in the target
            pose (extracted to an OpenPose skeleton), or a synthesized map from
            generate_pose_map (pass pose_preprocess=False for those). Pinned via
            ControlNet.
        pose_strength: OpenPose ControlNet strength when pose_ref_path is set.
            For genuine back views (yaw=180 mannequin maps), 1.0 pins the pose
            but drifts back toward a front-facing figure — 1.4-1.5 is what
            actually forces the direction; see generate_pose_map's docstring.
        pose_preprocess: True (default) runs OpenposePreprocessor on
            pose_ref_path — use this for real photos/art. False feeds the image
            straight to ControlNet unprocessed — use this for maps already in
            OpenPose format, i.e. anything from generate_pose_map (running the
            human-detector preprocessor on a stick figure fails).
        pose_control_type: FLUX models + pose_ref_path only (ARCHITECTURE.md
            §8b.9). "openpose" (default) uses mannequin.py's line-skeleton
            maps, ~2/3-seed direction-lock reliability. "depth" uses
            generate_pose_depth_map's VRM mesh depth maps instead — ~3/3-seed
            reliability once calibrated, but the character's bible
            `description` is automatically EXCLUDED from the prompt in this
            mode (the VRM mesh wears a plain t-shirt; describing a different
            costume causes text-vs-geometry texture-clash artifacts) — apply
            the real costume afterward via edit_character_image. Forces
            pose_preprocess off automatically (OpenposePreprocessor doesn't
            apply to depth maps).
        detail_fix: Auto-repair hallucinated hands/faces after the main render.
            Default False (needs extra custom nodes — see README.md; costs
            roughly 2x generation time when on).
        lora / lora_strength: Optional style LoRA — same pool as the background
            server's (e.g. the Niji V5 Style LoRA). Overrides the character's own
            baked LoRA (Tier 3) if one exists; pass lora="" to force neither.
        matte: Auto-remove the clean backdrop to RGBA (default True). Set False to
            keep the raw render with its backdrop, e.g. to eyeball the pose first.

    Returns:
        The filesystem path to the matted (or raw) pose PNG.
    """
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character), "poses")
    try:
        raw_path, tier_note = _render_pose(
            character, pose, prompt, negative, project, model, width, height, seed,
            ref_denoise, identity_mode, ip_adapter_weight, pose_ref_path, pose_strength,
            lora, lora_strength, out_dir, pose_preprocess=pose_preprocess,
            detail_fix=detail_fix, pose_control_type=pose_control_type)
    except characters.CharacterError as e:
        return f"Could not generate pose: {e}"
    except workflow.ComfyUIError as e:
        return f"Generation failed: {e}\nIs ComfyUI running at {workflow.COMFY_URL}?"

    if not matte:
        return (f"Pose generated (not matted): {raw_path}\n"
                f"{tier_note}, ref_denoise={ref_denoise} — curate before use.")
    try:
        matted_path = workflow.matte(raw_path)
    except workflow.ComfyUIError as e:
        return f"Pose generated but matting failed: {e}\n  raw render: {raw_path}"
    return (f"Pose generated: {matted_path}\n"
            f"  raw render (with backdrop): {raw_path}\n"
            f"{tier_note}, ref_denoise={ref_denoise} — curate before compose_panel. "
            f"Feed this to compose_panel as character_layer_path.")



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


# Reduced from the original 7-view checklist (front/back/side/3-4 body + 3 face)
# to match Avery's actual template (2026-07-19, per Tobias): a frontal view, a
# back view, and a few 3/4 close-ups with different expressions — not a full
# angle survey. "3/4 view" for the close-ups (Avery's expression rows use that
# angle), applied to the head/face specifically — "face close-up, 3/4 view"
# alone was ambiguous enough that a live test (2026-07-20) got interpreted as
# a 3/4-angle BODY shot, not a tight face crop; "close-up portrait, head/
# shoulders only" makes the framing an instruction, not just a vibe.
DEFAULT_SHEET_VIEWS = [
    "full body, front view",
    "full body, back view",
    "close-up portrait, head and shoulders only, head turned three-quarters, neutral expression",
    "close-up portrait, head and shoulders only, head turned three-quarters, smiling",
    "close-up portrait, head and shoulders only, head turned three-quarters, determined expression",
]

# Real-world tuning (2026-07-19, against actual RxR art — see CHANGELOG): the
# original defaults (ip_adapter_weight=0.8, ref_denoise=0.7) let a busy source
# illustration's own composition (VFX, specific pose) dominate every view
# regardless of what the text prompt asked for — every "view" came out as a
# near-identical re-roll of the source pose, backdrop and all. Fix, in order of
# how much each moved the needle: (1) ref_denoise near 1.0 lets the img2img
# branch go, so the text prompt actually gets to steer composition; (2) a much
# lower ip_adapter_weight (0.8 -> 0.25) — IP-Adapter's identity embedding
# doesn't separate "this person" from "this scene," so a high weight drags the
# reference's exact VFX/lighting along regardless of the backdrop prompt; (3)
# explicit VFX-suppression terms, now baked into workflow.py's
# CLEAN_BACKDROP_NEGATIVE globally (not just here) since clean backdrops are
# Tier 1's whole promise, not a sheet-only concern. This also surfaced a second
# artifact — SD1.5 sometimes renders two figures side-by-side at full denoise —
# suppressed via the extra negative terms below. Genuine back/3-4 views remain
# unreliable even after all of this (see the tool's honest caveat) — a real
# SD1.5-checkpoint limitation for non-front angles on top of the composition-
# anchoring bug, not something parameter tuning alone fully solves.
SHEET_NEGATIVE = (workflow.DEFAULT_NEGATIVE
                  + ", two people, duplicate, multiple figures, split screen, "
                    "comparison, twins, side by side, before and after, "
                    # Validated during the SDXL back-view campaign (2026-07-19):
                    # these specifically eliminated the fused-body/multi-figure
                    # artifacts that OpenPose-conditioned generations produced.
                    "2boys, 2girls, multiple people, clone, duplicate character, "
                    "multiple views, character sheet, fused body, conjoined")


@mcp.tool()
def generate_reference_sheet(
    character: str,
    views: list[str] | None = None,
    project: str = characters.DEFAULT_PROJECT,
    model: str = workflow.DEFAULT_MODEL,
    width: int = 640,
    height: int = 896,
    identity_mode: str = "plus",
    ip_adapter_weight: float = 0.25,
    ref_denoise: float = 1.0,
    detail_fix: bool = False,
    lora: str | None = None,
    lora_strength: float | None = None,
    matte: bool = False,
    combine: bool = True,
) -> str:
    """Grow a registered character's reference set toward a standard turnaround
    checklist (front view, back view, a few 3/4 expression close-ups) — Concept
    Genesis on-ramp for both a writer who just registered a first concept and an
    artist with one finished drawing who doesn't want to redraw six angles by
    hand (ARCHITECTURE.md §8b.6). One Tier-2 generation per view.

    Generation is a disciplined SEQUENCE, not N independent rolls: regardless of
    the order `views` is passed in, the front view is always rendered first,
    then the back view, then everything else (expressions). Once the front
    view succeeds, it becomes the back view's identity anchor (img2img seed +
    IP-Adapter reference) instead of the bible's raw source photo — expression/
    face close-ups deliberately do NOT chain off it (tried, reverted: a
    close-up chained off a full-body reference drags that framing and pose
    along, since IP-Adapter conditions on the whole reference image, not just
    "this person's face"). If front-view generation fails, the back view falls
    back to the bible's primary reference instead.

    Honest limitation, not solved by the above: genuine back views remain
    unreliable through this tool. Automatically wiring in the 3D mannequin's
    ControlNet pose map here was tried and reverted (2026-07-20) — forcing
    identity_mode="off" to win the direction fight against IP-Adapter did get
    back-facing content into frame, but full-resolution review found it came
    with a fused hand and hoof-like feet, worse anatomy than just being
    front-facing, and it didn't improve on retry. If you actually need a back
    view, use generate_pose_map + generate_character_pose directly and curate
    across a few seeds by hand — the validated, reviewed, one-at-a-time flow
    (ARCHITECTURE.md §8b.7) — rather than expecting this bulk multi-view call
    to land one unattended.

    By default (combine=True) all views are ALSO laid out on one poster-style
    reference sheet, in addition to the individual files — modeled on Tobias's
    friend Avery's hand-composed character sheets: title, a large front-view
    hero pose, a back-view panel, a labeled row of expression close-ups, and
    short text blocks pulled from the Character Bible's profile/abilities
    fields plus its description (shown here as "Appearance" — see
    register_character's docstring; set these before calling this for a sheet
    worth looking at, empty fields are just skipped, no blank boxes).
    Deliberately far less text than Avery's actual sheets (no bio paragraphs,
    no quotes) — this server generates panels, it doesn't write your story.
    Needs a front view among the generated views to build the poster; falls
    back to a plain labeled grid otherwise (e.g. redoing a single non-front
    view). The individual files are still what you pass to register_character
    — the composed sheet is for looking at everything at once.

    Nothing is auto-appended to the bible. Look at each view, then
    register_character(image_paths=[<the keepers>], character_id=<character>,
    project=...) to grow the reference set — the same append-on-reregister
    behavior every other tier already relies on (the §8b.2 bootstrap loop, now
    with a front door).

    Write the character's `description` (register_character) with real visual
    detail — hair/eye/skin color, build, costume colors — BEFORE calling this.
    Without it, the text prompt has nothing to anchor identity with, and every
    view leans entirely on the source image (dragging its exact pose/background
    along too). This matters more than it sounds like it should.

    Honest caveat: back/3-4 views drift more than front/face views even with
    good settings — this looks like a real limitation of this checkpoint for
    non-front angles, not just "needs curation." Expect to retry those
    specifically, or supply an actual back-facing photo via
    generate_character_pose's pose_ref_path (OpenPose) to force the angle
    structurally instead of hoping the prompt/IP-Adapter balance gets there.
    This is genesis, not verification — curate hard, and consider
    bake_character_lora once ~10+ curated refs accumulate.

    Args:
        character: A character_id already in the bible (register_character or
            generate_character_concept first).
        views: Which views to generate. Defaults to a 7-view standard checklist
            (front/back/side/3-4 body views + 3 face expressions). Pass a single
            view (e.g. ["full body, back view"]) to redo just one.
        project: Which comic's bible/output to use.
        model / width / height: As generate_character_pose.
        identity_mode: Defaults to "plus" (Tier 2 IP-Adapter identity lock) —
            unlike generate_character_pose, this defaults ON. Needs the Tier-2
            models + ComfyUI_IPAdapter_plus custom node (see README.md); pass
            "off" if those aren't installed yet (Tier 1 alone, weaker turnarounds).
        ip_adapter_weight: IP-Adapter strength. Default 0.25 — much lower than
            generate_character_pose's 0.8, so identity locks (helped by a good
            text description, see above) without dragging the reference's exact
            composition/background along (see the module note above for how
            this default was actually tuned).
        ref_denoise: How much of the reference survives Tier-1 img2img seeding.
            Default 1.0 (effectively lets the text prompt drive composition
            instead of the source image) — much higher than
            generate_character_pose's 0.55; turnarounds need real freedom from
            the source framing, not a nudge away from it.
        detail_fix: Auto-repair hallucinated hands/faces on every view. Default
            False — see generate_character_pose's docstring. Costs ~2x
            generation time per view when on; consider enabling only once you
            like the poses and are generating the keeper set.
        lora / lora_strength: Optional style LoRA; defaults to the character's
            baked Tier-3 LoRA if one exists, same as generate_character_pose.
        matte: Auto-remove the clean backdrop to RGBA. Default False — sheet
            views are reference material to look at/draw from, not compositing
            layers (compose_panel is what wants RGBA cutouts).
        combine: Also lay every view out on the poster-style sheet (or a plain
            grid, if no front view was generated this call). Default True.

    Returns:
        The filesystem path for each view, one line each, plus the combined
        sheet path if requested. A single view's generation failure is reported
        inline rather than aborting the whole sheet.
    """
    view_list = views if views else DEFAULT_SHEET_VIEWS
    if not view_list:
        return "generate_reference_sheet needs at least one view."

    # Sequential discipline: front first, then back, then everything else —
    # regardless of the order the caller listed them in. See the docstring
    # above for why (front becomes the identity anchor for what follows).
    def _bucket(v: str) -> int:
        vl = v.lower()
        if "front" in vl:
            return 0
        if "back" in vl:
            return 1
        return 2
    view_list = sorted(view_list, key=_bucket)

    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character),
                           "_concepts", "sheet")
    lines = []
    ok_paths, ok_labels = [], []
    front_path = back_path = None
    expr_items = []  # (path, short_label)
    chain_ref = None  # set once the front view succeeds; reused for the back view only
    for view in view_list:
        bucket = _bucket(view)
        # Automatically wiring the mannequin's ControlNet pose map into the back
        # view was tried and reverted (2026-07-20): forcing identity_mode="off"
        # + pose_strength=1.45 to win the direction fight against IP-Adapter did
        # get genuine back-facing content into frame, but live scrutiny (not
        # just checking "does it face backward") showed it came with a fused,
        # fingerless hand and hoof-like feet — worse overall anatomy, not just
        # a wrong-direction one, and retrying didn't fix it. Back view stays
        # plain text + IP-Adapter here, honestly unreliable (see the docstring
        # caveat below) — the validated mannequin recipe
        # (pose_strength=1.4-1.5, identity_mode="off", multi-seed curation) is
        # a deliberate, reviewed, one-at-a-time flow via generate_pose_map +
        # generate_character_pose, not something safe to bulk-automate
        # unattended inside a multi-view sheet call.
        #
        # Only the back view (still a full-body shot, like the front) reuses
        # the front view as an img2img/IP-Adapter identity anchor for costume/
        # color continuity. Expression/face close-ups do NOT chain off front —
        # a close-up chained off a full-body reference drags that framing and
        # pose along (IP-Adapter conditions on the whole reference image, not
        # just "this person's face"), which is exactly what broke here: a
        # "face close-up, smiling" request came back as a repeat of the front
        # view's full-body pose. Expressions fall back to the bible's own
        # primary reference, matching this tool's pre-chaining behavior.
        view_ref_override = chain_ref if bucket == 1 else None
        try:
            raw_path, tier_note = _render_pose(
                character, view, "", SHEET_NEGATIVE, project, model, width, height, None,
                ref_denoise, identity_mode, ip_adapter_weight, None, 1.0,
                lora, lora_strength, out_dir,
                ref_override=view_ref_override, detail_fix=detail_fix)
        except characters.CharacterError as e:
            return f"Could not generate reference sheet: {e}"
        except workflow.ComfyUIError as e:
            lines.append(f"• {view}: FAILED — {e}")
            continue
        view_path = raw_path
        if matte:
            try:
                view_path = workflow.matte(raw_path)
                lines.append(f"• {view}: {view_path}")
            except workflow.ComfyUIError as e:
                lines.append(f"• {view}: generated but matting failed ({e}) — raw: {raw_path}")
        else:
            lines.append(f"• {view}: {view_path}")
        ok_paths.append(view_path)
        ok_labels.append(view)

        if bucket == 0:  # front
            if front_path is None:
                front_path = raw_path
            chain_ref = raw_path  # anchor the back view off this
        elif bucket == 1:  # back
            if back_path is None:
                back_path = raw_path
        else:
            expr_items.append((raw_path, view.split(",")[-1].strip() or view))

    combined_note = ""
    if combine and front_path:
        try:
            entry = characters.get_character(character, project) or {}
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
            combined_note = f"\nCombined sheet (plain grid — no front view generated this call, so the poster layout was skipped): {sheet_path}"
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
    width: int = flux_workflow.FLUX_TURNAROUND_WIDTH,
    height: int = flux_workflow.FLUX_TURNAROUND_HEIGHT,
) -> str:
    """FLUX-only (ARCHITECTURE.md §8b.9, Stage 5): generate a multi-pose
    turnaround sheet from a registered character's primary reference image, via
    FLUX Kontext dev + a dedicated turnaround-sheet LoRA. This is the
    recommended staged workflow for getting a new character into the bible
    with FLUX, designed to catch mistakes early rather than discover them after
    a full sheet is built:

    1. generate_character_concept(description=..., model="flux_manwha", n=1) —
       one candidate front view. Look at it. Not right? Regenerate (different
       seed, or n>1 to compare a few) before spending time on the next step.
    2. register_character(image_paths=[<the approved concept>], ...) — make it
       canon. This becomes the reference this tool reads from.
    3. generate_turnaround_sheet(character=...) — this tool. Typically comes
       back as 7 panels in a horizontal row (some front/3-4/profile repeats
       alongside one back view, per the LoRA's own design — not exactly 5
       distinct poses in practice). Inspect the WHOLE figure on every panel you
       care about, not just whether it's facing the right way — check the
       collar/neckline shape (front necklines dip toward the chest, back
       collars sit flat), hands, and shoe orientation (toe box vs. heel). A
       genuine back view has correct back-of-garment details throughout (back
       seam, rear pockets, no belt buckle), not just a turned head. If the
       back-view panel isn't genuinely clean, retry with a different seed —
       one successful seed doesn't mean every seed will land it (this hasn't
       been measured across many seeds the way the ControlNet path's ~2/3 rate
       has).
    4. crop_reference(sheet_path, boxes=[...]) — slice out the panels you want
       to keep. Must include a front view and the back view; a profile/3-4 view
       and 1-2 close-ups (crop tighter to head-and-shoulders if needed) round
       out the Avery-template's three image slots (hero + back panel +
       expression row).
    5. compose_reference_sheet(character=..., front_path=..., back_path=...,
       expression_paths=[...], ...) — assemble the final poster sheet from
       those crops, pulling the bible's profile/abilities/appearance text in
       automatically.
    6. Optionally, edit_character_image on any panel with a specific anatomy
       problem (e.g. hidden/malformed hands) before step 4/5 — validated for
       local fixes on a pose that's already facing the right direction, see
       its own docstring for what it's NOT good for.

    Nothing is auto-registered or auto-composed by this tool — same staging
    discipline as everything else here.

    Args:
        character: A character_id already in the bible, with a primary
            reference image set.
        project: Which comic's bible to use.
        seed: Fixed seed for reproducibility; random if omitted.
        width / height: Output canvas — wide, since panels lay out in a
            horizontal row. Defaults validated 2026-07-22.

    Returns:
        The filesystem path to the raw (uncropped) turnaround sheet.
    """
    try:
        ref_path = characters.primary_ref_path(character, project)
    except characters.CharacterError as e:
        return f"Could not generate turnaround sheet: {e}"
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), characters._slug(character),
                           "_concepts", "turnaround")
    try:
        sheet_path = flux_workflow.generate_turnaround_sheet(
            image_path=ref_path, out_dir=out_dir, seed=seed, width=width, height=height)
    except workflow.ComfyUIError as e:
        return f"Turnaround sheet generation failed: {e}\nIs ComfyUI running at {workflow.COMFY_URL}?"
    return (f"Turnaround sheet generated: {sheet_path}\n"
            f"Scan the WHOLE figure on each panel you care about (collar shape, "
            f"hands, shoe orientation), not just facing direction — a partial "
            f"rotation can look right at a glance and still be wrong. If the "
            f"back view isn't genuinely clean, retry with a different seed.\n"
            f"Next: crop_reference to slice out front + back (+ a profile view "
            f"and 1-2 close-ups), then compose_reference_sheet to build the "
            f"final poster.")


@mcp.tool()
def edit_character_image(
    image_path: str,
    instruction: str,
    project: str = characters.DEFAULT_PROJECT,
    seed: int | None = None,
) -> str:
    """FLUX-only (ARCHITECTURE.md §8b.9, Stage 5): surgically edit an existing
    image with a plain-English instruction, via FLUX Kontext dev as a pure
    image editor (no LoRA).

    Validated for LOCAL fixes on a pose that's already facing the right
    direction — e.g. "show both of his hands fully visible hanging at his
    sides, relaxed and open, fingers clearly separated. Keep everything else
    exactly the same." That combination (a targeted ask + an explicit
    "keep everything else the same") produced a clean result with no
    side effects on direction, costume, or pose.

    NOT validated, and one test actively disproved, for a full viewpoint
    rotation in a single edit — asking it to both "turn him around" and "keep
    everything else the same" is self-contradicting for a full pose change: one
    test produced a chimera (back-facing head/hair/hands, but front-facing
    torso/shoes — the tank-top's neckline was still a front-facing scoop and
    both shoes still showed their toe box, not the heel). Use
    generate_turnaround_sheet for direction changes instead of trying to
    reproduce that here.

    Args:
        image_path: An existing image to edit (any generated output, or a
            registered reference).
        instruction: Plain-English edit instruction. Be specific about what to
            keep unchanged, not just what to change — vague instructions risk
            the same kind of partial-edit inconsistency described above.
        project: Which comic's output folder to save under.
        seed: Fixed seed for reproducibility; random if omitted.

    Returns:
        The filesystem path to the edited image.
    """
    out_dir = os.path.join(OUTPUT_DIR, characters._slug(project), "_edits")
    try:
        edited_path = flux_workflow.edit_image(
            image_path=image_path, instruction=instruction, out_dir=out_dir, seed=seed)
    except workflow.ComfyUIError as e:
        return f"Edit failed: {e}\nIs ComfyUI running at {workflow.COMFY_URL}?"
    return (f"Edited image: {edited_path}\n"
            f"Scan the WHOLE figure before trusting this — head, collar/"
            f"neckline, hands, legs, shoes — not just the region the "
            f"instruction targeted; a local edit can succeed exactly where "
            f"asked and still leave the rest of the figure inconsistent with "
            f"it.")


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
    bordered boxes scattered across left/center/right columns (not one
    stacked text column), front+back shown side by side in one box, plus
    optional FUNCTIONS/FILE NOTES bullet boxes, a boxed prop illustration, an
    ability-mechanism diagram box, and an "IN ACTION" pose row. Built from
    the real Trevor sheet run (ARCHITECTURE.md §8b.11) — same staging
    discipline as compose_reference_sheet: nothing auto-registered.

    Do NOT invent content for functions/notes/prop/diagram — these need real
    text/images the caller actually has (derived from the bible's real
    abilities/profile text, or genuinely generated assets). Leave a param
    unset rather than filling it with placeholder content; the layout skips
    any section with nothing given it.

    Args:
        character: A character_id already in the bible (pulls name/profile/
            abilities/description/palette from it, same as
            compose_reference_sheet).
        front_path / back_path: full-body views, shown side by side.
        expression_paths / expression_labels: face/angle close-ups shown as
            a row of same-height crops (full aspect preserved, not
            square-cropped — a square top-anchored crop can cut off the chin
            on a taller-than-wide source).
        subtitle: one line under the character's name.
        functions: bullet list for a "FUNCTIONS" box — short phrases derived
            from the bible's real abilities text.
        notes: bullet list for a "FILE NOTES" box — short phrases derived
            from the bible's real profile text.
        prop_path / prop_label / prop_caption: one boxed illustration (a
            signature item/artifact).
        diagram_path: one boxed illustration explaining how the character's
            ability works — render this separately (e.g. PIL boxes+arrows)
            and just pass the path; this tool only embeds it.
        action_paths / action_labels: a labeled row of action/combat poses,
            shown at full aspect ratio (not square-cropped, since the
            prop/effect can be anywhere in frame).
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
def bake_character_lora(
    character: str,
    project: str = characters.DEFAULT_PROJECT,
    epochs: int = 10,
    repeats: int = 10,
    network_dim: int = 32,
    network_alpha: int = 16,
    learning_rate: float = 1e-4,
    resolution: int = 512,
    class_word: str = "person",
    model: str | None = None,
    style_lora: str | None = training.STYLE_LORA,
    style_lora_multiplier: float = training.STYLE_LORA_MULTIPLIER,
) -> str:
    """Start Tier-3 training: bake a per-character LoRA from the character's
    reference set. Strongest consistency tier — but takes 30-90 min on a
    3060-class GPU, so this returns immediately once training has STARTED, not
    once it's done. Poll with check_lora_training.

    Needs a separate kohya-ss/sd-scripts install (see README.md's Tier-3 setup
    steps) — this is heavier than Tier 1/2, which only need ComfyUI.

    Best with 10-20 reference images. Fewer still works but risks overfitting;
    the bootstrap loop (register_character with curated Tier-1/2 renders you
    like, then re-bake) is the intended way to grow a thin reference set. Only
    one training job per character at a time.

    Args:
        character: A character_id already in the bible, with at least one
            reference image.
        project: Which comic's bible to train from.
        epochs / repeats: Training length — total exposure per image ≈
            epochs × repeats. Defaults (10, 10) suit a 10-20 image set.
        network_dim / network_alpha: LoRA rank/scale. Defaults (32, 16) are a
            reasonable general-purpose starting point.
        learning_rate: Default 1e-4.
        resolution: Training resolution, default 512 (SD1.5-native).
        class_word: The regularization class word paired with the character's
            own trigger token in captions (default "person").
        model: Which checkpoint to train against (default: the server's default
            render model). Use the same one you'll generate poses with.
        style_lora: Merged into the checkpoint before training, so the baked
            character LoRA carries this style permanently — same mechanism as
            generate_character_pose's `lora=`, but baked in rather than applied
            per call. Defaults to the Niji V5 Style LoRA (matching the project's
            usual style pool); pass "" to train against a plain checkpoint instead.
        style_lora_multiplier: Strength of the style merge (default 1.0).

    Returns:
        Confirmation that training has started, with how to check progress.
    """
    try:
        job = training.bake(character, project, epochs=epochs, repeats=repeats,
                            network_dim=network_dim, network_alpha=network_alpha,
                            learning_rate=learning_rate, resolution=resolution,
                            class_word=class_word, model=model,
                            style_lora=style_lora, style_lora_multiplier=style_lora_multiplier)
    except (training.TrainingError, characters.CharacterError) as e:
        return f"Could not start training: {e}"
    style_note = f", style base: {job['style_lora']}" if job.get("style_lora") else ""
    return (f"Training started for '{character}' in project '{project}' "
            f"({job['num_images']} reference image(s), {job['epochs']} epochs{style_note}, "
            f"pid {job['pid']}).\n"
            f"This runs 30-90 min in the background. Check progress with "
            f"check_lora_training(character='{character}', project='{project}').\n"
            f"Log: {job['log_path']}")


@mcp.tool()
def check_lora_training(character: str, project: str = characters.DEFAULT_PROJECT) -> str:
    """Check the status of a Tier-3 LoRA training job (queued/training/done/
    failed/cancelled). Once done, the LoRA is automatically installed into
    ComfyUI's models/loras/ and recorded on the character's bible entry —
    generate_character_pose will use it automatically from then on."""
    job = training.status(character, project)
    state = job.get("state", "none")
    if state == "none":
        return f"No training job found for '{character}' in project '{project}'."
    if state == "done":
        style_note = f" (style base: {job['style_lora']})" if job.get("style_lora") else ""
        return (f"Training complete: {job['installed_lora']}{style_note} installed in "
                f"ComfyUI's models/loras/ and set as '{character}''s default LoRA. "
                f"generate_character_pose will use it automatically now.")
    if state == "failed":
        return (f"Training failed for '{character}'. Last log lines:\n{job['log_tail']}\n"
                f"Full log: {job['log_path']}")
    if state == "cancelled":
        return f"Training for '{character}' was cancelled."
    started = job.get("started_at", "?")
    return (f"Training in progress for '{character}' (started {started}, pid {job['pid']}).\n"
            f"Recent log:\n{job['log_tail']}")


@mcp.tool()
def cancel_lora_training(character: str, project: str = characters.DEFAULT_PROJECT) -> str:
    """Cancel an in-progress Tier-3 training job for a character."""
    cancelled = training.cancel(character, project)
    if not cancelled:
        return f"No in-progress training job for '{character}' in project '{project}'."
    return f"Cancelled training for '{character}' in project '{project}'."


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
