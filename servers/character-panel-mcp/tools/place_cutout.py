"""Paste an RGBA cutout into a panel, aligned by two landmark point pairs.

Nudging a layer by hand is the tedious half of the composite route. Two
correspondences (say a boot's toe tip and the center of its opening, matched to
where those belong on the target limb) pin down scale, rotation and position
exactly, so placement becomes a number to tune rather than a drag.

Mirroring is a separate flag rather than something inferred: two points cannot
tell a flipped boot from a rotated one, and getting it wrong puts the sole on
the outside of the leg.

    python place_cutout.py PANEL CUTOUT OUT --from x1 y1 x2 y2 --to X1 Y1 X2 Y2
                           [--mirror] [--under-mask ...]
"""
import argparse
import math

from PIL import Image


def place(panel: str, cutout: str, out: str,
          src_pts, dst_pts, mirror: bool = False) -> str:
    p = Image.open(panel).convert("RGBA")
    c = Image.open(cutout).convert("RGBA")

    (ax, ay), (bx, by) = src_pts
    (cx, cy), (dx, dy) = dst_pts

    if mirror:
        c = c.transpose(Image.FLIP_LEFT_RIGHT)
        ax, bx = c.width - ax, c.width - bx

    src_v = complex(bx - ax, by - ay)
    dst_v = complex(dx - cx, dy - cy)
    scale = abs(dst_v) / abs(src_v)
    th = math.atan2(dst_v.imag, dst_v.real) - math.atan2(src_v.imag, src_v.real)

    # One affine straight onto a panel-sized canvas. Doing it as
    # resize-then-rotate(expand=True) means tracking where the anchor drifted
    # to inside a growing bbox, which is easy to get subtly wrong; solving the
    # inverse map lands landmark A exactly on C by construction.
    #   dest = scale * R(th) * (src - A) + C   ->   src = R(-th)/scale * (dest - C) + A
    ca, sa = math.cos(th) / scale, math.sin(th) / scale
    m = (ca, sa, ax - (ca * cx + sa * cy),
         -sa, ca, ay - (-sa * cx + ca * cy))
    layer = c.transform(p.size, Image.AFFINE, m, resample=Image.BICUBIC)
    out_im = Image.alpha_composite(p, layer)
    out_im.convert("RGB").save(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("panel")
    ap.add_argument("cutout")
    ap.add_argument("out")
    ap.add_argument("--src", nargs=4, type=float, required=True)
    ap.add_argument("--dst", nargs=4, type=float, required=True)
    ap.add_argument("--mirror", action="store_true")
    a = ap.parse_args()
    s = [(a.src[0], a.src[1]), (a.src[2], a.src[3])]
    d = [(a.dst[0], a.dst[1]), (a.dst[2], a.dst[3])]
    print(place(a.panel, a.cutout, a.out, s, d, a.mirror))


if __name__ == "__main__":
    main()
