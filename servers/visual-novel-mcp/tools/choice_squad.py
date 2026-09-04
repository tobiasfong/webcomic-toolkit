"""Build a choice card from registered sprites: a group, on a dark field.

    python choice_squad.py <path-to-game-dir> <out-name> <sprite> <sprite> ...

Every sprite is a folder name under `game/images/sprites/`. The LAST one given
is the lead: it stands forward, centered and largest, with the others flanking
it and slightly behind. Two, three or four work; more than four and the faces
stop reading at card size.

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


def main(argv):
    if len(argv) < 4:
        sys.exit("usage: python choice_squad.py <game-dir> <out-name> "
                 "<sprite> <sprite> [sprite ...]   (last sprite leads)")
    g = game_dir(argv[:1])
    out_name, sprites = argv[1], argv[2:]
    if len(sprites) not in LAYOUT:
        sys.exit("choice_squad: %d sprites given; 2, 3 or 4 are supported."
                 % len(sprites))

    card = Image.new("RGBA", (W, H), BG + (255,))
    xs = LAYOUT[len(sprites)]
    for i, (folder, fx) in enumerate(zip(sprites, xs)):
        lead = (i == len(sprites) - 1)
        src = os.path.join(g, "images", "sprites", folder, "body.png")
        if not os.path.exists(src):
            sys.exit("choice_squad: no sprite at %s" % src)
        im = Image.open(src).convert("RGBA")
        scale = 0.90 if lead else 0.74
        base = 1.00 if lead else 0.97
        th = int(H * 0.80 * scale)
        tw = int(im.size[0] * th / im.size[1])
        fig = im.resize((tw, th), Image.LANCZOS)
        x, y = int(W * fx - tw / 2), int(H * base - th)
        card.alpha_composite(rim_light(fig), (x, y))
        card.alpha_composite(fig, (x, y))

    p = os.path.join(out_dir(g, "images", "fx"), out_name + ".png")
    card.save(p)
    print("  %-15s %dx%d  %6.0f KB  %d figures, lead last"
          % (out_name, W, H, os.path.getsize(p) / 1024, len(sprites)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
