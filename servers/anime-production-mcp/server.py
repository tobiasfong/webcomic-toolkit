"""
Anime Production — MCP Server
=============================
Turns finished illustrations into an animated, music-cut video, entirely
locally. Closes the loop with music-generation-mcp: that server makes the track,
this one animates the art and cuts to it.

Runs on the same 6 GB RTX 3060 Laptop as the other GPU servers. Unlike the ACE
path, LTX needs a THIRD-PARTY custom node (city96's ComfyUI-GGUF) — see README.

THE RULE THAT DECIDES WHETHER A SHOT WILL WORK AT ALL, and the reason this
server is shaped the way it is:

    LTX RELOCATES what exists. It cannot RE-IMAGINE it.

  works: arm swings, head turns, hair and cloth, drifting snow, rotating runes,
         fire (existing pixels churning), camera drift
  fails: blinks (the eyelid was never drawn) · mouth shapes (no teeth or tongue
         exist) · growing crystals (new geometry) · foreshortening (a punch
         toward the viewer needs knuckles redrawn at a new angle)

Everything follows from that line. `animate_shot` is for the left column.
`edit_frame` + `composite_patch` cover eye- and mouth-scale features. The
`add_*` effects cover anything that must APPEAR. Choosing the wrong one wastes
GPU-hours re-rolling seeds on a shot that can never work.

Usage discipline, taught here because a server should teach it rather than let
it be discovered the hard way:

  * ComfyUI runs prompts SERIALLY. The seed hunt is a sequential loop, not a
    fan-out; stacking jobs just burns timeouts in the queue.
  * ASK FOR THE LARGEST MOTION THAT READS, AND PUT IT FIRST in the prompt. The
    leading request gets the motion budget. "Blinks slowly" froze on four seeds;
    the same shot asked to "turn her head gently" moved — and the eyes closed
    along with it. Feature-scale motion only ever arrives as a passenger.
  * Then run ~3 seeds and keep the best; roughly 1 in 3 lands. Seed variance is
    real, but ONLY when the request is achievable. Re-rolling an impossible ask
    is pure waste.
  * SEEDS DO NOT TRANSFER ACROSS CONFIGS. Change length or variant and the space
    reshuffles. Re-hunt after any parameter change.
  * NEGATIVE INSTRUCTIONS ARE IGNORED BY BOTH MODELS. "Do not close her eyes"
    closed them; "without turning" turned. Phrase every request positively.
  * Freezing is as useful as animating. If hands go wrong, a `hold` scene that
    plays the motion and rests on the last frame beats another twenty seeds.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

import comfy
import kontext_workflow as kw
import ltx_workflow as lw
import shots as sh
from tools import artifacts
from tools import assemble as asm
from tools import effects, framing, motion, subs

BASE = os.path.dirname(os.path.abspath(__file__))

mcp = FastMCP("anime-production")


def _fetch_one(outs: dict, dest: str) -> str:
    for refs in outs.values():
        for ref in refs:
            return comfy.fetch(ref, dest)
    raise comfy.ComfyUIError("ComfyUI returned outputs but no files.")


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #

@mcp.tool()
def animate_shot(project: str, name: str, image_path: str, prompt: str,
                 seeds: list[int] | None = None, length: int = 17,
                 strength: float = 0.9, variant: str = "distilled",
                 width: int = 832, height: int = 576, fps: float = 48.0,
                 measure_box: list[int] | None = None,
                 view_fps: int = 12) -> dict:
    """Animate one illustration — THE SEED HUNT, as a single call.

    For each seed: submit to LTX, retime the take to `view_fps` (ComfyUI writes
    at 24, so a 17-frame take otherwise plays in 0.7 s and reads as "nothing
    happened"), measure its motion, and record it. Returns every take, sorted
    best-first by `maxdev`.

    Defaults are the SETTLED RECIPE — distilled / length 17 / strength 0.9 /
    fps 48, about 65 s a take. Do not tune them speculatively; `strength` is the
    one real lever (1.0 grips the input so hard the clip FREEZES).

    `prompt`: lead with the LARGEST motion that reads. Phrase positively —
    negatives are ignored by this model.

    `measure_box` [left, top, right, bottom] restricts scoring to the region that
    is supposed to move. Pass it whenever the motion is smaller than the frame;
    the whole-frame figure cannot resolve anything at feature scale.

    ⚠ THE SCORE IS NOT QUALITY. It measures CHANGE — a take whose faces dissolve
    scores very high. Always look at the retimed clip or a contact_sheet before
    approving. Three seeds is the working default; roughly one lands.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    seeds = seeds or [1, 2, 3]
    if not 1 <= len(seeds) <= 8:
        raise ValueError("Run 1-8 seeds at a time; ComfyUI is serial and each take costs ~65s.")
    lw.validate(width, height, length, variant)

    uploaded = comfy.upload_image(image_path)
    results = []
    for seed in seeds:
        shot_id = sh.new_shot_id(name, seed)
        d = sh.shot_dir(project, shot_id)
        params = dict(image=uploaded, prompt=prompt, seed=seed, width=width,
                      height=height, length=length, variant=variant,
                      strength=strength, fps=fps)
        outs = comfy.submit_and_wait(lw.build(prefix=f"anime/{shot_id}", **params))
        raw = _fetch_one(outs, os.path.join(d, f"{shot_id}.webp"))
        view = os.path.join(d, f"{shot_id}_{view_fps}fps.webp")
        motion.retime(raw, view, fps=view_fps)
        m = motion.measure(view, tuple(measure_box) if measure_box else None)
        rec = sh.record(project, shot_id, name,
                        lw.recipe(**dict(params, image=os.path.basename(image_path))),
                        {"webp": raw, "retimed": view},
                        {"maxdev": m["maxdev"], "span": m["span"],
                         "peak_frame": m["peak_frame"], "reading": m["reading"]})
        results.append({"shot_id": shot_id, "seed": seed, "view": view,
                        "maxdev": m["maxdev"], "span": m["span"],
                        "peak_frame": m["peak_frame"], "reading": m["reading"]})

    results.sort(key=lambda r: r["maxdev"], reverse=True)
    return {
        "project": project, "name": name, "takes": results,
        "next": ("LOOK at the top take's `view` file (or contact_sheet it) before "
                 "approve_shot. If every seed froze, the ask is probably impossible "
                 "for LTX — check the works/fails table and consider edit_frame or "
                 "a drawn effect instead of more seeds."),
    }


@mcp.tool()
def edit_frame(image_path: str, edit: str, out_dir: str,
               seeds: list[int] | None = None, steps: int = 20,
               guidance: float = 2.5) -> dict:
    """Generate a KEYFRAME with FLUX.1 Kontext — for what LTX cannot animate.

    A blink is ~0.2% of frame pixels and about four latent pixels wide after the
    VAE's 8x compression; there is nothing there for a video model to move. So
    eye and mouth positions come from generated keyframes played back by a frame
    player, not from video generation.

    ⚠ NEVER SHIP THE OUTPUT WHOLESALE. Kontext regenerates the WHOLE frame and
    will quietly restyle linework or shift colour. Follow every call with
    `composite_patch` to bring back ONLY the region that was meant to change.

    ⚠ Kontext is BINARY — it cannot draw a half-lid. Make mid positions by
    compositing with `blend` between 0 and 1.

    Sweep a few seeds and keep the least-drifted, not the most obedient.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    seeds = seeds or [1, 2, 3]
    uploaded = comfy.upload_image(image_path)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    out = []
    for seed in seeds:
        outs = comfy.submit_and_wait(
            kw.build(uploaded, edit, seed=seed, steps=steps, guidance=guidance,
                     prefix=f"anime/{stem}"))
        dest = os.path.join(out_dir, f"{stem}_edit_s{seed}.png")
        out.append({"seed": seed, "path": _fetch_one(outs, dest)})
    return {"source": image_path, "edit": edit, "results": out,
            "recipe": kw.recipe(image_path, edit, steps=steps, guidance=guidance),
            "next": "composite_patch each result over the ORIGINAL, region only."}


@mcp.tool()
def composite_patch(base_path: str, patch_path: str, out_path: str,
                    box: list[int], feather: float = 6.0,
                    blend: float = 1.0) -> dict:
    """Paste ONLY `box` [l,t,r,b] of a generated image back over the original.

    The other half of edit_frame, and skipping it is what ruins a shot.
    `blend` < 1 mixes with the original underneath — how a half-lid is made.
    """
    return framing.composite_patch(base_path, patch_path, out_path,
                                   tuple(box), feather, blend)


# --------------------------------------------------------------------------- #
# judging
# --------------------------------------------------------------------------- #

@mcp.tool()
def measure_motion(clip_path: str, box: list[int] | None = None) -> dict:
    """How much a clip actually moves, and whether it round-trips.

    ⚠ Measures CHANGE, not quality. ⚠ The whole-frame figure cannot see
    eye-scale features — pass a `box`. ⚠ `span` is blind to round trips; read
    `maxdev` and its `peak_frame` instead. Compare the SAME region across takes,
    and use an unmoved region as a control.
    """
    return motion.measure(clip_path, tuple(box) if box else None)


@mcp.tool()
def retime_clip(clip_path: str, out_path: str, fps: int = 12,
                pingpong: bool = False, hold_ms: int = 0) -> dict:
    """Re-save a clip at a watchable rate. 12 fps is this pipeline's rate."""
    return motion.retime(clip_path, out_path, fps, pingpong, hold_ms)


@mcp.tool()
def contact_sheet(clip_path: str, out_path: str, cols: int = 4,
                  scale: float = 0.5, box: list[int] | None = None) -> dict:
    """Tile a clip's frames into one image — the fastest way to actually LOOK.

    Crop to `box` at native scale when judging a hand or a pair of eyes; they
    vanish in a shrunken full frame.
    """
    return motion.contact_sheet(clip_path, out_path, cols, scale,
                                tuple(box) if box else None)


# --------------------------------------------------------------------------- #
# drawn effects — for anything that must APPEAR
# --------------------------------------------------------------------------- #

@mcp.tool()
def add_impact(clip_path: str, out_path: str, focal: list[float] | None = None,
               at: int = 2, attack: int = 1, decay: int = 9,
               color: list[int] | None = None, lines: float = 1.0,
               flash: float = 1.0, shake: float = 1.0, fps: int = 12) -> dict:
    """Speed lines, flash and camera shake — sells a hit with no extra drawing.

    Anime does not animate the punch travelling; it sells the MOMENT OF CONTACT.
    `focal` is [x, y] as fractions of the frame; `at` is the contact frame.
    """
    return effects.impact(clip_path, out_path,
                          tuple(focal) if focal else (0.5, 0.5),
                          at, attack, decay,
                          tuple(color) if color else (235, 235, 235),
                          lines, flash, shake, fps=fps)


@mcp.tool()
def grow_layer(src_path: str, out_path: str, layer_path: str,
               kmax: float = 1.13, anchor: str = "bottom", frames: int = 30,
               fps: int = 12, hold: int = 6) -> dict:
    """Grow an artist-supplied transparent layer from an edge — ice, vines, fire.

    `layer_path` must be the element on its OWN layer with real alpha, exported
    from the drawing program. A traced polygon cannot substitute where the
    element overlaps a character. `src_path` may be a still or an existing clip,
    so generated motion and drawn growth combine in one pass.
    """
    return effects.grow_layer(src_path, out_path, layer_path, kmax, anchor,
                              frames, fps, hold)


@mcp.tool()
def add_streaks(clip_path: str, out_path: str, paths: list | None = None,
                mask_path: str | None = None, polygons: list | None = None,
                exclude: list | None = None, ref_size: list[int] | None = None,
                duration: float = 18.0, gain: float = 1.3, width: int = 7,
                twinkle: int = 70, fps: int = 12) -> dict:
    """Shooting stars across a masked sky, occluded by `exclude` shapes.

    Occlusion is the point: without it a streak crosses in FRONT of the buildings
    and reads as a scratch on the print. Stagger `paths` starts by a frame or two
    so they arrive as a group, not a queue.
    """
    return effects.streaks(clip_path, out_path, paths, mask_path, polygons,
                           exclude, tuple(ref_size) if ref_size else None,
                           duration, gain=gain, width=width, twinkle=twinkle, fps=fps)


@mcp.tool()
def add_water(clip_path: str, out_path: str, mask_path: str | None = None,
              polygons: list | None = None, ref_size: list[int] | None = None,
              sparkles: int = 22, ripples: int = 9, gain: float = 1.0,
              fps: int = 12) -> dict:
    """Glints and expanding rings on water. Ring centres are placed on an eroded,
    colour-filtered mask so a ring cannot expand onto the bank or a lily pad."""
    return effects.water(clip_path, out_path, mask_path, polygons,
                         tuple(ref_size) if ref_size else None,
                         sparkles, ripples, gain, fps)


# --------------------------------------------------------------------------- #
# framing
# --------------------------------------------------------------------------- #

@mcp.tool()
def add_motion_lines(clip_path: str, out_path: str, angle: float = 180.0,
                     density: int = 90, gain: float = 1.0, length: float = 0.55,
                     clear: list[float] | None = None, start: int = 0,
                     ramp: int = 3, fps: int = 12) -> dict:
    """Parallel streaks travelling one way — sells travel across the frame.

    Distinct from add_impact, whose lines radiate from a point of contact.
    Needed because LTX deforms locally and will NOT translate a subject across a
    composition: asked for a leap right-to-left it returned a weight shift and a
    fluttering hem. Anime sells travel with streaks rather than by drawing the
    body at every point on the path.

    `angle` 180 = right-to-left. `clear` [cx, cy, r] in frame fractions keeps an
    ellipse free of lines so the subject is not buried.
    """
    return effects.motion_lines(clip_path, out_path, angle, density, gain, length,
                                clear=tuple(clear) if clear else None,
                                start=start, ramp=ramp, fps=fps)


@mcp.tool()
def add_glow(clip_path: str, out_path: str, mask_path: str | None = None,
             key: str = "warm", period: float = 1.6, gain: float = 1.0,
             swirl: float = 0.0, floor: float = 0.25, fps: int = 12) -> dict:
    """Pulse and optionally rotate the lit parts of a region — runes, magic.

    A drawn sigil brightening is a change of VALUE, not relocation of existing
    pixels, so LTX leaves it static. This keys the lit pixels by colour
    (`warm`, `cool`, `bright`), blurs them into a halo and screens it back on a
    sine. `swirl` turns the halo about its own centroid, degrees per second —
    keep it slow, it is a blurred copy and spinning it fast just looks blurred.
    """
    return effects.glow(clip_path, out_path, mask_path, key, period, gain,
                        swirl, fps=fps, floor=floor)


@mcp.tool()
def scan_artifacts(clip_path: str, box: list[int] | None = None,
                   grid: bool = False) -> dict:
    """Find where a clip's linework collapses — smears, melts, blobbed hands.

    The motion score is blind to this: the highest-scoring take in testing
    (97.75) was the one whose face dissolved. Cel art is defined by its lines,
    and LTX does not replace lost lines, it blurs them away — so edge energy
    falling off its running peak localises the damage, and `last_clean` is where
    to truncate.

    `grid=True` tiles the frame and reports the worst tile — use it to RANK
    takes and to aim a contact_sheet, NOT to auto-truncate: a tile also dims
    when the subject merely moves out of it.

    ⚠ Detects LOSS OF DETAIL, not anatomy. A cleanly drawn but wrong hand
    passes. Never read a pass as "looks good".
    """
    if grid:
        return artifacts.scan_grid(clip_path)
    return artifacts.scan(clip_path, box)


@mcp.tool()
def measure_frame_slot(frame_path: str) -> dict:
    """Find the transparent slot in a drawn frame.

    ⚠ The alpha BOUNDING BOX is not the slot — decoration drawn on transparency
    makes the gaps between leaves count, and the bbox comes out far too wide.
    This measures the columns clear for the FULL height.
    """
    return framing.measure_slot(frame_path)


@mcp.tool()
def frame_clip(clip_path: str, out_path: str, frame_path: str,
               slot: list[int] | None = None, video_size: list[int] | None = None,
               bleed: int = 3, fps: int = 12) -> dict:
    """Composite a clip into a drawn frame's slot, centred in the video canvas.

    Portrait artwork in a 16:9 video is only ~720px wide at full height; the
    frame fills what would otherwise be dead screen with the artist's own work.
    """
    return framing.frame_clip(clip_path, out_path, frame_path,
                              tuple(slot) if slot else None,
                              tuple(video_size) if video_size else (1920, 1080),
                              bleed, fps)


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #

@mcp.tool()
def assemble_video(scenes: list[dict], out_path: str, audio_path: str | None = None,
                   beats_path: str | None = None, card: dict | None = None,
                   cues: list | None = None, video_size: list[int] | None = None,
                   fps: int = 24, clip_fps: int = 12, bars_loop: int = 6,
                   hold_seconds: float = 4.0, duration: float | None = None,
                   preview: float = 0.0) -> dict:
    """Cut the shots to the track and encode. Blocking; minutes.

    `scenes`: [{"clip": path, "kind": "loop"|"pong"|"once"|"hold", "name": str}].
    The KIND decides the timing, and picking it well is most of the edit:
      loop — ambient, no natural end. Holds the full panel.
      pong — oscillatory. Full panel, forward-then-back, no seam.
      once — an event. Lasts EXACTLY its clip; no static hold, because holding a
             still frame before an event reads as the video having frozen.
      hold — plays once then freezes on the last frame. Stillness AFTER motion
             reads as a beat; before it, as a bug.

    `beats_path` (from music-generation-mcp's extract_beats) makes looping panels
    hold whole bars, so cuts land on downbeats. `card` is the end card — see
    tools/assemble.build_card for its keys. `cues` burns in subtitles.

    Use `preview` (seconds) to check the opening before committing to a full run.
    """
    return asm.assemble(scenes, out_path, audio_path, beats_path, card, cues,
                        tuple(video_size) if video_size else (1920, 1080),
                        fps, clip_fps, bars_loop, hold_seconds, duration,
                        preview=preview)


@mcp.tool()
def write_srt(cues: list, out_path: str) -> dict:
    """Write a SubRip sidecar from the same cue list assemble_video burns in.

    ⚠ Do not upload BOTH a burned-in video and this file — players that default
    captions on will draw a second copy over the first.
    """
    return subs.write_srt(cues, out_path)


# --------------------------------------------------------------------------- #
# library
# --------------------------------------------------------------------------- #

@mcp.tool()
def list_shots(project: str | None = None, name: str | None = None) -> dict:
    """Terse listing of takes (id, seed, maxdev, approved, viewable path)."""
    return {"projects": sh.projects(), "shots": sh.listing(project, name)}


@mcp.tool()
def get_shot(shot_id: str) -> dict:
    """One take's full record — every parameter needed to reproduce it."""
    rec = sh.get(shot_id)
    if rec is None:
        raise ValueError(f"No such shot: {shot_id}. Use list_shots.")
    return rec


@mcp.tool()
def approve_shot(shot_id: str, slug: str | None = None) -> dict:
    """Lock a take as this shot's canon, published as FINAL_<slug>.webp.

    Approval is per NAME: a teaser has many approved shots at once, and
    approving a second take of the same name unapproves only the first.
    """
    return sh.approve(shot_id, slug)


@mcp.tool()
def forget_shot(shot_id: str) -> dict:
    """Delete one take. Refuses an approved one."""
    return {"forgotten": sh.forget(shot_id), "shot_id": shot_id}


@mcp.tool()
def forget_rejected(project: str, name: str | None = None) -> dict:
    """Bulk-delete every unapproved take, keeping the canon ones.

    A hunt for eight shots at three seeds leaves ~16 dead takes. Clearing them
    one id at a time never happens, so the library grows until someone deletes
    the folder by hand and takes the approved shots with it.
    """
    return sh.forget_rejected(project, name)


@mcp.tool()
def check_status() -> dict:
    """Is the GPU path usable? Call this first when a generation fails.

    Reports ComfyUI reachability, VRAM, whether city96's ComfyUI-GGUF custom node
    is installed (LTX cannot run without it), which model files each variant is
    missing, and whether an ffmpeg for encoding was found.
    """
    status: dict = {"comfy_url": comfy.COMFY_URL, "comfy_running": comfy.comfy_is_up()}
    try:
        status["ffmpeg"] = asm.find_ffmpeg()
    except FileNotFoundError as e:
        status["ffmpeg"] = None
        status["ffmpeg_hint"] = str(e)
    status["output_root"] = sh.OUTPUT_ROOT

    if not status["comfy_running"]:
        status["hint"] = ("Start ComfyUI (it auto-launches on first generation) — "
                          f"{comfy.COMFY_DIR}\\{comfy.COMFY_LAUNCH}")
        return status

    stats = comfy.system_stats()
    dev = (stats.get("devices") or [{}])[0]
    status["device"] = dev.get("name")
    status["vram_total_gb"] = round(dev.get("vram_total", 0) / 1e9, 2)
    status["comfyui_version"] = stats.get("system", {}).get("comfyui_version")

    try:
        gguf_unets = set(comfy.list_models("unet_gguf"))
        gguf_clips = set(comfy.list_models("clip_gguf"))
        status["comfyui_gguf_installed"] = True
    except comfy.ComfyUIError:
        status["comfyui_gguf_installed"] = False
        status["hint"] = ("city96's ComfyUI-GGUF custom node is NOT installed. Both LTX "
                          "and Kontext load GGUF weights through it; core ComfyUI cannot. "
                          "Install it into custom_nodes and restart.")
        return status

    vae = set(comfy.list_models("vae"))
    variants = {}
    for vname, v in lw.VARIANTS.items():
        missing = [n for n, present in ((v["unet"], gguf_unets),
                                        (v["connector"], gguf_clips),
                                        (v["vae"], vae)) if n not in present]
        if lw.GEMMA not in gguf_clips:
            missing.append(lw.GEMMA)
        variants[vname] = {"ready": not missing, "missing": missing}
    status["ltx_variants"] = variants
    status["kontext_ready"] = kw.UNET in gguf_unets and kw.VAE in vae

    if any(not v["ready"] for v in variants.values()):
        status["hint"] = ("Missing model files. NOTE: ComfyUI caches folder listings at "
                          "startup — if you just downloaded these, restart ComfyUI before "
                          "trusting this list. The text encoder must sit in "
                          "models/text_encoders/, NOT models/checkpoints/.")
    return status


if __name__ == "__main__":
    mcp.run()
