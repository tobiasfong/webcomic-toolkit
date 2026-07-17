"""
make_sketch.py — turn an environment reference photo into a ControlNet-ready
sketch (white lines on black) for use as `sketch_path` in generate_background.

Usage:
    python make_sketch.py <input_image> [output_path]
        [--low 80] [--high 180] [--blur 3] [--dilate 0] [--invert]

Defaults produce a Canny edge map: thin white lines on a black background,
which is what the MCP tool's ControlNet expects. Tune --low/--high for more
or fewer lines; --dilate makes lines bolder (better for scribble-style models).
"""
import sys
import argparse
import os
import cv2
import numpy as np


def make_sketch(inp, out, low=80, high=180, blur=3, dilate=0, invert=False):
    img = cv2.imread(inp, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"could not read image: {inp}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if blur and blur > 0:
        k = blur if blur % 2 == 1 else blur + 1
        gray = cv2.GaussianBlur(gray, (k, k), 0)
    edges = cv2.Canny(gray, low, high)  # white edges (255) on black (0)
    if dilate and dilate > 0:
        kernel = np.ones((dilate, dilate), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
    if invert:
        edges = 255 - edges
    cv2.imwrite(out, edges)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output", nargs="?", default=None)
    ap.add_argument("--low", type=int, default=80)
    ap.add_argument("--high", type=int, default=180)
    ap.add_argument("--blur", type=int, default=3)
    ap.add_argument("--dilate", type=int, default=0)
    ap.add_argument("--invert", action="store_true")
    a = ap.parse_args()
    out = a.output
    if out is None:
        base = os.path.splitext(os.path.basename(a.input))[0]
        out = os.path.join(os.path.dirname(a.input), f"sketch_{base}.png")
    make_sketch(a.input, out, a.low, a.high, a.blur, a.dilate, a.invert)
    print(out)
