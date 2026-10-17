"""
letter_plaque.py — set real hanzi onto a blank board or scroll in an approved plate.

The model writes pseudo-hanzi, so plates are generated with blank boards and the
real characters are set here: correct glyphs, traditional forms, chosen face.

Ming-period horizontal inscriptions read RIGHT TO LEFT, so "唐門" is drawn with
門 on the left and 唐 on the right (--ltr for modern order). --vertical sets a
single top-to-bottom column for hanging scrolls. --fill repaints the panel face
first, for a board that came back with marks on it.

Usage:
  python letter_plaque.py in.png out.png --text 唐門 --box x0 y0 x1 y1 \
      [--color D9B45A] [--shadow] [--vertical] [--ltr] [--fill 1E1912]
"""
import argparse
from PIL import Image, ImageDraw, ImageFont

FONT = (r"C:\Windows\Fonts\simsun.ttc", 0)   # SimSun: woodblock serif, has traditional forms


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _fit(chars, bw, bh, vertical, gap_ratio):
    """Largest font whose laid-out text fits the box."""
    best, size = ImageFont.truetype(FONT[0], 8, index=FONT[1]), 8
    while size < 600:
        f = ImageFont.truetype(FONT[0], size, index=FONT[1])
        ws = [f.getbbox(c)[2] - f.getbbox(c)[0] for c in chars]
        hs = [f.getbbox(c)[3] - f.getbbox(c)[1] for c in chars]
        if vertical:
            fits = (sum(hs) + max(hs) * gap_ratio * (len(chars) - 1) <= bh * 0.88
                    and max(ws) <= bw * 0.72)
        else:
            fits = (sum(ws) + max(ws) * gap_ratio * (len(chars) - 1) <= bw * 0.82
                    and max(hs) <= bh * 0.82)
        if not fits:
            break
        best, size = f, size + 2
    return best


def letter(inp, out, text, box, color, shadow=False, vertical=False, ltr=False,
           fill=None, gap_ratio=0.13):
    img = Image.open(inp).convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    if fill:
        d.rectangle([x0, y0, x1, y1], fill=_rgb(fill) + (255,))
    chars = list(text) if (vertical or ltr) else list(reversed(text))
    font = _fit(chars, bw, bh, vertical, gap_ratio)
    boxes = [font.getbbox(c) for c in chars]
    ink = _rgb(color) + (255,)

    def draw(x, y, c):
        if shadow:
            d.text((x + 2, y + 2), c, font=font, fill=(0, 0, 0, 110))
        d.text((x, y), c, font=font, fill=ink)

    if vertical:
        hs = [b[3] - b[1] for b in boxes]
        gap = max(hs) * gap_ratio
        y = y0 + (bh - (sum(hs) + gap * (len(chars) - 1))) / 2
        for c, (l, t, r, b) in zip(chars, boxes):
            draw(x0 + (bw - (r - l)) / 2 - l, y - t, c)
            y += (b - t) + gap
    else:
        ws = [b[2] - b[0] for b in boxes]
        gap = max(ws) * gap_ratio
        x = x0 + (bw - (sum(ws) + gap * (len(chars) - 1))) / 2
        for c, (l, t, r, b) in zip(chars, boxes):
            draw(x - l, y0 + (bh - (b - t)) / 2 - t, c)
            x += (r - l) + gap
    Image.alpha_composite(img, layer).convert("RGB").save(out)
    print(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--text", required=True)
    ap.add_argument("--box", nargs=4, type=int, required=True)
    ap.add_argument("--color", default="D9B45A")
    ap.add_argument("--shadow", action="store_true")
    ap.add_argument("--vertical", action="store_true")
    ap.add_argument("--ltr", action="store_true")
    ap.add_argument("--fill", default=None)
    a = ap.parse_args()
    letter(a.input, a.output, a.text, a.box, a.color, a.shadow, a.vertical, a.ltr, a.fill)
