"""Subset a CJK font down to the glyphs a game actually displays.

    python subset_font.py <path-to-game-dir> [font.ttf]

WHY
---
A full CJK font carries tens of thousands of glyphs. A script that shows three
kanji still ships all of them, and in a web build the font is NOT deferred --
it lands in the initial download, so every reader waits for it before the title
appears.

⚠ THE GLYPH SET IS DERIVED FROM THE SCRIPTS, NEVER HAND-WRITTEN. A hand-listed
subset is correct exactly once: the next kanji an author types comes back as an
empty box, and nothing warns anybody. This scans every .rpy file, so the subset
is a function of the script rather than a decision someone has to remember.

Kana and CJK punctuation are kept WHOLESALE even if unused, because they are
cheap (a few hundred glyphs) and because a Japanese release will need all of
them. Kanji are kept only where used, since that is where the tens of thousands
live.

⚠ KEEP THE MASTER FONT OUTSIDE THE PROJECT DIRECTORY ENTIRELY -- not merely
outside game/. A web build packs the WHOLE project, so both of these still ship
the full face and save nothing:

    <project>/game/gui/NotoSansJP-Regular.ttf     (obvious)
    <project>/fonts/NotoSansJP-Regular.ttf        (measured, and surprising)

Both were tried. The first build carried a 0.51 MB subset beside the 9.59 MB
original; moving the master up one level to <project>/fonts/ changed nothing at
all. Keep it somewhere like <repo>/vn/fonts/ and pass its path as the second
argument. Only the subset belongs in game/gui/.

Check it rather than assuming: the saving should be obvious in the build size,
and if it is not, the original is still in there.

Run it BEFORE a build whenever the script has gained CJK. It writes alongside
the source as <name>.subset.ttf and reports the saving; the original is never
modified, so a bad subset is undone by pointing the game back at it.
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir  # noqa: E402

# Whole blocks worth keeping regardless of use.
ALWAYS = [
    (0x0020, 0x00ff),      # Latin-1: the font may be asked for these as fallback
    (0x2000, 0x206f),      # general punctuation, quotes, dashes, ellipsis
    (0x3000, 0x303f),      # CJK punctuation, 、。「」
    (0x3040, 0x309f),      # hiragana
    (0x30a0, 0x30ff),      # katakana
    (0xff00, 0xffef),      # full-width forms
]

# Anything in these ranges is kept ONLY if the script uses it.
ON_DEMAND = [
    (0x3400, 0x4dbf),      # CJK extension A
    (0x4e00, 0x9fff),      # CJK unified ideographs
    (0xac00, 0xd7af),      # Hangul syllables
    (0xf900, 0xfaff),      # CJK compatibility ideographs
]


def used_codepoints(game):
    """Every character that appears in a QUOTED string in the scripts.

    Comments are skipped deliberately: a note that happens to quote a glyph
    does not mean the game ever draws it, and a subset built from comments
    would carry characters no reader will ever see.
    """
    used = set()
    for root, dirs, files in os.walk(game):
        dirs[:] = [d for d in dirs if d not in ("cache", "saves", "tl")]
        for fn in files:
            if not fn.endswith(".rpy"):
                continue
            for line in io.open(os.path.join(root, fn), encoding="utf-8"):
                s = line.strip()
                if s.startswith("#"):
                    continue
                for m in re.finditer(r'"([^"]*)"', s):
                    used.update(ord(c) for c in m.group(1))
    return used


def main():
    game = game_dir()
    font = (sys.argv[2] if len(sys.argv) > 2
            else os.path.join(game, "gui", "NotoSansJP-Regular.ttf"))
    if not os.path.exists(font):
        sys.exit("Font not found: %s" % font)

    used = used_codepoints(game)
    on_demand = sorted(c for c in used
                       if any(lo <= c <= hi for lo, hi in ON_DEMAND))

    keep = set()
    for lo, hi in ALWAYS:
        keep.update(range(lo, hi + 1))
    keep.update(on_demand)

    print("ideographs/hangul used by the scripts: %d" % len(on_demand))
    if on_demand:
        print("  " + "".join(chr(c) for c in on_demand))

    from fontTools import subset
    out = os.path.splitext(font)[0] + ".subset.ttf"
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.notdef_outline = True
    opts.recalc_bounds = True
    f = subset.load_font(font, opts)
    s = subset.Subsetter(options=opts)
    s.populate(unicodes=sorted(keep))
    s.subset(f)
    subset.save_font(f, out, opts)
    f.close()

    before, after = os.path.getsize(font), os.path.getsize(out)
    print("\n%-28s %7.1f MB" % (os.path.basename(font), before / 1e6))
    print("%-28s %7.1f MB   (%.0f%% smaller)"
          % (os.path.basename(out), after / 1e6, 100 * (1 - after / before)))
    print("\nPoint the FontGroup in presentation.rpy at the subset file.")
    print("⚠ RE-RUN THIS whenever new CJK appears in the script, or it will "
          "render as empty boxes.")


if __name__ == "__main__":
    main()
