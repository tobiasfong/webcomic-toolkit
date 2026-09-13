# -*- coding: utf-8 -*-
"""Repair a malformed hand on a generated figure with a MASKED Kontext pass.

    python repair_hand.py <project> <label> --grid              # find the box
    python repair_hand.py <project> <label> --box 520 690 660 820 [--seed 9001]

`label` is a concept folder under output/<project>/_concepts. The newest
render there is the source.

⚠ THIS IS THE ONE THING KONTEXT IS VALIDATED FOR HERE. The repo's measured
result: repairing a damaged hand went from 0 of 6 frames usable at Q3_K_S to
3 of 3 at Q6_K, which is the whole reason both FLUX models run Q6. Quantization
error surfaces when the task is hard, and reconstructing a hand from corrupted
pixels sits right at the edge of what the model can do.

Do NOT reach for this to change a silhouette, move a marking, or complete a
figure that runs off the canvas. Those are the restructure and
invent-what-lies-beyond cases that fail however they are worded; a clipped
figure needs a taller canvas (complete_figure.py, beside this) and a
misplaced emblem needs a mirror or a regeneration.

⚠ KEEP THE MASK SMALL AND KEEP IT INSIDE THE FIGURE. Two separate findings
push the same way:

  * A masked pass that repainted 780 px of face drifted everything inside it
    and failed twice; a tight 140x105 mask over a mouth and chin succeeded.
    The less there is inside the box, the less the model re-decides.
  * A mask whose box ends in open background leaves a visible rectangular
    seam, because the area outside the subject is repainted differently
    inside the box than outside it. Masks that stay within a solid object
    blend invisibly. A hand at the end of a sleeve is usually reachable with
    a box that is mostly sleeve and hand rather than mostly backdrop -- bias
    the box INWARD toward the body, and check the result for an edge.

--grid writes a coordinate overlay beside the render so the box can be read
off it rather than guessed, which is how a plaque on a wall plate was
located once.

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
from PIL import Image, ImageDraw  # noqa: E402

# Positives only, and it names what a hand IS rather than what is wrong with
# it -- naming the defect is the negation trap that summons it back.
INSTRUCTION = ("a single clean hand with four fingers and one thumb, the "
               "fingers together and relaxed, hanging at the end of the "
               "sleeve, crisp black outlines and hard-edged flat color, "
               "every edge in sharp focus")


def newest(folder):
    fs = [f for f in glob.glob(os.path.join(folder, "flux_*.png"))
          if not f.endswith(("_body.png", "_rgba.png", "_cut.png"))]
    return sorted(fs, key=os.path.getmtime)[-1] if fs else None


def grid(src, out):
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    for x in range(0, im.width, 50):
        d.line([(x, 0), (x, im.height)], fill=(255, 0, 0))
        d.text((x + 2, 2), str(x), fill=(255, 0, 0))
    for y in range(0, im.height, 50):
        d.line([(0, y), (im.width, y)], fill=(0, 200, 0))
        d.text((2, y + 2), str(y), fill=(0, 140, 0))
    im.save(out)
    print("grid written: %s  (%dx%d)" % (out, im.width, im.height))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("label")
    ap.add_argument("--box", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--seed", type=int, default=9001)
    ap.add_argument("--feather", type=int, default=24)
    a = ap.parse_args(argv)

    folder = os.path.join(SERVER, "output", a.project, "_concepts", a.label)
    src = newest(folder)
    if not src:
        sys.exit("no render in %s" % folder)

    if a.grid or not a.box:
        out = os.path.join(folder, "_grid.png")
        grid(src, out)
        if not a.box:
            print("Read the hand's box off that, then rerun with "
                  "--box X0 Y0 X1 Y1")
            return 0

    x0, y0, x1, y1 = a.box
    print("repairing %s  box (%d,%d)-(%d,%d)  %dx%d px"
          % (os.path.basename(src), x0, y0, x1, y1, x1 - x0, y1 - y0),
          flush=True)
    if (x1 - x0) * (y1 - y0) > 200000:
        print("  ⚠ that box is large. A masked pass that repainted 780 px of "
              "face drifted everything in it; tighten toward the hand.",
              flush=True)

    out = flux_workflow.edit_image(
        image_path=src,
        instruction=INSTRUCTION,
        out_dir=folder,
        seed=a.seed,
        mask_box=(x0, y0, x1, y1),
        mask_feather=a.feather,
    )
    print("wrote %s" % os.path.basename(out), flush=True)
    print("Check for a rectangular seam at the box edge, then re-matte it "
          "with the project's matte tool.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
