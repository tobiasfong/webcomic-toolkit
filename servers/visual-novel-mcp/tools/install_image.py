"""
install_image.py -- put one piece of art (a CG, a background, an effect plate)
into a Ren'Py game as WebP.

    python install_image.py <master> <project-dir> <images/sub/name> [--replace]

The destination is given relative to game/, extension optional:
`images/cg/rihwa_sword` installs game/images/cg/rihwa_sword.webp.

Installed art is a COPY. The master stays where it was made, in whatever
format it was made, and is the thing to keep. Sprites and expression bodies
install through the server's register_sprite / register_body, which use the
same encoder (sprites.save_game_image) -- one encoder for everything in
game/images, at quality 90 (see convert_images_webp.py for why).

Refuses to overwrite a different existing file unless --replace is passed:
replacing installed art is a decision, not a side effect.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sprites  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("master")
    ap.add_argument("project")
    ap.add_argument("dest")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args()
    from PIL import Image
    rel = os.path.splitext(a.dest.replace("\\", "/"))[0] + sprites.GAME_IMAGE_EXT
    if not rel.startswith("images/"):
        sys.exit("destination must be under images/ (relative to game/): %s" % a.dest)
    out = os.path.join(a.project, "game", rel)
    with Image.open(a.master) as im:
        im.load()
        blob = sprites.game_image_bytes(im)
        size = im.size
    if os.path.isfile(out) and not a.replace:
        with open(out, "rb") as f:
            if f.read() != blob:
                sys.exit("%s already exists with different content; pass --replace "
                         "to overwrite it" % rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(blob)
    print("installed %s  %dx%d  %d KB" % (rel, size[0], size[1], len(blob) // 1024))


if __name__ == "__main__":
    main()
