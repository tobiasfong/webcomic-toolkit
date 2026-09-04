"""Draw pictogram choice cards: flat symbols, not illustrations.

    python choice_glyphs.py <path-to-game-dir>

WHY THESE ARE GLYPHS WHERE OTHER CHOICE CARDS ARE PICTURES
--------------------------------------------------------
The author asked for "circles as heads on top of rectangle bodies... like
restroom signs". That is a deliberate register, not a shortcut: a pictogram
states a CATEGORY of action where an illustration states a moment. "Get
reinforcements" is a category -- it means people, generally, arriving -- and
a painted crowd would have to decide which people, wearing what, lit how,
none of which the scene has yet.

ONLY THE CROWD IS DRAWN HERE. The rescue card REUSES the existing painted
sword, `choice fight`, and that is the author's decision and a correct one:
where a rescue means cutting through the enemy to reach someone, the blade
means what it meant the first time it was offered. Two chapters using one
image for one action is consistency, not collision.

So the two cards sit in different registers on purpose: a painted object for
the act, a flat sign for the abstraction.

Both are drawn rather than generated for the reason the impact plates are:
they are exact geometry, and diffusion is bad at exact geometry and good at
volume. A pictogram with a wobbly crossguard is a failed pictogram.

Output is RGBA on transparency at the same 615x920 as the existing cards, so
the choice screen lays them out identically without touching its code.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir, out_dir  # noqa: E402

W, H = 615, 920
INK = (232, 240, 252)          # the same pale silver the sword style uses
GLOW = (150, 200, 255)


def finish(mask):
    """Flat ink plus a soft outer glow, on transparency.

    The glow is what keeps a flat symbol from looking like clip art dropped
    on the scene -- the existing cards sit in near-darkness and carry their
    own light, so these have to as well.
    """
    halo = mask.filter(ImageFilter.GaussianBlur(26)).point(lambda v: int(v * 0.55))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(Image.new("RGBA", (W, H), GLOW + (255,)), (0, 0), halo)
    out.paste(Image.new("RGBA", (W, H), INK + (255,)), (0, 0), mask)
    return out


def crowd(n=3):
    """Three figures: circle heads on tapered bodies, the restroom sign.

    The middle one stands forward and slightly larger so the group has a
    front rather than reading as a row -- a crowd arrives, it does not queue.
    """
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    # (x offset as a fraction of width, scale, baseline as a fraction of height)
    figs = [(-0.255, 0.82, 0.80), (0.255, 0.82, 0.80), (0.0, 1.0, 0.87)]
    for fx, s, base in figs:
        cx = W * (0.5 + fx)
        by = H * base
        head_r = W * 0.085 * s
        head_cy = by - H * 0.415 * s
        d.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r],
                  fill=255)
        # body: a rounded trapezoid, wide at the shoulders, narrowing down
        top = head_cy + head_r * 1.42
        sw = W * 0.135 * s          # half-width at the shoulders
        hw = W * 0.088 * s          # half-width at the hem
        d.polygon([(cx - sw, top + H * 0.045 * s), (cx - sw * 0.72, top),
                   (cx + sw * 0.72, top), (cx + sw, top + H * 0.045 * s),
                   (cx + hw, by), (cx - hw, by)], fill=255)
    return finish(m)


def main(argv):
    if not argv:
        sys.exit("usage: python choice_glyphs.py <path-to-game-dir>")
    out = out_dir(game_dir(argv), "images", "fx")
    for name, img in (("choice_crowd", crowd()),):
        p = os.path.join(out, name + ".png")
        img.save(p)
        print("  %-15s %dx%d  %6.0f KB  %s"
              % (name, img.size[0], img.size[1], os.path.getsize(p) / 1024, p))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
