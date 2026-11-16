"""Build a choice card from registered sprites: a group, on a dark field.

    python choice_squad.py <path-to-game-dir> <out-name> <sprite> [<sprite> ...] [--out PATH]

Every sprite is a folder name under `game/images/sprites/`. The LAST one given
is the lead: it stands forward, centered and largest, with the others flanking
it and slightly behind. One, two, three or four work; more than four and the
faces stop reading at card size. ONE is a solo card -- a choice between two
people, each card the person (added 2026-11-16).

SOURCES ARE THE PNG MASTERS. Since the game's art went to WebP, the installed
sprite is a lossy copy; the master is <project>/_png_backup/game/images/
sprites/<folder>/body.png when convert_images_webp.py moved it there. That is
read first, then a body.png in the game, then the installed body.webp.

--out PATH writes the card there instead of into game/images/fx, so the PNG
master stays out of the game and install_image.py encodes the WebP copy.

--closeup (one sprite only) crops head to chest, centered on the face, and
fills the card with it. A whole standing figure on a card reads small at the
choice screen's size; a card that means "this person" wants the face (the
author's note on the first solo cards, 2026-11-16: "They're too small").

⚠ NO SPRITE NAMES ARE BAKED INTO THIS FILE, and that is deliberate. The tool
is public and every project's cast is not. Pass them on the command line, or
wrap the call in a project script that lives beside the game.

WHY A COMPOSITE RATHER THAN NEW ART
-----------------------------------
When a card means "go and fetch them", the them already exists as matted
sprites. Painting a fresh crowd would have to decide which people, dressed
how, lit how -- all of it already decided and already on disk. Assembling the
card from the sprites also means it stays correct: re-render a sprite, rerun
this, and the card follows.

⚠ THE RIM LIGHT IS LOAD-BEARING, NOT DECORATION. A cast wearing dark livery on
a card that sits over a dimmed screen loses its silhouette exactly where the
card has to read at a glance. The halo is derived from each sprite's OWN
ALPHA -- blurred, with the solid body subtracted -- so it hugs the figure
instead of being a painted glow that would have to be redrawn per sprite.

STAGING: the lead stands forward and larger so the group has a FRONT. Three
figures at one scale in a row reads as a lineup; a crowd arrives, it does not
queue. Pick as lead whoever speaks for the group in the scene, so the card's
front figure is the voice the player already associates with them.
"""
import os
import sys

from PIL import Image, ImageChops, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir, out_dir  # noqa: E402

W, H = 615, 920                 # matches the choice cards this project uses
BG = (12, 14, 20)
RIM = (150, 190, 255)

# x center as a fraction of width, per figure count. The lead is last.
LAYOUT = {
    1: [0.50],
    2: [0.28, 0.66],
    3: [0.20, 0.80, 0.50],
    4: [0.16, 0.50, 0.84, 0.50],
}


def rim_light(im, spread=9, strength=0.85):
    """A halo that follows the figure, built from its own alpha."""
    a = im.split()[3]
    glow = ImageChops.subtract(a.filter(ImageFilter.GaussianBlur(spread)), a)
    glow = glow.point(lambda v: int(min(255, v * 2.4 * strength)))
    lay = Image.new("RGBA", im.size, RIM + (0,))
    lay.putalpha(glow)
    return lay


def sprite_source(g, folder):
    """The sprite's PNG master if there is one, else what the game has."""
    for p in (os.path.join(os.path.dirname(g), "_png_backup", "game", "images", "sprites", folder, "body.png"),
              os.path.join(g, "images", "sprites", folder, "body.png"),
              os.path.join(g, "images", "sprites", folder, "body.webp")):
        if os.path.exists(p):
            return p
    return None


def closeup(im, frac=0.40):
    """Head to chest of a standing sprite, at the card's aspect, face centered."""
    a = im.split()[3].point(lambda v: 255 if v > 8 else 0)
    x0, y0, x1, y1 = a.getbbox()
    h = int((y1 - y0) * frac)
    w = int(h * W / H)
    # the head's center: the opaque columns of the top tenth of the figure
    band = a.crop((x0, y0, x1, y0 + max(1, (y1 - y0) // 10)))
    cols = [x for x in range(band.width) if band.crop((x, 0, x + 1, band.height)).getbbox()]
    cx = x0 + (sum(cols) / len(cols) if cols else band.width / 2)
    # HEADROOM: a band of empty card above the hair (the author, 2026-11-16:
    # "a small space between the top of their heads and the top border").
    # The crop may start above the sprite's own canvas; that part is empty.
    top = y0 - int(h * 0.09)
    left = int(cx - w / 2)
    crop = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    crop.paste(im.crop((left, max(0, top), left + w, top + h)), (0, max(0, -top)))
    return crop


def main(argv):
    close = "--closeup" in argv
    argv = [a for a in argv if a != "--closeup"]
    out_path = None
    if "--out" in argv:
        i = argv.index("--out")
        out_path = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if len(argv) < 3:
        sys.exit("usage: python choice_squad.py <game-dir> <out-name> "
                 "<sprite> [sprite ...] [--out PATH]   (last sprite leads)")
    g = game_dir(argv[:1])
    out_name, sprites = argv[1], argv[2:]
    if len(sprites) not in LAYOUT:
        sys.exit("choice_squad: %d sprites given; 1 to 4 are supported."
                 % len(sprites))

    card = Image.new("RGBA", (W, H), BG + (255,))
    if close:
        if len(sprites) != 1:
            sys.exit("choice_squad: --closeup takes exactly one sprite")
        src = sprite_source(g, sprites[0])
        if not src:
            sys.exit("choice_squad: no sprite for %s" % sprites[0])
        fig = closeup(Image.open(src).convert("RGBA")).resize((W, H), Image.LANCZOS)
        card.alpha_composite(rim_light(fig), (0, 0))
        card.alpha_composite(fig, (0, 0))
        p = out_path or os.path.join(out_dir(g, "images", "fx"), out_name + ".png")
        card.save(p)
        print("  %-15s %dx%d  %6.0f KB  close-up" % (out_name, W, H, os.path.getsize(p) / 1024))
        return 0
    xs = LAYOUT[len(sprites)]
    for i, (folder, fx) in enumerate(zip(sprites, xs)):
        lead = (i == len(sprites) - 1)
        src = sprite_source(g, folder)
        if not src:
            sys.exit("choice_squad: no sprite for %s" % folder)
        im = Image.open(src).convert("RGBA")
        scale = 0.90 if lead else 0.74
        base = 1.00 if lead else 0.97
        th = int(H * 0.80 * scale)
        tw = int(im.size[0] * th / im.size[1])
        fig = im.resize((tw, th), Image.LANCZOS)
        x, y = int(W * fx - tw / 2), int(H * base - th)
        card.alpha_composite(rim_light(fig), (x, y))
        card.alpha_composite(fig, (x, y))

    p = out_path or os.path.join(out_dir(g, "images", "fx"), out_name + ".png")
    card.save(p)
    print("  %-15s %dx%d  %6.0f KB  %d figures, lead last"
          % (out_name, W, H, os.path.getsize(p) / 1024, len(sprites)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
