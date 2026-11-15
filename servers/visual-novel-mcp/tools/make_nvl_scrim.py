"""Draw the NVL scrim: a vertical fade that darkens ONLY the band the text
sits in, and clears completely below it.

Why this exists rather than a flat Solid(): a full-screen translucent panel at
the opacity text needs (~85%) flattens the art behind it, which is what the
author saw -- the throne hall and both figures were nearly invisible. Fate/stay
night does not use a panel at all; it outlines the glyphs and lets the art show.

This is the middle road, and it is the same principle as the magic circle:
CONSTRUCT the gradient deterministically instead of asking a Solid to be
something it is not. The text gets help where it lives, and the rest of the
frame is left untouched.

FROM THE BOTTOM since 2026-11-15, when the page moved into the lower 70% of
the screen to clear the sprites' faces: the darkest band is now along the
bottom edge, fading out by 44% from the top. Same strength and curve as the
top-down version it replaced, turned over -- that is what the author approved
in the mockup. Set FROM_BOTTOM = False for a page that starts at the top.

    python make_nvl_scrim.py <path-to-game-dir>
"""
import os
import sys

from PIL import Image

W, H = 1920, 1080
TOP_ALPHA = 150          # 59% at the dark edge
FADE_END = 0.56          # fully clear 56% of the way in from the dark edge
FROM_BOTTOM = True       # the dark edge is the bottom (the page is in the lower 70%)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir, out_dir  # noqa: E402

OUT = os.path.join(out_dir(game_dir(), "gui"), "nvl_scrim.png")
img = Image.new("RGBA", (1, H), (0, 0, 0, 0))
px = img.load()
end = H * FADE_END
for y in range(H):
    if y >= end:
        a = 0
    else:
        # Smoothstep, so the fade has no visible banding edge where it ends.
        t = y / end
        a = TOP_ALPHA * (1 - (t * t * (3 - 2 * t)))
    px[0, y] = (0, 0, 0, int(round(a)))

if FROM_BOTTOM:
    img = img.transpose(Image.FLIP_TOP_BOTTOM)
img.resize((W, H), Image.NEAREST).save(OUT)
edge = "bottom" if FROM_BOTTOM else "top"
clear = H - int(end) if FROM_BOTTOM else int(end)
print(f"wrote {OUT}  {W}x{H}  {edge} alpha {TOP_ALPHA}/255  clear {'above' if FROM_BOTTOM else 'below'} y={clear}")
