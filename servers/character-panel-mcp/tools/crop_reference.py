"""
crop_reference.py — deterministic slicing of a composite character-concept sheet
into clean single-view crops, ready for register_character. See ARCHITECTURE.md
§8b.6 (Concept Genesis): a composite sheet — the kind ChatGPT/Midjourney sheet
generators produce, with a hero pose + expressions strip + text overlay all in
one JPEG — is unusable as a direct img2img/IP-Adapter reference. The model would
condition on the layout (text blocks, panel borders), not the person. Sheets
must be sliced into single-view crops first.

Crop boxes are pixel coordinates [x0, y0, x1, y1], top-left origin. They come
from a human eyeballing the sheet, or from the harness looking at it once
(vision, opt-in — don't do this by default, it costs tokens) and proposing
boxes for approval.

Usage:
    python crop_reference.py sheet.png --box 40,20,300,600 --box 320,20,580,600
        [--out-dir crops/]
"""
import os
import argparse


def crop_reference(image_path, boxes, out_dir=None):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("crop_reference needs Pillow: <venv>/python -m pip install pillow")
    if not os.path.isfile(image_path):
        raise SystemExit(f"could not read image: {image_path}")
    if not boxes:
        raise SystemExit("crop_reference needs at least one box [x0, y0, x1, y1].")

    im = Image.open(image_path)
    iw, ih = im.size
    if out_dir is None:
        out_dir = os.path.splitext(image_path)[0] + "_crops"
    os.makedirs(out_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(image_path))[0]
    out_paths = []
    for i, box in enumerate(boxes):
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            raise SystemExit(f"invalid box {box}: x1/y1 must exceed x0/y0")
        if x0 < 0 or y0 < 0 or x1 > iw or y1 > ih:
            raise SystemExit(f"box {box} is outside the image bounds ({iw}x{ih})")
        crop = im.crop((x0, y0, x1, y1)).convert("RGB")
        out_path = os.path.join(out_dir, f"{base}_crop_{i:02d}.png")
        crop.save(out_path)
        out_paths.append(out_path)
    return out_paths


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--box", action="append", required=True,
                    help="x0,y0,x1,y1 (pixels) — repeat for multiple crops")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args()
    boxes = [[int(v) for v in b.split(",")] for b in a.box]
    for p in crop_reference(a.image, boxes, a.out_dir):
        print(p)
