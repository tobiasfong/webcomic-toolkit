# -*- coding: utf-8 -*-
"""Draw an anime-style magic circle as a transparent PNG.

Why this is a script and not a prompt: FLUX will not PLACE a seal where you ask
it to (two explicit "directly in front of him" attempts both put it off to one
side, the same unsteerable-placement failure as a shoulder emblem), and it
smears fine repeated detail, so rune bands come back as texture rather than
marks. A magic circle is pure geometry -- concentric rings, an evenly spaced
rune band, a star polygon -- so it is cheaper and exact to construct it.

Output is RGBA on full transparency, ready to composite over a CG at whatever
size, angle and opacity the panel needs.

Everything is drawn at SS x scale and downsampled once at the end, which is what
keeps thin strokes smooth without a blur pass.

    python magic_circle.py out.png --size 1400 --points 7 --skip 3
    python magic_circle.py out.png --color "#c9a6ff" --runes 44 --rings 2
"""
import argparse
import math
import random

from PIL import Image, ImageDraw, ImageFilter

SS = 4  # supersample factor


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _rune(d, cx, cy, h, col, w, rng):
    """One angular pseudo-rune: a stem plus two or three branches.

    Deliberately not a real script -- it needs to READ as writing at panel size,
    which is a matter of consistent stroke weight and stem rhythm, not meaning.
    """
    half = h / 2
    d.line([(cx, cy - half), (cx, cy + half)], fill=col, width=w)
    for _ in range(rng.randint(2, 3)):
        y0 = cy - half + rng.uniform(0.05, 0.85) * h
        dy = rng.choice([-1, 1]) * rng.uniform(0.18, 0.42) * h
        dx = rng.choice([-1, 1]) * rng.uniform(0.22, 0.40) * h
        d.line([(cx, y0), (cx + dx, y0 + dy)], fill=col, width=w)
    if rng.random() < 0.35:
        r = rng.uniform(0.06, 0.11) * h
        yy = cy + rng.choice([-1, 1]) * half * 0.7
        d.ellipse([cx - r, yy - r, cx + r, yy + r], outline=col, width=max(1, w - 1))


def _ring_of_runes(img, cx, cy, radius, count, height, col, w, seed):
    """Runes stamped around a circle, each rotated to sit tangent to it."""
    rng = random.Random(seed)
    for i in range(count):
        a = 2 * math.pi * i / count
        cell = Image.new("RGBA", (int(height * 1.6), int(height * 1.6)), (0, 0, 0, 0))
        _rune(ImageDraw.Draw(cell), cell.width / 2, cell.height / 2, height, col, w, rng)
        cell = cell.rotate(-math.degrees(a) - 90, resample=Image.BICUBIC)
        img.alpha_composite(cell, (int(cx + radius * math.cos(a) - cell.width / 2),
                                   int(cy + radius * math.sin(a) - cell.height / 2)))


def _star(d, cx, cy, r, points, skip, col, w):
    """A {points/skip} star polygon — the straight-line figure at the centre."""
    pts = [(cx + r * math.cos(2 * math.pi * i / points - math.pi / 2),
            cy + r * math.sin(2 * math.pi * i / points - math.pi / 2))
           for i in range(points)]
    i, seen = 0, set()
    while (i, (i + skip) % points) not in seen:
        j = (i + skip) % points
        seen.add((i, j))
        d.line([pts[i], pts[j]], fill=col, width=w)
        i = j
    return pts


def build(size=1400, color="#8fd3ff", points=7, skip=3, runes=40, inner_runes=28,
          seed=7, glow=True, glow_strength=1.0, glow_radius=1.0, core=0.75):
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = _hex(color) + (255,)
    cx = cy = S / 2
    w = max(2, int(S * 0.0016))          # base stroke
    wt = max(2, int(S * 0.0011))         # thin stroke

    def circle(rr, width):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=width)

    R = S * 0.47
    circle(R, w)                          # outer edge
    circle(R * 0.955, wt)                 # rune band, outer wall
    circle(R * 0.845, wt)                 # rune band, inner wall
    _ring_of_runes(img, cx, cy, R * 0.90, runes, R * 0.075, col, wt, seed)

    circle(R * 0.795, w)                  # second band
    circle(R * 0.715, wt)
    _ring_of_runes(img, cx, cy, R * 0.755, inner_runes, R * 0.052, col, wt, seed + 1)

    circle(R * 0.66, wt)
    pts = _star(d, cx, cy, R * 0.63, points, skip, col, w)
    for (px, py) in pts:                  # a node on each star point
        rr = R * 0.036
        d.ellipse([px - rr, py - rr, px + rr, py + rr], outline=col, width=wt)
    circle(R * 0.30, wt)                  # centre
    circle(R * 0.255, w)
    _ring_of_runes(img, cx, cy, R * 0.155, 8, R * 0.055, col, wt, seed + 2)

    img = img.resize((size, size), Image.LANCZOS)
    if glow:
        img = bloom(img, color, strength=glow_strength, radius=glow_radius, core=core)
    return img


def bloom(line_img, color, strength=1.0, radius=1.0, core=0.75):
    """Turn flat line art into something that reads as LIGHT.

    Three things separate a glow from a blurred copy, and the old one-radius
    version had none of them:

      * a WHITE-HOT CORE. Real light clips its sensor, so the line itself goes
        near-white and the hue survives only in the halo. Lines that stay fully
        saturated read as painted, not lit.
      * SEVERAL blur radii summed, not one. A single blur gives a flat mush with
        a visible edge; stacking a tight bright halo, a mid one and a wide faint
        one is what produces falloff the eye accepts.
      * ADDITIVE accumulation. Alpha-compositing a blur over itself saturates
        toward opaque; summing intensities keeps the falloff smooth.

    Returns RGBA that already looks lit under a NORMAL blend, so it can be
    dropped straight into a paint program. Setting the layer to Screen or
    Linear Dodge on top of that adds spill onto the figure.
    """
    import numpy as np
    rgb = np.array(_hex(color), dtype=np.float64) / 255.0
    a = np.asarray(line_img.split()[-1], dtype=np.float64) / 255.0
    S = line_img.size[0]

    halo = np.zeros_like(a)
    for rad, wgt in ((0.004, 1.00), (0.012, 0.55), (0.030, 0.30), (0.070, 0.16)):
        blurred = Image.fromarray((a * 255).astype("uint8")).filter(
            ImageFilter.GaussianBlur(max(1.0, S * rad * radius)))
        halo += np.asarray(blurred, dtype=np.float64) / 255.0 * wgt
    halo = np.clip(halo * strength, 0.0, 1.0)

    out_a = np.clip(a + halo * (1.0 - a), 0.0, 1.0)
    # hue in the halo, white at the core: mix toward white by the line's own
    # coverage, so only the drawn strokes blow out
    white = np.ones(3)
    mix = (a[..., None] ** 0.7) * core
    out_rgb = rgb[None, None, :] * (1 - mix) + white[None, None, :] * mix
    # lift the near-core halo toward the hue's bright end so falloff stays colored
    out_rgb = np.clip(out_rgb + (halo[..., None] * 0.25) * rgb[None, None, :], 0, 1)

    arr = np.dstack([(out_rgb * 255).astype("uint8"),
                     (out_a * 255).astype("uint8")])
    return Image.fromarray(arr, "RGBA")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("out")
    p.add_argument("--size", type=int, default=1400)
    p.add_argument("--color", default="#8fd3ff")
    p.add_argument("--points", type=int, default=7, help="star polygon vertices")
    p.add_argument("--skip", type=int, default=3, help="step between vertices; 1 = plain polygon")
    p.add_argument("--runes", type=int, default=40)
    p.add_argument("--inner-runes", type=int, default=28)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--no-glow", action="store_true")
    p.add_argument("--glow-strength", type=float, default=1.0,
                   help="halo intensity; 0.6 subtle, 1.6 fierce")
    p.add_argument("--glow-radius", type=float, default=1.0,
                   help="halo spread multiplier")
    p.add_argument("--core", type=float, default=0.75,
                   help="how far the line itself blows out to white, 0-1")
    a = p.parse_args()
    im = build(a.size, a.color, a.points, a.skip, a.runes, a.inner_runes,
               a.seed, glow=not a.no_glow, glow_strength=a.glow_strength,
               glow_radius=a.glow_radius, core=a.core)
    im.save(a.out)
    bbox = im.split()[-1].getbbox()
    print(f"{a.out}  {im.size} RGBA  alpha bbox {bbox}")


if __name__ == "__main__":
    main()
