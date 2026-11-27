"""
bubbles.py — bubble shapes, tails, placement and still compositing.

DRAWN, NEVER GENERATED. A balloon is a flat symbolic mark -- an outline, a
fill and type -- the same category as the magic circle and the plaque
lettering in the repo's AGENTS.md. Nothing here touches a GPU.

Every shape is built from simple primitives (ellipses, circles, polygons)
drawn TWICE: once grown by the stroke width in the outline color, then at
true size in the fill color. The union of any set of primitives therefore gets
one clean outline with no seam where the tail meets the body or where cloud
bumps overlap, and nothing needs a slow morphological dilation. Everything is
drawn at 3x and downsampled, which is the antialiasing.

Kinds:
  speech   ellipse around the text, curved tapering tail toward the speaker
  thought  cloud of bumps, a trail of shrinking circles toward the thinker
  caption  rectangle box for narration, no tail
  shout    spiky burst, straight sharp tail, type 15% larger
  whisper  ellipse with a dashed outline

Coordinates in a bubble spec are NORMALIZED to the frame (0-1) so one spec
works on a 1536x864 render and on the 1920x1080 delivery alike. Values above 1
are read as pixels.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import lettering as lt

KINDS = ("speech", "thought", "caption", "shout", "whisper")
SS = 3  # supersampling factor

NAMED_AT = ("top-left", "top", "top-right", "left", "center", "right",
            "bottom-left", "bottom", "bottom-right")
NAMED_TAIL = {"far-left": 0.12, "left": 0.28, "center": 0.5, "right": 0.72,
              "far-right": 0.88}


@dataclass
class Style:
    """Project-wide lettering settings. One type size for the whole project."""
    font_scale: float = 0.034        # type size as a fraction of the frame's short side
    line_spacing: float = 1.18
    pad_scale: float = 0.62          # padding between type and outline, in type sizes
    stroke_scale: float = 0.09       # outline width, in type sizes
    max_width: float = 0.42          # widest a bubble body may be, fraction of frame width
    fill: tuple = (255, 255, 255)
    stroke: tuple = (18, 18, 20)
    text: tuple = (18, 18, 20)
    caption_fill: tuple = (255, 255, 255)
    caption_text: tuple = (18, 18, 20)
    uppercase: bool = False
    vertical_ja: bool = True
    reading: str = "ltr"             # ltr for English, rtl for manga order
    fonts: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Style":
        s = cls()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                if k in ("fill", "stroke", "text", "caption_fill", "caption_text"):
                    v = tuple(v)
                setattr(s, k, v)
        return s


@dataclass
class Body:
    kind: str
    lang: str
    shape: str            # ellipse | rect
    hw: float             # half extents of the text-fitting shape
    hh: float
    layout: lt.Layout
    font_path: str
    font_px: int
    text: str


@dataclass
class Placed:
    id: str
    body: Body
    cx: float
    cy: float
    tail: tuple | None
    sprite: Image.Image | None = None
    x0: int = 0
    y0: int = 0

    def extents(self):
        """Half extents of the drawn body (cloud bumps and spikes stick out)."""
        b = self.body
        if b.kind == "thought":
            rb = _bump_radius(b)
            return b.hw + 0.4 * rb, b.hh + 0.4 * rb
        if b.kind == "shout":
            return b.hw * 1.04 + b.font_px * 0.9, b.hh * 1.04 + b.font_px * 0.9
        return b.hw, b.hh


# --- text ---------------------------------------------------------------------

def bubble_text(bubble: dict, lang: str) -> str:
    t = bubble.get("text", "")
    if isinstance(t, dict):
        if lang in t:
            return t[lang]
        raise KeyError(f"Bubble {bubble.get('id', '?')} has no '{lang}' text "
                       f"(has: {', '.join(t)}).")
    return str(t)


def font_px(style: Style, frame: tuple[int, int]) -> int:
    return max(10, int(round(min(frame) * style.font_scale)))


def measure(bubble: dict, lang: str, frame: tuple[int, int], style: Style) -> Body:
    kind = bubble.get("kind", "speech")
    if kind not in KINDS:
        raise ValueError(f"Unknown bubble kind '{kind}'. Use one of {KINDS}.")
    text = lt.apply_case(bubble_text(bubble, lang),
                         style.uppercase and lang not in ("ja", "zh", "ko"))
    px = font_px(style, frame)
    scale = float(bubble.get("scale", 1.15 if kind == "shout" else 1.0))
    px = max(8, int(round(px * scale)))
    path = lt.resolve_font_path(lang, bubble.get("font") or style.fonts.get(lang))
    font = lt.load_font(path, px)
    pad = px * style.pad_scale
    max_w = frame[0] * float(bubble.get("max_width", style.max_width))
    vertical = (lang == "ja" and style.vertical_ja and kind != "caption"
                and not bubble.get("horizontal"))
    if bubble.get("vertical"):
        vertical = True

    if vertical:
        cands = lt.vertical_candidates(text, font, px, pitch=px * 1.45)
        target = 0.62
    else:
        cands = lt.horizontal_candidates(text, font, px * style.line_spacing)
        # 1.7 wide with a small charge per line, chosen on sample dialogue:
        # "Is that / really him?" rather than three stacked words, and
        # "Wait. You think / I came here / for the money?".
        target = 3.2 if kind == "caption" else 1.7

    best = None
    for lay in cands:
        if kind == "caption":
            hw, hh, score = lt.fit_rect(lay.rects, pad * 0.8, target)
        else:
            hw, hh, score = lt.fit_ellipse(lay.rects, pad, target)
            if not vertical:
                score *= 1.0 + 0.08 * (len(lay.lines) - 1)
        too_wide = 2 * hw > max_w
        key = (too_wide, score if not too_wide else hw)
        if best is None or key < best[0]:
            best = (key, lay, hw, hh)
    _, lay, hw, hh = best
    return Body(kind, lang, "rect" if kind == "caption" else "ellipse",
                hw, hh, lay, path, px, text)


# --- placement ----------------------------------------------------------------

def _to_px(v, size):
    v = float(v)
    return v * size if v <= 1.0 else v


def resolve_tail(bubble: dict, frame) -> tuple | None:
    t = bubble.get("tail")
    W, H = frame
    if t in (None, "none", False) or bubble.get("kind") == "caption":
        return None
    if isinstance(t, str):
        if t not in NAMED_TAIL:
            raise ValueError(f"Unknown tail position '{t}'. Use {list(NAMED_TAIL)} or [x, y].")
        return (NAMED_TAIL[t] * W, 0.5 * H)
    return (_to_px(t[0], W), _to_px(t[1], H))


def _named_center(name, ex, ey, frame, margin):
    W, H = frame
    xs = {"left": margin + ex, "center": W / 2, "right": W - margin - ex}
    ys = {"top": margin + ey, "middle": H / 2, "bottom": H - margin - ey}
    parts = name.split("-")
    if name == "center":
        return W / 2, H / 2
    if len(parts) == 1:
        if parts[0] in ("top", "bottom"):
            return W / 2, ys[parts[0]]
        return xs[parts[0]], H / 2
    return xs[parts[1]], ys[parts[0]]


def busy_map(image: Image.Image, width: int = 240) -> tuple[np.ndarray, float]:
    """Local detail, 0-1, on a small grid: where type would fight the art.
    Purely numeric -- no image is shown to anyone to place a bubble."""
    W, H = image.size
    s = width / W
    small = image.convert("L").resize((width, max(1, int(H * s))), Image.BILINEAR)
    a = np.asarray(small, dtype=np.float32)
    gx = np.abs(np.diff(a, axis=1, prepend=a[:, :1]))
    gy = np.abs(np.diff(a, axis=0, prepend=a[:1, :]))
    g = Image.fromarray(np.clip(gx + gy, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(2))
    g = np.asarray(g, dtype=np.float32)
    g /= max(1.0, float(np.percentile(g, 98)))
    return np.clip(g, 0, 1), s


def auto_center(p: Placed, frame, placed: list[Placed], busy, style: Style, index: int):
    """Grid search for a spot: calm art, near (and above) the speaker, not on
    top of the speaker or another bubble, in reading order. Bubbles may still
    overlap the art -- that is allowed -- this only picks the best of the spots
    that exist."""
    W, H = frame
    ex, ey = p.extents()
    m = 0.025 * W
    xs = np.linspace(m + ex, max(m + ex, W - m - ex), 33)
    ys = np.linspace(m + ey, max(m + ey, H - m - ey), 19)
    grid, s = busy if busy is not None else (None, 1.0)
    integral = None
    if grid is not None:
        integral = np.pad(grid.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    best = None
    for cy in ys:
        for cx in xs:
            score = 0.0
            if integral is not None:
                x0 = int(max(0, (cx - ex) * s)); x1 = int(min(grid.shape[1], (cx + ex) * s))
                y0 = int(max(0, (cy - ey) * s)); y1 = int(min(grid.shape[0], (cy + ey) * s))
                if x1 > x0 and y1 > y0:
                    tot = (integral[y1, x1] - integral[y0, x1] - integral[y1, x0]
                           + integral[y0, x0])
                    score += 2.0 * tot / ((x1 - x0) * (y1 - y0))
            if p.tail is not None:
                tx, ty = p.tail
                # Ideal: above the speaker's head, clear of the face.
                ix, iy = tx, ty - ey - p.body.font_px * 4
                score += 1.5 * math.hypot((cx - ix) / W, (cy - iy) / H)
                if abs(cx - tx) < ex and abs(cy - ty) < ey + p.body.font_px * 2:
                    score += 3.0
            else:
                score += 0.8 * (cy / H)  # captions and tailless lines prefer the top
            for q in placed:
                qx, qy = q.extents()
                ox = max(0.0, min(cx + ex, q.cx + qx) - max(cx - ex, q.cx - qx))
                oy = max(0.0, min(cy + ey, q.cy + qy) - max(cy - ey, q.cy - qy))
                if ox > 0 and oy > 0:
                    score += 6.0 + 4.0 * (ox * oy) / (4 * ex * ey)
                # A tail (or a thought's trail) must not run across another bubble.
                if p.tail is not None and _tail_hits((cx, cy), p.tail, (q.cx, q.cy, qx, qy)):
                    score += 4.0
                if q.tail is not None and _tail_hits((q.cx, q.cy), q.tail, (cx, cy, ex, ey)):
                    score += 4.0
            if placed:
                prev = placed[-1]
                # Reading order: later bubbles sit lower or further along the line.
                along = (cx - prev.cx) if style.reading == "ltr" else (prev.cx - cx)
                if cy < prev.cy - ey and along < 0:
                    score += 1.2
            if best is None or score < best[0]:
                best = (score, cx, cy)
    return best[1], best[2]


def _tail_hits(start, target, box) -> bool:
    """Does the line from a bubble's center toward its speaker pass through
    another bubble's box (cx, cy, half-w, half-h)? Sampled, which is plenty at
    bubble scale."""
    bx, by, ex, ey = box
    for i in range(1, 25):
        f = i / 24
        x = start[0] + (target[0] - start[0]) * f
        y = start[1] + (target[1] - start[1]) * f
        if abs(x - bx) < ex and abs(y - by) < ey:
            return True
    return False


def plan(bubbles: list[dict], lang: str, frame: tuple[int, int], style: Style,
         image: Image.Image | None = None) -> list[Placed]:
    """Measure, place and draw every bubble. Returns them in input order."""
    W, H = frame
    busy = busy_map(image) if image is not None else None
    out: list[Placed] = []
    for i, b in enumerate(bubbles):
        bid = str(b.get("id") or f"b{i + 1}")
        body = measure(b, lang, frame, style)
        p = Placed(bid, body, 0, 0, resolve_tail(b, frame))
        ex, ey = p.extents()
        at = b.get("at")
        if isinstance(at, str):
            if at not in NAMED_AT:
                raise ValueError(f"Unknown position '{at}'. Use {NAMED_AT} or [x, y].")
            p.cx, p.cy = _named_center(at, ex, ey, frame, 0.025 * W)
        elif at is not None:
            p.cx, p.cy = _to_px(at[0], W), _to_px(at[1], H)
        else:
            p.cx, p.cy = auto_center(p, frame, out, busy, style, i)
        p.sprite, p.x0, p.y0 = draw(p, style, seed=b.get("seed", i))
        out.append(p)
    return out


# --- geometry -----------------------------------------------------------------

def _bump_radius(b: Body) -> float:
    return max(b.font_px * 0.55, min(b.hw, b.hh) * 0.30)


def _ellipse_r(a, b, theta):
    return 1.0 / math.sqrt((math.cos(theta) / a) ** 2 + (math.sin(theta) / b) ** 2)


def _bezier(p0, c, p1, n=10):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1])
            for t in (i / n for i in range(n + 1))]


def _tail_poly(p: Placed, a, b, sharp=False):
    """Tapering wedge from inside the body toward the speaker. It stops short
    of them, as a lettered tail does, and bends slightly so it reads as drawn."""
    tx, ty = p.tail
    dx, dy = tx - p.cx, ty - p.cy
    dist = math.hypot(dx, dy)
    th = math.atan2(dy, dx)
    r = _ellipse_r(a, b, th)
    fs = p.body.font_px
    gap = dist - r
    if gap < fs * 0.8:
        return None  # the speaker is under the bubble; no room for a tail
    length = max(fs * 0.9, min(gap - fs * 0.7, fs * 3.2))
    half = max(fs * 0.32, min(min(a, b) * (0.18 if sharp else 0.26), fs * 0.85))
    dlt = half / r
    b1 = (p.cx + 0.86 * _ellipse_r(a, b, th - dlt) * math.cos(th - dlt),
          p.cy + 0.86 * _ellipse_r(a, b, th - dlt) * math.sin(th - dlt))
    b2 = (p.cx + 0.86 * _ellipse_r(a, b, th + dlt) * math.cos(th + dlt),
          p.cy + 0.86 * _ellipse_r(a, b, th + dlt) * math.sin(th + dlt))
    tip = (p.cx + (r + length) * math.cos(th), p.cy + (r + length) * math.sin(th))
    if sharp:
        return [b1, tip, b2]
    # Bend toward the vertical: a tail from the bottom of a bubble curls a
    # little outward rather than pointing like a ruler.
    bend = 0.22 * length * (1 if math.cos(th) >= 0 else -1)
    nx, ny = -math.sin(th), math.cos(th)
    m1 = ((b1[0] + tip[0]) / 2 + nx * bend, (b1[1] + tip[1]) / 2 + ny * bend)
    m2 = ((b2[0] + tip[0]) / 2 + nx * bend, (b2[1] + tip[1]) / 2 + ny * bend)
    return _bezier(b1, m1, tip) + _bezier(tip, m2, b2)[1:]


def primitives(p: Placed, rng: random.Random):
    b = p.body
    cx, cy, a, bb = p.cx, p.cy, b.hw, b.hh
    fs = b.font_px
    prims = []
    if b.kind == "caption":
        prims.append(("rect", cx - a, cy - bb, cx + a, cy + bb))
    elif b.kind == "thought":
        rb = _bump_radius(b)
        ia, ib = max(a - 0.6 * rb, a * 0.5), max(bb - 0.6 * rb, bb * 0.5)
        prims.append(("ellipse", cx, cy, ia, ib))
        # bumps at equal arc length around the inner ellipse
        pts = [(ia * math.cos(t), ib * math.sin(t))
               for t in np.linspace(0, 2 * math.pi, 720, endpoint=False)]
        per = sum(math.dist(pts[i], pts[i - 1]) for i in range(len(pts)))
        n = max(7, int(per / (rb * 1.45)))
        step, acc, k, nxt = per / n, 0.0, 0, 0.0
        jitter = rng.uniform(0, step)
        for i in range(len(pts)):
            acc += math.dist(pts[i], pts[i - 1])
            if acc >= nxt + jitter and k < n:
                r = rb * rng.uniform(0.9, 1.1)
                prims.append(("circle", cx + pts[i][0], cy + pts[i][1], r))
                k += 1
                nxt += step
        if p.tail is not None:
            tx, ty = p.tail
            th = math.atan2(ty - cy, tx - cx)
            edge = _ellipse_r(ia, ib, th) + rb
            gap = math.hypot(tx - cx, ty - cy) - edge
            if gap > fs:
                for frac, rad in ((0.25, 0.42), (0.52, 0.30), (0.75, 0.20)):
                    d = edge + min(gap * 0.8, fs * 3.6) * frac + fs * 0.2
                    prims.append(("circle", cx + d * math.cos(th),
                                  cy + d * math.sin(th), fs * rad))
    elif b.kind == "shout":
        per = math.pi * (3 * (a + bb) - math.sqrt((3 * a + bb) * (a + 3 * bb)))
        n = max(10, int(per / (fs * 1.15)))
        pts = []
        for i in range(2 * n):
            t = math.pi * i / n + rng.uniform(-0.15, 0.15) * math.pi / n
            if i % 2 == 0:
                k = 1.04
                pts.append((cx + a * k * math.cos(t), cy + bb * k * math.sin(t)))
            else:
                L = fs * 0.9 * rng.uniform(0.7, 1.3)
                ox, oy = a * math.cos(t), bb * math.sin(t)
                norm = math.hypot(ox / a ** 2, oy / bb ** 2) or 1.0
                nx, ny = (ox / a ** 2) / norm, (oy / bb ** 2) / norm
                pts.append((cx + ox * 1.04 + nx * L, cy + oy * 1.04 + ny * L))
        prims.append(("poly", pts))
        prims.append(("ellipse", cx, cy, a, bb))
        if p.tail is not None:
            tp = _tail_poly(p, a * 1.1, bb * 1.1, sharp=True)
            if tp:
                prims.append(("poly", tp))
    else:  # speech, whisper
        prims.append(("ellipse", cx, cy, a, bb))
        if p.tail is not None:
            tp = _tail_poly(p, a, bb)
            if tp:
                prims.append(("poly", tp))
    return prims


def _prim_bounds(pr):
    if pr[0] == "rect":
        return pr[1], pr[2], pr[3], pr[4]
    if pr[0] == "ellipse":
        return pr[1] - pr[3], pr[2] - pr[4], pr[1] + pr[3], pr[2] + pr[4]
    if pr[0] == "circle":
        return pr[1] - pr[3], pr[2] - pr[3], pr[1] + pr[3], pr[2] + pr[3]
    xs = [q[0] for q in pr[1]]
    ys = [q[1] for q in pr[1]]
    return min(xs), min(ys), max(xs), max(ys)


def _draw_prims(d: ImageDraw.ImageDraw, prims, ox, oy, grow):
    def P(x, y):
        return ((x - ox) * SS, (y - oy) * SS)
    g = grow * SS
    for pr in prims:
        if pr[0] == "rect":
            x0, y0 = P(pr[1], pr[2]); x1, y1 = P(pr[3], pr[4])
            d.rectangle([x0 - g, y0 - g, x1 + g, y1 + g], fill=255)
        elif pr[0] in ("ellipse", "circle"):
            cx, cy = P(pr[1], pr[2])
            rx = pr[3] * SS + g
            ry = (pr[4] if pr[0] == "ellipse" else pr[3]) * SS + g
            d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
        else:
            pts = [P(*q) for q in pr[1]]
            d.polygon(pts, fill=255)
            if g > 0:
                d.line(pts + [pts[0]], fill=255, width=int(round(2 * g)), joint="curve")
                for x, y in pts:
                    d.ellipse([x - g, y - g, x + g, y + g], fill=255)


def draw(p: Placed, style: Style, seed=0):
    """Render one bubble to an RGBA sprite. Returns (sprite, x0, y0) with the
    sprite's top-left corner in frame pixels."""
    rng = random.Random(f"{p.id}:{seed}")
    prims = primitives(p, rng)
    fs = p.body.font_px
    stroke = max(1.5, fs * style.stroke_scale)
    xs0, ys0, xs1, ys1 = zip(*[_prim_bounds(pr) for pr in prims])
    m = stroke + 3
    x0, y0 = math.floor(min(xs0) - m), math.floor(min(ys0) - m)
    x1, y1 = math.ceil(max(xs1) + m), math.ceil(max(ys1) + m)
    w, h = (x1 - x0) * SS, (y1 - y0) * SS

    smask = Image.new("L", (w, h), 0)
    fmask = Image.new("L", (w, h), 0)
    _draw_prims(ImageDraw.Draw(smask), prims, x0, y0, stroke)
    _draw_prims(ImageDraw.Draw(fmask), prims, x0, y0, 0)

    sa = np.asarray(smask, dtype=np.float32) / 255.0
    fa = np.asarray(fmask, dtype=np.float32) / 255.0
    if p.body.kind == "whisper":
        # Dashes: knock gaps out of the outline ring by angle around the center.
        yy, xx = np.mgrid[0:h, 0:w]
        ang = np.arctan2((yy / SS + y0) - p.cy, (xx / SS + x0) - p.cx)
        rmean = (p.body.hw + p.body.hh) / 2
        dash = fs * 0.55
        gaps = (np.floor((ang + math.pi) * rmean / dash) % 2) == 1
        ring = (sa > 0) & (fa < 1)
        sa = np.where(ring & gaps, fa, sa)

    fill = style.caption_fill if p.body.kind == "caption" else style.fill
    txt = style.caption_text if p.body.kind == "caption" else style.text
    rgb = (np.array(style.stroke, np.float32)[None, None, :] * (1 - fa[..., None])
           + np.array(fill, np.float32)[None, None, :] * fa[..., None])
    rgba = np.dstack([rgb, sa * 255.0]).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    _draw_text(img, p, (p.cx - x0) * SS, (p.cy - y0) * SS, txt)
    img = img.resize((x1 - x0, y1 - y0), Image.LANCZOS)
    return img, x0, y0


def _draw_text(img: Image.Image, p: Placed, ox: float, oy: float, color):
    b = p.body
    font = lt.load_font(b.font_path, b.font_px * SS)
    d = ImageDraw.Draw(img)
    col = (*color, 255)
    for kind, s, x, y, rot in b.layout.items:
        X, Y = ox + x * SS, oy + y * SS
        if not rot:
            d.text((X, Y), s, font=font, fill=col, anchor="mm")
            continue
        size = int(b.font_px * SS * 1.6)
        tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((size / 2, size / 2), s, font=font, fill=col, anchor="mm")
        tile = tile.rotate(-90, resample=Image.BICUBIC)
        img.alpha_composite(tile, (int(X - size / 2), int(Y - size / 2)))


# --- compositing ----------------------------------------------------------------

def layer(frame: tuple[int, int], placed: list[Placed]) -> Image.Image:
    """All bubbles on one transparent full-frame layer, later ones on top.
    Sprites hanging off the frame are clipped, which is allowed."""
    out = Image.new("RGBA", frame, (0, 0, 0, 0))
    for p in placed:
        tmp = Image.new("RGBA", frame, (0, 0, 0, 0))
        tmp.paste(p.sprite, (p.x0, p.y0))
        out = Image.alpha_composite(out, tmp)
    return out


def describe(p: Placed, frame) -> dict:
    W, H = frame
    return {
        "id": p.id,
        "kind": p.body.kind,
        "at": [round(float(p.cx) / W, 4), round(float(p.cy) / H, 4)],
        "size_px": [p.sprite.width, p.sprite.height] if p.sprite else None,
        "font_px": p.body.font_px,
        "lines": p.body.layout.lines,
        "direction": "vertical" if p.body.layout.direction == "v" else "horizontal",
        "box_px": [p.x0, p.y0, p.x0 + (p.sprite.width if p.sprite else 0),
                   p.y0 + (p.sprite.height if p.sprite else 0)],
        "off_frame": bool(p.sprite and (p.x0 < 0 or p.y0 < 0
                                        or p.x0 + p.sprite.width > W
                                        or p.y0 + p.sprite.height > H)),
    }
