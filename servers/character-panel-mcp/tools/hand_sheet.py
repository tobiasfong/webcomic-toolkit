# -*- coding: utf-8 -*-
"""One review sheet of every hand in a batch of renders, zoomed, a row per image.

    <comfy python> hand_sheet.py <out.png> <image> [<image> ...] [--expect N]

WHY. When a picture shows several hands, the odds that all of them come out
right in one render are low, so a good one is found by rolling seeds -- and
the slow part is the human review, opening each full render and hunting for
the hands. This puts every detected hand of every render side by side at a
glance-able size, so the reviewer can pick the seed whose hands all pass.

A HUMAN JUDGES. Nothing here grades a hand: a model grader passed hands an
author failed, on small two-figure CG hands. This only finds and enlarges.

THE DETECTOR MISSES BADLY DEFORMED HANDS (hand_yolov8s, seen on manhwa art),
so it cannot be the gate either: a row that found fewer hands than --expect
is MARKED, and the reviewer should open that full render -- a missing box may
be exactly the broken hand.

Needs ultralytics, which the main ComfyUI's embedded python has, with the
model at ComfyUI/models/ultralytics/bbox/hand_yolov8s.pt (or pass the path
in the HAND_MODEL environment variable).
"""
import os
import sys

from PIL import Image, ImageDraw

TILE = 260
PAD = 8
LABEL_W = 170


def find_model():
    p = os.environ.get("HAND_MODEL")
    if p and os.path.exists(p):
        return p
    here = os.path.dirname(sys.executable)
    for cand in (os.path.join(here, "..", "ComfyUI", "models", "ultralytics", "bbox", "hand_yolov8s.pt"),
                 r"C:\AI\ComfyUI_windows_portable\ComfyUI\models\ultralytics\bbox\hand_yolov8s.pt"):
        if os.path.exists(cand):
            return os.path.abspath(cand)
    sys.exit("hand_sheet: hand_yolov8s.pt not found; set HAND_MODEL")


def hands(model, path, conf=0.2):
    res = model.predict(path, conf=conf, verbose=False)[0]
    boxes = []
    for b in res.boxes:
        x0, y0, x1, y1 = [float(v) for v in b.xyxy[0]]
        boxes.append((x0, y0, x1, y1, float(b.conf[0])))
    boxes.sort(key=lambda b: (b[0] + b[2]) / 2)        # left to right
    return boxes


def main(argv):
    expect = 0
    if "--expect" in argv:
        i = argv.index("--expect")
        expect = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) < 2:
        sys.exit(__doc__)
    out, images = argv[0], argv[1:]
    from ultralytics import YOLO
    model = YOLO(find_model())
    rows = []
    for p in images:
        im = Image.open(p).convert("RGB")
        found = hands(model, p)
        tiles = []
        for x0, y0, x1, y1, c in found[:8]:
            s = max(x1 - x0, y1 - y0) * 1.7
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            crop = im.crop((int(cx - s / 2), int(cy - s / 2), int(cx + s / 2), int(cy + s / 2)))
            tiles.append(crop.resize((TILE, TILE), Image.LANCZOS))
        rows.append((os.path.basename(p), tiles, len(found)))
    cols = max(1, max(len(t) for _, t, _ in rows))
    W = LABEL_W + cols * (TILE + PAD)
    H = len(rows) * (TILE + PAD) + PAD
    sheet = Image.new("RGB", (W, H), (245, 245, 245))
    d = ImageDraw.Draw(sheet)
    for r, (name, tiles, n) in enumerate(rows):
        y = PAD + r * (TILE + PAD)
        warn = expect and n < expect
        d.text((8, y + 8), name[:24], fill=(0, 0, 0))
        d.text((8, y + 28), "%d hand(s) found" % n, fill=(200, 0, 0) if warn else (0, 0, 0))
        if warn:
            d.text((8, y + 48), "CHECK THE FULL RENDER:", fill=(200, 0, 0))
            d.text((8, y + 64), "a hand may be missed", fill=(200, 0, 0))
        for c, t in enumerate(tiles):
            sheet.paste(t, (LABEL_W + c * (TILE + PAD), y))
    sheet.save(out)
    print("sheet ->", out, "| rows", len(rows))
    for name, _, n in rows:
        print("  %-40s %d hand(s)%s" % (name, n, "  <- fewer than expected" if expect and n < expect else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
