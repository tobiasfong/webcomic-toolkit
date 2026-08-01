"""
make_sketch.py — turn a reference image into a ControlNet-ready sketch
(white lines on black) for use as `sketch_path` in generate_background.

TWO INPUT KINDS, TWO DIFFERENT TREATMENTS — this matters, and getting it wrong
is a real bug with a visible signature:

  • PHOTO / 3D render  -> Canny edge detection.
    An edge here is one boundary between two regions (wall|sky, building|building),
    so Canny returns ONE line per edge. Correct.

  • HAND-DRAWN SKETCH  -> binarize, NOT Canny.
    A pencil stroke is a dark band with TWO sides, so Canny finds both and a
    single drawn line becomes two parallel control edges with a gap between
    them. At any ControlNet strength strong enough to hold a composition the
    model paints those doubled hairlines literally — visible white scratch
    lines over the finished art, plus a desaturated frame. This cost the
    sibling character-panel server six live tests that wrongly blamed the
    ControlNet model (see its tools/sketch_to_lineart.py, 2026-07-27).
    Binarizing to a single solid stroke removes the doubling.

`--mode auto` (the default) picks for you by measuring how much of the image is
paper-white, and prints which branch it took. Override with `--mode photo` or
`--mode drawing` if the guess is wrong.

Usage:
    python make_sketch.py <input_image> [output_path]
        [--mode auto|photo|drawing]
        [--low 80] [--high 180] [--blur 3] [--dilate 0] [--invert]
        [--threshold 215]

Photo knobs: --low/--high tune Canny line density; --dilate bolds the lines.
Drawing knob: --threshold is the paper/stroke cutoff. It defaults to 215, NOT
a conventional 128 — hand sketches are faint and pencil-grey, and 128 drops
most of the drawing. Lower it if strokes are being missed, raise it if paper
grain/shadow is coming through as noise.

NOTE (applies to both modes): ControlNet reproduces only what is actually
drawn. Anything you leave out of the sketch comes out missing or malformed —
that's a property of the input, not a model defect. Draw every element you
want to appear.
"""
import sys
import argparse
import os
import cv2
import numpy as np

# Hand sketches are faint; a conventional 128 drops most of the drawing.
DEFAULT_DRAWING_THRESHOLD = 215
# Above this fraction of near-white pixels, the image is paper with strokes on
# it rather than a photograph.
_PAPER_FRACTION = 0.65


def looks_like_drawing(gray) -> bool:
    """True if the image reads as strokes-on-paper rather than a photo.

    Line art is overwhelmingly background paper; photos and 3D renders spread
    their tones much more widely."""
    return float((gray > 200).mean()) > _PAPER_FRACTION


def binarize_drawing(gray, threshold=DEFAULT_DRAWING_THRESHOLD):
    """Hand-drawn sketch -> single-stroke white-on-black map.

    Everything darker than `threshold` is treated as a stroke and turned
    white; the paper goes black. One stroke stays one line, which is the
    whole point (see module docstring)."""
    _, out = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)
    return out


def canny_edges(gray, low=80, high=180, blur=3):
    """Photo / 3D render -> Canny edge map (white edges on black)."""
    if blur and blur > 0:
        k = blur if blur % 2 == 1 else blur + 1
        gray = cv2.GaussianBlur(gray, (k, k), 0)
    return cv2.Canny(gray, low, high)


def make_sketch(inp, out, low=80, high=180, blur=3, dilate=0, invert=False,
                mode="auto", threshold=DEFAULT_DRAWING_THRESHOLD, verbose=True):
    img = cv2.imread(inp, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"could not read image: {inp}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if mode == "auto":
        chosen = "drawing" if looks_like_drawing(gray) else "photo"
        if verbose:
            print(f"[make_sketch] auto-detected: {chosen}"
                  + (" (binarizing — Canny would double every stroke)"
                     if chosen == "drawing" else " (Canny edges)"))
    elif mode in ("photo", "drawing"):
        chosen = mode
    else:
        raise SystemExit(f"unknown mode '{mode}'; use auto, photo or drawing")

    if chosen == "drawing":
        edges = binarize_drawing(gray, threshold)
    else:
        edges = canny_edges(gray, low, high, blur)

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
    ap.add_argument("--mode", choices=["auto", "photo", "drawing"], default="auto")
    ap.add_argument("--low", type=int, default=80)
    ap.add_argument("--high", type=int, default=180)
    ap.add_argument("--blur", type=int, default=3)
    ap.add_argument("--dilate", type=int, default=0)
    ap.add_argument("--threshold", type=int, default=DEFAULT_DRAWING_THRESHOLD)
    ap.add_argument("--invert", action="store_true")
    a = ap.parse_args()
    out = a.output
    if out is None:
        base = os.path.splitext(os.path.basename(a.input))[0]
        out = os.path.join(os.path.dirname(a.input), f"sketch_{base}.png")
    make_sketch(a.input, out, a.low, a.high, a.blur, a.dilate, a.invert,
                a.mode, a.threshold)
    print(out)
