# -*- coding: utf-8 -*-
"""Fix a sprite's hands in one step: options for both hands on one sheet, then
one pick per hand.

    fix_hands(raw)                 -> a sheet + a manifest of candidates
    apply_hand_fix(raw, {0: s, 1: s})  -> the picture with the picked hands
    touch_up(raw, box, text)       -> one small defect redrawn at 6x

WHY THIS EXISTS (2026-11-07). Two hands on one sprite took about two hours,
and almost all of it went to routes that cannot work:

  * In a full-body 832x1216 render a hand is ~50 px wide -- too few pixels for
    the model to draw five fingers, the same resolution failure as a childish
    face. Every route that kept the hand at that size failed: a boxed region
    redraw, an erase-and-redraw of the whole figure, a hand drawing as a second
    reference (its white line art came back as white hands), new seeds of the
    whole figure, transplanting another sprite's hands.
  * Every CODE patch on hand pixels -- stretching, filling, re-drawing an
    outline, inking a dent -- created a new defect that took rounds to undo.

What worked, and is all this does: crop the hand WITH its sleeve, enlarge it
4x (the hand ~200 px), redraw it inside a box sized to the hand that is
WANTED (a layout box sets size as well as place), shrink it back, and paste
only the box. Several seeds, both hands, on ONE sheet; a person picks.

Three rules the code enforces, each from a defect it caused:
  * The cuff, hem and wrist are redrawn TOGETHER: each hand's box starts a
    quarter of its height up, inside the sleeve, and the paste fades in over
    the sleeve's plain cloth. Splitting at the hem failed both ways -- a
    straight edge cut a diagonal hem and redrew the sleeve out of line; an
    edge following the hem kept bits of the old wrist.
  * A redraw never erases first. A flat erase patch is read as the new hand's
    SILHOUETTE and comes back flat and pale.
  * Sides are named both ways on the sheet -- "viewer's left (their right)" --
    because two rounds went to the wrong hand.
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

import klein_workflow as kw

SCALE = 4
TEXT = ("Redraw this hand as a relaxed, natural hand hanging from the sleeve, with five clearly separated "
        "fingers and a thumb, drawn with the same fine linework and skin tone as the face.")
TOUCH_TEXT = "Redraw this small area cleanly, with one smooth continuous outline, in the same style."


# ------------------------------------------------------------- finding them

def _skin_tone(rgb, face):
    """The face's own skin color: bright, warm pixels in the middle of its box."""
    x0, y0, x1, y1 = face
    w, h = x1 - x0, y1 - y0
    sub = rgb[y0 + h // 3:y1 - h // 4, x0 + w // 4:x1 - w // 4].reshape(-1, 3).astype(int)
    warm = sub[(sub.mean(1) > 170) & (sub[:, 0] - sub[:, 2] > 15)]
    return np.median(warm, 0) if len(warm) > 20 else np.array([240, 215, 200])


def find_hands(raw, rgba=None):
    """Boxes for the two hands, by the face's own skin tone, below the chest.

    Returns [(x0, y0, x1, y1), ...] left to right in the picture. The box's
    top is the wrist (the first row of skin under the sleeve); it is grown to
    a natural hand length -- about the face's height -- because a hand drawn
    in a box comes back the box's size.
    """
    im = Image.open(raw).convert("RGB")
    rgb = np.asarray(im).astype(int)
    if rgba is None:
        al = np.ones(rgb.shape[:2], bool)
        face = kw.find_face_box(raw)
    else:
        al = np.asarray(Image.open(rgba).convert("RGBA"))[..., 3] > 128
        face = kw.find_face_box(rgba)
    skin = _skin_tone(rgb, face)
    fh = face[3] - face[1]
    d = np.sqrt(((rgb - skin) ** 2).sum(2))
    cand = al & (d < 26)
    cand[:face[3] + fh] = False                    # nothing above the chest
    lab, n = ndimage.label(cand)
    if not n:
        return []
    sizes = ndimage.sum(cand, lab, range(1, n + 1))
    order = [i + 1 for i in np.argsort(sizes)[::-1][:2] if sizes[i] > 120]
    boxes = []
    for i in order:
        ys, xs = np.nonzero(lab == i)
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max(), ys.max()
        length = max(y1 - y0, int(0.85 * fh))
        width = max(x1 - x0, int(0.45 * fh))
        cx = (x0 + x1) // 2
        boxes.append((int(cx - width * 0.6), int(y0 + 1), int(cx + width * 0.6), int(y0 + 1 + length * 1.1)))
    return sorted(boxes)


# ----------------------------------------------------------- redrawing one

def _redraw(im, box, seed, out_dir, text, scale, margin, skin=None):
    """The picture with ONE box redrawn at `scale`x.

    The box is pasted with soft edges, fading in from its top (14 px for a
    hand, whose box starts inside the sleeve; 6 px for a touch-up). `skin`
    marks a hand. Pasting only the detected hand shape was tried and reverted:
    it cut pale fingertips and left the old fingers as ghosts."""
    W, H = im.size
    x0, y0, x1, y1 = box
    mx, my = margin
    crop = (max(0, x0 - mx), max(0, y0 - my), min(W, x1 + mx), min(H, y1 + my))
    c = im.crop(crop)
    big = c.resize((c.width * scale, c.height * scale), Image.LANCZOS)
    tmp = os.path.join(out_dir, f"_crop_{seed}.png")
    big.save(tmp)
    bx = ((x0 - crop[0]) * scale, (y0 - crop[1]) * scale, (x1 - crop[0]) * scale, (y1 - crop[1]) * scale)
    p = kw.edit_region(tmp, text, out_dir, bx, seed=seed, pad=4 * scale, feather=3 * scale)
    os.remove(tmp)
    small = Image.open(p).convert("RGB").resize(c.size, Image.LANCZOS)
    os.remove(p)
    # paste inside the box only: grown a little left, right and down, NEVER up into the cuff
    # The whole box, so no fingertip is ever cut (pasting only the detected hand
    # shape lost pale fingertips and left old fingers as ghosts -- tried and
    # reverted). Its seams are softened instead: a wide feather on the sides and
    # bottom, and a short fade-in from the top edge so the sleeve's hem blends.
    bm = np.zeros((c.height, c.width), np.float32)
    bm[y0 - crop[1]:y1 - crop[1] + 4, max(0, x0 - crop[0] - 4):x1 - crop[0] + 4] = 1
    bm = ndimage.gaussian_filter(bm, 4)
    ty = y0 - crop[1]
    bm[:max(0, ty)] = 0
    bm = np.minimum(bm * 1.3, 1)
    # The paste fades in from the box's top over FADE px. For a hand the box
    # starts INSIDE the sleeve (see fix_hands), so the cuff, hem and wrist are
    # drawn together and the fade falls on the sleeve's plain cloth. Splitting
    # at the hem failed both ways: a straight edge cut a diagonal hem and
    # redrew the sleeve out of line; an edge following the hem kept bits of
    # the old wrist where the new hand was drawn differently (his catches).
    fade = 14 if skin is not None else 6
    bm = bm * np.clip((np.arange(c.height) - ty) / float(fade), 0, 1)[:, None]
    m = Image.fromarray((bm * 255).astype(np.uint8))
    out = im.copy()
    out.paste(Image.composite(small, c, m), crop[:2])
    return out


def _side(box, W):
    cx = (box[0] + box[2]) / 2
    return "viewer's left (their right)" if cx < W / 2 else "viewer's right (their left)"


# ------------------------------------------------------------------ the tool

def fix_hands(raw, out_dir, seeds=(1, 2, 3, 4), boxes=None, rgba=None, text=TEXT, seed_base=0):
    """Candidates for every hand, and one sheet to pick from."""
    os.makedirs(out_dir, exist_ok=True)
    im = Image.open(raw).convert("RGB")
    W, H = im.size
    boxes = [tuple(int(v) for v in b) for b in (boxes or find_hands(raw, rgba))]
    skin = _skin_tone(np.asarray(im).astype(int), kw.find_face_box(rgba or raw))
    if not boxes:
        raise ValueError("no hands found; pass hand_boxes")
    seeds = [seed_base + s for s in seeds]
    variants = {}
    for hi, box in enumerate(boxes):
        bw, bh = box[2] - box[0], box[3] - box[1]
        box = (box[0], max(0, box[1] - bh // 4), box[2], box[3])      # up into the sleeve
        boxes[hi] = box
        margin = (int(bw * 0.6) + 8, int(bh * 0.35) + 8)
        for s in seeds:
            out = _redraw(im, box, s, out_dir, text, SCALE, margin, skin=skin)
            p = os.path.join(out_dir, f"hand{hi}_seed{s}.png")
            out.save(p)
            variants.setdefault(str(hi), {})[str(s)] = p
    manifest = {"raw": os.path.abspath(raw), "boxes": boxes, "seeds": seeds, "variants": variants}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    sheet = _sheet(im, boxes, seeds, variants, out_dir)
    return sheet, manifest


def _sheet(im, boxes, seeds, variants, out_dir):
    W, H = im.size
    fig = im.copy()
    d = ImageDraw.Draw(fig)
    for hi, b in enumerate(boxes):
        d.rectangle(b, outline=(255, 0, 0), width=3)
        d.text((b[0], max(0, b[1] - 14)), f"hand {hi}", fill=(255, 0, 0))
    fig = fig.resize((W * 520 // H, 520))
    rows = []
    for hi, b in enumerate(boxes):
        bw, bh = b[2] - b[0], b[3] - b[1]
        cb = (max(0, b[0] - bw // 2), max(0, b[1] - bh // 4), min(W, b[2] + bw // 2), min(H, b[3] + bh // 4))
        k = 3
        cells = []
        orig = im.crop(cb).resize(((cb[2] - cb[0]) * k, (cb[3] - cb[1]) * k), Image.LANCZOS)
        ImageDraw.Draw(orig).text((4, 4), "now", fill=(0, 0, 255))
        cells.append(orig)
        for s in seeds:
            v = Image.open(variants[str(hi)][str(s)]).convert("RGB").crop(cb)
            v = v.resize(((cb[2] - cb[0]) * k, (cb[3] - cb[1]) * k), Image.LANCZOS)
            ImageDraw.Draw(v).text((4, 4), f"seed {s}", fill=(0, 0, 255))
            cells.append(v)
        rw = sum(c.width for c in cells) + 10 * len(cells)
        row = Image.new("RGB", (rw, cells[0].height + 22), "white")
        ImageDraw.Draw(row).text((4, 4), f"hand {hi}: {_side(b, W)}", fill=(0, 0, 0))
        x = 0
        for c in cells:
            row.paste(c, (x, 22)); x += c.width + 10
        rows.append(row)
    sw = max([fig.width] + [r.width for r in rows])
    sh = fig.height + sum(r.height + 10 for r in rows) + 10
    sheet = Image.new("RGB", (sw, sh), "white")
    sheet.paste(fig, (0, 0))
    y = fig.height + 10
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height + 10
    p = os.path.join(out_dir, "hands_sheet.png")
    sheet.save(p)
    return p


def apply_hand_fix(out_dir, picks):
    """The raw picture with each picked hand pasted in (only inside its box).

    picks: {hand index: seed}; a hand left out keeps its current drawing.
    """
    with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    base = np.asarray(Image.open(man["raw"]).convert("RGB")).copy()
    H, W = base.shape[:2]
    for hi, s in picks.items():
        b = man["boxes"][int(hi)]
        v = np.asarray(Image.open(man["variants"][str(hi)][str(s)]).convert("RGB"))
        raw0 = np.asarray(Image.open(man["raw"]).convert("RGB"))
        changed = np.any(v != raw0, axis=2)
        base[changed] = v[changed]
    stem = os.path.splitext(os.path.basename(man["raw"]))[0]
    p = os.path.join(out_dir, f"{stem}_hands_fixed.png")
    Image.fromarray(base).save(p)
    return p


def touch_up(raw, box, out_dir, seed=1, text=TOUCH_TEXT, scale=6):
    """One small defect (a dent in an outline, a stray line) redrawn at `scale`x,
    BUILT ON what is there -- the fix that worked first time on a finger dent."""
    os.makedirs(out_dir, exist_ok=True)
    im = Image.open(raw).convert("RGB")
    bw, bh = box[2] - box[0], box[3] - box[1]
    out = _redraw(im, tuple(int(v) for v in box), seed, out_dir, text, scale, (bw + 10, bh + 10))
    p = os.path.join(out_dir, f"touchup_{seed}.png")
    out.save(p)
    return p
