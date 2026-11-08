"""
convert_images_webp.py -- turn a Ren'Py project's installed art into WebP, once.

    python convert_images_webp.py <project-dir> [--apply]

<project-dir> is the folder CONTAINING game/. Without --apply it only reports
what it would do.

WHY
---
Installed art is a COPY of a master kept elsewhere, and PNG is the wrong
format for the copy: measured 2026-11-09 on one project, WebP at quality 90
took game/images from 253 MB to 39 MB, and the author could not tell the two
apart side by side. A web host caps a browser game at 500 MB, and the PNGs
alone were already half of that.

WHAT IT DOES
------------
1. Encodes every game/images/**.png as a .webp beside it, with the same
   settings every install now uses (sprites.save_game_image -- one encoder,
   so a later re-install of the same master compares byte-equal).
2. MOVES each original PNG, and any stray non-image file under game/images
   (a `body.png.old`), into <project>/_png_backup/ under the same relative
   path. Nothing is deleted. The backup sits beside game/, never inside it,
   so it is not built into the game.
3. Rewrites every "images/....png" reference to ".webp" -- but only where
   that .webp now exists -- in game/**.rpy, the project's top-level .json
   files and progressive_download.txt (whose rules name files outright: the
   main-menu cover is kept in the first download by its full name).
4. Reports any "images/....png" reference left that resolves to nothing, so
   a miss is listed, not discovered in play.

Interface art under game/gui/ is left as PNG: it is small, ships in the
first download, and its names are built at run time ("[prefix_]bar.png").
"""

import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sprites  # noqa: E402  (the one encoder for installed art)

REF = re.compile(r"(images/[A-Za-z0-9_./\-]+)\.png")


def plan(project):
    game = os.path.join(project, "game")
    root = os.path.join(game, "images")
    pngs, strays = [], []
    for d, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            low = f.lower()
            if low.endswith(".png"):
                pngs.append(p)
            elif not low.endswith((".webp", ".jpg", ".jpeg", ".avif")):
                strays.append(p)
    texts = [os.path.join(d, f) for d, _ds, fs in os.walk(game)
             for f in fs if f.endswith(".rpy")]
    texts += [os.path.join(project, f) for f in os.listdir(project)
              if f.endswith(".json") or f == "progressive_download.txt"]
    return game, pngs, strays, sorted(texts)


def rewrite(text, game):
    """Swap .png for .webp in every images/ reference whose .webp exists."""
    hits = []

    def sub(m):
        rel = m.group(1)
        if os.path.isfile(os.path.join(game, rel + ".webp")):
            hits.append(rel)
            return rel + ".webp"
        return m.group(0)
    return REF.sub(sub, text), hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    project = os.path.abspath(a.project)
    game, pngs, strays, texts = plan(project)
    backup = os.path.join(project, "_png_backup")
    before = sum(os.path.getsize(p) for p in pngs)
    print("%d PNG under game/images (%.1f MB), %d stray files"
          % (len(pngs), before / 1048576, len(strays)))
    if not a.apply:
        for s in strays:
            print("  stray:", os.path.relpath(s, project))
        print("dry run -- pass --apply to convert")
        return

    from PIL import Image
    after = 0
    for p in pngs:
        with Image.open(p) as im:
            im.load()
            blob = sprites.game_image_bytes(im)
        out = os.path.splitext(p)[0] + ".webp"
        if os.path.exists(out):
            sys.exit("refusing: %s already exists" % os.path.relpath(out, project))
        with open(out, "wb") as f:
            f.write(blob)
        after += len(blob)
    for p in pngs + strays:                     # move only after every encode succeeded
        dest = os.path.join(backup, os.path.relpath(p, project))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(p, dest)
    print("encoded %d: %.1f MB -> %.1f MB; originals in %s"
          % (len(pngs), before / 1048576, after / 1048576, os.path.relpath(backup, project)))

    changed = 0
    for t in texts:
        with open(t, encoding="utf-8", newline="") as f:   # keep each file's line endings
            old = f.read()
        new, hits = rewrite(old, game)
        if new != old:
            with open(t, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            changed += 1
            print("  %-40s %d references" % (os.path.relpath(t, project), len(hits)))
    print("rewrote %d files" % changed)

    left = []
    for t in texts:
        with open(t, encoding="utf-8") as f:
            for m in REF.finditer(f.read()):
                if not os.path.isfile(os.path.join(game, m.group(0))):
                    left.append((os.path.relpath(t, project), m.group(0)))
    for t, ref in left:
        print("  UNRESOLVED %s: %s" % (t, ref))
    print("unresolved .png references: %d" % len(left))
    sys.exit(1 if left else 0)


if __name__ == "__main__":
    main()
