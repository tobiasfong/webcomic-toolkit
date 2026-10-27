"""
Anime Production — MCP Server
=============================
Turns finished illustrations into an animated, music-cut video, entirely
locally. Closes the loop with music-generation-mcp: that server makes the track,
this one animates the art and cuts to it.

Runs on the same 6 GB RTX 3060 Laptop as the other GPU servers. LTX-2.5 and
Klein both run on the separate v0.41 ComfyUI (port 8189) — see README. LTX-2.3
was removed on 2026-10-22, after the artist judged 2.5 much better.

THE RULE THAT DECIDES WHETHER A SHOT WILL WORK AT ALL, and the reason this
server is shaped the way it is:

    LTX RELOCATES what exists. It cannot RE-IMAGINE it.

  works: arm swings, head turns, hair and cloth, drifting snow, rotating runes,
         fire (existing pixels churning), camera drift
  fails: blinks (the eyelid was never drawn) · mouth shapes (no teeth or tongue
         exist) · growing crystals (new geometry) · foreshortening (a punch
         toward the viewer needs knuckles redrawn at a new angle)
  (That column was measured on LTX-2.3. 2.5 moved it: it threw a punch toward
  the viewer, two people talked, one seed in three blinked, and ice grew from
  a raised hand — judge that as video; still frames hide it.)

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
    along with it. On 2.3 feature-scale motion only arrived as a passenger; on
    2.5 it can lead when DESCRIBED, not named ("her eyes close, then open wide,
    then close again" blinked where "blink" shut the eyes for good).
  * Then run ~3 seeds and keep the best; roughly 1 in 3 lands. Seed variance is
    real, but ONLY when the request is achievable. Re-rolling an impossible ask
    is pure waste.
  * SEEDS DO NOT TRANSFER ACROSS CONFIGS. Change length or prompt and the space
    reshuffles. Re-hunt after any parameter change.
  * RESOLUTION IS THE LEVER FOR HANDS. pick_size aims at ~2 MP from the
    artwork's own shape. 832x576 puts a hand at ~5 latent pixels and cannot
    render one that moves; at that size, one 15-panel scene needed 65 frames
    hand-repaired.
  * NEGATIVE INSTRUCTIONS ARE IGNORED BY BOTH MODELS. "Do not close her eyes"
    closed them; "without turning" turned. Phrase every request positively.
  * Freezing is as useful as animating. If hands go wrong, a `hold` scene that
    plays the motion and rests on the last frame beats another twenty seeds.
"""

from __future__ import annotations

import os
import time

from PIL import Image
from mcp.server.fastmcp import FastMCP

import cloud_video as cv
import comfy
import klein
import ltx_workflow as lw
import shots as sh
from tools import artifacts
from tools import assemble as asm
from tools import effects, framing, motion, subs

BASE = os.path.dirname(os.path.abspath(__file__))

mcp = FastMCP("anime-production")


def _upload_ref25(image_path: str) -> str:
    """Resize to LTX-2.5's reference size and upload to the Klein ComfyUI.

    The template's own resize (longest side to 1536, Lanczos), done here.
    """
    import tempfile
    klein.ensure_running()
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        s = lw.LTX25_REF_LONG_SIDE / max(im.size)
        if s < 1:
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        im.save(tmp)
    try:
        return klein._upload(tmp)
    finally:
        os.remove(tmp)


def _upload_exact(image_path: str, width: int, height: int) -> str:
    """Fit to exactly width x height (cover, centered) and upload to Klein.

    First-and-last-frame pins both pictures at the render size; the template
    resizes them to it with a centered crop, done here in Python.
    """
    import tempfile
    klein.ensure_running()
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        s = max(width / im.width, height / im.height)
        r = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        x, y = (r.width - width) // 2, (r.height - height) // 2
        r = r.crop((x, y, x + width, y + height))
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        r.save(tmp)
    try:
        return klein._upload(tmp)
    finally:
        os.remove(tmp)


def _clear_card(url: str, what: str) -> None:
    """Never put LTX and Klein on the 6 GB card at once — or in RAM at once.

    They live on two ComfyUIs, so neither queue can see the other's job. One
    edit submitted during an LTX batch once thrashed until the job hung and cost
    five hours and two finished takes. So refuse while the other side is busy.

    And when it is idle, unload it: an idle ComfyUI keeps its model in system
    RAM, and LTX streams ~24 GB of weights from there. With Klein resident an
    LTX take started at 3.7 GB free and took 694 s; unloaded, 176 s cold.
    """
    n = klein.busy(url)
    if n:
        raise RuntimeError(
            f"{what} is running on {url} ({n} job(s) in its queue). LTX and Klein "
            f"cannot share the 6 GB card — wait for it to finish, then retry.")
    klein.unload(url)


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #

@mcp.tool()
def animate_shot(project: str, name: str, image_path: str, prompt: str,
                 seeds: list[int] | None = None, length: int = 49,
                 strength: float = 0.7,
                 width: int | None = None, height: int | None = None,
                 fps: float = 24.0,
                 measure_box: list[int] | None = None,
                 view_fps: int = 12,
                 last_frame_path: str | None = None) -> dict:
    """Animate one illustration with LTX-2.5 — THE SEED HUNT, as a single call.

    For each seed: render on the Klein ComfyUI, make a `view_fps` preview (every
    other frame of the 24 fps take, so it plays at true speed on twos), measure
    its motion, and record it. Returns every take, sorted best-first by `maxdev`.

    length: 49 (2 s) or 97 (4 s). NOT 17 — at 17 frames 2.5 has only three
    latent frames: every take sat still to frame 8, lurched at frame 9 and tore
    faces. ~3.5 min a 49-frame take on the 6 GB card at 1920x1088. A 97 is NOT
    twice that: two 97-frame takes at 1920x1088 ran 21 and 23 min (2026-10-25).
    Default to 49 and slow a shot in the edit if it must run longer.

    LEAVE width/height UNSET. They are derived from the artwork by
    `lw.pick_size`, which matches the source's own aspect and then maximizes
    pixels within the card's budget — 1216x832 art becomes 1792x1216, 16:9 art
    becomes 1920x1088. Setting them by hand is how panels ship stretched:
    LTXVImgToVideo resizes the input to whatever it is told, silently, with no
    letterboxing. The chosen size and any warnings come back in `size`.

    Resolution is THE lever for hands — at ~5 latent pixels a moving hand cannot
    be drawn, which cost 65 hand-repaired frames on one scene at 832x576.
    `strength` is the template's stage-1 image strength; stage 2 re-applies the
    image at 1.0.

    `prompt`: lead with the LARGEST motion that reads. Phrase positively —
    negatives are ignored by this model.

    `measure_box` [left, top, right, bottom] restricts scoring to the region that
    is supposed to move. Pass it whenever the motion is smaller than the frame;
    the whole-frame figure cannot resolve anything at feature scale.

    ⚠ THE SCORE IS NOT QUALITY. It measures CHANGE — a take whose faces dissolve
    scores very high. Always look at the retimed clip or a contact_sheet before
    approving. Three seeds is the working default; roughly one lands.

    last_frame_path: the picture the shot should END on — FIRST-AND-LAST-FRAME
    mode. A LAST RESORT, and for KLEIN-GENERATED ART ONLY: after rewording and
    more seeds have failed on an action, render the end pose with Klein
    (edit_frame on the panel, "her leg fully extended in a kick", keeps the
    composition) and the model fills in the motion between the two. Hand-drawn
    art: no one draws extra poses. Make the end pose with a BOXED edit_frame
    first, so only the moving part is redrawn; if that fails, an unboxed
    edit_frame as the last resort — which re-inks the WHOLE drawing in Klein's
    style. No shot ends as a still: a still is a failed shot. Image-to-video
    alone handled a whole hand-drawn teaser, a punch included.
    It must match the panel's shape; both are fitted to the render size. This
    mode renders in ONE stage at full size, so expect it slower than i2v.

    Measured on an 8-scene teaser of hand-drawn panels (2026-10-21): a real
    punch, a waltz turn, a prayer pose, two people talking. Still weak: asked to
    "blink", eyes closed for good on three seeds ("her eyes close, then open
    wide, then close again" worked on one in three); a head drawn in profile
    turned toward the camera until the prompt said it stays in profile.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    seeds = seeds or [1, 2, 3]
    if not 1 <= len(seeds) <= 8:
        raise ValueError("Run 1-8 seeds at a time; ComfyUI is serial and each take costs ~2 min.")

    if width is None or height is None:
        with Image.open(image_path) as im:
            src_w, src_h = im.size
        size = lw.pick_size(src_w, src_h)
        width, height = size["width"], size["height"]
    else:
        size = {"width": width, "height": height, "notes":
                ["size supplied by caller — NOT checked against the artwork's "
                 "aspect; a mismatch is a silent stretch"]}
    lw.validate25(width, height, length)
    if last_frame_path:
        if not os.path.isfile(last_frame_path):
            raise FileNotFoundError(f"End frame not found: {last_frame_path}")
        with Image.open(image_path) as a, Image.open(last_frame_path) as b:
            ra, rb = a.width / a.height, b.width / b.height
        if abs(ra - rb) / ra > 0.02:
            raise ValueError(f"The end frame's shape ({rb:.3f}) does not match the panel's "
                             f"({ra:.3f}); both are fitted to one size, so one would be cropped.")
    # LTX-2.5 lives on the Klein ComfyUI; the main one holds music and matting.
    _clear_card(comfy.COMFY_URL, "A music or matting job")
    if last_frame_path:
        first_up = _upload_exact(image_path, width, height)
        last_up = _upload_exact(last_frame_path, width, height)
    else:
        uploaded = _upload_ref25(image_path)

    results = []
    for seed in seeds:
        shot_id = sh.new_shot_id(name, seed)
        d = sh.shot_dir(project, shot_id)
        params = dict(prompt=prompt, seed=seed, width=width,
                      height=height, length=length, strength=strength, fps=fps)
        if last_frame_path:
            graph = lw.build25_flf(first_up, last_up, prefix=f"anime_{shot_id}", **params)
        else:
            graph = lw.build25(uploaded, prefix=f"anime_{shot_id}", **params)
        os.makedirs(d, exist_ok=True)
        raw = os.path.join(d, f"{shot_id}.webp")
        # An hour, not the usual 30 min: the first take of a session pages
        # ~37 GB of weights through 32 GB of RAM.
        with open(raw, "wb") as f:
            f.write(klein._submit(graph, "41", timeout=3600))
        view = os.path.join(d, f"{shot_id}_{view_fps}fps.webp")
        # A 24 fps take is real-time motion: keep every other frame for 12 fps
        # on twos.
        motion.retime(raw, view, fps=view_fps, step=max(1, round(fps / view_fps)))
        m = motion.measure(view, tuple(measure_box) if measure_box else None)
        sh.record(project, shot_id, name,
                        lw.recipe25(image=os.path.basename(image_path),
                                    last_frame=(os.path.basename(last_frame_path)
                                                if last_frame_path else None), **params),
                        {"webp": raw, "retimed": view},
                        {"maxdev": m["maxdev"], "span": m["span"],
                         "peak_frame": m["peak_frame"], "reading": m["reading"]})
        results.append({"shot_id": shot_id, "seed": seed, "view": view,
                        "maxdev": m["maxdev"], "span": m["span"],
                        "peak_frame": m["peak_frame"], "reading": m["reading"]})

    results.sort(key=lambda r: r["maxdev"], reverse=True)
    return {
        "project": project, "name": name, "size": size, "takes": results,
        "next": ("LOOK at the top take's `view` file (or contact_sheet it) before "
                 "approve_shot. If every seed froze or tore, REWORD first (describe "
                 "what happens rather than naming it) and try more seeds. Still "
                 "failing: a Klein-made end pose with last_frame_path — for "
                 "hand-drawn art a BOXED edit_frame first, the whole panel only "
                 "as the last resort."),
    }


@mcp.tool()
def animate_shot_cloud(project: str, name: str, image_path: str, prompt: str,
                       model: str, takes: int = 1, last_frame_path: str | None = None,
                       duration: int = 5, resolution: str = "720p",
                       max_usd: float | None = None, estimate_only: bool = False,
                       ref_images: list[str] | None = None,
                       measure_box: list[int] | None = None,
                       view_fps: int = 12) -> dict:
    """Animate one illustration on a paid Higgsfield video model — BILLED PER TAKE.

    For the shots LTX cannot do: an action that must actually happen (a full
    kick, a thrust, a sprint) and faces and hands that must survive it.
    Everything else — hair, cloth, small gestures, camera drift — stays on the
    free `animate_shot`.

    model: REQUIRED, so a paid run always names its model — one of
        seedance-2.5, seedance-2.0, kling-3.0-std, kling-3.0-pro, kling-o3,
        kling-o3-ref (cloud_video.MODELS has each one's limits).
    ref_images: the characters' sprites, so the model draws them from their
        own designs, including a character who enters the shot. Only
        kling-o3-ref takes them; any other model refuses rather than drop them.

    ⚠ EACH TAKE IS BILLED, and none of these models takes a seed, so a take
    cannot be reproduced. Defaults to ONE take; at most 3 per call. Higgsfield
    prices the exact request before anything is submitted; `max_usd` refuses
    the run if the total would exceed it, and `estimate_only=True` returns the
    price and spends nothing. Failed and moderated takes are not charged.

    ⚠ The panel (and the end pose, if given) is uploaded to Higgsfield — even
    for estimate_only, since the price is quoted on the real request.

    last_frame_path: the pose the action should END on. Interpolating between
        two drawings is the mode for actions a model refuses — render the end
        pose with Klein, then let this fill in the motion.
    duration: seconds, within the model's range (Seedance 4-15 or 4-30, Kling
        3-15). resolution: Seedance only (480p / 720p / 1080p; 2.0 also 4k);
        Kling's tier is in the model name. The clip follows the panel's framing.

    Takes land in the same shot library as LTX takes, as an mp4 plus a 12 fps
    webp and the last frame as a png, so contact_sheet, approve_shot and
    assemble_video treat them alike. Prompt the same way as for LTX: camera
    first, the motion, then what stays still — but ask for the FULL action;
    that is what is being paid for.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    for p in [last_frame_path] + list(ref_images or []):
        if p and not os.path.isfile(p):
            raise FileNotFoundError(f"Image not found: {p}")
    if not 1 <= takes <= 3:
        raise ValueError("Run 1-3 takes per call; each one is billed.")
    # Everything that can fail locally fails before a byte is uploaded.
    dummy = "https://example.com/panel.png"
    cv.payload(model, prompt, dummy, dummy if last_frame_path else None, duration, resolution,
               [dummy] * len(ref_images or []))
    ffmpeg = asm.find_ffmpeg()

    first_url = cv.upload(image_path)
    last_url = cv.upload(last_frame_path) if last_frame_path else None
    ref_urls = [cv.upload(p) for p in ref_images or []]
    body = cv.payload(model, prompt, first_url, last_url, duration, resolution, ref_urls)
    per_take = cv.estimate_usd(model, body)
    total = round(per_take * takes, 4) if per_take is not None else None
    if estimate_only:
        return {"model": model, "est_usd_per_take": per_take, "est_usd_total": total,
                "takes": takes, "next": "Nothing was generated or billed."}
    if max_usd is not None and (total is None or total > max_usd):
        raise ValueError(f"Estimated ${total} for {takes} take(s) of {model}; over the "
                         f"max_usd of ${max_usd}. Nothing was submitted.")

    results = []
    for take in range(1, takes + 1):
        t0 = time.time()
        handle = cv.submit(model, body)
        rec = cv.wait(handle)
        shot_id = f"{sh.slugify(name)}_{sh.slugify(model)}{take}_{time.strftime('%Y%m%d_%H%M%S')}"
        d = sh.shot_dir(project, shot_id)
        raw = cv.download(rec["video"]["url"], os.path.join(d, f"{shot_id}.mp4"))
        view = os.path.join(d, f"{shot_id}_{view_fps}fps.webp")
        last_png = os.path.join(d, f"{shot_id}_last.png")
        cv.to_view(raw, view, ffmpeg, fps=view_fps, last_png=last_png)
        files = {"mp4": raw, "retimed": view, "last_frame": last_png}
        m = motion.measure(view, tuple(measure_box) if measure_box else None)
        sh.record(project, shot_id, name,
                  {"provider": "higgsfield", "model": model,
                   "endpoint": cv.model_spec(model)["endpoint"],
                   "prompt": prompt, "image": os.path.basename(image_path),
                   "last_frame": os.path.basename(last_frame_path) if last_frame_path else None,
                   "refs": [os.path.basename(p) for p in ref_images or []],
                   "duration": duration, "resolution": body.get("resolution"),
                   "request_id": handle.get("request_id"), "est_usd": per_take},
                  files,
                  {"maxdev": m["maxdev"], "span": m["span"],
                   "peak_frame": m["peak_frame"], "reading": m["reading"]})
        results.append({"shot_id": shot_id, "take": take, "view": view, "mp4": raw,
                        "last_frame": last_png, "est_usd": per_take,
                        "seconds": round(time.time() - t0), "maxdev": m["maxdev"],
                        "reading": m["reading"]})

    return {
        "project": project, "name": name, "model": model, "takes": results,
        "est_usd_total": round(per_take * len(results), 4) if per_take is not None else None,
        "next": ("LOOK at each `view` before approve_shot. The cost is Higgsfield's "
                 "estimate; the console at console.higgsfield.ai has the real bill."),
    }

@mcp.tool()
def edit_shot_cloud(project: str, name: str, clip_path: str, prompt: str, model: str,
                    ref_images: list[str] | None = None, takes: int = 1,
                    resolution: str = "720p", fit: str = "slow",
                    max_usd: float | None = None, estimate_only: bool = False,
                    view_fps: int = 12) -> dict:
    """Redo an existing take on a paid Higgsfield video-edit model — BILLED PER TAKE.

    For an LTX take whose MOTION is right but whose faces or hands smear: the
    model gets the take itself and redraws it, keeping the motion and camera.
    When the motion itself is wrong, animate_shot_cloud from the panel instead.

    model: REQUIRED — seedance-2.5-edit or kling-o3-edit.
    clip_path: the take, at its full frame rate (the shot's own .webp or .mp4,
        not the 12 fps preview), so the model sees every drawing.
    ref_images: the panel the take was made from, and any character sheet, so
        the redrawn faces stay on model (Kling takes 4, Seedance 30).
    fit: LTX takes run ~2 s, under both models' minimum (Kling 3 s, Seedance
        4 s). "slow" sends the same frames at a lower rate; "pad" holds the last
        frame. The result is put back to the take's own length either way.
    resolution: Seedance only.

    ⚠ EACH TAKE IS BILLED, with no seed. One take by default, at most 3.
    Priced by Higgsfield before submitting; max_usd and estimate_only work as
    in animate_shot_cloud. ⚠ The take and the reference images are uploaded.

    Prompt what to KEEP first (the same motion, camera and composition), then
    what to redraw (his face and both hands clear and on model in every frame).
    """
    if not os.path.isfile(clip_path):
        raise FileNotFoundError(f"Clip not found: {clip_path}")
    for r in ref_images or []:
        if not os.path.isfile(r):
            raise FileNotFoundError(f"Image not found: {r}")
    if not 1 <= takes <= 3:
        raise ValueError("Run 1-3 takes per call; each one is billed.")
    # Everything that can fail locally fails before a byte is uploaded.
    dummy = "https://example.com/x"
    cv.edit_payload(model, prompt, dummy, [dummy] * len(ref_images or []), resolution)
    ffmpeg = asm.find_ffmpeg()

    stem = f"{sh.slugify(name)}_{sh.slugify(model)}_{time.strftime('%Y%m%d_%H%M%S')}"
    # The clip as sent lives beside the first take, for comparing the two.
    src = cv.edit_source(clip_path, os.path.join(sh.shot_dir(project, stem + "1"),
                                                 stem + "_sent.mp4"), model, fit)
    video_url = cv.upload(src["mp4"])
    image_urls = [cv.upload(r) for r in ref_images or []]
    body = cv.edit_payload(model, prompt, video_url, image_urls, resolution)
    per_take = cv.estimate_usd(model, body)
    total = round(per_take * takes, 4) if per_take is not None else None
    if estimate_only:
        return {"model": model, "est_usd_per_take": per_take, "est_usd_total": total,
                "takes": takes, "sent": src, "next": "Nothing was generated or billed."}
    if max_usd is not None and (total is None or total > max_usd):
        raise ValueError(f"Estimated ${total} for {takes} take(s) of {model}; over the "
                         f"max_usd of ${max_usd}. Nothing was submitted.")

    results = []
    for take in range(1, takes + 1):
        t0 = time.time()
        handle = cv.submit(model, body)
        rec = cv.wait(handle)
        shot_id = f"{stem}{take}"
        d = sh.shot_dir(project, shot_id)
        raw = cv.download(rec["video"]["url"], os.path.join(d, f"{shot_id}.mp4"))
        view = os.path.join(d, f"{shot_id}_{view_fps}fps.webp")
        last_png = os.path.join(d, f"{shot_id}_last.png")
        cv.to_view(raw, view, ffmpeg, fps=view_fps, last_png=last_png,
                   speed=src["speed"], max_seconds=src["source_seconds"])
        files = {"mp4": raw, "retimed": view, "last_frame": last_png}
        m = motion.measure(view)
        sh.record(project, shot_id, name,
                  {"provider": "higgsfield", "model": model,
                   "endpoint": cv.model_spec(model)["endpoint"], "prompt": prompt,
                   "source_clip": os.path.basename(clip_path), "fit": fit,
                   "sent_seconds": src["sent_seconds"], "speed": src["speed"],
                   "refs": [os.path.basename(r) for r in ref_images or []],
                   "resolution": body.get("resolution"),
                   "request_id": handle.get("request_id"), "est_usd": per_take},
                  files,
                  {"maxdev": m["maxdev"], "span": m["span"],
                   "peak_frame": m["peak_frame"], "reading": m["reading"]})
        results.append({"shot_id": shot_id, "take": take, "view": view, "mp4": raw,
                        "est_usd": per_take, "seconds": round(time.time() - t0),
                        "maxdev": m["maxdev"], "reading": m["reading"]})

    return {
        "project": project, "name": name, "model": model, "takes": results, "sent": src,
        "est_usd_total": round(per_take * len(results), 4) if per_take is not None else None,
        "next": ("LOOK at each `view` beside the source take before approve_shot. The "
                 "cost is Higgsfield's estimate; the console has the real bill."),
    }


@mcp.tool()
def edit_frame(image_path: str, edit: str, out_dir: str,
               seeds: list[int] | None = None, box: list[int] | None = None,
               steps: int = 16) -> dict:
    """Generate a KEYFRAME or repair a frame with FLUX 3 Klein — for what LTX
    cannot animate, and for the hands it breaks.

    A blink is ~0.2% of frame pixels and about four latent pixels wide after the
    VAE's 8x compression; there is nothing there for a video model to move. So
    eye and mouth positions come from generated keyframes played back by a frame
    player, not from video generation.

    Runs on Klein's own ComfyUI (port 8189), started on first use. Refuses while
    the main ComfyUI has a job — the two cannot share the 6 GB card — and
    otherwise unloads the main one's models from RAM first.

    box: [l, t, r, b] of the region to change. Klein is told where to draw AND
        how big — a box sets size as well as place, so fit it to the thing.
        Only the box comes back (`path`); outside it the frame is unchanged.

    ⚠ NEVER SHIP THE FULL FRAME (`full`). Klein redraws the WHOLE frame even for
    a boxed edit — 18.5 of mean change outside the box, measured. Without a
    box, follow with `composite_patch` to bring back only the region that was
    meant to change; for a blink, its `ellipses` take just the eye interiors.

    ⚠ HANDS ARE STILL THE WEAK POINT. On character art, six region repairs gave
    one clean hand. Run three seeds and expect to discard most. Klein has not yet
    been measured on LTX frames — the old Kontext numbers do not carry over.

    Whether Klein can draw a half-lid is untested. Mid positions can always be
    made by compositing with `blend` between 0 and 1.

    Sweep a few seeds and keep the least-drifted, not the most obedient.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    seeds = seeds or [1, 2, 3]
    _clear_card(comfy.COMFY_URL, "An LTX or music job")
    out = [klein.edit(image_path, edit, out_dir, seed, box=box, steps=steps)
           for seed in seeds]
    return {"source": image_path, "edit": edit, "results": out,
            "recipe": klein.recipe(image_path, edit, box=box, steps=steps),
            "next": ("LOOK at each `path` against the original. Only the box came back."
                     if box else
                     "composite_patch each `full` result over the ORIGINAL, region only.")}


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
def cut_frames(clip: str, out_path: str, drop: list[int], fps: int = 12) -> dict:
    """Drop specific frames from a clip and join what remains.

    LTX damage arrives in a WINDOW, not at the tail — measured at 1920x1088,
    length 25 was clean but for frames 18-19 and length 33 clean but for 11-13.
    Truncating from the end throws those takes away; this removes just the bad
    frames. `drop` is indices into the uniform frame grid, matching what you
    counted on a `contact_sheet`.

    ⚠ CHECK THE `seams` REPORT, DO NOT ASSUME THE CUT IS FREE. Each seam's
    `ratio` is the jump at the join against the clip's own median frame-to-frame
    change. Under ~2x it is invisible; above ~4x it reads as a skip. Counter-
    intuitively a SLOW clip is where a cut shows most, because the elision is
    large relative to everything around it: on a real length-33 take, dropping
    3 of 33 frames produced a 5.2x jump and was rejected. A clean shorter take
    beats a longer one with a pop in it.
    """
    if not os.path.isfile(clip):
        raise FileNotFoundError(f"Clip not found: {clip}")
    return motion.cut_frames(clip, out_path, drop, fps=fps)


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

    Anime does not animate the punch traveling; it sells the MOMENT OF CONTACT.
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
    """Glints and expanding rings on water. Ring centers are placed on an eroded,
    color-filtered mask so a ring cannot expand onto the bank or a lily pad."""
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
    """Parallel streaks traveling one way — sells travel across the frame.

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
    pixels, so LTX leaves it static. This keys the lit pixels by color
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
def inspect_moment(clip_path: str, center_s: float, window_s: float = 1.0, slow: int = 4,
                   threshold: float = 0.7) -> dict:
    """Step one of fixing a smear: a slow-motion clip of a ROUGH moment, every frame numbered.

    For when someone has seen a smear but cannot name the frame ("around 0:57"). Cuts
    [center_s - window_s, center_s + window_s] out of a take (12 fps webp) or a finished video (mp4),
    plays it `slow` times slower, and burns each frame's number in large; they read off the bad
    numbers while it plays and pass them to repair_frames. Frames the detector suspects get a red
    border: a HINT. It cannot tell fast motion from damage (measured: a real smear 0.62-0.69, clean
    drawings in the same push-in 0.65-0.75), so it narrows where to look and nothing more. Send the
    clip as video.
    """
    from tools import repair as rp
    return rp.inspect(clip_path, center_s, window_s, slow, threshold=threshold)


@mcp.tool()
def repair_frames(clip_path: str, bad_frames: list[int], mode: str = "hold",
                  out_path: str | None = None) -> dict:
    """Step two: replace the frames someone named from inspect_moment's numbers.

    mode "hold" repeats the nearest clean frame before the run: an ordinary anime hold at 12 fps, but it
    reads as a stutter during a camera move. mode "interp" redraws the run as in-betweens of the clean
    frames on both sides with RIFE (needs WEBCOMIC_ANIME_RIFE pointing at rife-ncnn-vulkan). Exact
    doubles of a bad frame (a 24 fps video's copy of a 12 fps drawing) are replaced too. Writes
    `<name>_repaired` beside the source unless `out_path` is given, never over it; a video keeps its
    audio. Show the result as video before using it.
    """
    from tools import repair as rp
    if mode not in ("hold", "interp"):
        raise ValueError("mode must be 'hold' or 'interp'")
    return rp.repair(clip_path, bad_frames, mode, out_path)


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
    """Composite a clip into a drawn frame's slot, centered in the video canvas.

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

    Everything this server renders — LTX-2.5 and Klein — runs on the separate
    Klein ComfyUI (v0.41, port 8189). Reports whether it is up, which LTX-2.5 and
    Klein model files are missing from it, the paid cloud path's key status,
    and whether an ffmpeg for encoding was found. The main ComfyUI is reported
    only because the server unloads it (music, matting) before rendering.
    """
    status: dict = {"klein": {"url": klein.KLEIN_URL, "running": klein.is_up(),
                              "dir": klein.KLEIN_DIR, "missing": klein.missing_files()}}
    root25 = os.path.join(klein.KLEIN_DIR, "ComfyUI", "models")
    status["ltx25"] = {"missing": [f"{lw.LTX25_FOLDERS[k]}/{n}" for k, n in lw.LTX25.items()
                                   if not os.path.isfile(os.path.join(root25, lw.LTX25_FOLDERS[k], n))]}
    status["main_comfy"] = {"url": comfy.COMFY_URL, "running": comfy.comfy_is_up()}
    status["cloud"] = {"provider": "higgsfield", "models": sorted(cv.MODELS),
                       "key_set": cv.has_key(),
                       "key_env": [cv.KEY_ID_ENV, cv.KEY_SECRET_ENV]}
    try:
        status["ffmpeg"] = asm.find_ffmpeg()
    except FileNotFoundError as e:
        status["ffmpeg"] = None
        status["ffmpeg_hint"] = str(e)
    status["output_root"] = sh.OUTPUT_ROOT
    if status["ltx25"]["missing"] or status["klein"]["missing"]:
        status["hint"] = ("Model files missing from the Klein ComfyUI — see README "
                          "'Models'. ComfyUI caches folder listings at startup, so "
                          "restart it after adding files.")
    return status


if __name__ == "__main__":
    mcp.run()
