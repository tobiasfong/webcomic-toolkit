"""
compose_strip.py — deterministic CPU compositing of finished panels into one
vertical webtoon strip. No GPU, no tokens, instant to iterate — same "cheap
compositing, expensive generation stays separate" principle as compose_panel.

Panels can arrive at whatever aspect ratio their own generation used (portrait
character shots, landscape action panels, mixed) — this tool normalizes all of
them to one shared strip width before stacking, since that's how a webtoon
vertical-scroll strip actually reads (fixed width, panels flow top to bottom).
A wide landscape panel just ends up shorter in the stack than a portrait one at
the same width, which is correct — it's not supposed to be forced square.

Usage:
    python compose_strip.py panel1.png panel2.png panel3.png ...
        --width 800 --gutter 24 [--gutter-color 255,255,255] [--out strip.png]
"""
import os
import argparse


def compose_strip(panel_paths, width=800, gutter=24, gutter_color=(255, 255, 255), out=None):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("compose_strip needs Pillow: <venv>/python -m pip install pillow")

    if not panel_paths:
        raise SystemExit("compose_strip needs at least one panel")
    for p in panel_paths:
        if not os.path.isfile(p):
            raise SystemExit(f"could not read panel: {p}")

    resized = []
    for p in panel_paths:
        im = Image.open(p).convert("RGB")
        w, h = im.size
        if w <= 0:
            raise SystemExit(f"panel has zero width: {p}")
        scale = width / w
        new_h = max(1, round(h * scale))
        resized.append(im.resize((width, new_h), Image.LANCZOS))

    total_h = sum(im.height for im in resized) + gutter * (len(resized) - 1)
    strip = Image.new("RGB", (width, total_h), gutter_color)
    y = 0
    for im in resized:
        strip.paste(im, (0, y))
        y += im.height + gutter

    if out is None:
        root = os.path.splitext(panel_paths[0])[0]
        out = f"{root}_strip.png"
        n = 1
        while os.path.exists(out):
            out = f"{os.path.splitext(panel_paths[0])[0]}_strip_{n}.png"
            n += 1
    strip.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("panels", nargs="+", help="panel image paths, in reading order")
    ap.add_argument("--width", type=int, default=800, help="shared strip width in px")
    ap.add_argument("--gutter", type=int, default=24, help="gap between panels in px")
    ap.add_argument("--gutter-color", default="255,255,255",
                     help="R,G,B for the gap between panels")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    color = tuple(int(x) for x in a.gutter_color.split(","))
    print(compose_strip(a.panels, a.width, a.gutter, color, a.out))
