"""Paste a rectangular region from one render into another, with a feathered
edge so the seam does not read.

Why this exists: `flux_workflow.edit_image` runs Kontext at denoise=1.0 over the
whole canvas — there is no mask, so NOTHING in the frame is protected. On panel
4 that let two separate costume passes repaint the raised kicking leg as an
extension of the sleeve (the fusion rule, in Kontext rather than in ControlNet).

Prompt wording cannot fence a region off. This can: run the edit, keep the part
of it that came out right, and take the rest from the render that already had
that part right. Both images must share a canvas size and framing — that holds
when every pass descends from the same base render, which is how the panel-4
repair chain is built.

    python region_composite.py BASE PATCH OUT --box x0 y0 x1 y1 [--feather 24]

BASE  the image that is mostly right (receives the paste)
PATCH the image the region is taken FROM
"""
import argparse

from PIL import Image, ImageDraw, ImageFilter


def composite_region(base: str, patch: str, out: str,
                     box: tuple[int, int, int, int],
                     feather: int = 24) -> str:
    b = Image.open(base).convert("RGB")
    p = Image.open(patch).convert("RGB")
    if b.size != p.size:
        raise ValueError(
            f"canvas mismatch: base {b.size} vs patch {p.size}. Both images must "
            "come from the same base render for the framing to line up.")

    # The mask is drawn inset by the feather radius and then blurred back out,
    # so the fully-opaque core still covers the requested box rather than the
    # blur eating into it.
    mask = Image.new("L", b.size, 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(mask).rectangle(
        (x0 + feather, y0 + feather, x1 - feather, y1 - feather), fill=255)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather / 2))

    b.paste(p, (0, 0), mask)
    b.save(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base")
    ap.add_argument("patch")
    ap.add_argument("out")
    ap.add_argument("--box", nargs=4, type=int, required=True,
                    metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--feather", type=int, default=24)
    a = ap.parse_args()
    print(composite_region(a.base, a.patch, a.out, tuple(a.box), a.feather))


if __name__ == "__main__":
    main()
