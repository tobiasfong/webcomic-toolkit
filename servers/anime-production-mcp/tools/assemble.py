"""
assemble.py — cut finished shots to a track and encode the video.

STRUCTURE COMES FROM THE MUSIC, not from arbitrary durations. Given a beat grid,
each looping panel holds a whole number of bars, so cuts land on downbeats.

NO KEN BURNS. A camera move already in progress makes an animated beat read as
less of an event — which is the whole reason the motion exists. This assembler
deliberately does not pan or zoom the panels.

THE PROBLEM THIS SOLVES: a 1.4 s clip inside a 9.6 s panel leaves 8 s of dead
air, and putting the motion first means every panel DECAYS into stillness. So a
scene declares what KIND of motion it has, and the kind decides the timing:

  loop  — ambient, no natural end (drifting cloth, an argument, falling snow).
          Runs the whole panel; something is always moving, so it can hold.
  pong  — oscillatory (a sway, a drift back and forth). Runs the whole panel,
          played forward-then-back so there is no jump at the seam.
  once  — an event that cannot repeat (an impact; ping-ponging would literally
          un-grow the ice). Lasts EXACTLY as long as its clip. No static hold at
          all: holding a still frame before an event reads, to a viewer who does
          not know an event is coming, as the video having frozen. The stationary
          time is cut and handed to the end card.
  hold  — play the motion once, then FREEZE the last frame. The one case where
          stillness is right, and only AFTER the motion: a hold before movement
          reads as a bug, a hold after it reads as a beat, because the viewer has
          just watched something happen and lingering there is contemplation.

FRAMES ARE PIPED, not written to disk — 2500+ frames of 1920x1080 would be
gigabytes for nothing. They go as PNG over image2pipe, NOT rawvideo: some
bundled ffmpeg builds (Remotion's, notably) are compiled with --disable-demuxers
and an allow-list that excludes the rawvideo demuxer, and the failure is a bare
"Invalid argument" on the pipe.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .motion import expand_frames

KINDS = ("loop", "pong", "once", "hold")


def find_ffmpeg(explicit: str | None = None) -> str:
    for cand in (explicit, os.environ.get("WEBCOMIC_ANIME_FFMPEG"),
                 shutil.which("ffmpeg")):
        if cand and os.path.isfile(cand):
            return cand
        if cand and shutil.which(cand):
            return shutil.which(cand)
    raise FileNotFoundError(
        "No ffmpeg found. Put one on PATH or set WEBCOMIC_ANIME_FFMPEG. "
        "Everything else in this server works without it; only encoding needs it."
    )


def plan(scenes: list[dict], beats: dict | None = None, clip_fps: int = 12,
         bars_loop: int = 6, hold_seconds: float = 4.0,
         default_panel: float = 6.0) -> tuple[list[dict], float]:
    """Lay scenes out on a timeline. Returns (windows, end_of_last_scene).

    Each scene: {"clip": path, "kind": one of KINDS, "name": optional label}.
    With `beats`, a looping panel holds `bars_loop` bars; without one it holds
    `default_panel` seconds.
    """
    if beats:
        bar = 60.0 / beats["bpm"] * 4
        cursor = (beats.get("downbeats") or [0.0])[0]
    else:
        bar = default_panel / bars_loop
        cursor = 0.0

    out = []
    for sc in scenes:
        kind = sc.get("kind", "loop")
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        # expand_frames, NOT read_frames: a clip that expresses holds as frame
        # durations stores fewer frames than it plays, and reading the stored
        # count drops every hold.
        frames = expand_frames(sc["clip"], clip_fps)
        clen = len(frames) / clip_fps
        t0 = cursor
        if kind == "once":
            t1 = t0 + clen
        elif kind == "hold":
            t1 = t0 + clen + hold_seconds
        else:
            t1 = t0 + bars_loop * bar
        out.append({"name": sc.get("name") or os.path.basename(sc["clip"]),
                    "clip": sc["clip"], "kind": kind, "t0": t0, "t1": t1,
                    "clip_seconds": round(clen, 2), "frames": frames})
        cursor = t1
    return out, cursor


def fit(img: Image.Image, size: tuple[int, int], mode: str = "contain",
        background: tuple[int, int, int] = (12, 12, 14)) -> Image.Image:
    """Place a frame on the canvas without distorting it.

    ⚠ A plain resize STRETCHES. Comic panels are drawn at whatever shape the
    page needed — in one scene they ranged from 1216x507 to 704x1216 — so
    resizing each to 16:9 squashes faces on nearly every one. That is the kind
    of damage nobody notices in a still and everybody notices in motion.

    "contain" letterboxes onto `background`; "cover" fills and center-crops.
    """
    W, H = size
    if img.size == (W, H):
        return img
    s = (min(W / img.width, H / img.height) if mode == "contain"
         else max(W / img.width, H / img.height))
    r = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))),
                   Image.LANCZOS)
    if mode == "cover":
        return r.crop(((r.width - W) // 2, (r.height - H) // 2,
                       (r.width - W) // 2 + W, (r.height - H) // 2 + H))
    canvas = Image.new("RGB", (W, H), background)
    canvas.paste(r, ((W - r.width) // 2, (H - r.height) // 2))
    return canvas


def _pick(scene: dict, t: float, clip_fps: int) -> Image.Image:
    """Which frame of a scene's clip is showing at time t."""
    frames = scene["frames"]
    n = len(frames)
    k = int((t - scene["t0"]) * clip_fps)
    if scene["kind"] == "pong":
        m = (2 * n - 2) or 1
        j = k % m
        return frames[j if j < n else m - j]
    if scene["kind"] == "loop":
        return frames[k % n]
    return frames[min(max(k, 0), n - 1)]          # once / hold — play, then freeze


def build_card(spec: dict, duration: float, size=(1920, 1080), fps: int = 24):
    """Yield frames of an end card: images in a row, text beneath, alive.

    spec keys:
      images        [paths] shown side by side (covers, key art)
      frame         optional drawn frame each image sits inside
      columns       [[line, ...], ...] text columns beneath, one per image
      fonts         [path, ...] one per column
      flutter       animate the frame's decoration (see framing.Flutter)
      push          per-image slow scale-up over the card's life, e.g. [0.035, 0.028]
      glow          pulse warm lettering in the upper region of each image
      stagger/fade/lead   text reveal timing, seconds

    WHY IT MOVES. A card that holds for a minute is most of the video. Still, it
    reads as the file having ended. Fluttering decoration and a slow push keep it
    alive without a Ken Burns move over the artwork.
    """
    W, H = size
    imgs = [Image.open(p).convert("RGB") for p in spec["images"]]
    cols = spec.get("columns") or []
    fonts = [ImageFont.truetype(f, spec.get("font_size", 34))
             for f in (spec.get("fonts") or [])]
    stagger = spec.get("stagger", 1.1)
    fade = spec.get("fade", 0.7)
    lead = spec.get("lead", 0.6)
    lh = spec.get("line_height", 46)
    gap = spec.get("gap", 40)
    pad = spec.get("pad", 26)
    lift = spec.get("lift", 0)          # raise the block to clear a caption band

    flutter = None
    frame_img = None
    slot = None
    if spec.get("frame"):
        from .framing import Flutter, measure_slot
        slot = tuple(spec.get("slot") or measure_slot(spec["frame"])["slot"])
        if spec.get("flutter", True):
            flutter = Flutter(spec["frame"], protect=(slot[0], slot[2]))
        else:
            frame_img = Image.open(spec["frame"]).convert("RGBA")

    # Pre-compose each image into the frame's slot once — the artwork does not
    # change over the card's life, only the decoration and the push do.
    backdrops = []
    ref = flutter.frame if flutter else (frame_img if frame_img else None)
    for art in imgs:
        if ref is None:
            backdrops.append(art.convert("RGBA"))
            continue
        sw, sh = slot[2] - slot[0], slot[3] - slot[1]
        s = max((sw + 6) / art.width, (sh + 6) / art.height)
        r = art.resize((round(art.width * s), round(art.height * s)), Image.LANCZOS)
        cx, cy = (r.width - sw - 6) // 2, (r.height - sh - 6) // 2
        bd = Image.new("RGBA", ref.size, (255, 255, 255, 255))
        bd.paste(r.crop((cx, cy, cx + sw + 6, cy + sh + 6)), (slot[0] - 3, slot[1] - 3))
        backdrops.append(bd)

    # The glow mask is keyed ONCE per image, not per frame. The lettering never
    # moves, and rescanning every pixel of every frame dominated the render.
    glow_masks = []
    if spec.get("glow"):
        for bd in backdrops:
            reg = bd.convert("RGB").crop((0, 0, bd.width, round(bd.height * 0.34)))
            px = reg.load()
            m = Image.new("L", reg.size, 0)
            mp = m.load()
            for yy in range(reg.height):
                for xx in range(reg.width):
                    r_, g_, b_ = px[xx, yy]
                    if r_ > 110 and r_ > g_ + 45 and r_ > b_ + 45:
                        mp[xx, yy] = 255
            glow_masks.append(m.filter(ImageFilter.GaussianBlur(9)))

    pw = spec.get("panel_width", round((W - gap * (len(imgs) + 1)) / max(1, len(imgs))))
    ph = round(pw * backdrops[0].height / backdrops[0].width)
    rows = max((len(c) for c in cols), default=0)
    blk = ph + pad + lh * rows
    y0 = (H - blk) // 2 - lift
    x0 = (W - (pw * len(imgs) + gap * (len(imgs) - 1))) // 2
    push = spec.get("push") or [0.0] * len(imgs)

    n = int(duration * fps) + fps            # slack, so the caller can never run it dry
    for i in range(n):
        t = min(i / fps, duration)
        deco = flutter.render(t) if flutter else frame_img
        canvas = Image.new("RGB", (W, H), (255, 255, 255))
        g = 0.5 + 0.5 * math.sin(2 * math.pi * t / spec.get("glow_period", 6.0))

        for pi, bd in enumerate(backdrops):
            panel = Image.alpha_composite(bd, deco).convert("RGB") if deco is not None \
                else bd.convert("RGB")
            if glow_masks and g > 0.02:
                gm = glow_masks[pi]
                reg = panel.crop((0, 0, panel.width, gm.height))
                tint = Image.new("RGB", reg.size,
                                 (int(78 * g), int(20 * g), int(26 * g)))
                panel.paste(ImageChops.screen(reg, Image.composite(
                    tint, Image.new("RGB", reg.size, (0, 0, 0)), gm)), (0, 0))
            k = 1.0 + (push[pi] if pi < len(push) else 0.0) * (t / max(duration, 1e-6))
            w2, h2 = round(pw * k), round(ph * k)
            canvas.paste(panel.resize((w2, h2), Image.LANCZOS),
                         (x0 + pi * (pw + gap) + (pw - w2) // 2, y0 + (ph - h2) // 2))

        d = ImageDraw.Draw(canvas)
        cy = y0 + ph + pad
        for ci, lines in enumerate(cols):
            font = fonts[ci] if ci < len(fonts) else (fonts[0] if fonts else None)
            cx = x0 + ci * (pw + gap) + pw // 2
            for li, text in enumerate(lines):
                idx = li * len(cols) + ci          # interleave, so columns reveal together
                al = min(1.0, max(0.0, (t - lead - idx * stagger) / fade))
                if al <= 0.01:
                    continue
                v = int(35 + (1 - al) * 220)
                tw = d.textbbox((0, 0), text, font=font)[2]
                d.text((cx - tw // 2, cy + li * lh), text, font=font, fill=(v, v, v))
        yield canvas


def assemble(scenes: list[dict], out: str, audio: str | None = None,
             beats_path: str | None = None, card: dict | None = None,
             cues: list | None = None, size=(1920, 1080), fps: int = 24,
             clip_fps: int = 12, bars_loop: int = 6, hold_seconds: float = 4.0,
             duration: float | None = None, ffmpeg: str | None = None,
             crf: int = 18, preview: float = 0.0, fit_mode: str = "contain",
             shortest: bool = True,
             background: tuple = (12, 12, 14)) -> dict:
    """Encode the whole video. Blocking; minutes for a two-minute piece."""
    exe = find_ffmpeg(ffmpeg)
    beats = None
    if beats_path:
        with open(beats_path, encoding="utf-8") as f:
            beats = json.load(f)

    windows, card_start = plan(scenes, beats, clip_fps, bars_loop, hold_seconds)
    total = duration or (beats or {}).get("duration") or card_start
    if preview:
        total = min(preview, total)
    nframes = int(total * fps)

    subs = None
    if cues:
        from .subs import Subtitles
        subs = Subtitles(cues, size=size)

    card_gen = None
    if card and card_start < total:
        card_gen = build_card(card, total - card_start, size, fps)

    cmd = [exe, "-y", "-f", "image2pipe", "-vcodec", "png", "-r", str(fps), "-i", "-"]
    if audio:
        # `-shortest` truncates the VIDEO to the audio. That is wrong whenever the
        # music was written against the cut: the composer scored to specific panel
        # timings, so shortening the video moves every beat. Pass shortest=False to
        # keep the full picture and let a slightly shorter track end early.
        cmd += ["-i", audio, "-c:a", "aac", "-b:a", "192k"]
        if shortest:
            cmd += ["-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p", out]

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    log_path = os.path.splitext(out)[0] + ".ffmpeg.log"
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            for i in range(nframes):
                t = i / fps
                sc = next((s for s in windows if s["t0"] <= t < s["t1"]), None)
                if sc is not None:
                    img = fit(_pick(sc, t, clip_fps), tuple(size),
                              sc.get("fit", fit_mode), background)
                elif card_gen is not None:
                    img = next(card_gen)
                else:
                    img = Image.new("RGB", size, background)
                if subs is not None:
                    img = subs.draw(img, t)
                img.save(proc.stdin, format="PNG", compress_level=1)
        finally:
            proc.stdin.close()
            rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed (exit {rc}) — see {log_path}")

    return {
        "path": out,
        "seconds": round(total, 2),
        "frames": nframes,
        "size": list(size),
        "fps": fps,
        "mb": round(os.path.getsize(out) / 1e6, 1),
        "timeline": [{"name": w["name"], "kind": w["kind"],
                      "t0": round(w["t0"], 2), "t1": round(w["t1"], 2)}
                     for w in windows]
                    + ([{"name": "card", "kind": "card",
                         "t0": round(card_start, 2), "t1": round(total, 2)}]
                       if card_gen else []),
        "log": log_path,
    }
