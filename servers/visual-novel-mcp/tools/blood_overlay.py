"""Draw a dried-blood layer for a matted character sprite.

    python blood_overlay.py <body.png> [strength] [seed]

Writes <body>_blood.png (the RGBA layer alone, for tuning or hand-editing)
and <body>_hurt.png (the layer composited onto the body).

WHY THIS EXISTS
---------------
A character who appears both intact and wounded does not need two renders.
Generate him CLEAN -- that is the version that gets recycled as any other
rank-and-file mob -- and lay the damage over it for the scene that needs it.
Damage on a separate layer can be tuned or pulled off; damage baked into a
render cannot.

⚠ THE HARD LIMIT, inherited from decay_overlay.py and just as binding here:
AN OVERLAY ADDS AND CANNOT SUBTRACT. It can put blood ON a robe. It cannot
TEAR one, because a tear removes cloth the sprite contains and reveals what
was behind it. "Torn and tattered" is a second render or the author's brush;
only "dried bloodstains" is in range. Do not extend this tool toward tears.

WHY IT IS NOT DRAWN AS GEOMETRY
-------------------------------
Same split the sibling tools already draw. magic_circle and fx_plates
CONSTRUCT geometry -- rings, rune bands, star polygons -- because diffusion
cannot place those accurately. Blood is the opposite: irregular, and any
shape regular enough to name reads as a shape. So stains are clustered blobs
at several scales and runs are gravity-aligned walks with per-step jitter.
Deterministic from the seed, organic in form.

⚠ IT MUST READ AGAINST THE COSTUME IT LANDS ON, and this is the thing that
decides whether the pass is worth anything. Dried blood is a dark
desaturated red. On a CHARCOAL robe that is nearly the same value as the
fabric and vanishes; on the off-white inner robe and on skin it reads
immediately. So placement is WEIGHTED BY LOCAL LUMINANCE rather than
scattered evenly -- the same principle as decay_overlay refusing to put mold
in the sky, for the same reason: an overlay that lands where it cannot be
seen is indistinguishable from no overlay at all.

Blood is composited as a DARKENING, not an additive glow. Additive is for
light (see the bloom rules); a stain absorbs.

⚠ NOTHING IS DRAWN ON THE FACE, and that exclusion is load-bearing rather
than cosmetic -- the luminance weighting aims at it, because skin is the
lightest thing on the figure. See spare_the_face().
"""
import os
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# Dried blood, not fresh: darker, browner and less saturated than arterial red.
BLOOD = (94, 22, 20)
BLOOD_DARK = (58, 14, 14)


def body_mask(im, erode_px=2):
    """The figure's own alpha, pulled in slightly.

    Blood painted right up to the silhouette edge haloes against whatever the
    sprite is composited over, because the outer pixels are the soft matte
    ramp rather than solid figure.
    """
    a = im.split()[3].point(lambda v: 255 if v > 200 else 0)
    for _ in range(erode_px):
        a = a.filter(ImageFilter.MinFilter(3))
    return a


# Fraction of the figure's height, from the top, that is off limits: head,
# neck AND shoulders. Nothing is drawn there. See spare_the_face().
#
# It started at 0.16 -- head only -- which cleared the face but pushed the
# big patches into the collar and shoulder line, high on the chest. The
# author's correction: they belong lower and outboard, on the side of the
# chest. So the band now runs past the shoulders, and the large stains get a
# placement region of their own below it rather than merely being allowed
# anywhere that is not forbidden.
HEAD_FRACTION = 0.22

# Where the SOAKED PATCHES go: the side of the chest. Fractions of figure
# height for the band, and a horizontal bias away from the centerline, so
# they land outboard on the ribs rather than centered on the sternum.
CHEST_BAND = (0.26, 0.48)


def spare_the_face(mask, head_fraction=HEAD_FRACTION):
    """Zero the weight over the head. NOT optional, and not squeamishness.

    ⚠ THE LUMINANCE WEIGHTING AIMS STRAIGHT AT THE FACE IF YOU LET IT. Skin
    is the lightest thing on the figure, so it scores highest on exactly the
    "where will this read" test that makes the rest of the pass work. The
    weighting and the face exclusion have to be added together or the tool
    reliably does the wrong thing well.

    THE AUTHOR'S ACTUAL REASON, recorded because a previous version of this
    docstring argued something else: with blood on it the face came back
    "completely concealed ... like a mask", and crucially "not bloody". It
    did not read as an injury at all -- it read as a flat covering. That was
    a COMPOSITING bug, not a placement one (see composite_stain), and it was
    worst on the face only because a face is small, light and dense with
    detail, so flat paint erases the most there.

    A sprite also has to ACT, and marks across the face fight the
    expression, which is the one thing a sprite carries at conversation
    distance. That is a real second reason to keep it clear. But it is NOT
    why the author asked, and an earlier draft here also claimed a bloodied
    face "escalates the injury the script describes" -- reasoning invented
    after the fact to dress up a note that was really about the art looking
    wrong. Do not restore it.

    Implemented as a proportional band rather than by detecting the head,
    because this figure's arms hang at his sides, so the top of the alpha
    bbox is head and nothing else. If a future sprite is posed with a hand
    raised past the chin, revisit this -- it would spare the hand too.
    """
    W, H = mask.size
    out = mask.copy()
    ImageDraw.Draw(out).rectangle([0, 0, W, int(H * head_fraction)], fill=0)
    return out


def luminance_weight(im, mask):
    """Per-pixel weight for how well a stain would READ there.

    Light fabric scores high, charcoal scores low. Returned as an L-mode
    image so it can be multiplied straight into the layer's alpha.
    """
    lum = im.convert("L")
    # Below ~70 the robe is dark enough that a stain is invisible; above ~150
    # it reads fully. Ramp between, and zero outside the figure.
    w = lum.point(lambda v: 0 if v < 70 else min(255, int((v - 70) * 255 / 80)))
    return ImageChops.multiply(w, spare_the_face(mask))


def chest_side_weight(weight):
    """Restrict to the chest band and push outboard from the centerline.

    Two separate biases, and both are needed. The band alone would center
    the patches on the sternum, which reads as a chest wound straight
    through the middle; the side bias alone would run stains down the whole
    length of the figure. Together they put them where a body takes a blow
    from someone standing beside you.
    """
    W, H = weight.size
    out = Image.new("L", (W, H), 0)
    src, dst = weight.load(), out.load()
    top, bot = int(H * CHEST_BAND[0]), int(H * CHEST_BAND[1])
    cx = W / 2.0
    for y in range(top, bot):
        for x in range(W):
            v = src[x, y]
            if not v:
                continue
            # 0 at the centerline, 1 at either edge; kept off zero so a
            # narrow figure still has somewhere to put them.
            side = 0.25 + 0.75 * min(1.0, abs(x - cx) / (cx or 1))
            dst[x, y] = int(v * side)
    return out


def pick_sites(rng, mask, weight, n):
    """Sample n stain centers, rejecting points that would not read."""
    W, H = mask.size
    mpx, wpx = mask.load(), weight.load()
    out, tries = [], 0
    while len(out) < n and tries < 20000:
        tries += 1
        x, y = rng.randrange(W), rng.randrange(H)
        if not mpx[x, y]:
            continue
        # Accept in proportion to how well it would show.
        if rng.randrange(255) < wpx[x, y]:
            out.append((x, y))
    return out


def blob(draw, rng, x, y, r, color, alpha):
    """One irregular stain: overlapping ellipses at jittered offsets."""
    for _ in range(rng.randint(4, 8)):
        dx, dy = rng.uniform(-r * .6, r * .6), rng.uniform(-r * .6, r * .6)
        rr = r * rng.uniform(.45, 1.0)
        draw.ellipse([x + dx - rr, y + dy - rr * rng.uniform(.7, 1.3),
                      x + dx + rr, y + dy + rr * rng.uniform(.7, 1.3)],
                     fill=color + (alpha,))


def run(draw, rng, x, y, mask, length, width, color, alpha):
    """A drip, walking DOWNWARD with jitter and thinning as it goes.

    Gravity is the whole point: a run that wanders sideways reads as a smear
    and puts the viewer on a ceiling.
    """
    mpx = mask.load()
    W, H = mask.size
    w = width
    for _ in range(length):
        y += rng.uniform(0.8, 1.6)
        x += rng.uniform(-0.55, 0.55)
        w *= rng.uniform(0.965, 0.998)
        if not (0 <= int(x) < W and 0 <= int(y) < H) or not mpx[int(x), int(y)]:
            break
        draw.ellipse([x - w, y - w, x + w, y + w], fill=color + (alpha,))
        if w < 0.6:
            break
    return x, y


def composite_stain(base, layer):
    """Lay the stain on by MULTIPLYING, not by painting over.

    ⚠ THIS IS THE DIFFERENCE BETWEEN BLOOD AND A MASK, and the first version
    of this tool got it wrong while the docstring above it claimed
    otherwise. `alpha_composite` puts flat opaque color ON TOP of the
    pixels, so every fold, shadow and feature underneath is gone and what is
    left is a solid shape in the outline of a splash. The author's verdict
    on that output was exact: concealed, "like a mask", and "not bloody".

    A stain ABSORBS light in proportion to what is already there. Multiply
    does that: the fabric's own shading, the seams and the linework all
    survive and simply darken and go red. Cheap, correct, and it is what
    makes the result read as something soaked INTO the cloth rather than
    sitting on it.

    Where the layer is transparent the tint is white, which is multiply's
    identity, so untouched pixels come through exactly unchanged.
    """
    rgb = base.convert("RGB")
    alpha = layer.split()[3]
    tint = Image.new("RGB", base.size, (255, 255, 255))
    tint.paste(layer.convert("RGB"), (0, 0), alpha)
    out = Image.composite(ImageChops.multiply(rgb, tint), rgb, alpha)
    out = out.convert("RGBA")
    out.putalpha(base.split()[3])
    return out


def main(argv):
    if not argv:
        sys.exit(__doc__.strip().split("\n\n")[0])
    src = argv[0]
    strength = float(argv[1]) if len(argv) > 1 else 1.0
    seed = int(argv[2]) if len(argv) > 2 else 7

    rng = random.Random(seed)
    im = Image.open(src).convert("RGBA")
    W, H = im.size
    mask = body_mask(im)
    weight = luminance_weight(im, mask)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Big soaked patches, then their runs, then fine spatter -- coarse to fine,
    # so the small marks sit on top of the large ones rather than under them.
    big = pick_sites(rng, mask, chest_side_weight(weight), 5)
    for x, y in big:
        r = rng.uniform(W * .045, W * .085) * strength
        blob(d, rng, x, y, r, BLOOD_DARK, int(215 * strength))
        for _ in range(rng.randint(2, 4)):
            run(d, rng, x + rng.uniform(-r, r), y + r * .6, mask,
                int(H * rng.uniform(.05, .16)), r * .16,
                BLOOD_DARK, int(200 * strength))

    for x, y in pick_sites(rng, mask, weight, 14):
        blob(d, rng, x, y, rng.uniform(W * .012, W * .03) * strength,
             BLOOD, int(185 * strength))

    for x, y in pick_sites(rng, mask, weight, 90):
        r = rng.uniform(0.7, 2.6)
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=BLOOD + (int(rng.uniform(120, 210) * strength),))

    # Soften very slightly: dried blood has a soaked edge, not a cut one.
    layer = layer.filter(ImageFilter.GaussianBlur(0.6))
    # Clip hard to the figure so nothing sits in open air.
    layer.putalpha(ImageChops.multiply(layer.split()[3], spare_the_face(mask)))

    base = os.path.splitext(src)[0]
    lay_path, hurt_path = base + "_blood.png", base + "_hurt.png"
    layer.save(lay_path)

    hurt = composite_stain(im, layer)
    hurt.save(hurt_path)

    cov = sum(1 for v in layer.split()[3].getdata() if v > 12)
    fig = sum(1 for v in mask.getdata() if v > 0)
    print("blood_overlay: %dx%d  seed %d  strength %.2f" % (W, H, seed, strength))
    print("  coverage    %.1f%% of the figure" % (100.0 * cov / max(fig, 1)))
    print("  LAYER  -> %s" % lay_path)
    print("  HURT   -> %s" % hurt_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
