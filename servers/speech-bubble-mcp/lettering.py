"""
lettering.py — fonts and text layout for bubbles.

THE BUBBLE FOLLOWS THE TEXT, NEVER THE REVERSE. A letterer sizes the balloon
around the words at one fixed point size for the whole book; the text is never
shrunk to fit a balloon someone drew first. Uneven type sizes from panel to
panel are the first thing that makes lettering look amateur, so the font size
here is a PROJECT setting (a fraction of the frame's short side), not a
per-bubble one. A bubble can be scaled for a shout, and that is all.

Two layouts:

  horizontal — English, Chinese, Korean. Lines are centered. Wrapping tries
               every line count and keeps the shape that fills an ellipse best,
               which naturally gives the short-long-short "diamond" of a
               hand-lettered balloon.
  vertical   — Japanese tategaki: columns run top to bottom and are read right
               to left, so the bubble is tall and narrow. Brackets, dashes and
               the long-vowel mark are turned 90 degrees and small punctuation
               sits in the upper right of its cell, as in print.

Line breaking follows the basic kinsoku rules for CJK: closing punctuation and
small kana never start a line, opening brackets never end one. An explicit
newline in the text is always honored -- the author's break wins over ours.
"""

from __future__ import annotations

import math
import os
import re
import sys
from dataclasses import dataclass, field

from PIL import ImageFont

# --- fonts -------------------------------------------------------------------

WIN = r"C:\Windows\Fonts"

# First existing file wins. Every entry is a font that ships with its OS; none
# is a lettering face, because no lettering font is licensed on record for this
# toolkit yet (ARCHITECTURE.md §12 q4). Set real ones per project with
# set_project_style(fonts=...).
FALLBACK_FONTS = {
    "en": [os.path.join(WIN, "comicbd.ttf"), os.path.join(WIN, "segoeuib.ttf"),
           "/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "ja": [os.path.join(WIN, "YuGothB.ttc"), os.path.join(WIN, "meiryob.ttc"),
           os.path.join(WIN, "NotoSansJP-VF.ttf"),
           "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
    "zh": [os.path.join(WIN, "msyhbd.ttc"), os.path.join(WIN, "simhei.ttf"),
           "/System/Library/Fonts/PingFang.ttc",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
    "ko": [os.path.join(WIN, "malgunbd.ttf"),
           "/System/Library/Fonts/AppleSDGothicNeo.ttc",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
}

_font_cache: dict = {}


def resolve_font_path(lang: str, override: str | None = None) -> str:
    if override:
        if os.path.isfile(override):
            return override
        cand = os.path.join(WIN, override)
        if os.path.isfile(cand):
            return cand
        raise FileNotFoundError(f"Font not found: {override}")
    for p in FALLBACK_FONTS.get(lang, []) + FALLBACK_FONTS["en"]:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(
        f"No font found for language '{lang}'. Pass one with set_project_style(fonts=...).")


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, int(size))
    f = _font_cache.get(key)
    if f is None:
        f = ImageFont.truetype(path, int(size))
        # A variable font opens at its default instance, which for several CJK
        # families is Thin. Lettering wants a heavy weight.
        try:
            names = [n.decode() if isinstance(n, bytes) else n
                     for n in f.get_variation_names()]
            for want in ("Bold", "SemiBold", "Medium"):
                if want in names:
                    f.set_variation_by_name(want)
                    break
        except Exception:
            pass
        _font_cache[key] = f
    return f


# --- tokens and kinsoku ------------------------------------------------------

NO_START = set("、。，．,.・：；:;？！?!ー」』）】〉》〕］｝\"”’'…‥〜～"
               "っゃゅょぁぃぅぇぉゎッャュョァィゥェォヮヵヶ)]}")
NO_END = set("「『（【〈《〔［｛“‘([{")

_TOKEN = re.compile(r"\s+|[A-Za-z0-9\u00C0-\u024F'’\-]+|.", re.S)


def is_wide(ch: str) -> bool:
    o = ord(ch)
    return (0x2E80 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF or 0xF900 <= o <= 0xFAFF
            or 0xFF00 <= o <= 0xFFEF or 0x3000 <= o <= 0x303F or 0x1100 <= o <= 0x11FF)


@dataclass
class Token:
    text: str
    space_before: bool = False


def tokenize(paragraph: str) -> list[Token]:
    """Words for spaced scripts, single characters for CJK, then kinsoku glue:
    a no-start character joins the token before it, a no-end one the token
    after it, so neither can be stranded at a line edge."""
    raw: list[Token] = []
    pending_space = False
    for m in _TOKEN.finditer(paragraph):
        s = m.group(0)
        if s.isspace():
            pending_space = bool(raw)
            continue
        raw.append(Token(s, pending_space))
        pending_space = False

    glued: list[Token] = []
    carry = None  # an opening bracket waiting for its word
    for t in raw:
        if carry is not None:
            t = Token(carry.text + (" " if t.space_before else "") + t.text,
                      carry.space_before)
            carry = None
        if glued and not t.space_before and t.text[0] in NO_START:
            glued[-1] = Token(glued[-1].text + t.text, glued[-1].space_before)
            continue
        if t.text[-1] in NO_END and len(t.text) == 1:
            carry = t
            continue
        glued.append(t)
    if carry is not None:
        glued.append(carry)
    return glued


# --- horizontal layout -------------------------------------------------------

@dataclass
class Layout:
    """Text laid out around (0, 0). `rects` are the ink boxes the bubble must
    contain; `items` are what to draw: (kind, text, x, y, rotate)."""
    direction: str
    lines: list[str]
    rects: list[tuple[float, float, float, float]]
    items: list[tuple[str, float, float, bool]] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0


def _wrap(tokens: list[Token], font, max_w: float) -> list[str]:
    lines, cur = [], ""
    for t in tokens:
        cand = (cur + (" " if (cur and t.space_before) else "") + t.text) if cur else t.text
        if cur and font.getlength(cand) > max_w:
            lines.append(cur)
            cur = t.text
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def _wrap_paragraphs(paras: list[list[Token]], font, max_w: float) -> list[str]:
    out = []
    for toks in paras:
        out.extend(_wrap(toks, font, max_w) if toks else [""])
    return out


def horizontal_candidates(text: str, font, line_h: float,
                          max_lines: int = 9) -> list[Layout]:
    """One layout per achievable line count, each at the NARROWEST width that
    still gives that count -- i.e. the most balanced version of it."""
    paras = [tokenize(p) for p in text.split("\n")]
    words = [t.text for toks in paras for t in toks]
    if not words:
        return [Layout("h", [""], [(-1, -1, 1, 1)])]
    lo = max(font.getlength(w) for w in words)
    hi = max(font.getlength(" ".join(t.text for t in toks)) for toks in paras if toks)
    hi = max(hi, lo)
    forced = sum(1 for _ in paras)
    seen, out = set(), []
    for n in range(forced, max_lines + 1):
        # smallest width that yields <= n lines
        a, b = lo, hi
        if len(_wrap_paragraphs(paras, font, b)) > n:
            continue
        for _ in range(22):
            mid = (a + b) / 2
            if len(_wrap_paragraphs(paras, font, mid)) <= n:
                b = mid
            else:
                a = mid
        lines = _wrap_paragraphs(paras, font, b + 0.5)
        key = tuple(lines)
        if key in seen:
            continue
        seen.add(key)
        out.append(_place_lines(lines, font, line_h))
    return out


def _place_lines(lines: list[str], font, line_h: float) -> Layout:
    n = len(lines)
    total = n * line_h
    rects, items = [], []
    # Ink height of a line, measured once on caps and descenders so every line
    # in a bubble shares one box height.
    asc_box = font.getbbox("Hg国")
    ink = asc_box[3] - asc_box[1]
    widths = []
    for i, ln in enumerate(lines):
        w = font.getlength(ln)
        widths.append(w)
        cy = -total / 2 + line_h * (i + 0.5)
        rects.append((-w / 2, cy - ink / 2, w / 2, cy + ink / 2))
        items.append(("text", ln, 0.0, cy, False))
    lay = Layout("h", lines, rects, items, max(widths), total)
    return lay


# --- vertical layout (tategaki) ----------------------------------------------

# Characters drawn turned 90 degrees clockwise in a vertical column.
ROTATE_V = set("ー－—―‐-~〜～…‥「」『』（）()【】〈〉《》〔〕［］[]｛｝{}=＝→←")
# Small punctuation that sits in the upper right of its cell.
CORNER_V = set("、。，．,.")
SMALL_KANA = set("っゃゅょぁぃぅぇぉゎッャュョァィゥェォヮヵヶ")


def vertical_candidates(text: str, font, size: int, pitch: float,
                        max_cols: int = 8) -> list[Layout]:
    paras = []
    for p in text.split("\n"):
        chars = [c for c in p if not c.isspace()]
        paras.append(_vtokens(chars))
    total = sum(len(t) for p in paras for t in p)
    if total == 0:
        return [Layout("v", [""], [(-1, -1, 1, 1)])]
    longest_tok = max((len(t) for p in paras for t in p), default=1)
    first = max(longest_tok, 2)
    longest_para = max(sum(len(t) for t in p) for p in paras)
    if len(paras) > 1 and longest_para <= 14:
        # The author broke the columns himself, at phrases. Keep them whole:
        # auto-wrapping inside them split 吹き出し in the first test.
        first = longest_para
    seen, out = set(), []
    for per_col in range(first, total + 1):
        cols = []
        for toks in paras:
            cols.extend(_vwrap(toks, per_col) if toks else [""])
        if len(cols) > max_cols:
            continue
        key = tuple(cols)
        if key in seen:
            continue
        seen.add(key)
        out.append(_place_columns(cols, size, pitch))
    return out


def _vtokens(chars: list[str]) -> list[str]:
    toks: list[str] = []
    carry = ""
    for c in chars:
        if carry:
            c = carry + c
            carry = ""
        if toks and c[0] in NO_START:
            toks[-1] += c
            continue
        if c in NO_END:
            carry = c
            continue
        toks.append(c)
    if carry:
        toks.append(carry)
    return toks


def _vwrap(tokens: list[str], per_col: int) -> list[str]:
    cols, cur = [], ""
    for t in tokens:
        if cur and len(cur) + len(t) > per_col:
            cols.append(cur)
            cur = t
        else:
            cur += t
    if cur:
        cols.append(cur)
    return cols


def _place_columns(cols: list[str], size: int, pitch: float) -> Layout:
    n = len(cols)
    cell = size * 1.02
    total_w = (n - 1) * pitch + size
    rects, items = [], []
    for i, col in enumerate(cols):
        # Right to left: column 0 is the rightmost.
        cx = total_w / 2 - size / 2 - i * pitch
        h = len(col) * cell
        top = -h / 2  # columns centered vertically, as in most manga balloons
        rects.append((cx - size / 2, top, cx + size / 2, top + h))
        for j, ch in enumerate(col):
            cy = top + cell * (j + 0.5)
            if ch in CORNER_V:
                items.append(("char", ch, cx + size * 0.32, cy - size * 0.30, False))
            elif ch in SMALL_KANA:
                items.append(("char", ch, cx + size * 0.08, cy - size * 0.08, False))
            else:
                items.append(("char", ch, cx, cy, ch in ROTATE_V))
    return Layout("v", cols, rects, items, total_w, max(len(c) for c in cols) * cell)


# --- fitting -----------------------------------------------------------------

def fit_ellipse(rects, pad: float, target_aspect: float):
    """Smallest-area ellipse centered on the origin containing every padded
    rect, nudged toward a target width/height ratio. Returns (a, b, score)."""
    pts = [(max(abs(x0), abs(x1)) + pad, max(abs(y0), abs(y1)) + pad)
           for x0, y0, x1, y1 in rects]
    ymax = max(p[1] for p in pts)
    best = None
    for k in range(1, 400):
        b = ymax * (1.0 + k * 0.01)
        a = max(px / math.sqrt(1.0 - (py / b) ** 2) for px, py in pts)
        score = a * b * (1.0 + 0.55 * abs(math.log((a / b) / target_aspect)))
        if best is None or score < best[2]:
            best = (a, b, score)
    return best


def fit_rect(rects, pad: float, target_aspect: float):
    x = max(max(abs(r[0]), abs(r[2])) for r in rects) + pad * 1.4
    y = max(max(abs(r[1]), abs(r[3])) for r in rects) + pad
    score = x * y * (1.0 + 0.4 * abs(math.log((x / y) / target_aspect)))
    return x, y, score


def apply_case(text: str, uppercase: bool) -> str:
    return text.upper() if uppercase else text


if __name__ == "__main__":  # quick manual check: python lettering.py "text" en
    t = sys.argv[1] if len(sys.argv) > 1 else "Hello there, how are you doing today?"
    lang = sys.argv[2] if len(sys.argv) > 2 else "en"
    f = load_font(resolve_font_path(lang), 36)
    for lay in horizontal_candidates(t, f, 42):
        print(lay.lines, fit_ellipse(lay.rects, 18, 1.45)[2])
