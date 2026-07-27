"""sketch_to_lineart.py — turn a hand-drawn sketch into a ControlNet lineart map.

Why this exists: feeding a pencil sketch to ControlNet via CannyEdgePreprocessor
produces visible white scratch lines composited over the finished art, plus a
badly desaturated frame. The cause is that Canny detects *both* edges of every
drawn stroke — a 2px pencil line becomes two parallel control edges with a gap
between them, and at any ControlNet strength high enough to hold a composition
the model renders those doubled hairlines literally instead of interpreting
them. Six live tests varying strength, preprocessor and model all showed the
same signature; swapping the ControlNet model did not fix it.

Binarizing to a single-stroke white-on-black map and feeding it DIRECTLY (with
pose_preprocess=False) removes the doubling, and with it most of the bleed.

Validated settings for the result of this script, on Union Pro 2.0:

    pose_control_type="canny_auto"   # Pro 2.0 has no per-type embedding
    pose_preprocess=False            # already an edge map, do not re-detect
    pose_strength=0.65
    pose_end_percent=0.80

Higher strengths (0.80) do reproduce the drawn composition faithfully but smear
and desaturate the art; lower (0.40-0.50) render cleanly but ignore the pose.

NOTE: ControlNet reproduces only what is actually drawn. Limbs left out of the
sketch come out missing or as empty sleeves — this is a property of the input,
not a model defect. Draw every limb you want to appear.

Usage:
    python sketch_to_lineart.py sketch.png [--out lineart.png] [--threshold 215]
"""
import os
import argparse


def sketch_to_lineart(path, out=None, threshold=215):
    """Binarize a dark-on-light sketch into a white-on-black lineart map.

    threshold is a luminance cutoff on 0-255: anything darker counts as a
    stroke. The default is deliberately high (215, i.e. only just below paper
    white) because hand sketches are often very faint grey — a conventional
    128 drops most of the drawing.
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        raise SystemExit(
            "sketch_to_lineart needs Pillow and numpy: "
            "<venv>/python -m pip install pillow numpy")

    if not os.path.isfile(path):
        raise SystemExit(f"could not read sketch: {path}")

    arr = np.array(Image.open(path).convert("L"))
    mask = arr < threshold
    if not mask.any():
        raise SystemExit(
            f"no strokes found below threshold={threshold} — the sketch may be "
            f"blank, or already inverted (white lines on black).")
    coverage = mask.sum() / mask.size
    if coverage > 0.5:
        raise SystemExit(
            f"{coverage:.0%} of pixels read as strokes — this looks like an "
            f"already-inverted image or a filled drawing, not a line sketch.")

    if out is None:
        out = os.path.splitext(path)[0] + "_lineart.png"
    lineart = np.where(mask, 255, 0).astype("uint8")
    Image.fromarray(lineart).convert("RGB").save(out)
    return out, int(mask.sum())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sketch")
    ap.add_argument("--out", default=None)
    ap.add_argument("--threshold", type=int, default=215,
                    help="luminance cutoff 0-255; lower keeps only darker strokes")
    a = ap.parse_args()
    path, n = sketch_to_lineart(a.sketch, a.out, a.threshold)
    print(f"{path}\t{n} stroke px")
