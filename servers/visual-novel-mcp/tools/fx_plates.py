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


def ribbon(centerline, half_widths, fill=255):
    """A filled band along a centerline, thickness varying per point.

    ⚠ USE THIS RATHER THAN SUBTRACTING TWO ELLIPSES. The older arc in
    crescent() is built that way, and the two ellipses barely differ over most
    of their length, so the band it produces is thin to the point of vanishing
    -- which is why that plate reads as loose shards with no body, and why it
    was eventually replaced by a rendered image rather than fixed.

    Offsetting a centerline by an explicit half-width cannot fail that way:
    the thickness is a number you set, not an accident of two curvatures.
    """
    left, right = [], []
    n = len(centerline)
    for i, (x, y) in enumerate(centerline):
        xa, ya = centerline[max(0, i - 1)]
        xb, yb = centerline[min(n - 1, i + 1)]
        ang = math.atan2(yb - ya, xb - xa)
        nx, ny = -math.sin(ang), math.cos(ang)
        hw = half_widths[i]
        left.append((x + nx * hw, y + ny * hw))
        right.append((x - nx * hw, y - ny * hw))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(left + right[::-1], fill=fill)
    return mask


def lance(hue, start=(0.06, 0.90), end=(0.78, 0.18), width=58, seed=13):
    """A crystalline spear driven from the caster toward the enemies.

    NOT streak(). A thrown token is a soft tapered trail with a round head --
    an object catching light. A lance is a RIGID BODY with straight edges and
    a point, so it is drawn as a polygon with internal facets rather than as a
    stroke that fades. The difference is what separates a spear from a comet.

    The default travel is lower-left to upper-right because that is where the
    battle stage puts the caster and the enemies; a lance flying the other way
    would read as the player being attacked.
    """
    from PIL import ImageChops
    rng = random.Random(seed)
    x0, y0 = start[0] * W, start[1] * H
    x1, y1 = end[0] * W, end[1] * H
    ang = math.atan2(y1 - y0, x1 - x0)
    nx, ny = -math.sin(ang), math.cos(ang)          # unit normal

    # A SPEAR PROFILE, not a wedge: a long even shaft, a blade that swells
    # before the point, and a sharp tip. A shape that tapers evenly end to end
    # is a shard of light -- the swell is what the eye reads as a weapon.
    N = 120
    line = [(x0 + (x1 - x0) * i / N, y0 + (y1 - y0) * i / N) for i in range(N + 1)]
    halves = []
    for i in range(N + 1):
        t = i / N
        if t < 0.55:                       # shaft, slowly thickening
            hw = width * (0.30 + 0.22 * (t / 0.55))
        elif t < 0.82:                     # blade shoulders
            hw = width * (0.52 + 0.48 * ((t - 0.55) / 0.27))
        else:                              # converge to the point
            hw = width * (1.0 - ((t - 0.82) / 0.18) ** 0.75)
        halves.append(max(0.6, hw))

    # ⚠ The body is drawn at 150, NOT 255. light() keeps the mask value as the
    # core and adds the halo on top, so a solid filled at full white comes back
    # pure white with the hue only in a thin fringe -- which is what made the
    # first attempt read as a laser beam rather than as ice. Held below white,
    # the ice color survives across the whole body and the bright marks below
    # are what actually catch the light.
    mask = ribbon(line, halves, fill=150)
    d = ImageDraw.Draw(mask)

    # Facets along the shaft, and the tip lit hardest.
    for f in (-0.55, -0.2, 0.18, 0.5):
        pts = [(px + nx * hw * f, py + ny * hw * f)
               for (px, py), hw in zip(line, halves)]
        d.line(pts, fill=245, width=2)
    d.line([line[int(N * 0.86)], line[N]], fill=255, width=5)

    # Frost shards shed along the flight path.
    for _ in range(22):
        t = rng.uniform(0.10, 0.80)
        px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        off = rng.choice((-1, 1)) * rng.uniform(width * 0.7, width * 2.0)
        L = rng.uniform(16, 62)
        a = ang + rng.choice((-1, 1)) * rng.uniform(0.5, 1.2)
        d.line([(px + nx * off, py + ny * off),
                (px + nx * off + math.cos(a) * L, py + ny * off + math.sin(a) * L)],
               fill=rng.randint(110, 230), width=rng.randint(2, 5))

    # A dim motion trail BEHIND the tail, tapering away off-frame.
    trail = Image.new("L", (W, H), 0)
    td = ImageDraw.Draw(trail)
    reach = math.hypot(W, H) * 0.45
    for i in range(60):
        t0, t1 = i / 60.0, (i + 1) / 60.0
        v = int(80 * (1.0 - t0) ** 2)
        w = max(1, int(width * 0.5 * (1.0 - t0)))
        td.line([(x0 - math.cos(ang) * reach * t0, y0 - math.sin(ang) * reach * t0),
                 (x0 - math.cos(ang) * reach * t1, y0 - math.sin(ang) * reach * t1)],
                fill=v, width=w)
    return ImageChops.add(light(mask, hue), light(trail, hue))


def dark_crescent(rim_hue, seed=17, rim_px=9):
    """A yin arc: a VOID torn across the frame, lit only at its edge.

    ⚠ A DARK EFFECT CANNOT BE AN ADDITIVE PLATE. Additive compositing adds
    light, and black adds nothing -- so a black arc drawn that way is
    literally invisible. The plate is opaque instead, and the arc is read by
    the absence of light inside a luminous rim.

    That inverts the repo's bloom rule rather than breaking it. The rule says
    a white-hot CORE with the hue surviving only in the halo; here the core is
    a hole and the hue lives on the boundary. Both say the same thing: the
    color belongs where the intensity is falling off.

    The core has to be punched back to black AFTER the glow is built, because
    bloom spreads inward as well as outward and would otherwise fill the void
    with the very light it is supposed to be missing.
    """
    from PIL import ImageChops
    rng = random.Random(seed)

    # An explicit arc, swept the way the blade travels on the battle stage:
    # up from the lower left, across, and down to the right. Thickest at the
    # middle of the stroke and tapering to nothing at both ends, which is the
    # shape a real cut leaves.
    N = 200
    line, halves = [], []
    for i in range(N + 1):
        t = i / N
        x = -W * 0.06 + W * 1.12 * t
        y = H * 0.74 - math.sin(t * math.pi) * H * 0.46
        line.append((x, y))
        halves.append(max(1.0, math.sin(t * math.pi) ** 0.7 * H * 0.115))
    arc = ribbon(line, halves)

    # Shrink by blur-and-threshold rather than repeated MinFilter: one radius
    # is the rim width in pixels, which is the number worth tuning.
    core = arc.filter(ImageFilter.GaussianBlur(rim_px)).point(
        lambda v: 255 if v > 200 else 0)
    rim = ImageChops.subtract(arc, core)

    # Ragged marks ALONG THE RIM ONLY, so the cut looks torn rather than
    # machined. Drawn onto the rim after the core is taken out, or they would
    # be erased by the void punch below.
    d = ImageDraw.Draw(rim)
    for _ in range(80):
        t = rng.uniform(0.05, 0.95)
        i = int(t * N)
        px, py = line[i]
        side = rng.choice((-1, 1))
        xa, ya = line[max(0, i - 1)]
        xb, yb = line[min(N, i + 1)]
        a = math.atan2(yb - ya, xb - xa)
        nx, ny = -math.sin(a), math.cos(a)
        ox, oy = px + nx * halves[i] * side, py + ny * halves[i] * side
        L = rng.uniform(14, 90)
        sa = a + side * rng.uniform(0.35, 1.15)
        d.line([(ox, oy), (ox + math.cos(sa) * L, oy + math.sin(sa) * L)],
               fill=rng.randint(150, 255), width=rng.randint(2, 5))

    img = light(rim, rim_hue)
    img.paste((0, 0, 0), (0, 0), core)          # punch the void back out
    return img


ICE = (120, 214, 255)
QI = (150, 96, 255)
BLAST = (255, 150, 70)
GOLD = (255, 198, 74)
YIN = (150, 60, 235)          # the rim of a shadow blade, not its body
# ⚠ COLOR IS ASSIGNED PER TECHNIQUE, NOT PER CHARACTER, and getting that
# backwards has already produced two wrong plates. The protagonist's ice is
# AZURE, his sword style is SILVER, and his yin technique is BLACK -- three
# different looks for one man. Meanwhile the purple above is a different
# character's ki entirely. Do not reach for a plate because the shape fits.
STEEL = (196, 220, 255)       # an enemy's mundane blade: cold, slightly dim
SILVER = (232, 240, 252)      # the sword style: a bright colorless flash
AZURE = (64, 150, 255)        # the ice spells
# The yin arc's edge. AZURE rather than colorless, and the reason is
# legibility rather than palette: the arc's body is a void and the plate
# behind it is black, so with a white rim the whole effect can vanish into
# the frame it is drawn on. A colored edge is what keeps a black shape
# readable against black.
VOID_RIM = AZURE

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
    # The defensive ice barrier.
    "crescent_ice": crescent(ICE),
    # An explosive going off.
    "burst_blast": convergence((W * 0.50, H * 0.56), 170, BLAST, seed=303),
    # A small object thrown across frame. Shown ADDITIVELY rather than as an
    # opaque plate: the other plates cut the scene to black for an impact, and
    # blacking out a quiet conversation for a thrown object would hit far
    # harder than the moment is.
    "streak_gold": streak(GOLD),
    # The ice lance: a rigid spear thrown from the caster's corner of the
    # battle stage toward the enemies' corner.
    "lance_ice": lance(AZURE),
    # The yin arc: a void with a lit edge. See dark_crescent()
    # for why this one cannot be an additive plate like the ice.
    "crescent_dark": dark_crescent(VOID_RIM),
    # AN ENEMY'S SWING, which has to be told apart from the player's at a
    # glance because the two land seconds apart in the same frame.
    #
    # Two things separate them, both deliberate. The TILT is mirrored -- the
    # player's beam leans one way and this leans the other -- and the COLOR is
    # plain steel rather than ki. A slash is a symmetric line and carries no
    # direction of its own, so tilt is the only geometric cue available;
    # reusing the player's plate would read as the player swinging on the
    # enemy's turn.
    # ⚠ POSITIVE ANGLES LEAN "\", NOT "/". Screen y increases DOWNWARD, so
    # +24 degrees runs upper-left to lower-right. Getting this backwards is
    # easy and silent -- the plate still looks like a slash, just the wrong
    # way -- so check the sign against the stage rather than the intuition.
    #
    # The battle stage puts the player lower-left and the enemies upper-right,
    # which makes "/" the axis an attack actually travels along. The player
    # gets that axis; the enemy's swing is deliberately CROSSED against it,
    # which is the only cue a symmetric line can carry about who is swinging.
    "slash_steel": beam(math.radians(24), 22, STEEL),
    # THE SWORD STYLE: silver, which is also the word the prose uses for it.
    #
    # ⚠ It is NOT the purple above. That belongs to a different character --
    # the scenes use it for his pressure, and the protagonist answers it with
    # frost rather than sharing it.
    #
    # This and slash_steel are deliberately close in color, because both are
    # ordinary blades catching light and dressing one of them up would be a
    # lie about what it is. They are told apart by TILT, by this one being
    # brighter and heavier, and by the line that names who swung.
    "slash_silver": beam(math.radians(-28), 27, SILVER),
}

for name, img in plates.items():
    p = os.path.join(OUT, name + ".png")
    img.save(p)
    print(f"{name:14} {os.path.getsize(p) / 1024:7.0f} KB  {p}")
