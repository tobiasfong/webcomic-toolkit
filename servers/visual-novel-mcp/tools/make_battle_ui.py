"""Draw the battle UI panels: the box frame and the selection cursor.

Pokemon's battle screen is three boxes -- combatant status, a command grid, and
an info panel -- and the boxes are what make it readable at a glance. They are
rounded rectangles with a hard border, which is geometry, so they are DRAWN
here rather than hand-made or generated. Same reasoning as fx_plates.py.

Both images are 9-PATCH: Ren'Py's Frame() keeps the corners and stretches the
edges, so one 96x96 source serves a 460-wide status box and a 1260-wide command
box without distorting the corner radius.

PALETTE NOTE: Pokemon's boxes are cream with a navy border. This game is dark
manhwa, and a cream panel would fight every background in it, so the STRUCTURE
is copied and the colors come from the game's own UI (near-black panel, cool
border, accent-cyan cursor). Change CURSOR to "#e0483c" for the red cursor of
the reference.

    python make_battle_ui.py <path-to-game-dir>
"""
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir, out_dir  # noqa: E402

OUT = out_dir(game_dir(), 'gui')
S = 96              # source size
R = 22              # corner radius
B = 3               # border width
INSET = 6           # 9-patch border, must sit outside the radius

PANEL = (14, 16, 24, 238)        # near-black, slightly transparent
EDGE = (138, 146, 172, 255)      # cool gray border
CURSOR = (0, 184, 195, 255)      # gui.accent_color

PANEL_SOFT = (10, 12, 20, 128)   # ~50%, for a plate over artwork
EDGE_SOFT = (200, 208, 228, 150)


def rounded(fill, outline, width, radius=R):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, S - 2, S - 2], radius=radius,
                        fill=fill, outline=outline, width=width)
    return img



# The panel every battle box uses.
rounded(PANEL, EDGE, B).save(os.path.join(OUT, "battle_box.png"))

# A SOFTER panel, for menus laid over artwork. Same shape, roughly half the
# opacity: a menu needs its text to sit on something so it does not float, but
# the picture behind it is the thing worth seeing, so the plate must not do
# what the battle box does and hide it.
rounded(PANEL_SOFT, EDGE_SOFT, B).save(os.path.join(OUT, "panel_soft.png"))

# The selection cursor: outline only, no fill, so the panel shows through.
rounded(None, CURSOR, B + 1, radius=R - 6).save(
    os.path.join(OUT, "battle_select.png"))

for n in ("battle_box.png", "battle_select.png", "panel_soft.png"):
    p = os.path.join(OUT, n)
    print(f"{n:20} {S}x{S}  9-patch border {INSET}px  {os.path.getsize(p)} bytes")
