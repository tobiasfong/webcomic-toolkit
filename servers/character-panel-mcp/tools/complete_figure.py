# -*- coding: utf-8 -*-
"""Re-frame a CLIPPED figure without losing the design, on FLUX 3 Klein.

    python complete_figure.py <project> <label> [--seed 8501] [--height 1344]

`label` is a concept folder under output/<project>/_concepts. The newest
render there is used as the reference.

⚠ WHAT THIS IS NOT: outpainting. A clipped figure needs pixels that lie
OUTSIDE the canvas, and a boxed edit only redraws inside it.

⚠ WHAT THIS IS: a fresh render with the clipped one as its reference. Every
pixel is drawn new with the reference's identity, so it is a REROLL THAT KEEPS
THE DESIGN -- the face, the robe, the sash and the sword come from the
reference rather than from the prompt getting lucky twice.

⚠ PAD THE REFERENCE, or Klein copies the clip. When the pose asked for is the
one the reference shows, Klein copies the reference -- its CROP included.
Measured 2026-10-17 on a whole cast: renders from tight crops came back cut
off at the head or feet 17 times in 40, and new seeds did not help (7 of 8 cut
again); padding the reference to ~18% more height on its own backdrop color
fixed all 9 retried. This pads by --pad (default 0.18) before rendering.

A TALLER CANVAS buys the clearance as well. Default 1344 gives roughly 10%
headroom over a 1216 render at the same width.

⚠ AND READ THE DESCRIPTION BEFORE BLAMING THE SEED. A figure clipped on six
rolls while two others on a byte-identical costume prompt did not; the only
difference was the word "tall" in his build clause, and deleting it took the
bottom-edge contact from 192 px to 15. The description is a fact and the
framing clause is a bias, and when they conflict the description wins.

Score BOTH ends afterwards. A figure has two terminal features and both get
measured: one check measured the shoes and missed a clipped topknot.
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
sys.path.insert(0, SERVER)
import klein_workflow  # noqa: E402
from PIL import Image  # noqa: E402

INSTRUCTION = (
    "The character from image 1, the whole figure standing with clear empty "
    "space above the top of the head and clear empty space below the feet, "
    "full body head to toe within the frame, on a plain flat pale gray "
    "backdrop. They keep the face, hair, costume and pose of image 1."
)


def newest(folder):
    fs = [f for f in glob.glob(os.path.join(folder, "*.png"))
          if not os.path.basename(f).startswith("_")
          and not f.endswith(("_body.png", "_rgba.png", "_cut.png", "_matted.png", "_padded.png"))]
    return sorted(fs, key=os.path.getmtime)[-1] if fs else None


def pad(src, frac, out):
    """Grow the canvas by `frac` of its height, split top and bottom, on the
    reference's own backdrop color (its corner pixel), and widen to keep the
    aspect."""
    im = Image.open(src).convert("RGB")
    w, h = im.size
    nh = int(round(h * (1 + frac)))
    nw = int(round(w * nh / h))
    canvas = Image.new("RGB", (nw, nh), im.getpixel((0, 0)))
    canvas.paste(im, ((nw - w) // 2, (nh - h) // 2))
    canvas.save(out)
    return out


def edges(path):
    """Opaque pixel counts on all four edges of a matted PNG."""
    import numpy as np
    a = np.asarray(Image.open(path).convert("RGBA"))[:, :, 3]
    return dict(top=int((a[0, :] > 8).sum()), bottom=int((a[-1, :] > 8).sum()),
                left=int((a[:, 0] > 8).sum()), right=int((a[:, -1] > 8).sum()))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("label")
    ap.add_argument("--seed", type=int, default=8501)
    ap.add_argument("--height", type=int, default=1344)
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--pad", type=float, default=0.18)
    a = ap.parse_args(argv)

    folder = os.path.join(SERVER, "output", a.project, "_concepts", a.label)
    src = newest(folder)
    if not src:
        sys.exit("no render in %s" % folder)
    print("reference: %s  %s" % (os.path.basename(src), Image.open(src).size), flush=True)
    padded = pad(src, a.pad, os.path.join(folder, "_" + os.path.splitext(os.path.basename(src))[0]
                                          + "_padded.png"))
    out = klein_workflow.generate(INSTRUCTION, folder, a.width, a.height, seed=a.seed,
                                  refs=[padded], stem="complete")
    print("wrote %s  %s" % (os.path.basename(out), Image.open(out).size), flush=True)
    print("Now matte it and check ALL FOUR edges.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
