"""
artifacts.py — detect where a generated clip starts to fall apart.

THE PROBLEM THIS SOLVES. `motion.measure` reports CHANGE, and cannot tell a
gesture from a face dissolving — in testing, the take that scored HIGHEST
(maxdev 97.75) was the one whose eyes and glasses melted into pulp, while the
usable take scored 26. Every judgement therefore needed a human to look.

THE SIGNAL. Cel-shaded artwork is defined by its linework. When LTX loses a
region it does not replace the lines with different lines — it BLURS them away.
So total edge energy (mean gradient magnitude) is roughly flat across a clean
take, and DECLINES on a degrading one. Blobbed fingers, smeared faces and
dissolving glasses all show up as a drop.

WHAT IT IS NOT. This does not understand anatomy. A hand can be well-drawn and
anatomically wrong, and this will call it clean. It detects LOSS OF DETAIL,
which is the specific failure LTX has on this art. Treat a pass as "no smearing
detected", never as "this looks good".

Legitimate motion blur also lowers edge energy, so the threshold is deliberately
loose and the per-frame curve is always returned — a gentle dip during fast
movement reads very differently from a monotonic slide to 0.6.
"""

from __future__ import annotations

import numpy as np

from .motion import read_frames


def _edge_energy(img, box=None) -> float:
    """Mean gradient magnitude — a proxy for how much linework survives."""
    a = img.convert("L")
    if box:
        a = a.crop(box)
    arr = np.asarray(a, dtype=np.float32)
    if arr.size == 0:
        return 0.0
    gy, gx = np.gradient(arr)
    return float(np.hypot(gx, gy).mean())


def scan(clip_path: str, box: list[int] | None = None,
         threshold: float = 0.85, run: int = 2) -> dict:
    """Per-frame linework retention, and the last frame before it collapses.

    `threshold` is the fraction of frame 0's edge energy below which a frame is
    called degraded. 0.85 is loose on purpose — real motion blur costs some
    edge energy legitimately.

    `run` is how many CONSECUTIVE degraded frames must appear before the clip is
    called broken from that point. One dipped frame mid-movement is normal; two
    in a row is a slide.

    `last_clean` is the actionable number: truncate there and the surviving clip
    has no visible smearing. That is exactly how the reference panel was
    salvaged — cut before the fingers blobbed, then rest on the clean frame.
    """
    frames = read_frames(clip_path)
    if len(frames) < 2:
        raise ValueError(f"{clip_path}: needs at least 2 frames")

    box = tuple(box) if box else None
    energies = [_edge_energy(f, box) for f in frames]
    base = energies[0] or 1e-6
    ratio = [e / base for e in energies]

    # Judge against the RUNNING PEAK, not only frame 0. When new content moves
    # into the measured region (a book rising into the crop brings its own
    # linework), total edge energy can climb even while a sub-region is
    # dissolving — measured at 1.10 on a take whose fingers were already
    # merging. Falling away from the peak catches that; falling below frame 0
    # alone does not.
    peak = []
    p = ratio[0]
    for r in ratio:
        p = max(p, r)
        peak.append(p)
    rel = [r / pk for r, pk in zip(ratio, peak)]

    bad = [i for i, v in enumerate(rel) if v < threshold]
    last_clean = len(frames) - 1
    streak = 0
    for i in range(1, len(frames)):
        if rel[i] < threshold:
            streak += 1
            if streak >= run:
                last_clean = i - streak
                break
        else:
            streak = 0

    worst = int(np.argmin(ratio))
    return {
        "clip": clip_path.rsplit("\\", 1)[-1],
        "frames": len(frames),
        "region": f"box {box}" if box else "whole frame",
        "retention": [round(r, 3) for r in ratio],
        "vs_peak": [round(v, 3) for v in rel],
        "min_retention": round(min(ratio), 3),
        "min_vs_peak": round(min(rel), 3),
        "worst_frame": worst,
        "degraded_frames": bad,
        "last_clean": last_clean,
        "clean": last_clean >= len(frames) - 1,
        "verdict": ("no detail loss detected across the clip"
                    if last_clean >= len(frames) - 1 else
                    f"linework collapses from frame {last_clean + 1}; "
                    f"truncate at {last_clean}"),
        "caveat": ("Detects LOSS OF DETAIL, not anatomy. A cleanly drawn but wrong "
                   "hand passes. Never read a pass as 'looks good'."),
    }


def scan_grid(clip_path: str, cols: int = 4, rows: int = 3,
              threshold: float = 0.85, run: int = 2) -> dict:
    """Scan a grid of tiles and report the WORST one.

    Why this exists: a whole-frame scan is too coarse to judge a face. A head is
    roughly a tenth of a wide panel, so a face dissolving completely moved the
    whole-frame figure only from 1.00 to 0.87 — inside the tolerance a clean
    take needs. Measured on a take whose eyes and glasses melted into pulp.

    Tiling localises it without needing to know where anything is: whatever
    region collapses, some tile is mostly that region, and that tile's retention
    falls off a cliff. The cost is one extra pass over the frames.

    ⚠ USE THIS TO RANK AND TO AIM, NOT TO AUTO-TRUNCATE. A tile also loses edge
    energy when the subject simply MOVES OUT of it, which is ordinary motion,
    not damage. On the melting-face take this reported a collapse from frame 2
    while the face visibly held to frame 8 — the head descending out of a tile
    tripped it. `scan` on a region you chose is the number to cut on; this is
    the number that tells you a take is worth looking at, and `worst_tile` is
    where to point a contact_sheet.
    """
    frames = read_frames(clip_path)
    W, H = frames[0].size
    tw, th = W // cols, H // rows
    worst = None
    tiles = []
    for r in range(rows):
        for c in range(cols):
            box = (c * tw, r * th,
                   (c + 1) * tw if c < cols - 1 else W,
                   (r + 1) * th if r < rows - 1 else H)
            s = scan(clip_path, list(box), threshold, run)
            entry = {"tile": [c, r], "box": list(box),
                     "last_clean": s["last_clean"],
                     "min_vs_peak": s["min_vs_peak"], "clean": s["clean"]}
            tiles.append(entry)
            if worst is None or (entry["last_clean"], entry["min_vs_peak"]) < \
                    (worst["last_clean"], worst["min_vs_peak"]):
                worst = entry
    n = len(frames)
    return {
        "clip": clip_path.rsplit("\\", 1)[-1],
        "frames": n,
        "grid": [cols, rows],
        "worst_tile": worst,
        "last_clean": worst["last_clean"],
        "clean": worst["last_clean"] >= n - 1,
        "tiles": tiles,
        "verdict": ("no tile loses detail"
                    if worst["last_clean"] >= n - 1 else
                    f"tile {worst['tile']} collapses from frame "
                    f"{worst['last_clean'] + 1} (min {worst['min_vs_peak']}); "
                    f"truncate at {worst['last_clean']}"),
    }


def face_box(clip_path: str, upper: float = 0.7, pad: int = 22) -> list[int] | None:
    """Guess where the faces are, from skin tone on frame 0.

    Faces are what a viewer watches and what LTX damages most visibly, but they
    are a small fraction of a panel — a head is about a tenth of a wide frame,
    so whole-frame scanning cannot see one dissolve. Scanning a face box catches
    it; the problem is knowing where the face is without being told.

    Skin is a usable proxy on cel art: warm, bright, red above blue, and quite
    unlike foliage, cloth or sky. Restricted to the upper part of the frame,
    because hands and bare legs are skin too and would drag the box downward.

    Returns None when nothing skin-like is found — a boots-only panel, say — and
    the caller should fall back to the whole frame rather than trust a guess.
    """
    import numpy as np

    frames = read_frames(clip_path)
    a = np.asarray(frames[0], dtype=np.int16)
    H, W, _ = a.shape
    skin = ((a[:, :, 0] > 170) & (a[:, :, 0] > a[:, :, 2] + 18) &
            (a[:, :, 1] > 130) & (a[:, :, 1] < a[:, :, 0]))
    skin[int(H * upper):, :] = False
    if skin.sum() < (W * H) * 0.0015:
        return None
    ys, xs = np.where(skin)
    # median-centred window rather than the raw bbox: a stray warm pixel in the
    # background would otherwise stretch the box across the whole panel
    cx, cy = int(np.median(xs)), int(np.median(ys))
    rx = int(max(np.percentile(xs, 85) - cx, cx - np.percentile(xs, 15))) + pad
    ry = int(max(np.percentile(ys, 85) - cy, cy - np.percentile(ys, 15))) + pad
    return [max(0, cx - rx), max(0, cy - ry), min(W, cx + rx), min(H, cy + ry)]


def rank(clips: list[str], box: list[int] | None = None,
         threshold: float = 0.85) -> dict:
    """Scan several takes of the same shot and order them by usable length.

    The seed hunt produces takes whose motion scores say nothing about whether
    they hold together. This sorts by how many frames survive, then by how much
    linework is retained — so the winner is the longest clean take, not the one
    that moved most while falling apart.
    """
    rows = []
    for c in clips:
        try:
            s = scan(c, box, threshold)
        except Exception as e:
            rows.append({"clip": c, "error": str(e)})
            continue
        rows.append({
            "clip": c,
            "usable_frames": s["last_clean"] + 1,
            "total_frames": s["frames"],
            "min_retention": s["min_retention"],
            "clean": s["clean"],
            "last_clean": s["last_clean"],
        })
    ok = [r for r in rows if "error" not in r]
    ok.sort(key=lambda r: (r["usable_frames"], r["min_retention"]), reverse=True)
    return {"ranked": ok + [r for r in rows if "error" in r],
            "best": ok[0]["clip"] if ok else None}
