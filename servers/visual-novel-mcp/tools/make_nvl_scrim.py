"""Draw the NVL scrim: a vertical fade that darkens ONLY the band the text
sits in, and clears completely below it.

Why this exists rather than a flat Solid(): a full-screen translucent panel at
the opacity text needs (~85%) flattens the art behind it, which is what the
author saw -- the throne hall and both figures were nearly invisible. Fate/stay
night does not use a panel at all; it outlines the glyphs and lets the art show.

This is the middle road, and it is the same principle as the magic circle:
CONSTRUCT the gradient deterministically instead of asking a Solid to be
something it is not. The text still gets help where it lives (the top of the
page, since NVL entries accumulate downward from there), and the lower two
thirds of the frame -- where the sprites and the background actually are --
are left untouched.

    python make_nvl_scrim.py <path-to-game-dir>
"""
import os
import sys

from PIL import Image

W, H = 1920, 1080
TOP_ALPHA = 150          # 59% at the very top, where the first line sits
FADE_END = 0.56          # fully clear by 56% down -- above the figures' faces

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

img.resize((W, H), Image.NEAREST).save(OUT)
print(f"wrote {OUT}  {W}x{H}  top alpha {TOP_ALPHA}/255  clear by y={int(end)}")
