"""Draw an ADDITIVE decay layer for a background plate: mold, rust, stains,
creeping growth.

    python decay_overlay.py <plate.png> [strength] [seed]

WHY THIS EXISTS
---------------
A location that appears both derelict and repaired does not need two renders.
Generate the REPAIRED plate — it is the one that accumulates screen time — and
lay decay over it for the scenes that need it.

⚠ THE HARD LIMIT, and it decides what this tool may attempt: AN OVERLAY ADDS
AND CANNOT SUBTRACT. It can put grime, rust and vines ON a wall. It cannot put
a hole THROUGH a roof, peel a board OFF a wall, or topple a gate, because all
three require removing geometry the plate contains. Structural decay belongs in
the prose, or in a second render. Do not extend this tool toward it.

WHY THE GROWTH IS NOT GEOMETRIC
-------------------------------
The sibling tools (magic_circle, fx_plates) draw GEOMETRY — rings, rune bands,
beams — because that is what diffusion cannot place accurately and what reads
correctly when constructed. Foliage is the opposite: it is irregular and
high-frequency, and geometric shapes read as shapes. So vines here are grown by
recursive branching with per-segment jitter, and mold by clustered blobs at
several scales. Deterministic, but organic in form.

Output is RGBA on transparency, the same size as the plate, for the author to
composite (or for a `show` over the background in-engine).
"""
import math
import os
import random
import sys
from collections import deque

from PIL import Image, ImageDraw, ImageFilter


def sky_mask(im, tol=42):
    """Which pixels are SKY, found by flooding inward from the top edge.

    ⚠ Decay must never land on sky. Nothing grows on air, and blobs scattered
    across the whole frame put mold in the clouds -- which is exactly what the
    first version did.

    A flood from the top is used rather than a colour test because sky is the
    one region guaranteed to touch the top edge and to be interrupted by the
    roofline. It therefore works on a night-graded plate as well as a daylight
    one, where a blue-vs-red test would not.
    """
    px = im.convert("RGB").load()
    W, H = im.size
    seen = bytearray(W * H)
    # Seed from every top-edge pixel; sky may be split by a roof or a tower.
    q = deque()
    for x in range(W):
        q.append((x, 0))
        seen[x] = 1
    ref = [px[x, 0] for x in range(0, W, max(1, W // 64))]
    ref = tuple(sum(c[i] for c in ref) / len(ref) for i in range(3))

    while q:
        x, y = q.popleft()
        c = px[x, y]
        if sum(abs(c[i] - ref[i]) for i in range(3)) > tol * 3:
            continue
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < W and 0 <= ny < H and not seen[ny * W + nx]:
                seen[ny * W + nx] = 1
                q.append((nx, ny))

    # ⚠ FILL THE HOLES. The flood stops wherever colour departs from the top-row
    # reference, which includes CLOUDS -- so a first version masked the blue but
    # left every cloud unprotected, and grime survived inside them. Anything
    # above the lowest sky pixel in a column is also sky.
    for x in range(W):
        low = -1
        for y in range(H - 1, -1, -1):
            if seen[y * W + x]:
                low = y
                break
        for y in range(low):
            seen[y * W + x] = 1

    m = Image.new("L", (W, H), 0)
    m.putdata([255 if v else 0 for v in seen])
    # Soften the edge so the cut-off is not a hard line along the roofs.
    return m.filter(ImageFilter.GaussianBlur(3))


def _vine(d, x, y, angle, length, width, rng, color, depth=0):
    """One creeper, grown by recursive branching rather than drawn as a shape."""
    if length < 6 or depth > 5:
        return
    steps = max(3, int(length / 7))
    px, py = x, y
    for i in range(steps):
        angle += rng.uniform(-0.32, 0.32)          # wander
        nx = px + math.cos(angle) * (length / steps)
        ny = py + math.sin(angle) * (length / steps)
        w = max(1, int(width * (1 - i / steps)))
        d.line([(px, py), (nx, ny)], fill=color, width=w)
        # leaves, thicker toward the tip
        if rng.random() < 0.45:
            r = rng.uniform(2.0, 4.5) * (0.5 + 0.5 * i / steps)
            d.ellipse([nx - r, ny - r, nx + r, ny + r], fill=color)
        px, py = nx, ny
        if rng.random() < 0.16:
            _vine(d, px, py, angle + rng.choice((-0.9, 0.9)),
                  length * rng.uniform(0.35, 0.6), width * 0.7, rng, color, depth + 1)


def _blobs(size, rng, n, rmin, rmax, color, blur):
    """Clustered patches — mold, rust, water staining."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    W, H = size
    for _ in range(n):
        cx, cy = rng.uniform(0, W), rng.uniform(0, H)
        for _ in range(rng.randint(4, 12)):        # a cluster, not a dot
            x = cx + rng.gauss(0, rmax * 1.6)
            y = cy + rng.gauss(0, rmax * 1.6)
            r = rng.uniform(rmin, rmax)
            d.ellipse([x - r, y - r, x + r, y + r], fill=color)
    return layer.filter(ImageFilter.GaussianBlur(blur))


def build(plate_path, strength=1.0, seed=11):
    im = Image.open(plate_path)
    W, H = im.size
    rng = random.Random(seed)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    a = lambda v: int(max(0, min(255, v * strength)))

    # Mold: cool green-black, low on the walls and in the corners.
    out = Image.alpha_composite(
        out, _blobs((W, H), rng, int(26 * strength), 6, 22, (46, 58, 40, a(78)), 9))
    # Rust and water staining: warm ochre, smaller and sparser.
    out = Image.alpha_composite(
        out, _blobs((W, H), rng, int(18 * strength), 3, 12, (110, 70, 34, a(70)), 5))
    # Grime: broad, very soft, darkening what it lies on.
    out = Image.alpha_composite(
        out, _blobs((W, H), rng, int(6 * strength), 24, 60, (30, 30, 28, a(38)), 34))

    # Creeping growth, climbing the SIDE MARGINS only.
    #
    # ⚠ This tool cannot see the plate. Grown from the whole bottom edge, vines
    # climb straight up through open ground -- on the first run they crossed a
    # flagstone courtyard in mid-air, because nothing told them a wall was not
    # there. The margins are where a wall meets the ground in almost any
    # composition, so that is where growth is allowed by default.
    #
    # For growth somewhere specific, pass a narrower `bands`, or take the
    # vines layer and place it by hand -- there is no substitute for knowing
    # where the walls are, and this tool does not.
    vines = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dv = ImageDraw.Draw(vines)
    for _ in range(int(14 * strength)):
        side = rng.random() < 0.5
        x = rng.uniform(0, W * 0.22) if side else rng.uniform(W * 0.78, W)
        lean = rng.uniform(0.05, 0.45) * (1 if side else -1)   # in from the edge
        _vine(dv, x, H + 10, -math.pi / 2 + lean,
              rng.uniform(H * 0.14, H * 0.38), rng.uniform(2.5, 5.0), rng,
              (54, 78, 42, a(150)))
    out = Image.alpha_composite(out, vines.filter(ImageFilter.GaussianBlur(0.6)))

    # Erase everything that fell on sky.
    sky = sky_mask(im)
    keep = Image.eval(sky, lambda v: 255 - v)
    alpha = out.getchannel("A")
    out.putalpha(Image.composite(alpha, Image.new("L", (W, H), 0), keep))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python decay_overlay.py <plate.png> [strength] [seed]")
    src = sys.argv[1]
    strength = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 11
    layer = build(src, strength, seed)
    base, _ = os.path.splitext(src)
    dst = f"{base}_decay.png"
    layer.save(dst)

    # A flattened preview, so the effect can be judged without compositing.
    plate = Image.open(src).convert("RGBA")
    Image.alpha_composite(plate, layer).convert("RGB").save(f"{base}_decayed.png")
    cov = sum(1 for p in layer.getdata() if p[3] > 8) / (layer.width * layer.height)
    print(f"overlay  {dst}   coverage {cov:.1%} of frame")
    print(f"preview  {base}_decayed.png")
