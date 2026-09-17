# -*- coding: utf-8 -*-
"""Draw the click-to-continue mark: a right-pointing triangle centered on a
line-tall canvas.

    python draw_ctc.py <out.png> [--line 40] [--height 24] [--gap 7]

WHY A DRAWN TRIANGLE. Phone ports of visual novels add no tap button and no
mouse or console icon; they show a small blinking mark at the end of the
current line, on every platform, and a plain triangle is the one shape that
reads everywhere. It is geometry, so it is drawn, not generated.

WHY LINE-TALL. The engine aligns an inline image to the TOP of the text
line, so a glyph shorter than the line floats at the top of it. Drawing the
triangle centered on a canvas as tall as the line puts it mid-line whatever
the alignment. `--line` is the text's line height in pixels (about 1.2x the
font size); `--gap` is the transparent space before the triangle so it does
not touch the last letter.

WIRING. Declare it as a blinking image and give it to every speaker:

    image ctc_blink:
        "gui/ctc.png"
        alpha 1.0
        pause 0.6
        alpha 0.0
        pause 0.4
        repeat

    define speech = dict(kind=nvl, ctc="ctc_blink", ctc_position="nestled")
    define narrator = Character(kind=nvl_narrator, ctc="ctc_blink", ctc_position="nestled")

Nestled means the mark sits after the text's last character. The NVL screen
shows it with no change of its own.
"""
import argparse
import sys

from PIL import Image, ImageDraw


def draw(out, line=40, height=24, gap=7, width=None, rim=(0, 0, 0, 170), fill=(255, 255, 255, 255)):
    S = 4                                  # draw at 4x, downsample for clean edges
    width = width or int(height * 0.8) + gap
    W, H = width * S, line * S
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    top = (line - height) / 2.0 * S
    bot = top + height * S
    x0 = gap * S
    tip = (gap + height * 0.8) * S
    d.polygon([(x0, top), (tip, (top + bot) / 2), (x0, bot)], fill=rim)
    inset = 0.14 * height * S
    d.polygon([(x0 + inset * 0.7, top + inset), (tip - inset, (top + bot) / 2), (x0 + inset * 0.7, bot - inset)], fill=fill)
    im = im.resize((width, line), Image.LANCZOS)
    im.save(out)
    return im.size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--line", type=int, default=40, help="line height in px (about 1.2x the font size)")
    ap.add_argument("--height", type=int, default=24, help="triangle height in px")
    ap.add_argument("--gap", type=int, default=7, help="transparent space before the triangle")
    a = ap.parse_args(argv)
    w, h = draw(a.out, a.line, a.height, a.gap)
    print("wrote %s (%dx%d)" % (a.out, w, h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
