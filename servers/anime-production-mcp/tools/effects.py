"""
effects.py — drawn effects, layered over a clip.

THE LINE THAT DECIDES WHETHER AN EFFECT BELONGS HERE:

    LTX relocates what EXISTS. It cannot RE-IMAGINE.

So anything that must APPEAR — a growing crystal, a shooting star, a ripple
ring, a speed line — is drawn here rather than generated. That is not a
fallback. Drawn effects are deterministic (so they can be retimed onto musical
beats without re-rolling), and they cannot smear a face.

Measured cases that sent each effect to this file:
  * Ice: the ice region scored 3.16 while the arm on the same take scored 17.27.
    Growing crystals are new geometry.
  * Pond: 4.0-6.3 across three seeds, against 31-36 of face-control drift.
    Water looked like the easy "existing pixels churning" case, like fire — but
    a still pond has no turbulent texture to churn, and glints and rings are
    things that APPEAR.
  * Impact: anime does not animate the punch travelling, it sells the MOMENT OF
    CONTACT. One held drawing plus lines, flash and shake reads as a hit. This
    is why the pipeline never needed a paid image-to-video service for action.

EVERY effect here is masked. An unmasked overlay draws over the characters and
reads as a scratch on the print, not as weather. Masks come from the caller —
either a painted PNG (white = affected) or polygons — because the region is a
property of the artwork, not of this code.
"""

from __future__ import annotations

import math
import os
import random as pyr

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageSequence

from .motion import expand_frames, _dedupe_guard


def _save(frames: list[Image.Image], dst: str, fps: int) -> dict:
    frames = _dedupe_guard(frames)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    frames[0].save(dst, save_all=True, append_images=frames[1:],
                   duration=int(round(1000 / fps)), loop=0, quality=90)
    return {"path": dst, "frames": len(frames), "fps": fps,
            "seconds": round(len(frames) / fps, 2),
            "kb": os.path.getsize(dst) // 1024}


def region_mask(size: tuple[int, int], mask_path: str | None = None,
                polygons: list[list[list[int]]] | None = None,
                exclude: list[list[list[int]]] | None = None,
                ref_size: tuple[int, int] | None = None,
                blur: float = 4.0) -> Image.Image:
    """Build the L-mode mask an effect is confined to. White = affected.

    `mask_path` is the reliable option: a PNG painted in the same program as the
    artwork, so it follows the real silhouette. Polygons are the quick option
    for a rectangle of sky.

    `exclude` punches holes — the mansion and the boy in a shooting-star shot,
    so streaks vanish BEHIND them and reappear, which is what a real meteor over
    a landscape does. Without that they cross in front and read as a scratch.

    `ref_size` lets polygons be authored against one resolution and reused at
    another; they are scaled. Keep traced polygons a few pixels INSIDE the true
    boundary — a clip that pushes in will drift the artwork under a mask traced
    on frame 0.
    """
    W, H = size
    if mask_path:
        m = Image.open(mask_path).convert("L")
        if m.size != size:
            m = m.resize(size, Image.LANCZOS)
    elif polygons:
        m = Image.new("L", size, 0)
        d = ImageDraw.Draw(m)
        sx, sy = (W / ref_size[0], H / ref_size[1]) if ref_size else (1.0, 1.0)
        for poly in polygons:
            d.polygon([(int(x * sx), int(y * sy)) for x, y in poly], fill=255)
    else:
        m = Image.new("L", size, 255)          # whole frame

    if exclude:
        d = ImageDraw.Draw(m)
        sx, sy = (W / ref_size[0], H / ref_size[1]) if ref_size else (1.0, 1.0)
        for poly in exclude:
            d.polygon([(int(x * sx), int(y * sy)) for x, y in poly], fill=0)
    return m.filter(ImageFilter.GaussianBlur(blur)) if blur else m


# --------------------------------------------------------------------------- #
# growth — an artist-supplied layer scaled from an anchor edge
# --------------------------------------------------------------------------- #

def grow_layer(src: str, dst: str, layer_path: str, kmax: float = 1.13,
               anchor: str = "bottom", frames: int = 30, fps: int = 12,
               hold: int = 6) -> dict:
    """Scale a transparent PNG layer over the art, anchored to one edge.

    For anything that GROWS: ice, vines, fire columns, a rising tide.

    `layer_path` must be the element on its OWN layer with real alpha, exported
    from the drawing program. A hand-traced polygon cannot substitute: on the
    reference shot the ice overlapped the character's jacket, so any approximate
    silhouette either clipped the jacket or left the overlapping spike frozen.
    Both happened before the real layer was exported.

    Anchoring matters. Scaling from an edge means every pixel of the layer moves
    INWARD from it, so the layer only ever covers MORE than before — nothing is
    vacated, and no background has to be painted in behind it.

    `src` may be a still image or an already-animated clip, so generated motion
    (an arm, a magic circle, falling snow) and drawn growth combine in one pass.
    """
    if anchor not in ("bottom", "top", "left", "right"):
        raise ValueError("anchor must be bottom, top, left or right")
    if not os.path.isfile(layer_path):
        raise FileNotFoundError(f"Layer PNG not found: {layer_path}")

    if os.path.splitext(src)[1].lower() in (".webp", ".gif"):
        base = expand_frames(src)
    else:
        base = [Image.open(src).convert("RGB")] * frames
    n = len(base)
    W, H = base[0].size

    layer = Image.open(layer_path).convert("RGBA")
    if layer.size != (W, H):
        layer = layer.resize((W, H), Image.LANCZOS)

    out = []
    for i, im in enumerate(base):
        t = min(1.0, i / max(1, n - 1 - hold))
        t = t * t * (3 - 2 * t)                  # smoothstep, so it doesn't ramp linearly
        k = 1.0 + (kmax - 1.0) * t

        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if anchor in ("bottom", "top"):
            nh = max(1, int(H * k))
            scaled = layer.resize((W, nh), Image.LANCZOS)
            lay.paste(scaled, (0, H - nh if anchor == "bottom" else 0))
        else:
            nw = max(1, int(W * k))
            scaled = layer.resize((nw, H), Image.LANCZOS)
            lay.paste(scaled, (W - nw if anchor == "right" else 0, 0))

        f = im.convert("RGB").copy()
        f.paste(lay, (0, 0), lay)
        out.append(f)
    return _save(out, dst, fps)


# --------------------------------------------------------------------------- #
# streaks — shooting stars, with occlusion
# --------------------------------------------------------------------------- #

def streaks(src: str, dst: str, paths: list[list] | None = None,
            mask_path: str | None = None,
            polygons: list | None = None, exclude: list | None = None,
            ref_size: tuple[int, int] | None = None,
            duration: float = 18.0, tail: float = 0.28, gain: float = 1.3,
            width: int = 7, twinkle: int = 70, fps: int = 12) -> dict:
    """Meteor streaks across a masked sky, occluded by whatever `exclude` covers.

    `paths` is a list of [[x0,y0],[x1,y1],start_frame]. Give them a shared
    heading and stagger the starts by a frame or two: arriving as a GROUP reads
    as a shower, arriving in a queue reads as a loop. Start them off-frame in
    the widest unoccluded band, so each gets the longest visible run before
    anything eclipses it.

    `twinkle` scatters that many slowly-pulsing stars across the masked region.
    Partly decoration — but also load-bearing: Pillow's WebP writer drops
    identical consecutive frames, and a sky that holds still between events gets
    silently collapsed. Twinkle keeps every frame unique. (`_dedupe_guard` also
    catches this; the twinkle is what makes the shot not look dead.)
    """
    base = expand_frames(src)
    W, H = base[0].size
    n = len(base)
    mask = region_mask((W, H), mask_path, polygons, exclude, ref_size, blur=2.0)
    black = Image.new("RGB", (W, H), (0, 0, 0))

    if not paths:
        paths = [[[W + 60, -50], [-150, int(H * 0.45)], 4],
                 [[W + 60, -10], [-150, int(H * 0.55)], 7],
                 [[W + 60, 30], [-150, int(H * 0.65)], 10]]

    pyr.seed(5)
    mp = mask.load()
    stars = []
    guard = 0
    while len(stars) < twinkle and guard < 200000:
        guard += 1
        x, y = pyr.randint(0, W - 1), pyr.randint(0, H - 1)
        if mp[x, y] > 200:
            stars.append((x, y, pyr.random(), 5 + pyr.random() * 7))

    lerp = lambda a, b, t: (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    out = []
    for f in range(n):
        ov = Image.new("RGB", (W, H), (0, 0, 0))
        dr = ImageDraw.Draw(ov)
        for a, b, ts in paths:
            loc = (f - ts) / duration
            if loc < -0.05 or loc > 1.3:
                continue
            fade = 1.0 if loc <= 1 else max(0.0, 1 - (loc - 1) / 0.3)
            head = min(loc, 1.0)
            SEG = 26
            for k in range(SEG):
                t2 = head - tail * k / SEG
                t1 = max(head - tail * (k + 1) / SEG, 0.0)
                if t2 < 0:
                    continue
                v = int(255 * gain * fade * ((1 - k / SEG) ** 1.5))
                if v < 4:
                    continue
                v = min(255, v)
                dr.line([lerp(a, b, t1), lerp(a, b, t2)],
                        fill=(v, v, min(255, int(v * 1.12))),
                        width=max(1, width - k // 7))
            if loc <= 1:
                hx, hy = lerp(a, b, head)
                r = (width + 2) * fade
                dr.ellipse([hx - r, hy - r, hx + r, hy + r], fill=(255, 255, 255))
        for x, y, ph, per in stars:
            v = math.sin(2 * math.pi * (f / per + ph))
            if v <= 0:
                continue
            bv = int(150 * v)
            r = 0.8 + 1.6 * v
            dr.ellipse([x - r, y - r, x + r, y + r],
                       fill=(bv, bv, min(255, int(bv * 1.1))))
        ov = ov.filter(ImageFilter.GaussianBlur(2.4))
        out.append(ImageChops.screen(base[f], Image.composite(ov, black, mask)))
    return _save(out, dst, fps)


# --------------------------------------------------------------------------- #
# water — glints and expanding rings
# --------------------------------------------------------------------------- #

def _open_water(frame: Image.Image) -> Image.Image:
    """Classify OPEN water by colour, so a ripple never forms on a lily pad.

    Hand-listing the lilies was brittle — the pads are numerous and irregular,
    and listing only the flowers left rings forming on the leaves. Water is
    strongly blue while pads, reeds and rock are green or warm, so one threshold
    on (B - G) separates them.
    """
    W, H = frame.size
    px = frame.load()
    m = Image.new("L", (W, H), 0)
    mp = m.load()
    for y in range(H):
        for x in range(W):
            r, g, b = px[x, y]
            mp[x, y] = 255 if (b - g) > 28 and b > 60 else 0
    return m.filter(ImageFilter.MinFilter(5))


def water(src: str, dst: str, mask_path: str | None = None,
          polygons: list | None = None, ref_size: tuple[int, int] | None = None,
          sparkles: int = 22, ripples: int = 9, gain: float = 1.0,
          fps: int = 12) -> dict:
    """Sparkles and expanding ripples confined to a water region.

    Rings are placed on an ERODED, colour-filtered mask, not the raw region: a
    ring grows about 50px from its centre, so a centre that is valid right at
    the waterline still expands onto the bank. Two MinFilter passes pull the
    spawn area in far enough to prevent that.
    """
    base = expand_frames(src)
    W, H = base[0].size
    n = len(base)
    mask = region_mask((W, H), mask_path, polygons, None, ref_size, blur=6.0)
    black = Image.new("RGB", (W, H), (0, 0, 0))

    pyr.seed(11)
    mp = mask.load()

    def scatter(k, src_mask):
        pts, guard = [], 0
        sp = src_mask.load()
        while len(pts) < k and guard < 200000:
            guard += 1
            x, y = pyr.randint(0, W - 1), pyr.randint(0, H - 1)
            if sp[x, y] > 200:
                pts.append((x, y, pyr.random()))
        return pts

    sparks = scatter(sparkles, mask)
    spawn = ImageChops.multiply(mask, _open_water(base[0]))
    spawn = spawn.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.MinFilter(9))
    rings = scatter(ripples, spawn)
    short = ripples - len(rings)

    out = []
    for f in range(n):
        ov = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(ov)
        for i, (x, y, ph) in enumerate(sparks):
            s = math.sin(2 * math.pi * (f / (7 + (i % 5)) + ph))
            if s <= 0:
                continue
            v = int(235 * s * gain)
            r = 1.0 + 2.2 * s
            d.ellipse([x - r, y - r, x + r, y + r], fill=(v, v, min(255, int(v * 1.06))))
            d.line([(x - r * 3, y), (x + r * 3, y)], fill=(v // 2, v // 2, v // 2))
        for i, (x, y, ph) in enumerate(rings):
            period = 16 + (i % 4) * 4
            t = ((f / period) + ph) % 1.0
            rad = 4 + t * 46
            v = int(180 * ((1 - t) ** 1.5) * gain)
            if v < 6:
                continue
            # flattened for perspective — a circular ring reads as a hoop
            # standing up out of the water
            d.ellipse([x - rad, y - rad * 0.34, x + rad, y + rad * 0.34],
                      outline=(v, v, min(255, int(v * 1.08))), width=2)
        ov = ov.filter(ImageFilter.GaussianBlur(1.2))
        out.append(ImageChops.screen(base[f], Image.composite(ov, black, mask)))

    res = _save(out, dst, fps)
    if short > 0:
        res["note"] = (f"only fitted {len(rings)}/{ripples} ripples — the open-water "
                       f"area left after erosion is small. Widen the region or ask for fewer.")
    return res


# --------------------------------------------------------------------------- #
# impact — speed lines, flash, shake
# --------------------------------------------------------------------------- #

def _envelope(local: float, attack: int, decay: int) -> float:
    """Full strength on the contact frame, then decays.

    Attack is 0 by default because a one-frame-late flash reads as broken — the
    peak must land exactly on contact, not approach it.
    """
    if local < 0:
        return 0.0
    if attack > 0 and local < attack:
        return local / attack
    t = (local - attack) / max(1, decay)
    return 0.0 if t >= 1 else (1 - t) ** 1.8


def motion_lines(src: str, dst: str, angle: float = 180.0, density: int = 90,
                 gain: float = 1.0, length: float = 0.55, width: int = 3,
                 color: tuple[int, int, int] = (255, 255, 255),
                 clear: tuple[float, float, float] | None = None,
                 start: int = 0, ramp: int = 3, fps: int = 12) -> dict:
    """Parallel streaks travelling in one direction — the anime "he moved" cue.

    Distinct from `impact`, whose lines radiate from a point of contact. These
    are LATERAL: they sell travel across the frame.

    Why it is needed: LTX deforms locally, it does not translate a subject
    across a composition. Asked for a leap from right to left, it produced a
    weight shift and a fluttering hem — clean, but not a leap. Anime solves this
    the same way, with streaks rather than by drawing the body at every point
    along the path.

    `angle` is the direction of travel in degrees (180 = right-to-left).
    `clear` is (cx, cy, radius) in frame fractions — an ellipse kept free of
    lines so the subject is never buried by the effect meant to sell it.
    `ramp` fades the streaks in over N frames, so they arrive rather than blink on.
    """
    base = expand_frames(src)
    W, H = base[0].size
    n = len(base)
    diag = math.hypot(W, H)
    rad = math.radians(angle)
    dx, dy = math.cos(rad), math.sin(rad)
    px_, py_ = -dy, dx                                # perpendicular, for spacing

    pyr.seed(13)
    lines = [(pyr.random(), pyr.random(), pyr.random()) for _ in range(density)]
    cx0, cy0, cr = clear if clear else (0.5, 0.5, 0.0)

    out = []
    for i, im in enumerate(base):
        s = 0.0 if i < start else min(1.0, (i - start + 1) / max(1, ramp))
        if s <= 0.01:
            out.append(im)
            continue
        ov = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(ov)
        for k, (a, b, c) in enumerate(lines):
            off = (a - 0.5) * diag * 1.4
            mx = W / 2 + px_ * off
            my = H / 2 + py_ * off
            # stagger along the direction so they do not all start together
            phase = ((i * 0.22) + b) % 1.0
            ln = diag * length * (0.5 + c * 0.9)
            hx = mx + dx * (phase * diag * 1.3 - diag * 0.5)
            hy = my + dy * (phase * diag * 1.3 - diag * 0.5)
            if cr > 0:
                if ((hx / W - cx0) ** 2 + (hy / H - cy0) ** 2) ** 0.5 < cr:
                    continue
            SEG = 10
            for g in range(SEG):
                t0, t1 = g / SEG, (g + 1) / SEG
                v = int(255 * gain * s * ((1 - t0) ** 1.4) * (0.35 + 0.65 * c))
                if v < 5:
                    continue
                col = tuple(min(255, int(ch * v / 255)) for ch in color)
                d.line([(hx - dx * ln * t0, hy - dy * ln * t0),
                        (hx - dx * ln * t1, hy - dy * ln * t1)],
                       fill=col, width=max(1, width - g // 4))
        ov = ov.filter(ImageFilter.GaussianBlur(1.1))
        out.append(ImageChops.screen(im, ov))
    return _save(out, dst, fps)


def glow(src: str, dst: str, mask_path: str | None = None,
         key: str = "warm", period: float = 1.6, gain: float = 1.0,
         swirl: float = 0.0, blur: float = 12.0, floor: float = 0.25,
         fps: int = 12) -> dict:
    """Pulse (and optionally rotate) the bright parts of a region — magic, runes.

    Runes and magic circles are drawn ONCE and then have to look alive. LTX will
    not animate them: a glowing sigil brightening is not relocation of existing
    pixels, it is a change of value, so the model leaves it static.

    The lit parts are keyed out by colour, blurred into a halo and screened back
    on a sine. `key`: "warm" (gold/orange runes), "cool" (blue/cyan), "bright"
    (anything luminous regardless of hue).

    `swirl` rotates the halo about the region's centroid, degrees per second —
    a slow turn reads as circulating power. Keep it small; the halo is a blurred
    copy, and spinning it fast looks like a spinning blur, which it is.

    `floor` is the dimmest the pulse goes (0 = fully dark between beats, which
    reads as flickering rather than breathing).
    """
    base = expand_frames(src)
    W, H = base[0].size
    n = len(base)

    if mask_path:
        lit = Image.open(mask_path).convert("L")
        if lit.size != (W, H):
            lit = lit.resize((W, H), Image.LANCZOS)
    else:
        px = base[0].load()
        lit = Image.new("L", (W, H), 0)
        lp = lit.load()
        for y in range(H):
            for x in range(W):
                r, g, b = px[x, y]
                if key == "warm":
                    hit = r > 140 and r > b + 40 and r >= g
                elif key == "cool":
                    hit = b > 130 and b > r + 35
                else:
                    hit = (r + g + b) > 560
                if hit:
                    lp[x, y] = 255
    halo = lit.filter(ImageFilter.GaussianBlur(blur))

    # centroid, so a swirl turns about the sigil rather than the frame
    import numpy as np
    arr = np.asarray(halo, dtype=np.float32)
    tot = arr.sum() or 1.0
    ys, xs = np.mgrid[0:H, 0:W]
    cx = float((arr * xs).sum() / tot)
    cy = float((arr * ys).sum() / tot)

    tint = Image.new("RGB", (W, H), (255, 236, 190) if key == "warm"
                     else (190, 224, 255) if key == "cool" else (255, 255, 255))
    out = []
    for i, im in enumerate(base):
        t = i / fps
        s = floor + (1.0 - floor) * (0.5 + 0.5 * math.sin(2 * math.pi * t / period))
        h = halo
        if swirl:
            h = halo.rotate(swirl * t, resample=Image.BILINEAR,
                            center=(cx, cy), fillcolor=0)
        lay = Image.composite(tint, Image.new("RGB", (W, H), (0, 0, 0)),
                              h.point(lambda v: int(v * s * gain)))
        out.append(ImageChops.screen(im, lay))
    return _save(out, dst, fps)


def impact(src: str, dst: str, focal: tuple[float, float] = (0.5, 0.5),
           at: int = 2, attack: int = 1, decay: int = 9,
           color: tuple[int, int, int] = (235, 235, 235),
           lines: float = 1.0, flash: float = 1.0, shake: float = 1.0,
           margin: int = 18, fps: int = 12) -> dict:
    """Speed lines, a flash and camera shake, centred on `focal` (x,y fractions).

    ⚠ Shake uses OVERSCAN, never a circular offset. Offsetting wraps, so pixels
    pushed off one edge reappear on the other as a black seam. Every frame is
    scaled into a margin and cropped inside it — shake or not — so there is no
    wrap and no size pop when the effect starts.

    The speed lines keep a CLEAR CENTRE that widens with intensity, so the
    figure is never buried by the effect that is meant to sell it.
    """
    base = expand_frames(src)
    W, H = base[0].size
    diag = math.hypot(W, H)
    ox, oy = focal[0] * W, focal[1] * H
    M = margin

    pyr.seed(7)
    rnd = [(pyr.random(), pyr.random(), pyr.random(), pyr.random()) for _ in range(84)]

    def speedlines(s: float) -> Image.Image:
        ov = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(ov)
        for i, (ra, ri, rl, rt) in enumerate(rnd):
            ang = (i / 84) * math.tau + ra * 0.06
            inner = diag * (0.14 + ri * 0.16) * (1 - s * 0.35)
            ln = diag * (0.35 + rl * 0.5)
            th = max(1, int((2.5 + rt * 13 * s) * 0.5))
            x0, y0 = ox + math.cos(ang) * inner, oy + math.sin(ang) * inner
            x1, y1 = x0 + math.cos(ang) * ln, y0 + math.sin(ang) * ln
            for k in range(8):
                t0, t1 = k / 8, (k + 1) / 8
                v = tuple(min(255, int(c * s * (t0 ** 1.3))) for c in color)
                if max(v) < 5:
                    continue
                d.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                        (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)], fill=v, width=th)
        return ov.filter(ImageFilter.GaussianBlur(1.6))

    out = []
    for i, im in enumerate(base):
        s = _envelope(i - at, attack, decay)
        f = im
        if s > 0.01:
            if lines > 0:
                f = ImageChops.screen(f, speedlines(s * lines))
            if flash > 0:
                fl = s * s * flash * 0.6
                tint = tuple(min(255, int(c * fl)) for c in color)
                if max(tint) > 2:
                    f = ImageChops.screen(f, Image.new("RGB", (W, H), tint))
        big = f.resize((W + 2 * M, H + 2 * M), Image.LANCZOS)
        dx = int(math.sin(i * 2.9) * 13 * s * shake)
        dy = int(math.cos(i * 3.7) * 13 * s * shake)
        out.append(big.crop((M + dx, M + dy, M + dx + W, M + dy + H)))
    return _save(out, dst, fps)
