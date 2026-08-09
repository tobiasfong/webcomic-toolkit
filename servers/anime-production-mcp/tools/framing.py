"""
framing.py — put a clip inside a hand-drawn frame, animate that frame's
decoration, and composite a generated patch back over the original art.

Three jobs that share one idea: the artist's drawing stays authoritative, and
code only ever arranges or animates it.

WHY A DRAWN FRAME. Portrait artwork in a 16:9 video is only ~720px wide at full
height, leaving 1200px of dead screen. A drawn frame with a transparent slot
fills that with something the artist made, instead of blur or black.
"""

from __future__ import annotations

import math
import os
from collections import deque

from PIL import Image, ImageFilter, ImageSequence

from .motion import expand_frames, _dedupe_guard


# --------------------------------------------------------------------------- #
# slot measurement
# --------------------------------------------------------------------------- #

def measure_slot(frame_path: str, alpha_max: int = 8) -> dict:
    """Find the transparent slot in a drawn frame.

    ⚠ THE ALPHA BOUNDING BOX IS NOT THE SLOT. Decoration is drawn ON
    transparency, so the gaps between leaves count as transparent and the bbox
    comes out far too wide — on the reference frame, 1180px against a true
    802px. That left a white line along the bottom edge of every panel.

    The slot is the set of columns clear for the FULL height, and the rows clear
    for the full width. That is the only region where artwork can show through
    without a decorated pixel crossing it.
    """
    im = Image.open(frame_path).convert("RGBA")
    W, H = im.size
    a = im.getchannel("A")
    px = a.load()

    cols = [x for x in range(W) if all(px[x, y] <= alpha_max for y in range(H))]
    rows = [y for y in range(H) if all(px[x, y] <= alpha_max for x in range(W))]
    if not cols:
        raise ValueError(
            f"{os.path.basename(frame_path)} has no column that is transparent for its "
            f"full height — so it has no slot. Is this actually a frame with a hole in it?"
        )

    # Longest contiguous run, so a stray transparent margin can't widen the slot.
    def run(vals):
        best = cur = [vals[0], vals[0]]
        for v in vals[1:]:
            if v == cur[1] + 1:
                cur[1] = v
            else:
                if cur[1] - cur[0] > best[1] - best[0]:
                    best = cur
                cur = [v, v]
        return best if best[1] - best[0] >= cur[1] - cur[0] else cur

    x0, x1 = run(cols)
    y0, y1 = run(rows) if rows else (0, H - 1)
    return {"frame": frame_path, "frame_size": [W, H],
            "slot": [x0, y0, x1 + 1, y1 + 1],
            "slot_size": [x1 + 1 - x0, y1 + 1 - y0],
            "note": "measured by full-height columns, NOT the alpha bounding box"}


def _cover(art: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to cover w x h, centre-cropping the overflow. Never letterbox."""
    s = max(w / art.width, h / art.height)
    r = art.resize((round(art.width * s), round(art.height * s)), Image.LANCZOS)
    x, y = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


def frame_clip(src: str, dst: str, frame_path: str,
               slot: tuple[int, int, int, int] | None = None,
               video_size: tuple[int, int] = (1920, 1080),
               bleed: int = 3, fps: int = 12,
               background: tuple[int, int, int] = (255, 255, 255)) -> dict:
    """Composite every frame of a clip into the drawn frame's slot.

    `bleed` overfills the slot by a few pixels so the frame's own antialiased
    inner edge never reveals background through it.

    The panel is centred in `video_size` with the leftover as flat margin. Leave
    that the same colour as the frame's own margins and it reads as a mat rather
    than as letterboxing.
    """
    frame = Image.open(frame_path).convert("RGBA")
    if slot is None:
        slot = tuple(measure_slot(frame_path)["slot"])
    sx0, sy0, sx1, sy1 = slot
    sw, sh = sx1 - sx0, sy1 - sy0

    base_frames = expand_frames(src)
    VW, VH = video_size
    fw, fh = frame.size
    pw = round(fw * VH / fh)

    out = []
    for art in base_frames:
        base = Image.new("RGBA", frame.size, (*background, 255))
        base.paste(_cover(art, sw + bleed * 2, sh + bleed * 2), (sx0 - bleed, sy0 - bleed))
        panel = Image.alpha_composite(base, frame).convert("RGB")
        canvas = Image.new("RGB", (VW, VH), background)
        canvas.paste(panel.resize((pw, VH), Image.LANCZOS), ((VW - pw) // 2, 0))
        out.append(canvas)

    out = _dedupe_guard(out)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    out[0].save(dst, save_all=True, append_images=out[1:],
                duration=int(round(1000 / fps)), loop=0, quality=88)
    return {"path": dst, "frames": len(out), "slot": list(slot),
            "panel_size": [pw, VH], "video_size": [VW, VH],
            "kb": os.path.getsize(dst) // 1024}


def extract_bars(frame_path: str, bars: list[tuple[int, int]],
                 warm: bool = True) -> list[Image.Image]:
    """Key the frame's vertical rules out by colour, as standalone RGBA strips.

    For LANDSCAPE artwork, which cannot use a portrait slot. Place these either
    side of the wide image and every panel in the video shares one visual
    language — rules flanking the picture, mat beyond.

    ⚠ THE BARS MUST FLANK THE ART, NEVER OVERLAY IT. At their original x they
    run straight through the middle of a wide image.

    Only the given column runs are kept: a plain colour key also catches warm
    details elsewhere in the decoration (flower stamens), which would come along
    as stray specks.
    """
    f = Image.open(frame_path).convert("RGBA")
    W, H = f.size
    px = f.load()
    m = Image.new("L", (W, H), 0)
    mp = m.load()
    for y in range(H):
        for x in range(W):
            r, g, b, a = px[x, y]
            hit = (r > 120 and r > b + 35 and g > b + 15 and r >= g) if warm else (a > 40)
            if a > 40 and hit:
                mp[x, y] = a
    out = []
    for x0, x1 in bars:
        strip = Image.new("RGBA", (x1 - x0, H), (0, 0, 0, 0))
        strip.paste(f.crop((x0, 0, x1, H)), (0, 0), m.crop((x0, 0, x1, H)))
        out.append(strip)
    return out


# --------------------------------------------------------------------------- #
# fluttering decoration
# --------------------------------------------------------------------------- #

class Flutter:
    """Animate a drawn frame's decoration — leaves sway, blossoms nod.

    A credits card can hold for a minute. A still image that long reads as the
    video having ended, so the frame's own decoration is animated rather than
    adding a camera move.

    HOW THE PIECES ARE SEPARATED: the decoration may be painted on an OPAQUE
    field rather than on transparency, in which case connected-component
    labelling on alpha returns the whole margin as one blob. Colour separates
    them instead. `rules` is a list of (name, test) where test takes (r,g,b) —
    the defaults handle green foliage and pink blossom on a white field with
    warm rules excluded.

    Each sprite is lifted out and its original position painted over with
    `field`, so rotating it cannot leave a ghost of itself behind.

    Sprites are pre-rotated once per distinct angle and CACHED — rotating dozens
    of sprites live for every frame of a long hold would dominate the render.
    """

    ANGLE_STEPS = 24

    def __init__(self, frame_path: str,
                 protect: tuple[int, int] | None = None,
                 field: tuple[int, int, int] = (255, 255, 255),
                 min_blob: int = 250,
                 amp_primary: float = 3.4, amp_secondary: float = 1.8,
                 seed: int = 3):
        self.frame = Image.open(frame_path).convert("RGBA")
        self.protect = protect          # x-range to leave alone (the artwork slot)
        self.field = field
        self.min_blob = min_blob
        self.base, self.sprites = self._extract()
        self._prepare(amp_primary, amp_secondary, seed)

    def _classify(self, px, x, y):
        r, g, b, a = px[x, y]
        if a < 60:
            return None
        if self.protect and self.protect[0] <= x < self.protect[1]:
            return None
        if r > 200 and g > 200 and b > 200:
            return None                                    # the field itself
        if r > 120 and r > b + 35 and g > b + 15 and r >= g:
            return None                                    # warm rules/bars
        if g >= r and g >= b:
            return "primary"                               # foliage
        if r > g + 18 and b > g - 10 and r > 150:
            return "secondary"                             # blossom
        return None

    def _extract(self):
        W, H = self.frame.size
        px = self.frame.load()
        seen = [[0] * W for _ in range(H)]
        blobs = []
        for y in range(H):
            for x in range(W):
                if seen[y][x]:
                    continue
                k = self._classify(px, x, y)
                if k is None:
                    seen[y][x] = 1
                    continue
                q = deque([(x, y)])
                seen[y][x] = 1
                pts = []
                while q:
                    cx, cy = q.popleft()
                    pts.append((cx, cy))
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                                   (1, 1), (-1, -1), (1, -1), (-1, 1)):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < W and 0 <= ny < H and not seen[ny][nx] \
                                and self._classify(px, nx, ny) == k:
                            seen[ny][nx] = 1
                            q.append((nx, ny))
                if len(pts) > self.min_blob:
                    blobs.append((k, pts))

        base = self.frame.copy()
        bp = base.load()
        sprites = []
        for k, pts in blobs:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
            sp = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
            spp = sp.load()
            for cx, cy in pts:
                spp[cx - x0, cy - y0] = px[cx, cy]
                bp[cx, cy] = (*self.field, 255)            # erase, so no ghost remains
            sprites.append(dict(kind=k, img=sp, cx=(x0 + x1) / 2, cy=(y0 + y1) / 2))
        return base, sprites

    def _prepare(self, amp_primary, amp_secondary, seed):
        import random as pyr
        pyr.seed(seed)
        for s in self.sprites:
            s["phase"] = pyr.random()
            s["period"] = (3.2 + pyr.random() * 2.6) if s["kind"] == "primary" \
                else (5.5 + pyr.random() * 3.0)
            s["amp"] = amp_primary if s["kind"] == "primary" else amp_secondary
            s["drift"] = 2.2 if s["kind"] == "primary" else 1.0
            s["cache"] = {
                j: s["img"].rotate(-s["amp"] + 2 * s["amp"] * j / (self.ANGLE_STEPS - 1),
                                   resample=Image.BICUBIC, expand=True)
                for j in range(self.ANGLE_STEPS)
            }

    def counts(self) -> dict:
        return {"primary": sum(1 for s in self.sprites if s["kind"] == "primary"),
                "secondary": sum(1 for s in self.sprites if s["kind"] == "secondary")}

    def render(self, t: float) -> Image.Image:
        """The decorated frame at time t (seconds), as RGBA."""
        out = self.base.copy()
        for s in self.sprites:
            v = math.sin(2 * math.pi * (t / s["period"] + s["phase"]))
            j = int(round((v + 1) / 2 * (self.ANGLE_STEPS - 1)))
            rot = s["cache"][j]
            dx = int(round(v * s["drift"]))
            dy = int(round(math.cos(2 * math.pi * (t / s["period"] * 0.7 + s["phase"]))
                           * s["drift"] * 0.6))
            out.alpha_composite(rot, (int(s["cx"] - rot.width / 2) + dx,
                                      int(s["cy"] - rot.height / 2) + dy))
        return out


# --------------------------------------------------------------------------- #
# compositing a generated patch back over the original
# --------------------------------------------------------------------------- #

def freeze_region(src: str, dst: str, box, from_frame: int = 0,
                  source_frame: int = 0, feather: float = 18.0, fps: int = 12,
                  drift_tol: float = 6.0) -> dict:
    """Hold one region from an early frame over the later ones.

    For the common LTX failure where the BODY moves correctly but the FACE
    dissolves partway through. Rather than throw the take away or truncate it to
    a fraction of its length, keep the motion and paste the intact face back on.
    Anime does this constantly — a held face over a moving body is ordinary
    limited-animation practice, not a cheat.

    ⚠ ONLY VALID WHERE THE REGION BARELY MOVES. If the head travels, a static
    paste detaches it from the neck. This measures how far the region's content
    shifts and REPORTS it rather than silently shipping a floating head —
    `drift_tol` is the mean-abs-difference above which the region is judged to
    have moved. Check `safe` before using the result.
    """
    import numpy as np
    from PIL import ImageDraw

    box = tuple(box)
    frames = expand_frames(src)
    if not 0 <= source_frame < len(frames):
        raise ValueError(f"source_frame {source_frame} outside 0..{len(frames)-1}")
    src_reg = frames[source_frame].crop(box)

    a = np.asarray(src_reg.convert("L"), dtype=np.float32)
    drift = 0.0
    for f in frames[from_frame:]:
        b = np.asarray(f.crop(box).convert("L"), dtype=np.float32)
        drift = max(drift, float(np.abs(a - b).mean()))

    # ELLIPSE, not a rectangle. A rectangular paste leaves four corners and a
    # straight edge cutting across whatever it lands on — measured on a shot
    # where the seam ran visibly across the character's collar. An ellipse
    # inset from the box, heavily feathered, has no corners and dies out inside
    # the face rather than at its boundary.
    mask = Image.new("L", src_reg.size, 0)
    w, h = src_reg.size
    inset = max(2, int(min(w, h) * 0.06))
    ImageDraw.Draw(mask).ellipse([inset, inset, w - 1 - inset, h - 1 - inset], fill=255)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))

    out = []
    for i, f in enumerate(frames):
        if i < from_frame:
            out.append(f)
            continue
        g = f.copy()
        g.paste(src_reg, (box[0], box[1]), mask)
        out.append(g)

    out = _dedupe_guard(out)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    out[0].save(dst, save_all=True, append_images=out[1:],
                duration=int(round(1000 / fps)), loop=0, quality=90)
    return {"path": dst, "frames": len(out), "box": list(box),
            "from_frame": from_frame, "source_frame": source_frame,
            "drift": round(drift, 2), "safe": drift <= drift_tol,
            "warning": None if drift <= drift_tol else
                       (f"region moved (drift {drift:.1f} > {drift_tol}); a static "
                        f"paste will look detached — truncate instead")}


def register(base: Image.Image, patch: Image.Image,
             box: tuple[int, int, int, int],
             scales=tuple(0.88 + 0.02 * i for i in range(14)),
             span: int = 26) -> tuple[Image.Image, dict]:
    """Align a generated patch to the base using the parts that did NOT change.

    ⚠ WHY THIS IS NEEDED. `FluxKontextImageScale` snaps the input to one of the
    model's own supported resolutions, and that resolution does not preserve the
    source aspect ratio — measured drift of 0.024 to 0.095 on real panels.
    Resizing the result straight back to the base size therefore stretches it by
    a few percent in one axis, and a few percent is enormous on a face: the
    redrawn glasses come back visibly larger than the pair underneath, so the
    blink reads as a sticker rather than as eyelids closing.

    The fix is registration, not a better resize. Everything OUTSIDE the edited
    region is supposed to be identical, so scale and offset can be recovered by
    minimising the residual there. Scored on a downsampled greyscale copy — this
    only needs to land within a pixel, and full resolution would be far slower
    for no gain.
    """
    import numpy as np

    W, H = base.size
    q = max(1, min(W, H) // 220)                 # coarse enough to be quick
    bs = base.convert("L").resize((W // q, H // q), Image.BILINEAR)
    ba = np.asarray(bs, dtype=np.float32)

    # Score a RING around the edited region, not the whole frame.
    # Whole-frame scoring finds the alignment that best fits the picture on
    # average, which is not the alignment that fits THE FACE — measured on a
    # portrait where the global best still left the redrawn glasses visibly
    # oversized over the originals. The pixels that matter are the ones just
    # outside the eyes: cheekbone, nose bridge, spectacle rims. Fit those and
    # the new eyelids land inside the original frames.
    x0, y0, x1, y1 = [v // q for v in box]
    gx, gy = max(2, (x1 - x0)), max(2, (y1 - y0))
    ring = np.zeros_like(ba, dtype=bool)
    ring[max(0, y0 - gy):y1 + gy, max(0, x0 - gx):x1 + gx] = True
    hole = np.zeros_like(ring)
    pad = max(1, 4 // q)
    hole[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = True
    keep = ring & ~hole
    if keep.sum() < 64:
        keep = ~hole

    # Cover-fit factor: scales the patch so it fully covers the base while
    # keeping the PATCH's own proportions. Resizing to the base's width/height
    # instead re-applies the very stretch this function exists to undo — the
    # two aspect ratios differ by up to 0.095.
    cov = max(W / patch.width, H / patch.height)

    best = (None, 1e18, {})
    for s in scales:
        pw = max(1, round(patch.width * cov * s))
        ph = max(1, round(patch.height * cov * s))
        cand = patch.convert("L").resize((pw, ph), Image.BILINEAR)
        cand = cand.resize((max(1, pw // q), max(1, ph // q)), Image.BILINEAR)
        ca = np.asarray(cand, dtype=np.float32)
        for dy in range(-span // q, span // q + 1):
            for dx in range(-span // q, span // q + 1):
                # window of the candidate that lands on the base grid
                sy, sx = (ca.shape[0] - ba.shape[0]) // 2 + dy, \
                         (ca.shape[1] - ba.shape[1]) // 2 + dx
                if sy < 0 or sx < 0 or sy + ba.shape[0] > ca.shape[0] \
                        or sx + ba.shape[1] > ca.shape[1]:
                    continue
                win = ca[sy:sy + ba.shape[0], sx:sx + ba.shape[1]]
                err = float(np.abs(win - ba)[keep].mean())
                if err < best[1]:
                    best = (None, err, {"scale": s, "dx": dx * q, "dy": dy * q})

    if not best[2]:
        return patch.resize(base.size, Image.LANCZOS), {"aligned": False}

    s, dx, dy = best[2]["scale"], best[2]["dx"], best[2]["dy"]
    pw = max(1, round(patch.width * cov * s))
    ph = max(1, round(patch.height * cov * s))
    full = patch.convert("RGB").resize((pw, ph), Image.LANCZOS)
    left, top = (pw - W) // 2 + dx, (ph - H) // 2 + dy
    out = Image.new("RGB", (W, H))
    out.paste(full, (-left, -top))
    return out, {"aligned": True, "scale": s, "dx": dx, "dy": dy,
                 "residual": round(best[1], 3)}


def composite_patch(base_path: str, patch_path: str, dst: str,
                    box: tuple[int, int, int, int], feather: float = 6.0,
                    blend: float = 1.0,
                    ellipses: list | None = None) -> dict:
    """Paste ONLY `box` from a generated image back over the original art.

    This is the other half of the Kontext path, and skipping it is the mistake
    that ruins a shot. Kontext regenerates the WHOLE frame, so it quietly
    restyles linework and shifts colour in places nobody asked about. Only the
    region that was supposed to change may come back.

    `blend` < 1 mixes the patch with the original underneath — how a half-lid is
    made, since Kontext is binary and cannot draw one. 0.5 of a closed-eye patch
    over open eyes gives the mid position.
    """
    base = Image.open(base_path).convert("RGB")
    patch = Image.open(patch_path).convert("RGB")
    align = {"aligned": False}
    if patch.size != base.size:
        # NEVER a plain resize — Kontext's output does not share the source
        # aspect ratio, and stretching it makes the redrawn feature a few
        # percent too big, which reads as a sticker pasted on the face.
        patch, align = register(base, patch, tuple(box))

    from PIL import ImageDraw
    mask = Image.new("L", base.size, 0)
    ink = int(255 * max(0.0, min(1.0, blend)))
    d = ImageDraw.Draw(mask)
    if ellipses:
        # TAKE AS LITTLE AS POSSIBLE. Kontext regenerates the whole frame and
        # will redraw structure it was not asked about — on a bespectacled
        # character it returned the glasses noticeably larger, and a rectangular
        # box dragged those in, so the blink read as a sticker. Patching only the
        # eye INTERIORS drops new eyelids inside the original frames and leaves
        # every rim, brow and highlight untouched.
        for cx, cy, rx, ry in ellipses:
            d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=ink)
    else:
        d.rectangle(list(box), fill=ink)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))

    out = Image.composite(patch, base, mask)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    out.save(dst)
    return {"path": dst, "box": list(box), "blend": blend,
            "size": list(base.size), "alignment": align,
            "regions": "ellipses" if ellipses else "box"}
