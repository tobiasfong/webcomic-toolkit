"""
clean_crop.py — paint out neighbour bleed in a single-figure crop taken from a
multi-figure sheet (turnaround rows, expression strips, contact sheets).

Why this exists: cropping one panel out of a turnaround sheet almost always
catches slivers of the figures on either side, because the figures are spaced
closer than the panel's own framing needs. Tightening the crop to exclude them
cuts into the subject; painting them out keeps the framing and removes the
bleed. Deterministic CPU work, no GPU, no tokens — same class of tool as
compose_panel.py / compose_strip.py.

Method: threshold to a foreground mask, label connected components, keep the
largest one (the subject) and flood every other component with the crop's own
background colour (sampled as the median border pixel, so it works on white,
light-gray, or a flat tint alike). This also clears the thin dark edge strip
Kontext output often carries, since that is its own small component.

"Largest component" rather than anything cleverer on purpose: an earlier
version picked the component owning the topmost pixel nearest the horizontal
centre, reasoning that is a centred figure's head. On a crop with a 4px dark
strip along the top edge, that strip won and the entire figure was painted
out. Area is the property that actually distinguishes a subject from bleed.

Limitations: assumes the subject is the centre figure and is not touching a
neighbour. If a neighbour overlaps the subject they are one component and this
cannot separate them — recrop or repaint by hand instead.

Usage:
    python clean_crop.py panel.png [--out cleaned.png] [--threshold 225]
        [--min-area 200]
"""
import os
import argparse


def clean_crop(image_path, out=None, threshold=225, min_area=200):
    try:
        from PIL import Image
        import numpy as np
        from scipy import ndimage
    except ImportError as e:
        raise SystemExit(
            "clean_crop needs pillow, numpy and scipy: "
            "<venv>/python -m pip install pillow numpy scipy"
        ) from e

    if not os.path.isfile(image_path):
        raise SystemExit(f"could not read image: {image_path}")

    im = Image.open(image_path).convert("RGB")
    arr = np.array(im).astype(int)

    # background colour = median of the 1px border (robust to a stray dark edge)
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    bg = np.median(border, axis=0).astype(int)

    fg = (np.abs(arr - bg).max(axis=2) > (255 - threshold))
    labels, n = ndimage.label(fg)
    if n == 0:
        raise SystemExit("no foreground found — check --threshold")

    # the subject is the largest component; everything else is bleed or edge noise
    sizes = ndimage.sum(fg, labels, range(1, n + 1))
    keep = int(np.argmax(sizes)) + 1
    if sizes[keep - 1] < min_area:
        raise SystemExit(f"largest component is under --min-area {min_area} — check --threshold")

    out_arr = np.array(im)
    strays = fg & (labels != keep)
    out_arr[strays] = bg
    cleaned = Image.fromarray(out_arr)

    if out is None:
        root, ext = os.path.splitext(image_path)
        out = f"{root}_cleaned{ext or '.png'}"
    cleaned.save(out)
    return out, int(strays.sum())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", default=None)
    ap.add_argument("--threshold", type=int, default=225,
                    help="how far from the background colour counts as foreground")
    ap.add_argument("--min-area", type=int, default=200,
                    help="ignore components smaller than this when picking the subject")
    a = ap.parse_args()
    path, painted = clean_crop(a.image, a.out, a.threshold, a.min_area)
    print(f"{path} ({painted} px painted out)")
