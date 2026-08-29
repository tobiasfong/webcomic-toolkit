"""Draw the fight-scene impact plates: convergence bursts, slash beams, and
the ice crescent.

WHY THESE ARE DRAWN AND NOT PROMPTED
------------------------------------
Same reasoning as tools/magic_circle.py. These are GEOMETRY -- lines meeting at
a vanishing point, a beam at an exact angle, an arc of exact curvature -- and
diffusion cannot place geometry where you ask for it. It also turns fine
repeated marks into texture, and a speedline field is nothing but fine repeated
marks. Drawn, they are exact, instant, free to recolor, and reusable for every
fight in the series.

BLOOM, per the repo rule, all three parts or it reads as a blurred copy
rather than as light:
  1. a WHITE-HOT CORE, with the hue surviving only in the halo
  2. SEVERAL blur radii summed, never one
  3. ADDITIVE accumulation

Plates are fully opaque black-field frames, which is what Fate/stay night cuts
to and what the author referenced. They are shown for 30-50 ms over a Dissolve,
so they read as an impact, not as a background.

    python fx_plates.py <path-to-game-dir>
"""
import math
import os
import sys
import random

from PIL import Image, ImageDraw, ImageFilter

# 1280x720, not 1920x1080. These are shown for 30-50 ms as a full-frame flash;
# at that duration and with content this abstract, the engine's upscale costs
# nothing visible, and the files drop to roughly a third of the size. The web
# build fetches them on demand, so their size is wait time before an impact.
# Pass a width as the second argument to override.
W = int(sys.argv[2]) if len(sys.argv) > 2 else 1280
H = W * 9 // 16
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir, out_dir  # noqa: E402

OUT = out_dir(game_dir(), 'images', 'fx')
# Blur radii and their weights. The wide ones carry the atmospheric glow, the
# tight one carries the edge -- summing them is what separates light from blur.
BLOOM = [(3, 0.55), (9, 0.45), (26, 0.35), (70, 0.28)]


def bloom(mask):
    """Sum several blurred copies of a shape mask, additively, into one glow."""
    acc = Image.new("F", mask.size, 0.0)
    apx = acc.load()
    for radius, weight in BLOOM:
        blurred = mask.filter(ImageFilter.GaussianBlur(radius))
        bpx = blurred.load()
        for y in range(mask.height):
            for x in range(mask.width):
                apx[x, y] += bpx[x, y] * weight
    return acc


def bloom_fast(mask):
    """Same as bloom(), done with band arithmetic instead of a Python loop."""
    from PIL import ImageChops
    acc = None
    for radius, weight in BLOOM:
        b = mask.filter(ImageFilter.GaussianBlur(radius))
        b = b.point(lambda v, w=weight: int(min(255, v * w)))
        acc = b if acc is None else ImageChops.add(acc, b)
    return acc


def light(mask, hue):
    """Turn a shape mask into LIGHT of the given hue on a black field.

    The core stays white -- color survives only where the glow has fallen off,
    which is how a real highlight blows out. Channels are combined additively
    so overlapping beams brighten rather than average.
    """
    from PIL import ImageChops
    glow = bloom_fast(mask)
    r, g, b = hue
    halo = Image.merge("RGB", (
        glow.point(lambda v: int(v * r / 255)),
        glow.point(lambda v: int(v * g / 255)),
        glow.point(lambda v: int(v * b / 255)),
    ))
    core = Image.merge("RGB", (mask, mask, mask))
    return ImageChops.add(halo, core)


def convergence(vp, n, hue, seed, spread=math.tau, base=math.tau,
                warm=None, warm_span=None):
    """Speedlines converging on a vanishing point.

    Wedges rather than strokes: a line that narrows toward the vanishing point
    is what gives the field its sense of rushing inward. `warm` paints a second
    hue across `warm_span` radians, the way the reference frame splits cool and
    hot across the beam.
    """
    rng = random.Random(seed)
    cool_mask = Image.new("L", (W, H), 0)
    warm_mask = Image.new("L", (W, H), 0)
    dc, dw = ImageDraw.Draw(cool_mask), ImageDraw.Draw(warm_mask)
    reach = math.hypot(W, H) * 1.4

    for i in range(n):
        a = base + spread * (i / n) + rng.uniform(-0.012, 0.012)
        half = rng.uniform(0.0016, 0.020)          # angular half-width
        inner = rng.uniform(8, 90)                 # gap at the vanishing point
        val = rng.randint(70, 255)
        pts = [
            (vp[0] + math.cos(a - half * 0.25) * inner,
             vp[1] + math.sin(a - half * 0.25) * inner),
            (vp[0] + math.cos(a - half) * reach,
             vp[1] + math.sin(a - half) * reach),
            (vp[0] + math.cos(a + half) * reach,
             vp[1] + math.sin(a + half) * reach),
            (vp[0] + math.cos(a + half * 0.25) * inner,
             vp[1] + math.sin(a + half * 0.25) * inner),
        ]
        hot = warm is not None and warm_span[0] <= (a % math.tau) <= warm_span[1]
        (dw if hot else dc).polygon(pts, fill=val)

    img = light(cool_mask, hue)
    if warm is not None:
        from PIL import ImageChops
        img = ImageChops.add(img, light(warm_mask, warm))
    return img


def beam(angle, thickness, hue, offset=0):
    """One hard diagonal blade of light across the whole frame."""
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    cx, cy = W / 2, H / 2 + offset
    dx, dy = math.cos(angle), math.sin(angle)
    reach = math.hypot(W, H)
    d.line([(cx - dx * reach, cy - dy * reach), (cx + dx * reach, cy + dy * reach)],
           fill=255, width=thickness)
    return light(mask, hue)


def crescent(hue, seed=7):
    """The frozen arc: 'a colossal crescent moon descended onto the mortal
    plane' is the author's own line, so the shape is his, not an invention."""
    from PIL import ImageChops
    outer = Image.new("L", (W, H), 0)
    inner = Image.new("L", (W, H), 0)
    ImageDraw.Draw(outer).ellipse([-260, -560, W + 260, H + 900], fill=255)
    ImageDraw.Draw(inner).ellipse([-140, -980, W + 420, H + 620], fill=255)
    mask = ImageChops.subtract(outer, inner)

    # Shards along the arc, so the edge reads as ice rather than as a ribbon.
    rng = random.Random(seed)
    d = ImageDraw.Draw(mask)
    for _ in range(90):
        t = rng.uniform(0, 1)
        x = t * W
        y = 250 + math.sin(t * math.pi) * -120 + rng.uniform(-70, 70)
        L = rng.uniform(30, 190)
        a = rng.uniform(-0.5, 0.5) + math.pi / 2.4
        d.line([(x, y), (x + math.cos(a) * L, y + math.sin(a) * L)],
               fill=rng.randint(120, 255), width=rng.randint(2, 7))
    return light(mask, hue)


def streak(hue, start=(0.74, 0.18), end=(0.33, 0.56), head=15, tail=3,
           steps=110):
    """A small object crossing frame at speed: a tapered trail with a hot head.

    NOT beam(). A beam is a full-frame blade struck through the center -- an
    attack. A thrown object is short, off-center, thickest where the thing
    actually is, and fading to nothing behind it. Using the attack shape for a
    tossed object would read as someone striking at the viewer, which is the
    opposite of the beat.

    Drawn head-last so the brightest marks land on top, and paired with a round
    head glow so the leading end reads as an object catching light rather than
    as the end of a line.
    """
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    x0, y0 = start[0] * W, start[1] * H
    x1, y1 = end[0] * W, end[1] * H
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        # Cubic taper: the trail thins fast behind the head rather than
        # sloping evenly, which is what makes it read as motion.
        w = tail + (head - tail) * (t0 ** 3)
        v = int(40 + 215 * (t0 ** 2.2))
        d.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)],
               fill=v, width=max(1, int(round(w))))
    r = head * 1.35
    d.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=255)
    return light(mask, hue)


ICE = (120, 214, 255)
QI = (150, 96, 255)
BLAST = (255, 150, 70)
GOLD = (255, 198, 74)

plates = {
    # An overwhelming qi surge -- converging hard, with a hot rift down one
    # side the way the reference frame splits cool from hot.
    "burst_qi": convergence((W * 0.42, H * 0.30), 150, QI, seed=101,
                            warm=(255, 70, 70),
                            warm_span=(0.35, 1.15)),
    # The gesture: one blade of light, before anything is described.
    "slash_qi": beam(math.radians(28), 26, QI),
    # Frost answering, in the bandit fight.
    "burst_ice": convergence((W * 0.55, H * 0.46), 130, ICE, seed=202),
    # The Glacial Wall freeze.
    "crescent_ice": crescent(ICE),
    # An explosive going off.
    "burst_blast": convergence((W * 0.50, H * 0.56), 170, BLAST, seed=303),
    # A small object thrown across frame. Shown ADDITIVELY rather than as an
    # opaque plate: the other plates cut the scene to black for an impact, and
    # blacking out a quiet conversation for a thrown object would hit far
    # harder than the moment is.
    "streak_gold": streak(GOLD),
}

for name, img in plates.items():
    p = os.path.join(OUT, name + ".png")
    img.save(p)
    print(f"{name:14} {os.path.getsize(p) / 1024:7.0f} KB  {p}")
