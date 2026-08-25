"""Draw the ambient pieces a static title screen needs to stop feeling dead.

    python menu_fx.py <path-to-game-dir>

A cover under a looping theme reads as a freeze-frame. The figures cannot be
animated -- that is a redraw, not an effect -- but the AIR around them can, and
that is enough: drifting particles, a flame that breathes, ice that catches the
light. The eye reads the scene as alive because something in it is moving.

Three sprites, all additive and all drawn rather than generated, because they
are radial falloffs and noise -- the two things diffusion is worst at placing
and best at turning to mush.

  spark.png   one soft particle for the drift layer
  glow_warm   a flame's halo, to be pulsed over a fire
  glow_cool   an ice halo, to be pulsed over a crystal

⚠ BLOOM RULE, as everywhere else in this project: a WHITE-HOT CORE with the hue
surviving only in the halo, SEVERAL blur radii summed, ADDITIVE accumulation.
All three or it reads as a blurred disc rather than as light.
"""
import math
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir, out_dir  # noqa: E402

OUT = out_dir(game_dir(), "images", "fx")


def radial(size, hue, core=0.18, gamma=2.2):
    """A soft additive glow: white at the center, hue through the falloff.

    Drawn from the distance field rather than by blurring a disc, which is what
    keeps the center genuinely white instead of a tinted smear.
    """
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = im.load()
    r = size / 2.0
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - r, y - r) / r
            if d >= 1.0:
                continue
            v = (1.0 - d) ** gamma                 # falloff
            # Inside the core the color washes to white; outside, the hue
            # takes over. That transition IS the difference between light and
            # a colored circle.
            k = max(0.0, min(1.0, (core - d) / max(core, 1e-6)))
            cr = hue[0] + (255 - hue[0]) * k
            cg = hue[1] + (255 - hue[1]) * k
            cb = hue[2] + (255 - hue[2]) * k
            px[x, y] = (int(cr), int(cg), int(cb), int(255 * v))
    return im


if __name__ == "__main__":
    jobs = [
        ("spark.png", radial(48, (215, 235, 255), core=0.30, gamma=1.7)),
        ("glow_warm.png", radial(512, (255, 138, 40), core=0.22, gamma=2.4)),
        ("glow_cool.png", radial(512, (120, 210, 255), core=0.24, gamma=2.2)),
    ]
    for name, im in jobs:
        p = os.path.join(OUT, name)
        im.save(p)
        print(f"{name:16} {im.size}  {os.path.getsize(p) / 1024:.0f} KB")
    print("\nUse additively (blend=\"add\"); pulse with ATL, never with a timer.")
