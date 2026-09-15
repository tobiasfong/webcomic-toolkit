# -*- coding: utf-8 -*-
"""Losslessly shrink every PNG under a Ren'Py project's game folder.

    python optimize_png.py <project-dir> [--level 2] [--jobs 4] [--no-check]

WHY. The web build ships the game's PNGs byte-for-byte under progressive
download, so their size IS the browser download. Measured 2026-09-16 on a
project of 201 files: 101.8 MB -> 90.7 MB (10.9%) at level 2 in 85 s, every
pixel identical. Run it before build_web.py whenever images were added.

LOSSLESS, AND CHECKED. oxipng only rewrites the compression and safely
strips ancillary chunks; the pixel data cannot change. The check turns that
from a promise into a measurement: every file's RGBA pixels are hashed
before and after, and a mismatch fails the run and names the file. It costs
a couple of seconds on a hundred megabytes. Alpha optimization -- zeroing
the color under fully transparent pixels -- is deliberately NOT enabled. It
is invisible on screen but it IS a pixel change, and project tools that
compare an installed sprite against its source render by content would see
it as drift.

Level 2 is the sweet spot; higher levels take several times longer for
another percent or two. Needs `pyoxipng` in the venv (requirements.txt).
Idempotent: a second run finds nothing left to squeeze and changes no file.
"""
import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image


def png_files(root):
    return sorted(os.path.join(dp, f) for dp, _, fs in os.walk(root)
                  for f in fs if f.lower().endswith(".png"))


def pixels(path):
    """(sha1 of the RGBA pixel data, size) -- the identity a lossless pass must keep."""
    im = Image.open(path)
    im.load()
    return hashlib.sha1(im.convert("RGBA").tobytes()).hexdigest(), im.size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", help="Ren'Py project directory (the one containing game/)")
    ap.add_argument("--level", type=int, default=2, help="oxipng level, 0-6 (default 2)")
    ap.add_argument("--jobs", type=int, default=4, help="files in flight at once")
    ap.add_argument("--no-check", action="store_true",
                    help="skip the before/after pixel hash (not recommended)")
    a = ap.parse_args(argv)

    try:
        import oxipng
    except ImportError:
        sys.exit("optimize_png: pyoxipng is not installed in this venv "
                 "(pip install pyoxipng; it is in requirements.txt)")

    root = os.path.join(os.path.abspath(a.project), "game")
    if not os.path.isdir(root):
        sys.exit("optimize_png: no game/ folder under %s" % a.project)
    files = png_files(root)
    if not files:
        sys.exit("optimize_png: no PNG files under %s" % root)

    t0 = time.time()
    before = {f: os.path.getsize(f) for f in files}
    ident = {}
    if not a.no_check:
        ident = {f: pixels(f) for f in files}
        print("hashed %d files in %.0fs" % (len(files), time.time() - t0), flush=True)

    kw = {"level": a.level}
    try:
        kw["strip"] = oxipng.StripChunks.safe()
    except AttributeError:
        pass  # older pyoxipng: keep every chunk rather than guess an API

    t1 = time.time()
    with ThreadPoolExecutor(max(1, a.jobs)) as ex:
        list(ex.map(lambda f: oxipng.optimize(f, **kw), files))
    print("optimized in %.0fs" % (time.time() - t1), flush=True)

    after = sum(os.path.getsize(f) for f in files)
    total = sum(before.values())
    print("PNG: %d files  %.1f MB -> %.1f MB  (%.1f%% smaller)"
          % (len(files), total / 1048576.0, after / 1048576.0,
             100.0 * (1 - after / float(total)) if total else 0.0))

    if a.no_check:
        return 0
    bad = [f for f in files if pixels(f) != ident[f]]
    if bad:
        print("!! %d file(s) CHANGED PIXELS -- this pass was not lossless:" % len(bad))
        for f in bad:
            print("   " + os.path.relpath(f, root))
        return 1
    print("pixel-identical after: %d of %d" % (len(files), len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
