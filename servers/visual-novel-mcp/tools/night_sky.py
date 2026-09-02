"""Replace a daytime sky with a drawn night sky, and grade the rest to match.

    python night_sky.py <day-plate.png> <out.png> [--seed N] [--moon x,y]

WHY THIS IS DRAWN AND NOT GENERATED
-----------------------------------
The obvious route is to hand the plate to an image model and ask for the same
scene at night. It was tried twice and failed both times, for the same reason:

  * A whole-canvas restyle REGENERATES the scene. Edge correlation against the
    day master came back at 0.117, where a plain tint scores 0.908. The
    buildings moved.
  * A MASKED edit does not fix it, because the model returns its own canvas
    size -- 1392x752 from a 1536x864 source, and not even the same aspect. Once
    the frame has been stretched, nothing lines up, mask or no mask.

A night sky is a gradient, some points of light and a disc. That is geometry,
which this project draws rather than prompts, exactly like the magic circles
and the impact plates. Drawn, it is exact, instant, free of GPU time, and
IDENTICAL ACROSS EVERY PLATE -- so the same moon hangs over the whole city on
the same night, which a per-plate generation would never give you.

HOW THE SKY IS FOUND
--------------------
decay_overlay's sky_mask, imported rather than reimplemented. ⚠ THAT
DETECTOR LIES ON DARK PLATES: run against a dim interior it flooded straight
through the ceiling and reported 75% sky. So the region is CHECKED before it is
used -- if what was found is not bright and not blue-ish, this refuses rather
than painting a moon onto somebody's roof.

THE REST OF THE FRAME still has to come down to night, or you get a starfield
over a sunlit street. That part is a grade, which is legitimate: the ground
does not change shape after dark, only its light. It is the SKY that a grade
cannot fix, because a dark blue daytime sky still reads as daytime.
"""
import math
import os
import random
import sys


from PIL import Image, ImageDraw, ImageFilter


def sky_region(im, debug=None):
    """The sky, cut along the horizon traced as a single continuous seam.

    WHY NOT A THRESHOLD -- measured, not assumed. On one city plate here
    the distant mountains are indistinguishable from the sky above them:

        open sky          luminance 147-172   texture 0.44-1.41
        mountain ridge    luminance 162       texture 0.57

    Identical on both axes. Every per-pixel rule therefore either eats the
    mountain or leaves vertical bars of sky hanging down between buildings,
    and no amount of tuning escapes that, because the information a threshold
    needs is not in the pixel.

    What IS there is the OUTLINE -- faint, but continuous, which is exactly
    why a person sees a mountain where a threshold sees sky. So the horizon is
    traced as a seam: the single top-to-bottom-bounded path across the frame
    that best follows the edge, found by dynamic programming.

      * The cost of putting the horizon at (x, y) is low where there is a
        strong DOWNWARD-DARKENING edge, since sky sits above ground.
      * Moving between columns costs something, so the seam cannot jump. A
        bar would need a cliff and a return; both are paid for.
      * A shallow penalty on depth breaks ties toward the FIRST boundary from
        the top, so the trace stops at the ridge rather than sliding down to
        the rooftops behind it.

    Continuity is thus a property of the algorithm rather than a repair
    applied afterwards -- torn chunks and bars are not filtered out, they are
    unreachable.
    """
    rgb = im.convert("RGB")
    w, h = rgb.size
    L = rgb.convert("L").filter(ImageFilter.GaussianBlur(1.2))
    lp = L.load()

    # ⚠ UNSIGNED, AND CHROMA AS WELL AS LUMINANCE. A signed "bright above,
    # dark below" edge finds nothing along the left ridge, because there the
    # mountain is slightly BRIGHTER than the sky (162 against 156) -- the step
    # is inverted, and a one-directional metric reads it as flat. The eye does
    # not care which way the step goes, only that there is one. The hue turn
    # matters too: sky is bluer than the terrain in front of it even where the
    # brightness matches, so the blue-minus-red difference carries the ridge
    # when luminance alone cannot.
    band = 3
    px = rgb.load()
    edge = [[0.0] * w for _ in range(h)]
    for y in range(band, h - band):
        for x in range(w):
            ra, ga, ba = px[x, y - band]
            rb, gb, bb = px[x, y + band]
            dl = abs(lp[x, y - band] - lp[x, y + band])
            dc = abs((ba - ra) - (bb - rb))
            edge[y][x] = dl + dc * 1.8

    top_limit = int(h * 0.03)
    bot_limit = int(h * 0.86)
    BIG = 1e9
    cost = [[BIG] * w for _ in range(h)]
    back = [[0] * w for _ in range(h)]
    # Strong enough to beat a lower, crisper edge: the wall and the water
    # below the city are sharper than a hazy ridge, so without a real cost
    # on depth the seam slides all the way down to them.
    depth_pen = 0.11

    for y in range(top_limit, bot_limit):
        cost[y][0] = -edge[y][0] + depth_pen * (y - top_limit)
    STEP = 4
    for x in range(1, w):
        for y in range(top_limit, bot_limit):
            best, bi = BIG, y
            for dy in range(-STEP, STEP + 1):
                yy = y + dy
                if top_limit <= yy < bot_limit:
                    c = cost[yy][x - 1] + abs(dy) * 1.6
                    if c < best:
                        best, bi = c, yy
            cost[y][x] = best - edge[y][x] + depth_pen * (y - top_limit)
            back[y][x] = bi

    y = min(range(top_limit, bot_limit), key=lambda yy: cost[yy][w - 1])
    horizon = [0] * w
    for x in range(w - 1, -1, -1):
        horizon[x] = y
        y = back[y][x]

    mask = Image.new("L", (w, h), 0)
    mp = mask.load()
    for x in range(w):
        for y in range(horizon[x]):
            mp[x, y] = 255
    if debug:
        d = Image.composite(Image.new("RGB", (w, h), (255, 0, 255)), rgb, mask)
        d.save(debug)
    return mask


def looks_like_sky(im, mask):
    """Guard against the detector flooding a dark interior.

    Real daytime sky is BRIGHT and leans blue. An interior ceiling is neither,
    and a flood that escaped into one will fail both tests.
    """
    rgb = im.convert("RGB")
    px, mp = rgb.load(), mask.load()
    w, h = rgb.size
    n = lum = blue = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            if mp[x, y] > 128:
                r, g, b = px[x, y]
                lum += 0.299 * r + 0.587 * g + 0.114 * b
                blue += b - r
                n += 1
    if not n:
        return False, "no sky found at all", 0.0, 0.0
    L, B = lum / n / 255.0, blue / n
    ok = L > 0.45 and B > -8
    why = "mean luminance %.3f, blue-minus-red %+.1f" % (L, B)
    return ok, why, L, B


def bloom(mask, radii=((1, 0.9), (4, 0.55), (12, 0.35), (34, 0.22))):
    """Sum several blur radii additively -- the repo's bloom rule."""
    acc = Image.new("F", mask.size, 0.0)
    ap = acc.load()
    for r, wgt in radii:
        b = mask.filter(ImageFilter.GaussianBlur(r))
        bp = b.load()
        for y in range(mask.height):
            for x in range(mask.width):
                ap[x, y] += bp[x, y] * wgt
    out = Image.new("L", mask.size)
    op = out.load()
    for y in range(mask.height):
        for x in range(mask.width):
            op[x, y] = min(255, int(ap[x, y]))
    return out


def draw_night_sky(size, seed=1, moon=(0.78, 0.18), horizon=1.0):
    """A deep gradient, a field of stars, and a moon -- all with real bloom."""
    w, h = size
    rng = random.Random(seed)
    sky = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(sky)
    top = (7, 10, 26)
    bot = (28, 38, 72)          # lifts toward the horizon, as a real sky does
    span = max(1, int(h * horizon))
    for y in range(h):
        t = min(1.0, y / float(span))
        d.line([(0, y), (w, y)],
               fill=(int(top[0] + (bot[0] - top[0]) * t),
                     int(top[1] + (bot[1] - top[1]) * t),
                     int(top[2] + (bot[2] - top[2]) * t)))

    stars = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(stars)
    for _ in range(int(w * h / 5200)):
        x, y = rng.uniform(0, w), rng.uniform(0, h * 0.92)
        r = rng.choice([0.6, 0.6, 0.8, 1.0, 1.4])
        sd.ellipse([x - r, y - r, x + r, y + r], fill=rng.randint(120, 255))
    mx, my = moon[0] * w, moon[1] * h
    mr = max(9.0, h * 0.045)
    sd.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=255)

    glow = bloom(stars)
    sp, gp = sky.load(), glow.load()
    for y in range(h):
        for x in range(w):
            g = gp[x, y]
            if g:
                r0, g0, b0 = sp[x, y]
                # White core, cool halo -- light, not a pale disc.
                sp[x, y] = (min(255, r0 + int(g * 0.95)),
                            min(255, g0 + int(g * 0.97)),
                            min(255, b0 + int(g * 1.0)))
    return sky


def grade_to_night(im, keep, target=0.145, ceiling=46.0):
    """Bring the non-sky part of the frame down to night, to a MEASURED level.

    ⚠ AIM AT A NUMBER, NOT AT A FEELING. A hand-picked multiplier here landed
    the city at 0.071 mean luminance against the 0.141 of the night plate the
    author had already approved -- twice as dark as the agreed look. At that
    depth a city of tiered roofs, banners and distant peaks collapses into one
    silhouette and reads as industrial, which is not a tuning problem you can
    see coming; it is only obvious once the number is next to the old one.

    So the tone curve is applied first for its SHAPE -- desaturate, cool,
    and hold the warm end -- and the level is then scaled to hit `target`
    exactly. 0.145 is the middle of the band the approved plates occupy.
    """
    rgb = im.convert("RGB")
    px = rgb.load()
    w, h = rgb.size
    kp = keep.load()

    # ⚠ HAZE IS A DEPTH CUE, AND AT NIGHT IT INVERTS. In daylight the far
    # distance is bright and low-contrast because air scatters light into it;
    # after dark there is no light to scatter, so the same distance goes
    # DARKER than the near ground, not lighter. Grading everything by one
    # curve keeps a hazy mountain proportionally bright and it ends up glowing
    # white against the sky -- which is the one thing that cannot happen at
    # night. So local contrast in the SOURCE is measured, and whatever is flat
    # and hazy is pushed down harder than whatever is crisp and near.
    L8 = im.convert("L")
    flat = L8.filter(ImageFilter.GaussianBlur(9))
    lp, fp = L8.load(), flat.load()
    detail = Image.new("L", (w, h), 0)
    dp2 = detail.load()
    for y in range(h):
        for x in range(w):
            dp2[x, y] = min(255, abs(lp[x, y] - fp[x, y]) * 6)
    detail = detail.filter(ImageFilter.GaussianBlur(11))
    dp2 = detail.load()
    vals = sorted(dp2[x, y] for y in range(0, h, 4) for x in range(0, w, 4)
                  if kp[x, y])
    hi = vals[int(len(vals) * 0.85)] if vals else 1

    # Pass 1: shape only.
    shaped = {}
    n = 0
    total = 0.0
    for y in range(h):
        for x in range(w):
            if not kp[x, y]:
                continue
            r, g, b = px[x, y]
            L = 0.299 * r + 0.587 * g + 0.114 * b
            # Warm sources keep more of themselves, so lantern light and red
            # banners stay warm instead of going gray with everything else.
            warm = max(0.0, (r - b) / 255.0)
            # 0 where the source is flat and hazy (far), 1 where it is crisp
            # and detailed (near).
            near = min(1.0, dp2[x, y] / float(hi)) if hi else 1.0
            k = (0.62 + 0.30 * warm) * (0.42 + 0.58 * near)
            nr = (L * 0.30 + r * 0.70) * k * 1.06
            ng = (L * 0.38 + g * 0.62) * k * 1.00
            nb = (L * 0.42 + b * 0.58) * k * 1.26
            shaped[(x, y)] = (nr, ng, nb)
            total += 0.299 * nr + 0.587 * ng + 0.114 * nb
            n += 1

    if n:
        mean = total / n / 255.0
        scale = (target / mean) if mean > 0 else 1.0
        # A hard clamp: never brighten, and never crush past half the target.
        scale = max(0.25, min(1.0, scale))
        for (x, y), (nr, ng, nb) in shaped.items():
            px[x, y] = (int(min(255, nr * scale)),
                        int(min(255, ng * scale)),
                        int(min(255, nb * scale)))
        # ⚠ HOLD THE HIGHLIGHTS DOWN. Scaling to a target MEAN preserves
        # relative brightness, so a hazy distant mountain -- bright in the day
        # plate because it is far away -- stays proportionally bright and ends
        # up glowing white against the night sky. At night the far distance
        # recedes; nothing back there should out-shine the sky itself. So the
        # top end is compressed with a soft knee toward the sky's own level,
        # which leaves the midtones and the lit windows alone.
        vals = sorted(0.299*r + 0.587*g + 0.114*b
                      for (r, g, b) in (px[k] for k in shaped))
        p98 = vals[int(len(vals) * 0.98)] if vals else 255
        if p98 > ceiling:
            for (x, y) in shaped:
                r, g, b = px[x, y]
                L = 0.299 * r + 0.587 * g + 0.114 * b
                if L <= ceiling:
                    continue
                over = (L - ceiling) / max(1.0, p98 - ceiling)
                f = (ceiling + (p98 - ceiling) * (over ** 0.45) * 0.42) / L
                px[x, y] = (int(r * f), int(g * f), int(b * f))
        after = 0.0
        for (x, y) in shaped:
            r, g, b = px[x, y]
            after += 0.299 * r + 0.587 * g + 0.114 * b
        print("ground: shaped %.3f, scaled x%.2f, highlights p98 %.0f -> final %.3f"
              % (mean, scale, p98, after / n / 255.0))
    return rgb


def window_lights(day, keep, strength=1.0, hue=(255, 176, 74)):
    """Light the windows that are already in the plate.

    ⚠ A GRADE CANNOT INVENT LIGHT. Darkening a daytime city gives you a
    silhouette, because in daylight the windows are UNLIT -- there is nothing
    in the source for a grade to preserve. A city that the script says blazes
    with golden light therefore cannot be produced by grading alone, and the
    result reads as industrial rather than inhabited.

    But the openings are in the plate. In daylight a window is a small DARK
    spot against a lighter facade, so it can be found: blur the frame, and
    wherever a pixel is markedly darker than its own surroundings, that is a
    recess. Cities have hundreds of them and they are a few pixels across,
    which is exactly the work a person should never be asked to do by hand.

    Two gates keep the lights on buildings:
      * LOCAL CONTRAST finds the recess itself.
      * LINE DENSITY decides whether it is architecture. Buildings in this art
        are dense with drawn detail; rock faces and foliage are not, so their
        crevices are rejected.
    """
    w, h = day.size
    L = day.convert("L")
    soft = L.filter(ImageFilter.GaussianBlur(5))
    lines = L.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(7))
    lp, sp, dp, kp = L.load(), soft.load(), lines.load(), keep.load()

    # Line density that counts as "built" -- measured from the frame itself so
    # a hazy city and a crisp one both work.
    vals = [dp[x, y] for y in range(0, h, 4) for x in range(0, w, 4) if kp[x, y]]
    vals.sort()
    built = vals[int(len(vals) * 0.72)] if vals else 255

    spots = Image.new("L", (w, h), 0)
    q = spots.load()
    step = 2
    for y in range(1, h - 1, step):
        for x in range(1, w - 1, step):
            if not kp[x, y] or dp[x, y] < built:
                continue
            recess = sp[x, y] - lp[x, y]
            if recess > 16 and lp[x, y] < 150:
                q[x, y] = min(255, int((recess - 16) * 9))
    glow = bloom(spots, radii=((0.8, 1.0), (2.5, 0.65), (7, 0.4)))
    gp = glow.load()
    out = day.copy()
    op = out.load()
    lit = 0
    for y in range(h):
        for x in range(w):
            g = gp[x, y]
            if not g:
                continue
            lit += 1
            r0, g0, b0 = op[x, y]
            a = (g / 255.0) * strength
            op[x, y] = (min(255, int(r0 + hue[0] * a)),
                        min(255, int(g0 + hue[1] * a * 0.82)),
                        min(255, int(b0 + hue[2] * a * 0.55)))
    print("window lights: %d source recesses, %d px touched"
          % (sum(1 for v in spots.getdata() if v), lit))
    return out


def light_interior(day, target=0.115, lamp=(0.30, 0.62), warm=(255, 168, 92)):
    """Night for a room: grade down, then LIGHT it from somewhere.

    An interior has no sky to replace, so the sky path does not apply -- and a
    uniformly dimmed daytime room is exactly what reads as "someone turned the
    brightness down" rather than as night. What makes a night interior legible
    is that it is LIT: one warm source, everything falling off away from it,
    and the far corners genuinely dark.

    So the daylight is graded out first, and a lamp is then put back in. The
    falloff does the work -- near the lamp the plate keeps its detail and its
    warmth, away from it the room goes cold and dim. Nothing is drawn on top;
    the existing pixels are simply lit differently.
    """
    rgb = day.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    lx, ly = lamp[0] * w, lamp[1] * h
    reach = math.hypot(w, h) * 0.62

    acc = 0.0
    n = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            d = math.hypot(x - lx, y - ly) / reach
            fall = max(0.0, 1.0 - d) ** 1.7          # 1 at the lamp, 0 far off
            amb = 0.16                                # moonlight floor
            k = amb + 0.95 * fall
            # Warm where the lamp reaches, cool where it does not.
            wr = (warm[0] / 255.0) * fall + 0.55 * (1 - fall)
            wg = (warm[1] / 255.0) * fall + 0.62 * (1 - fall)
            wb = (warm[2] / 255.0) * fall + 0.95 * (1 - fall)
            nr, ng, nb = r * k * wr, g * k * wg, b * k * wb
            px[x, y] = (int(min(255, nr)), int(min(255, ng)), int(min(255, nb)))
            acc += 0.299 * nr + 0.587 * ng + 0.114 * nb
            n += 1
    mean = acc / n / 255.0
    scale = max(0.3, min(1.6, target / mean)) if mean > 0 else 1.0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            px[x, y] = (int(min(255, r * scale)), int(min(255, g * scale)),
                        int(min(255, b * scale)))
    print("interior: lit from (%.2f, %.2f), graded %.3f, scaled x%.2f -> %.3f"
          % (lamp[0], lamp[1], mean, scale, mean * scale))
    return rgb


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if len(args) < 2:
        sys.exit(__doc__.strip().split("\n")[2].strip())
    src, dst = args[0], args[1]
    seed = 1
    moon = (0.78, 0.18)
    lights = 0.0
    maskfile = dumpmask = None
    ceiling = 46.0
    force = False
    skyonly = False
    interior = False
    lamp = (0.30, 0.62)
    for f in flags:
        if f.startswith("--seed="):
            seed = int(f.split("=", 1)[1])
        if f.startswith("--moon="):
            moon = tuple(float(v) for v in f.split("=", 1)[1].split(","))
        if f.startswith("--mask="):
            maskfile = f.split("=", 1)[1]
        if f.startswith("--dump-mask="):
            dumpmask = f.split("=", 1)[1]
        if f == "--interior":
            interior = True
        if f.startswith("--lamp="):
            lamp = tuple(float(v) for v in f.split("=", 1)[1].split(","))
        if f == "--sky-only":
            skyonly = True
        if f == "--force":
            force = True
        if f.startswith("--ceiling="):
            ceiling = float(f.split("=", 1)[1])
        if f.startswith("--lights"):
            lights = float(f.split("=", 1)[1]) if "=" in f else 1.0

    im = Image.open(src).convert("RGB")
    print("source %s  %sx%s" % (os.path.basename(src), im.width, im.height))

    if interior:
        out = light_interior(im, lamp=lamp)
        out.save(dst)
        print("wrote %s  %sx%s  (same size as the source)"
              % (dst, out.width, out.height))
        return 0

    if maskfile:
        # ⚠ A HAND-CORRECTED MASK WINS. Deciding sky per column cannot tell
        # "sky showing through a gap between buildings" from "sky running down
        # over a building" -- both are bright pixels below the skyline, and
        # every threshold that fixes one breaks the other. On a hazy plate
        # that is a real limit, not a tuning problem. Painting the mask takes
        # a few coarse strokes; painting the result does not. So the mask is
        # the seam where a person can intervene cheaply.
        mask = Image.open(maskfile).convert("L")
        if mask.size != im.size:
            sys.exit("Mask is %sx%s but the plate is %sx%s."
                     % (mask.size + im.size))
        print("using hand-corrected mask: %s" % os.path.basename(maskfile))
    else:
        mask = sky_region(im)
    if dumpmask:
        mask.save(dumpmask)
        print("wrote the computed mask to %s -- white is sky. Paint it and "
              "pass it back with --mask=" % dumpmask)
    ok, why, L, B = looks_like_sky(im, mask)
    cov = sum(1 for p in mask.getdata() if p > 128) / float(im.width * im.height)
    print("sky region: %.1f%% of frame, %s" % (100 * cov, why))
    if not ok and force:
        print("guard overridden (--force): treating that region as sky anyway")
    elif not ok:
        sys.exit("REFUSING: that region does not look like daytime sky. A dark "
                 "or enclosed plate floods through its own ceiling and the "
                 "moon would land on a roof. Nothing was written.")

    # ⚠ PLACE THE MOON INSIDE THE MASK, not at a fixed height. Drawn at a
    # guessed position it was cut in half by the skyline, because the sky in
    # this plate simply does not reach that far down.
    mp = mask.load()
    col = int(moon[0] * im.width)
    col = min(im.width - 1, max(0, col))
    rows = [y for y in range(im.height) if mp[col, y] > 128]
    if rows:
        mr_px = max(9.0, im.height * 0.045)
        lo, hi = rows[0], rows[-1]
        # Keep the whole disc, plus a little air, within the sky in this column.
        want = lo + (hi - lo) * 0.42
        want = min(max(want, lo + mr_px * 1.4), hi - mr_px * 1.4)
        if hi - lo > mr_px * 3:
            moon = (moon[0], want / float(im.height))
        else:
            moon = (moon[0], (lo + hi) / 2.0 / im.height)
        print("moon placed at y=%.0f (sky in that column spans %d..%d)"
              % (moon[1] * im.height, lo, hi))

    night = draw_night_sky(im.size, seed=seed, moon=moon)
    keep = Image.eval(mask, lambda v: 255 - v)
    if skyonly:
        # ⚠ DO NOT GRADE A PLATE THAT IS ALREADY GRADED. An evening or night
        # plate whose only fault is a daytime sky needs the sky swapped and
        # nothing else; running the night curve over it a second time takes
        # the ground to roughly half the agreed level and buries the art.
        print("sky only: the ground is left exactly as it is")
        out = im.convert("RGB")
    else:
        out = grade_to_night(im, keep, ceiling=ceiling)
    if lights:
        out = window_lights(out, keep, strength=lights)
    # Feather the join so the skyline does not get a hard cut.
    soft = mask.filter(ImageFilter.GaussianBlur(1.5))
    out = Image.composite(night, out, soft)
    out.save(dst)
    print("wrote %s  %sx%s  (same size as the source)"
          % (dst, out.width, out.height))


if __name__ == "__main__":
    main()
