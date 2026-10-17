# -*- coding: utf-8 -*-
"""Repair a malformed hand on a generated figure with a boxed Klein redraw.

    python repair_hand.py <project> <label> --grid              # find the box
    python repair_hand.py <project> <label> --box 520 690 660 820 [--seed 9001]

`label` is a concept folder under output/<project>/_concepts. The newest
render there is the source.

⚠ REROLL FIRST. Measured on FLUX 3 Klein, 2026-10-17: six region repairs on
one figure produced one clean hand, while three fresh seeds of the FULL render
produced one with both hands right. Reach for this only when the rest of the
render is worth keeping and a reroll has already been tried.

How it works: klein_workflow.edit_region() redraws the whole frame from the
source as a reference, then pastes back only the box (grown and feathered), so
the change outside it is exactly zero. Klein on its own redraws the whole
frame even for a boxed edit -- 18.5 of mean change outside the box.

⚠ THE BOX SETS THE HAND'S SIZE, not only its place. A hand asked to fill a
220x166 box came back 220x166 and swollen beside the other one. Size the box
to the hand the figure should have, measured off the other hand.

⚠ A box does NOT decide which side of the hand the thumb grows on. Check
handedness on the result: a right hand on a left arm is a common failure.

⚠ The feather blends onto the WORKING image. Blending onto an original that
still holds the old hand let the old fingertips show through as ghosts.

--erase fills the box with the surrounding color first, so the model cannot
build on what is there. On a pale floor that gave a clean new hand; on a dark
textured floor the flat patch was read as the hand's SILHOUETTE and filled as
a paper cutout. Off by default.

--grid writes a coordinate overlay beside the render so the box can be read
off it rather than guessed.

Count the fingers at FULL resolution afterwards; a sixth finger was missed at
a downscaled look.
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
sys.path.insert(0, SERVER)
import klein_workflow  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

# Positives only, and it names what a hand IS rather than what is wrong with
# it -- naming the defect is the negation trap that summons it back.
INSTRUCTION = ("a single clean hand with four fingers and one thumb, the "
               "fingers together and relaxed, at the end of the sleeve, "
               "the same size as the other hand")


def newest(folder):
    fs = [f for f in glob.glob(os.path.join(folder, "*.png"))
          if not os.path.basename(f).startswith("_")
          and not f.endswith(("_body.png", "_rgba.png", "_cut.png", "_matted.png", "_region.png"))]
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
    ap.add_argument("--feather", type=int, default=14)
    ap.add_argument("--erase", action="store_true")
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
          % (os.path.basename(src), x0, y0, x1, y1, x1 - x0, y1 - y0), flush=True)
    out = klein_workflow.edit_region(src, INSTRUCTION, folder, (x0, y0, x1, y1),
                                     seed=a.seed, feather=a.feather, erase=a.erase)
    print("wrote %s" % os.path.basename(out), flush=True)
    print("Count the fingers at full resolution and check which hand it is, "
          "then re-matte it.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
