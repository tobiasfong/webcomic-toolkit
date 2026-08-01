"""
compose_strip.py — deterministic CPU compositing of finished panels into one
vertical webtoon strip. No GPU, no tokens, instant to iterate — same "cheap
compositing, expensive generation stays separate" principle as compose_panel.

Panels arrive at whatever aspect ratio their own generation used (portrait
character shots, landscape action panels, mixed). Scaling every one of them to
the full column width is the obvious thing to do and it looks wrong: the page
becomes a uniform ladder with no rhythm. Real pages vary panel WIDTH and
ALIGNMENT, and let white space carry the pacing.

So a panel may be:

  * full-bleed — runs edge to edge, no border. Reserve this for the big beats.
  * a bordered box — narrower than the column (`frac`), pushed to the "left",
    "right" or "center", with page showing beside it. This is where reaction
    shots, inserts and detail beats live; the smaller the box, the more it
    reads as a quick beat.
  * a PAIR — two boxes side by side, the second vertically offset, for two
    panels meant to be read as one moment (matched reaction shots, say).

Measured off hand-drawn storyboard sheets rather than guessed: a small insert
beat sits around 0.44-0.55 of the column, a medium box 0.72-0.78, and the
GUTTER is about 15% of the column width — much larger than looks right in the
abstract. `GUTTER_RATIO` below encodes that; the default gutter is derived from
the width rather than being a fixed 24px, which was far too tight.

Usage (API):
    compose_strip([
        "p01.png",                                        # full-bleed
        {"path": "p02.png", "frac": 0.72},                # centred box
        {"path": "p03.png", "frac": 0.44, "align": "right"},
        {"pair": ["p14a.png", "p14b.png"], "frac": 0.30}, # side-by-side pair
    ], width=900)

Usage (CLI — every panel full-bleed, or all boxed via --frac):
    python compose_strip.py p1.png p2.png --width 900
        [--gutter 132] [--frac 0.7] [--align center] [--border 3]
        [--gutter-color 255,255,255] [--out strip.png]

`inset` (a margin in px on each side) is still accepted for backward
compatibility; `frac` is the friendlier way to say the same thing.
"""
import os
import argparse

GUTTER_RATIO = 0.147     # gutter as a fraction of column width, off real sheets
DEFAULT_BORDER = 3
PAIR_GAP = 0.06          # horizontal gap inside a pair, fraction of column
PAIR_DROP = 0.10         # second box's vertical offset, fraction of its height


def _norm(spec):
    """Accept a bare path (full-bleed), or a dict of per-panel options."""
    base = {"inset": 0, "frac": None, "align": "center",
            "border": 0, "border_color": (0, 0, 0), "pair": None,
            "gap": PAIR_GAP, "drop": PAIR_DROP}
    if isinstance(spec, str):
        base["path"] = spec
        return base
    base.update(spec)
    if not base.get("path") and not base.get("pair"):
        raise SystemExit(f"panel spec needs 'path' or 'pair': {spec!r}")
    # A box that did not ask for a border still gets one — an unbordered panel
    # floating in white space reads as a mistake rather than a choice.
    if (base["frac"] or base["inset"]) and not base["border"]:
        base["border"] = DEFAULT_BORDER
    return base


def _framed(Image, ImageDraw, path, art_w, border, border_color, column, align):
    """Scale one panel to art_w, stroke it, and place it in a column-wide row."""
    im = Image.open(path).convert("RGB")
    if im.width <= 0:
        raise SystemExit(f"panel has zero width: {path}")
    art_h = max(1, round(im.height * (art_w / im.width)))
    art = im.resize((art_w, art_h), Image.LANCZOS)
    if not border:
        return art, art_h
    cell = Image.new("RGB", (art_w + 2 * border, art_h + 2 * border),
                     tuple(border_color))
    cell.paste(art, (border, border))
    return cell, cell.height


def compose_strip(panels, width=900, gutter=None, gutter_color=(255, 255, 255),
                  out=None, margin_top=0, margin_bottom=0):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("compose_strip needs Pillow: <venv>/python -m pip install pillow")

    if not panels:
        raise SystemExit("compose_strip needs at least one panel")
    if gutter is None:
        gutter = round(width * GUTTER_RATIO)

    specs = [_norm(p) for p in panels]
    for s in specs:
        for p in (s["pair"] or [s["path"]]):
            if not os.path.isfile(p):
                raise SystemExit(f"could not read panel: {p}")

    rendered = []
    for s in specs:
        if s["pair"]:
            bw = max(1, round(width * (s["frac"] or 0.30)))
            gap = round(width * s["gap"])
            boxes = [_framed(Image, ImageDraw, p, bw, s["border"] or DEFAULT_BORDER,
                             s["border_color"], width, "center")[0]
                     for p in s["pair"]]
            drop = round(boxes[-1].height * s["drop"])
            span = sum(b.width for b in boxes) + gap * (len(boxes) - 1)
            row = Image.new("RGB", (width, max(boxes[0].height,
                                               boxes[-1].height + drop)),
                            gutter_color)
            x = max(0, (width - span) // 2)
            for i, b in enumerate(boxes):
                row.paste(b, (x, drop if i else 0))
                x += b.width + gap
            rendered.append(row)
            continue

        if s["frac"] is not None:
            art_w = max(1, round(width * s["frac"]) - 2 * s["border"])
        else:
            art_w = width - 2 * int(s["inset"]) - 2 * int(s["border"])
        if art_w <= 0:
            raise SystemExit(f"frac/inset/border too small for width={width} "
                             f"on {s['path']}")

        cell, _ = _framed(Image, ImageDraw, s["path"], art_w, s["border"],
                          s["border_color"], width, s["align"])
        if cell.width >= width:
            rendered.append(cell)
            continue

        row = Image.new("RGB", (width, cell.height), gutter_color)
        if s["frac"] is None:                      # legacy inset behaviour
            x = int(s["inset"])
        else:
            x = {"left": 0, "right": width - cell.width,
                 "center": (width - cell.width) // 2}.get(s["align"],
                                                          (width - cell.width) // 2)
        row.paste(cell, (x, 0))
        rendered.append(row)

    total_h = (margin_top + sum(im.height for im in rendered)
               + gutter * (len(rendered) - 1) + margin_bottom)
    strip = Image.new("RGB", (width, total_h), gutter_color)
    y = margin_top
    for im in rendered:
        strip.paste(im, (0, y))
        y += im.height + gutter

    if out is None:
        first = specs[0]["pair"][0] if specs[0]["pair"] else specs[0]["path"]
        root = os.path.splitext(first)[0]
        out = f"{root}_strip.png"
        n = 1
        while os.path.exists(out):
            out = f"{root}_strip_{n}.png"
            n += 1
    strip.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("panels", nargs="+", help="panel image paths, in reading order")
    ap.add_argument("--width", type=int, default=900, help="shared strip width in px")
    ap.add_argument("--gutter", type=int, default=None,
                    help=f"gap between panels in px (default: width * {GUTTER_RATIO})")
    ap.add_argument("--gutter-color", default="255,255,255",
                    help="R,G,B of the page behind/between panels")
    ap.add_argument("--frac", type=float, default=None,
                    help="panel width as a fraction of the column (omit = full-bleed)")
    ap.add_argument("--align", default="center", choices=["left", "center", "right"])
    ap.add_argument("--inset", type=int, default=0,
                    help="legacy: side margin in px applied to every panel")
    ap.add_argument("--border", type=int, default=0,
                    help="border stroke in px (boxes get one automatically)")
    ap.add_argument("--margin-top", type=int, default=0)
    ap.add_argument("--margin-bottom", type=int, default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    color = tuple(int(x) for x in a.gutter_color.split(","))
    specs = [{"path": p, "inset": a.inset, "border": a.border,
              "frac": a.frac, "align": a.align} for p in a.panels]
    print(compose_strip(specs, a.width, a.gutter, color, a.out,
                        a.margin_top, a.margin_bottom))
