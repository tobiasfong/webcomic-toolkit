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


def beam(angle, thickness, hue, offset=0, fill=255):
    """One hard diagonal blade of light across the whole frame.

    ⚠ `fill` IS WHAT DECIDES WHETHER THE HUE SURVIVES, not the hue argument.
    light() keeps the mask value as the core and adds the halo around it, so a
    beam filled at 255 comes back WHITE whatever hue is passed -- the color
    lives only in a fringe too thin to read. That is correct for a blade of
    light and wrong for a dull one: a gray beam at full fill is just a white
    beam. Drop the fill and the hue comes back.

    Same mechanism that made the ice lance look like a laser on its first
    pass. Anything meant to read as dim, dull or colored belongs below 255.
    """
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    cx, cy = W / 2, H / 2 + offset
    dx, dy = math.cos(angle), math.sin(angle)
    reach = math.hypot(W, H)
    d.line([(cx - dx * reach, cy - dy * reach), (cx + dx * reach, cy + dy * reach)],
           fill=fill, width=thickness)
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


def shuriken(hue, center=(0.56, 0.44), radius=None, points=4, spin=True):
    """A thrown star, mid-flight and mid-spin.

    A star is the one shape here that must NOT read as a line. beam() and
    lance() both carry an axis, and a spinning object has none -- so the
    motion is expressed as CONCENTRIC ARCS around the body rather than as a
    trail behind it. Arcs say rotation; a tapered trail would say it was
    sliding sideways without turning, which is the wrong verb entirely.

    Drawn small against the frame on purpose. The other plates fill the
    screen because they are events; this is an OBJECT, and an object the size
    of the screen reads as a logo rather than as something thrown.
    """
    from PIL import ImageChops
    R = radius or W * 0.075
    cx, cy = center[0] * W, center[1] * H
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)

    # The star body: alternating outer points and inner waist, which is what
    # gives a shuriken its concave edges. A plain polygon of outer points
    # would be a diamond.
    pts = []
    for i in range(points * 2):
        a = math.pi * i / points - math.pi / 4
        r = R if i % 2 == 0 else R * 0.34
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    d.polygon(pts, fill=225)
    # A hole at the center, the way a real one is bored.
    hr = R * 0.11
    d.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=0)

    if spin:
        # Two partial rings, offset and unequal, so the blur reads as ROTATION
        # rather than as a target reticle. Full circles would look drawn.
        arcs = Image.new("L", (W, H), 0)
        ad = ImageDraw.Draw(arcs)
        for rr, start, extent, val, wid in ((R * 1.16, 20, 150, 150, 5),
                                            (R * 1.34, 200, 120, 95, 4),
                                            (R * 0.92, 300, 100, 120, 3)):
            ad.arc([cx - rr, cy - rr, cx + rr, cy + rr],
                   start, start + extent, fill=val, width=wid)
        return ImageChops.add(light(mask, hue), light(arcs, hue))
    return light(mask, hue)


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

    # ⚠ A CRESCENT IS TWO OVERLAPPING DISCS, NOT A BAND.
    #
    # The first version swept a ribbon of even thickness along an arc, and it
    # read as two parallel curved lines rather than as a shape -- the author's
    # word was "weird". A moon crescent is fat through the belly and comes to
    # a POINT at each horn, and only a disc subtracted from a disc does that:
    # the thickness falls away on its own toward the intersections, which is
    # exactly the taper a ribbon has to fake and fakes badly.
    #
    # This is the same construction the old crescent() uses and it is not the
    # reason that one is thin -- ITS two ellipses were nearly identical, so
    # almost nothing survived the subtraction. Sized deliberately, the method
    # is right.
    #
    # Geometry: outer disc radius R at the center; inner disc radius r offset
    # by d toward the opening. Belly thickness is R + d - r, so the three
    # numbers are chosen from the thickness wanted rather than by eye.
    R = H * 0.62
    belly = H * 0.30                       # how fat through the middle
    d = R * 0.26                           # how far the bite is offset
    r = R + d - belly
    cx, cy = W * 0.46, H * 0.52
    # Opening toward the upper right, so the concave face looks the way the
    # blade travels on the battle stage.
    ang = math.radians(-32)
    ox, oy = cx + math.cos(ang) * d, cy + math.sin(ang) * d

    outer = Image.new("L", (W, H), 0)
    inner = Image.new("L", (W, H), 0)
    ImageDraw.Draw(outer).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    ImageDraw.Draw(inner).ellipse([ox - r, oy - r, ox + r, oy + r], fill=255)
    arc = ImageChops.subtract(outer, inner)

    # Shrink by blur-and-threshold rather than repeated MinFilter: one radius
    # is the rim width in pixels, which is the number worth tuning.
    core = arc.filter(ImageFilter.GaussianBlur(rim_px)).point(
        lambda v: 255 if v > 200 else 0)
    rim = ImageChops.subtract(arc, core)

    # A little brush texture on the rim, so the edge is not a machined curve.
    #
    # SHORT AND TANGENTIAL, and far fewer than before. The previous version
    # threw long spikes outward at steep angles, which is what a torn hole
    # looks like -- not what a blade leaves. Strokes that lie ALONG the edge
    # read as ink drag; strokes that stand off it read as damage.
    #
    # Sampled from the rim mask itself rather than from a parametric
    # centerline, so the texture follows whatever shape the discs produced.
    import numpy as np
    ys, xs = np.nonzero(np.asarray(rim) > 0)
    dd = ImageDraw.Draw(rim)
    if len(xs):
        for _ in range(38):
            j = rng.randrange(len(xs))
            px, py = float(xs[j]), float(ys[j])
            # Tangent at this point: perpendicular to the radius from the
            # outer disc's center, which is the edge the eye actually follows.
            a = math.atan2(py - cy, px - cx) + math.pi / 2
            a += rng.uniform(-0.25, 0.25)
            L = rng.uniform(10, 46)
            dd.line([(px - math.cos(a) * L * 0.5, py - math.sin(a) * L * 0.5),
                     (px + math.cos(a) * L * 0.5, py + math.sin(a) * L * 0.5)],
                    fill=rng.randint(170, 255), width=rng.randint(2, 4))

    # ⚠ HELD BELOW WHITE so the rim is actually the color asked for. light()
    # keeps the mask value as the core, so a rim at 255 comes back a WHITE
    # line with the hue only in the halo around it -- correct for a blade of
    # light, wrong here, where the rim IS the color and the body is nothing.
    # Same mechanism as beam()'s `fill`, and the third place it has bitten.
    rim = rim.point(lambda v: int(v * 0.55))

    img = light(rim, rim_hue)
    img.paste((0, 0, 0), (0, 0), core)          # punch the void back out
    return img


def rake(hue, angle, thickness, gaps, bow=0.16, fill=232, seed=5, span=0.78):
    """Parallel gashes: a claw, not a blade.

    THREE STROKES, NOT ONE, and that is the whole read. A single beam is a
    sword; what makes a paw legible is repetition at a fixed spacing, which
    is exactly the fine repeated detail diffusion smears and geometry gets
    right. `gaps` are perpendicular offsets in pixels from the center stroke.

    ⚠ TWO THINGS THE FIRST VERSION GOT WRONG, both visible only once drawn.

    THE TAPER MUST HAPPEN INSIDE THE FRAME. That version ran each stroke to
    0.62 of the frame DIAGONAL, so the tapered tips fell outside the picture
    and every visible pixel came from the fat middle -- three uniform tubes
    that read as neon, not as a wound. `span` is now a fraction of the frame
    WIDTH and stays under 1.0 so both tips land on screen.

    AND A CLAW RAKES IN AN ARC. A straight stroke is a blade; the curve is
    what says the mark was made by something swinging on a joint. `bow` is
    how far the middle bulges perpendicular to the stroke, as a fraction of
    its length.
    """
    rng = random.Random(seed)
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    cx, cy = W / 2, H / 2
    dx, dy = math.cos(angle), math.sin(angle)
    px, py = -dy, dx                     # perpendicular: spacing, and the bow
    reach = W * span / 2.0
    for gi, g in enumerate(gaps):
        ox, oy = cx + px * g, cy + py * g
        curve = bow * reach * (1.0 + rng.uniform(-0.18, 0.18))
        steps = 60
        pts = []
        for i in range(steps + 1):
            t = -1.0 + 2.0 * i / steps
            # the bow: zero at the tips, greatest at the middle
            b = curve * (1.0 - t * t)
            pts.append((ox + dx * reach * t + px * b,
                        oy + dy * reach * t + py * b))
        for i in range(steps):
            t = -1.0 + 2.0 * i / steps
            # fat in the middle, nothing at the tips
            w = thickness * max(0.0, 1.0 - abs(t) ** 1.7) ** 0.75
            if w < 0.8:
                continue
            d.line([pts[i], pts[i + 1]], fill=fill, width=max(1, int(round(w))))
        # a claw leaves the deepest cut where it bites in: a short thickening
        # a third of the way along, so the stroke is not symmetrical.
        j = int(steps * 0.38)
        d.line([pts[j], pts[j + 1]], fill=fill,
               width=max(1, int(round(thickness * 1.15))))
    return light(mask, hue)


def jaws(hue, fill=244, seed=23, n_teeth=9):
    """Two opposing arcs of solid fangs closing on each other.

    ⚠ THE TEETH ARE FILLED TRIANGLES, NOT TICKS ON A LINE. Two earlier
    versions drew this as strokes -- first as parallel lines, then as arcs
    with short perpendicular marks -- and neither said "bite". The author
    pointed at the Pokemon BITE animation, which is exactly right and
    exactly this: a curved row of solid pointed fangs, top and bottom,
    with the gap between them reading as the mouth.

    A thin mark is a cut. A filled wedge is a tooth. That is the whole
    difference, and no amount of tuning the line width gets there.
    """
    rng = random.Random(seed)
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    cx, cy = W * 0.5, H * 0.47
    rx = W * 0.27
    ry = H * 0.24
    gape = H * 0.055                     # half the opening between the jaws
    for sign in (-1, 1):                 # -1 upper jaw, +1 lower
        # the gum line: a shallow arc the fangs stand on
        pts = []
        for i in range(49):
            t = -1.0 + 2.0 * i / 48
            aa = t * 1.02
            pts.append((cx + math.sin(aa) * rx,
                        cy + sign * (gape + ry * (1.0 - math.cos(aa)) * 1.5)))
        for i in range(48):
            d.line([pts[i], pts[i + 1]], fill=fill, width=7)
        # the fangs, standing off the gum line INTO the gap
        for k in range(n_teeth):
            t = (k + 0.5) / n_teeth
            i = int(t * 48)
            x, y = pts[i]
            # longest at the front of the mouth, shorter toward the corners
            taper = 1.0 - abs(t - 0.5) * 1.45
            ln = max(6.0, ry * (0.62 * taper) * rng.uniform(0.88, 1.12))
            half = max(3.0, ln * 0.34)
            d.polygon([(x - half, y), (x + half, y), (x, y - sign * ln)],
                      fill=fill)
    return light(mask, hue)


def shock_rings(hue, center=(0.5, 0.46), n=5, fill=150, seed=11):
    """An expanding ring of sound: concentric arcs, thinning outward.

    A scream has no shape of its own, so the plate draws its EFFECT -- the
    pressure front. Rings rather than a burst because a burst reads as an
    explosion with a source object, and there is no object here, only a
    mouth. They thin and dim with radius so the eye reads outward travel
    rather than a target.

    Deliberately dim: this move does less damage than the slash it sits
    beside, and a plate that outshines the harder attack lies about it.
    """
    rng = random.Random(seed)
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    cx, cy = W * center[0], H * center[1]
    for i in range(n):
        f = (i + 1) / n
        r = W * (0.06 + 0.52 * f ** 0.85)
        wdt = max(1, int(round(11 * (1.0 - f) + 2)))
        v = int(fill * (1.0 - 0.62 * f))
        squash = 0.72 + rng.uniform(-0.04, 0.04)
        d.ellipse([cx - r, cy - r * squash, cx + r, cy + r * squash],
                  outline=v, width=wdt)
    return light(mask, hue)


def grasp(hue, n=7, fill=190, seed=17):
    """Hooked strokes closing inward: hands reaching from every side.

    The lesser spirits in this fight both "clutch at the living", so the plate is a
    GRAB rather than a strike -- curved talons converging on the center from
    the frame edges, arriving from all around because there are three of
    them and they surround him.

    Arcs rather than straight lines: a straight stroke inward is a spear,
    and the hook is what makes it a hand.
    """
    rng = random.Random(seed)
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    cx, cy = W * 0.5, H * 0.48
    for i in range(n):
        a = math.tau * i / n + rng.uniform(-0.16, 0.16)
        far = W * rng.uniform(0.30, 0.46)
        near = W * rng.uniform(0.10, 0.16)
        # a short arc swept about the center, so the talon curves as it closes
        sweep = rng.uniform(0.20, 0.34) * (1 if rng.random() < 0.5 else -1)
        steps = 26
        for k in range(steps):
            t0, t1 = k / steps, (k + 1) / steps
            r0 = far + (near - far) * t0
            r1 = far + (near - far) * t1
            a0, a1 = a + sweep * t0, a + sweep * t1
            wdt = max(1, int(round(9 * (1.0 - t0) + 2)))
            d.line([(cx + math.cos(a0) * r0, cy + math.sin(a0) * r0 * 0.8),
                    (cx + math.cos(a1) * r1, cy + math.sin(a1) * r1 * 0.8)],
                   fill=fill, width=wdt)
    return light(mask, hue)


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
GRAY = (146, 150, 158)        # a knife in the dark: dull, no ki at all
# A RIVAL'S LIGHTNING SWORD ART.
#
# VIOLET, by the author's call. A gold-white version was drawn first on the
# reasoning that purple already belongs to another character; he overruled it,
# and he is right that the collision is theoretical -- that character is not
# in the scene, and lightning is violet in this genre far more often than it
# is gold.
#
# It is deliberately PALER AND PINKER than QI (150, 96, 255), which is that
# other character's ki, so the two are not the same energy on screen if they
# ever do share a scene. It also suits the medium better: bloom wants a
# white-hot core with the hue surviving only in the halo, and a pale violet
# gives that where a saturated one goes muddy.
#
# ⚠ It still must not be AZURE. The strike lands in the same exchange as the
# protagonist's ice -- she shatters his trap, he answers with an ice barrier
# -- and two people trading blows in one color read as one person.
# The cave chapter. BEAST marks are warm and organic against the cast's cold
# ki; SPECTER belongs to the spirit boss alone, a sick green-white that answers to
# none of the existing magic systems so her attacks cannot be mistaken for
# anyone's technique.
BEAST = (255, 138, 92)
SPECTER = (176, 255, 214)
THUNDER = (208, 156, 255)
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
    "crescent_dark": dark_crescent(VOID_RIM, rim_px=10),
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
    # A SECOND ENEMY TYPE'S TWO MOVES.
    #
    # The stab is GRAY and THIN against the other steel: a jab at a weak
    # point, not a swing. It keeps the enemy tilt, so it still crosses the
    # caster's axis, but it is narrower and duller -- a knife in the dark has
    # no ki behind it and should not flash like a sword does.
    "slash_gray": beam(math.radians(30), 13, GRAY, fill=118),
    # The thrown star. See shuriken() for why the motion is arcs and not a
    # trail, and why it is small when everything else here fills the frame.
    "star_shuriken": shuriken(STEEL),
    # ---- A SWORD FORM PERFORMED RATHER THAN SWUNG -----------------------
    #
    # TWO MORE SILVER SLASHES, so the DEMONSTRATION can be three
    # strokes rather than one flash shown three times. He is not hitting
    # anyone here -- he is performing a form to prove which school trained
    # him, and the prose describes it as continuous: "The sword coils and
    # lashes, the blade almost bending from the sharp motions."
    #
    # One plate repeated reads as a stutter. Three ANGLES read as a sequence,
    # and they alternate direction -- steeper "/", then "\\" as the return
    # stroke -- because a form that only ever cuts one way looks like a loop.
    #
    # ⚠ Mind the sign: screen y grows DOWNWARD, so POSITIVE leans "\\".
    "slash_silver_2": beam(math.radians(-58), 24, SILVER, offset=-70),
    "slash_silver_3": beam(math.radians(16), 25, SILVER, offset=60),
    # THE CONJURED ICE SCULPTURE, and deliberately NOT one of the ice attack
    # plates. He is not striking anything -- he raises a hand and grows a
    # small frozen thing in front of a hostile stranger to make a point.
    #
    # The attack plates are opaque black frames that cut the scene away for
    # 50 ms, which is what sells an impact. Blacking out a street to show
    # someone conjuring an ornament would land far harder than the beat does,
    # so this one is drawn to be shown ADDITIVE: radial, small, contributing
    # only light. Same reasoning as the tossed gold token.
    # ⚠ THE ICE FLOWER IS NOT DRAWN HERE ANY MORE, AND SHOULD NOT BE.
    #
    # It was, three times -- a convergence() starburst, then a six-fold
    # snowflake, then a drawn rose of concentric petals -- and all three were
    # rejected. The author wanted a BLOOM OF ICE with volume: translucent
    # crystal, overlapping depth, light coming through it.
    #
    # That is the wrong side of the line this file exists to hold. GEOMETRY is
    # drawn because diffusion cannot place it -- a magic circle in an exact
    # spot, an arc of exact curvature, evenly spaced runes that would come
    # back as texture. A SHADED VOLUMETRIC OBJECT is the opposite case: it is
    # what diffusion is good at and what ImageDraw is bad at, because polygons
    # and a bloom filter cannot fake refraction.
    #
    # It is now generated instead and lives at images/fx/ice_flower.png. What
    # finally worked, after the smooth translucent version came back reading
    # as "just a blue flower": describing the MATERIAL DAMAGE rather than the
    # optics -- fractured shards, internal cracks, frost crust, icicles.
    # Clarity is what glass looks like; ice looks CRACKED. Then a second pass
    # on the SAME SEED replaced a furled heart with upright ice needles,
    # because a furled heart is bud-shaped and kept growing an organic bud.
    # THE RIVAL'S LIGHTNING SWORD ART. A lance rather than a beam: she drops
    # to a knee and drives the point into the ground, so the shape should
    # travel and taper rather than cross the frame evenly.
    "slash_thunder": lance(THUNDER, start=(0.82, 0.12), end=(0.24, 0.82),
                           width=52, seed=29),
    # --- the cave chapter, 2026-09-05 ---
    # A beast's claw. Three gashes, angled DOWNWARD across the frame the way
    # a big cat strikes, and warm against every cold plate the cast owns.
    "slash_claw": rake(BEAST, math.radians(-34), 30, (-64, 0, 66)),
    # Its bite. The same marks turned near-vertical and pulled tighter, so it
    # reads as jaws closing rather than a swipe -- two rows, not three.
    "bite_beast": jaws(BEAST),
    # The spirit's rake: her color, wider spacing, thinner strokes. She is a
    # bigger thing with narrower fingers.
    "slash_specter": rake(SPECTER, math.radians(-26), 20, (-92, -12, 70, 132),
                          fill=214, seed=41),
    # Her scream.
    "wail_specter": shock_rings(SPECTER),
    # The lesser ghosts clutching. Shared by both ghost types: they do the
    # same thing and the fight already tells them apart by name.
    "grasp_specter": grasp(SPECTER),
}

for name, img in plates.items():
    p = os.path.join(OUT, name + ".png")
    img.save(p)
    print(f"{name:14} {os.path.getsize(p) / 1024:7.0f} KB  {p}")
