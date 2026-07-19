"""
compose_sheet.py — deterministic PIL grid layout: arrange N separately-generated
reference views into ONE composite sheet image, labeled, like a traditional
character turnaround sheet (front/back/side/expressions all on one canvas).

This is NOT the "designed sheet" ARCHITECTURE.md §8b.6 explicitly deferred as a
non-goal (text blocks, logos, bios, quotes — the cosmetic artifact a frontier
model's sheet generator produces). This is the plain grid-of-labeled-crops the
same section already called a "nice-to-have... deferred until someone actually
wants it" — no text rendering beyond a simple view-name caption per cell, no
layout design, just deterministic tiling. Zero GPU, zero tokens.

Usage:
    python compose_sheet.py view1.png view2.png view3.png --label "front" \
        --label "back" --label "side" --out sheet.png
"""
import os
import math
import argparse


def compose_sheet(image_paths, labels=None, out=None, columns=None,
                  cell_width=320, padding=16, label_height=28,
                  background_color=(255, 255, 255)):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise SystemExit("compose_sheet needs Pillow: <venv>/python -m pip install pillow")
    if not image_paths:
        raise SystemExit("compose_sheet needs at least one image.")
    if labels is not None and len(labels) != len(image_paths):
        raise SystemExit(f"got {len(labels)} labels for {len(image_paths)} images — "
                         f"pass one label per image, or none at all.")

    n = len(image_paths)
    if columns is None:
        columns = max(1, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / columns) if columns else 1

    imgs = []
    for p in image_paths:
        if not os.path.isfile(p):
            raise SystemExit(f"could not read image: {p}")
        im = Image.open(p).convert("RGB")
        scale = cell_width / im.width
        cell_h = max(1, round(im.height * scale))
        imgs.append(im.resize((cell_width, cell_h), Image.LANCZOS))

    row_heights = []
    for r in range(rows):
        row_imgs = imgs[r * columns:(r + 1) * columns]
        row_heights.append(max((im.height for im in row_imgs), default=0))

    label_block = label_height if labels else 0
    canvas_w = columns * cell_width + (columns + 1) * padding
    canvas_h = sum(h + label_block for h in row_heights) + (rows + 1) * padding
    canvas = Image.new("RGB", (canvas_w, canvas_h), background_color)
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    y = padding
    for r in range(rows):
        x = padding
        row_h = row_heights[r]
        for c in range(columns):
            i = r * columns + c
            if i >= n:
                break
            im = imgs[i]
            # vertically center within the row's tallest cell
            y_off = (row_h - im.height) // 2
            canvas.paste(im, (x, y + y_off))
            if labels:
                label = labels[i]
                text_y = y + row_h + 4
                if font is not None:
                    bbox = draw.textbbox((0, 0), label, font=font)
                    tw = bbox[2] - bbox[0]
                else:
                    tw = len(label) * 6
                draw.text((x + (cell_width - tw) // 2, text_y), label,
                         fill=(0, 0, 0), font=font)
            x += cell_width + padding
        y += row_h + label_block + padding

    if out is None:
        root = os.path.splitext(image_paths[0])[0]
        out = f"{root}_sheet.png"
        n2 = 1
        while os.path.exists(out):
            out = f"{root}_sheet_{n2}.png"
            n2 += 1
    canvas.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--label", action="append", default=None,
                    help="one per image, in order — repeat for multiple")
    ap.add_argument("--columns", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    print(compose_sheet(a.images, a.label, a.out, a.columns))
