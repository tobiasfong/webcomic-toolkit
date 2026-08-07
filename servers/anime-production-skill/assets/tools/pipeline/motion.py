"""
motion.py — retime a generated clip, and quantify how much it actually moves.

Two jobs that always run together, because judging an LTX take wrong is the
single most repeatable mistake in this pipeline.

RETIMING IS NOT COSMETIC. ComfyUI writes at 24 fps, so a 17-frame take plays in
0.7 seconds and reads as "nothing happened" even when the motion is fine. Every
take is retimed to 12 fps — the limited-animation rate this pipeline works in —
before anyone, human or model, looks at it.

⚠ THE MOTION NUMBER IS NOT QUALITY. It measures CHANGE. A take whose faces
dissolve into smears scores very high. A high score means "something happened",
never "it looks good".

⚠⚠ THE WHOLE-FRAME NUMBER CANNOT SEE SMALL FEATURES. Two eyes are ~0.2% of a
1024x768 frame, so a perfect blink moves the whole-frame mean by ~0.2 — an order
of magnitude BELOW the ~2.0 floor of a completely static clip. Judging a blink
or a mouth by the whole-frame figure is meaningless; pass a `box`.

⚠⚠⚠ `span` CANNOT SEE ROUND TRIPS. A blink returns to open, so frame0-vs-frameN
lands back near zero. `maxdev` — the largest deviation of ANY frame from frame 0
— is the statistic that sees it, and WHERE it peaks is the tell: a real round
trip peaks mid-clip, monotonic drift peaks at the last frame.
"""

from __future__ import annotations

import os

from PIL import Image, ImageChops, ImageSequence, ImageStat


def read_frames(path: str, mode: str = "RGB") -> list[Image.Image]:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Clip not found: {path}")
    return [f.convert(mode) for f in ImageSequence.Iterator(Image.open(path))]


def expand_frames(path: str, fps: int = 12, mode: str = "RGB") -> list[Image.Image]:
    """Frames on a UNIFORM `fps` grid, honouring each stored frame's duration.

    `read_frames` returns what is STORED, which is not the timeline when a clip
    uses durations to express holds (see build_sequence). A 13-frame file whose
    holds sum to 23 frames must play as 23, or every hold silently vanishes and
    the clip runs short.

    Falls back to one-frame-per-stored-frame when a file carries no duration
    metadata, which is the case for a plain uniform clip — so this is safe to
    use everywhere in place of read_frames.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Clip not found: {path}")
    per = 1000.0 / fps
    out = []
    for f in ImageSequence.Iterator(Image.open(path)):
        img = f.convert(mode)
        d = f.info.get("duration") or 0
        out.extend([img] * max(1, int(round(d / per)) if d else 1))
    return out


def _dedupe_guard(frames: list[Image.Image]) -> list[Image.Image]:
    """Nudge byte-identical consecutive frames apart by one pixel value.

    Pillow's animated-WebP writer DROPS identical consecutive frames. On a clip
    that holds still between two events this silently collapses the timeline —
    a 72-frame authored sequence stored as 23 played 2.7x too fast, and the
    symptom looks like a retiming bug rather than a writer bug. Perturbing one
    corner pixel by 1/255 is invisible and defeats the optimisation.
    """
    out = [frames[0]]
    for f in frames[1:]:
        if f.tobytes() == out[-1].tobytes():
            f = f.copy()
            px = f.load()
            r, g, b = px[0, 0][:3]
            px[0, 0] = ((r + 1) % 256, g, b)
        out.append(f)
    return out


def retime(src: str, dst: str, fps: int = 12, pingpong: bool = False,
           hold_ms: int = 0) -> dict:
    """Re-save a clip at a watchable frame rate.

    pingpong plays forward then backward — the honest way to judge subtle motion,
    and the right playback mode for genuinely oscillatory movement (a sway, a
    drift) because it has no seam.
    """
    frames = read_frames(src)
    if not frames:
        raise ValueError(f"No frames in {src}")
    if pingpong and len(frames) > 1:
        frames = frames + frames[::-1][1:]
    frames = _dedupe_guard(frames)

    durations = [int(round(1000 / fps))] * len(frames)
    if hold_ms:
        durations[-1] += hold_ms

    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    frames[0].save(dst, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, quality=90)
    return {"path": dst, "frames": len(frames), "fps": fps,
            "seconds": round(len(frames) / fps, 2),
            "kb": os.path.getsize(dst) // 1024}


def build_sequence(steps: list, dst: str, fps: int = 12) -> dict:
    """Write a clip from (image, hold_in_frames) pairs, using real durations.

    ⚠ DO NOT BUILD HOLDS BY REPEATING FRAMES. Repeating an image and relying on
    `_dedupe_guard` is not enough: the guard perturbs one pixel by 1/255, and a
    LOSSY WebP encode quantises that straight back out, so libwebp merges the
    frames anyway. Measured on a 23-frame build that came back as 13.

    Expressing a hold as a DURATION is unambiguous, cannot be merged away, and
    produces a much smaller file. `steps` is [(PIL image, frames_to_hold), ...].
    """
    if not steps:
        raise ValueError("build_sequence needs at least one step")
    per = 1000.0 / fps
    imgs = [s[0].convert("RGB") for s in steps]
    durs = [max(1, int(round(per * max(1, int(s[1]))))) for s in steps]
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    imgs[0].save(dst, save_all=True, append_images=imgs[1:],
                 duration=durs, loop=0, quality=90)
    total = sum(durs)
    return {"path": dst, "stored_frames": len(imgs),
            "timeline_frames": sum(max(1, int(s[1])) for s in steps),
            "seconds": round(total / 1000.0, 2), "fps": fps,
            "kb": os.path.getsize(dst) // 1024}


def _mad(a: Image.Image, b: Image.Image) -> float:
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def measure(path: str, box: tuple[int, int, int, int] | None = None) -> dict:
    """Motion statistics for one clip.

    `box` (left, top, right, bottom) restricts measurement to a region — REQUIRED
    for anything at eye or mouth scale.

    Compare the SAME region across takes, never different regions: mean-abs-diff
    scales with local contrast, so a dark background and high-contrast linework
    give different numbers under identical drift. And use an unmoved region as a
    control — if the arm scores 17 and the face scores 2, that is real localised
    motion; if both move, it is global drift.
    """
    grey = read_frames(path, "L")
    n = len(grey)
    if n < 2:
        raise ValueError(f"{os.path.basename(path)}: only {n} frame(s) — nothing to compare")

    full_w, full_h = grey[0].size
    region = "whole frame"
    if box:
        grey = [g.crop(box) for g in grey]
        pct = (box[2] - box[0]) * (box[3] - box[1]) / (full_w * full_h) * 100
        region = f"box {tuple(box)} = {pct:.2f}% of frame"

    consec = [_mad(grey[i], grey[i + 1]) for i in range(n - 1)]
    dev = [_mad(grey[0], g) for g in grey]
    mx = max(dev)
    mxi = dev.index(mx)

    return {
        "clip": os.path.basename(path),
        "size": [full_w, full_h],
        "frames": n,
        "region": region,
        "span": round(_mad(grey[0], grey[-1]), 2),
        "maxdev": round(mx, 2),
        "peak_frame": mxi,
        "peak_consecutive": round(max(consec), 2),
        "per_frame": [round(c, 2) for c in consec],
        # The interpretation, stated rather than left to be re-derived. A round
        # trip that peaks mid-clip is a gesture; a peak at the last frame is
        # drift, which on a "she blinks" ask means the blink did not happen.
        "reading": ("mid-clip peak: consistent with a round trip (blink, gesture, sway)"
                    if 0 < mxi < n - 1 else
                    "peak at the last frame: monotonic drift, not a round trip"),
        "caveat": "Measures CHANGE, not quality. A take whose faces smear scores high. Look at it.",
    }


def dump_frames(path: str, out_dir: str) -> dict:
    """Write per-frame PNGs at native resolution, so the number can be checked
    against what the eye sees. This is not optional diligence — it is how the
    metric gets caught lying."""
    frames = read_frames(path)
    os.makedirs(out_dir, exist_ok=True)
    for i, f in enumerate(frames):
        f.save(os.path.join(out_dir, f"f{i:02d}.png"))
    return {"dir": out_dir, "frames": len(frames)}


def contact_sheet(path: str, dst: str, cols: int = 4, scale: float = 0.5,
                  box: tuple[int, int, int, int] | None = None) -> dict:
    """Tile a clip's frames into one image — the fastest way to actually LOOK.

    Cropping to `box` at native resolution beats scaling the whole frame down:
    the thing under judgement is usually a hand or a pair of eyes, and those
    vanish in a shrunken full frame.
    """
    frames = read_frames(path)
    if box:
        frames = [f.crop(box) for f in frames]
    if scale != 1.0:
        frames = [f.resize((max(1, int(f.width * scale)), max(1, int(f.height * scale))),
                           Image.LANCZOS) for f in frames]
    w, h = frames[0].size
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, h * rows), (20, 20, 20))
    for i, f in enumerate(frames):
        sheet.paste(f, ((i % cols) * w, (i // cols) * h))
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    sheet.save(dst)
    return {"path": dst, "frames": len(frames), "cols": cols,
            "layout": "left-to-right, top-to-bottom"}
