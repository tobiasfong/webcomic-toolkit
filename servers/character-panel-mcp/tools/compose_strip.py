"""
compose_strip.py — deterministic CPU compositing of finished panels into one
vertical webtoon strip. No GPU, no tokens, instant to iterate — same "cheap
compositing, expensive generation stays separate" principle as compose_panel.

Panels arrive at whatever aspect ratio their own generation used (portrait
character shots, landscape action panels, mixed). Each is scaled to the strip's
shared column width before stacking, since that is how a vertical-scroll strip
reads. A wide landscape panel therefore ends up shorter in the stack than a
portrait one, which is correct — it is not forced square.

Per-panel framing: real webtoon pages alternate between full-bleed panels that
run edge to edge and inset panels sitting in the page margin with a border, and
that contrast carries a lot of the pacing. So a panel may be given an `inset`
(margin in px on each side, panel scaled down to fit) and a `border`. A plain
path means full-bleed, which is the old behaviour.

Usage (API):
    compose_strip([
        "p01.png",                                     # full-bleed
        {"path": "p02.png", "inset": 48, "border": 3}, # inset box with border
    ], width=800, gutter=28)

Usage (CLI — every panel full-bleed, or all inset via --inset):
    python compose_strip.py p1.png p2.png --width 800 --gutter 24
        [--inset 48] [--border 3] [--gutter-color 255,255,255] [--out strip.png]
"""
import os
import argparse


def _norm(spec):
    """Accept either a bare path (full-bleed) or a dict of per-panel options."""
    if isinstance(spec, str):
        return {"path": spec, "inset": 0, "border": 0, "border_color": (0, 0, 0)}
    out = {"inset": 0, "border": 0, "border_color": (0, 0, 0)}
    out.update(spec)
    if "path" not in out:
        raise SystemExit(f"panel spec is missing 'path': {spec!r}")
    return out


def compose_strip(panels, width=800, gutter=24, gutter_color=(255, 255, 255), out=None):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("compose_strip needs Pillow: <venv>/python -m pip install pillow")

    if not panels:
        raise SystemExit("compose_strip needs at least one panel")
    specs = [_norm(p) for p in panels]
    for s in specs:
        if not os.path.isfile(s["path"]):
            raise SystemExit(f"could not read panel: {s['path']}")

    rendered = []
    for s in specs:
        im = Image.open(s["path"]).convert("RGB")
        w, h = im.size
        if w <= 0:
            raise SystemExit(f"panel has zero width: {s['path']}")
        inset, border = int(s["inset"]), int(s["border"])
        # the artwork occupies the column minus the margins and the border stroke
        art_w = width - 2 * inset - 2 * border
        if art_w <= 0:
            raise SystemExit(
                f"inset/border too large for width={width} on {s['path']}")
        art_h = max(1, round(h * (art_w / w)))
        art = im.resize((art_w, art_h), Image.LANCZOS)

        if inset == 0 and border == 0:
            rendered.append(art)
            continue

        cell = Image.new("RGB", (width, art_h + 2 * border), gutter_color)
        cell.paste(art, (inset + border, border))
        if border:
            d = ImageDraw.Draw(cell)
            d.rectangle(
                [inset, 0, inset + art_w + 2 * border - 1, art_h + 2 * border - 1],
                outline=tuple(s["border_color"]), width=border)
        rendered.append(cell)

    total_h = sum(im.height for im in rendered) + gutter * (len(rendered) - 1)
    strip = Image.new("RGB", (width, total_h), gutter_color)
    y = 0
    for im in rendered:
        strip.paste(im, (0, y))
        y += im.height + gutter

    if out is None:
        root = os.path.splitext(specs[0]["path"])[0]
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
    ap.add_argument("--width", type=int, default=800, help="shared strip width in px")
    ap.add_argument("--gutter", type=int, default=24, help="gap between panels in px")
    ap.add_argument("--gutter-color", default="255,255,255",
                    help="R,G,B of the page behind/between panels")
    ap.add_argument("--inset", type=int, default=0,
                    help="side margin in px applied to every panel (0 = full-bleed)")
    ap.add_argument("--border", type=int, default=0,
                    help="border stroke in px applied to every panel")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    color = tuple(int(x) for x in a.gutter_color.split(","))
    specs = [{"path": p, "inset": a.inset, "border": a.border} for p in a.panels]
    print(compose_strip(specs, a.width, a.gutter, color, a.out))
