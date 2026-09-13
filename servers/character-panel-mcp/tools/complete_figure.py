# -*- coding: utf-8 -*-
"""Re-frame a CLIPPED figure without losing the design, via unmasked edit.

    python complete_figure.py <project> <label> [--seed 8501] [--height 1344]

`label` is a concept folder under output/<project>/_concepts. The newest
render there is used as the reference.

⚠ WHAT THIS IS NOT: it is not outpainting, and Kontext cannot do that. The
request it was written for was to "use Flux Kontext to complete him" after a
render came back with the topknot cut off above and the shoes cut off below.
A masked Kontext pass repairs damage INSIDE a frame -- that is the hand
repair this repo records going 0 of 6 usable to 3 of 3 at Q6 -- but a clipped
figure needs pixels that are OUTSIDE the canvas entirely, and inventing what
lies beyond the edge is the restructure case that fails however it is worded.

⚠ WHAT THIS IS: `edit_image()` WITHOUT a mask_box, which is not an edit at
all. Unmasked it starts from an empty latent at denoise 1.0 and injects the
reference through ReferenceLatent, so every pixel is generated fresh with an
identity bias and there is nothing underneath to preserve. That is the same
mechanism that took a standing character to seated on a throne with the
likeness held across six renders. So this is a REROLL THAT KEEPS THE DESIGN:
the face, the robe, the sash and the sword come from the reference rather
than from the prompt getting lucky twice.

Two things follow from that, and both matter:

  * The framing is re-decided, which is the entire point -- but it is decided
    by the SEED, not by the instruction, exactly as composition always is
    here. If it clips again, change the seed, not the words.
  * A TALLER CANVAS is what actually buys the clearance. The reference was
    832x1216 and the figure filled it end to end; asking the same canvas for
    more room just moves the problem. Default 1344 gives roughly 10% headroom
    at the same width.

⚠ AND READ THE DESCRIPTION BEFORE BLAMING THE SEED. The figure this was
written for clipped on six rolls while two others on a byte-identical costume
prompt did not; the only difference was the word "tall" in his build clause,
and deleting it took the bottom-edge contact from 192 px to 15. The framing
clause is a bias and the description is a fact, and when they conflict the
description wins. Relative height belongs in the sprite manifest's height_cm,
not in the render.

Score BOTH ends afterwards. The first check on that clipped render measured
the bottom, left and right edges and never the top, so it reported the shoes
and missed the topknot -- the author caught that. A figure has two terminal
features and both get measured.

Moved here from a project's tools folder on 2026-09-14: it is a general
technique and was living beside one game's emitters.
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
sys.path.insert(0, SERVER)
import flux_workflow  # noqa: E402
from PIL import Image  # noqa: E402

INSTRUCTION = (
    "the same character, the whole figure standing with clear empty space "
    "above the top of his head and clear empty space below his boots, "
    "full body head to toe within the frame, plain pale backdrop, "
    "crisp black outlines and hard-edged flat color, every edge in sharp focus"
)


def newest(folder):
    fs = [f for f in glob.glob(os.path.join(folder, "flux_*.png"))
          if not f.endswith(("_body.png", "_rgba.png", "_cut.png"))]
    return sorted(fs, key=os.path.getmtime)[-1] if fs else None


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
    a = ap.parse_args(argv)

    folder = os.path.join(SERVER, "output", a.project, "_concepts", a.label)
    src = newest(folder)
    if not src:
        sys.exit("no render in %s" % folder)
    print("reference: %s  %s" % (os.path.basename(src), Image.open(src).size),
          flush=True)

    out = flux_workflow.edit_image(
        image_path=src,
        instruction=INSTRUCTION,
        out_dir=folder,
        seed=a.seed,
        canvas_width=a.width,
        canvas_height=a.height,
    )
    print("wrote %s  %s" % (os.path.basename(out), Image.open(out).size),
          flush=True)
    print("Now matte it with the project's matte tool and check ALL FOUR "
          "edges.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
