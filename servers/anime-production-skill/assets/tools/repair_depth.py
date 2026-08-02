"""
repair_depth.py — fix monocular-depth artefacts before 3D displacement.

Monocular depth estimators (MiDaS / Depth Anything) fail in a specific way on
anime line art: dark, flat regions *inside* a figure — a shadowed face in
profile, the background showing between hair strands — get read as far away.
The result is a hole punched through the character.

A 2D pixel-shift parallax barely shows this. Displacing real geometry makes the
hole physical, and the face tears apart. So repair the map first.

⚠ DO NOT use this to "rescue" a character close-up. Measured 2026-08-02: on a
profile face the closing dilates near-depth OUTWARD across the silhouette, so
the face plane extends past the drawn edge and the mesh drags the nose, lips and
chin into the background — worse than the original hole. A character's profile
is a depth cliff and its features sit on it; no repair or strength value fixes
that. This tool is for ENVIRONMENT plates (landscapes, architecture, water),
where depth is continuous and there is no face to deform.

  1. grayscale morphological CLOSE — fills dark holes smaller than the kernel
     without brightening genuinely distant areas (sky stays sky)
  2. edge-preserving smooth — kills the stair-stepping that makes silhouettes
     stretch, while keeping the figure/background boundary crisp

Usage:
  python repair_depth.py <depth.png> [-o out.png] [--close 61] [--smooth 9]
                         [--compare]
"""
import argparse
import os

import cv2
import numpy as np


def repair(depth, close_k=61, smooth=9):
    if depth.ndim == 3:
        depth = cv2.cvtColor(depth, cv2.COLOR_BGR2GRAY)

    # 1. fill dark holes inside brighter regions (the face-shaped bite)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
    closed = cv2.morphologyEx(depth, cv2.MORPH_CLOSE, k)

    # 2. edge-preserving smooth: flatten interior noise, keep silhouettes sharp.
    #    A plain blur would round the silhouette and smear the figure into the
    #    background — exactly the stretching we are trying to avoid.
    if smooth > 0:
        closed = cv2.bilateralFilter(closed, d=smooth, sigmaColor=40, sigmaSpace=smooth * 2)
    return closed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("depth")
    ap.add_argument("-o", "--out")
    ap.add_argument("--close", type=int, default=61,
                    help="hole-filling kernel; must exceed the widest bad hole")
    ap.add_argument("--smooth", type=int, default=9)
    ap.add_argument("--compare", action="store_true",
                    help="also write a before/after strip for review")
    a = ap.parse_args()

    src = cv2.imread(a.depth, cv2.IMREAD_UNCHANGED)
    if src is None:
        raise SystemExit(f"cannot read {a.depth}")
    if src.ndim == 3:
        src = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)

    out = repair(src, a.close, a.smooth)
    dst = a.out or os.path.splitext(a.depth)[0] + "_repaired.png"
    cv2.imwrite(dst, out)

    changed = float(np.mean(np.abs(out.astype(np.int16) - src.astype(np.int16))))
    print(f"wrote {dst}")
    print(f"  mean abs change: {changed:.2f}/255  (0 = nothing filled)")

    if a.compare:
        strip = np.hstack([src, out])
        cmp_path = os.path.splitext(dst)[0] + "_compare.png"
        cv2.imwrite(cmp_path, strip)
        print(f"  comparison: {cmp_path}")


if __name__ == "__main__":
    main()
