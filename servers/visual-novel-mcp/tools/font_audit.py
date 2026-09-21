# -*- coding: utf-8 -*-
"""Fail when the installed CJK subset is behind the scripts.

    python font_audit.py <project-dir>

WHAT THIS CATCHES
-----------------
The game ships a SUBSET of a CJK face, cut to the glyphs the scripts
actually use, because the full font is ~9.6 MB and a web build does not
defer it -- it lands in the initial download, ahead of the title screen.

The subset is therefore a function of the script, and it is correct only
as long as somebody re-runs subset_font.py after writing new CJK. Nobody
is told when they forget. The font does not know it is stale, the engine
renders the missing glyph as an empty box, and the box is visible only in
play -- so it reaches the author rather than the build.

That is exactly what happened on 2026-09-21: a sung Japanese line
introduced 教, 仕 and 組 after the subset was last built, and all three
arrived on screen as tofu. Every other check was green, because every
other check reads text and this one is about GLYPHS.

HOW IT DECIDES
--------------
It asks the same question subset_font.py asks -- which codepoints do the
scripts use -- and then checks the installed font's cmap for each one. It
imports that scan rather than reimplementing it, so the audit and the
builder cannot drift apart; a checker that owns its own copy of the rule
is the failure this project has been bitten by repeatedly.

⚠ IT SKIPS QUIETLY WHERE THERE IS NOTHING TO CHECK. A project with no CJK
in its scripts, or with no subset installed, is not failing -- it simply
has no subset to be stale. Only a subset that EXISTS and is MISSING a
character the scripts use is an error.
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import subset_font  # noqa: E402


def installed_subsets(game):
    """Every *.subset.ttf the game carries, newest last."""
    pat = os.path.join(game, "gui", "*.subset.ttf")
    return sorted(glob.glob(pat))


def audit(project):
    game = os.path.join(project, "game")
    if not os.path.isdir(game):
        return None, "no game/ directory"

    fonts = installed_subsets(game)
    if not fonts:
        return None, "no CJK subset installed -- nothing to check"

    used = subset_font.used_codepoints(game)
    on_demand = sorted(c for c in used
                       if any(lo <= c <= hi
                              for lo, hi in subset_font.ON_DEMAND))
    if not on_demand:
        return None, "no CJK in the scripts"

    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        # ⚠ NOT A PASS. There IS CJK here and there IS a subset, so "I could
        # not look" is a different thing from "it is fine" -- and reporting
        # the second when you mean the first is how a green run stops meaning
        # anything. It reached verify_all as `font ok: fontTools not
        # installed` on the very first run of this check.
        raise SystemExit(
            "CANNOT CHECK THE FONT: fontTools is not installed in this "
            "interpreter, and the scripts contain %d CJK character(s) "
            "against an installed subset.\n\n"
            "Install it into the venv that runs verify_all:\n"
            "  <venv>/Scripts/python.exe -m pip install fonttools"
            % len(on_demand))

    problems = []
    for f in fonts:
        cmap = TTFont(f, lazy=True).getBestCmap()
        missing = [c for c in on_demand if c not in cmap]
        if missing:
            problems.append((os.path.basename(f), missing))

    if problems:
        return problems, None
    return [], ("%d CJK character(s) in the scripts, all present in %s"
                % (len(on_demand), ", ".join(os.path.basename(f)
                                             for f in fonts)))


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    problems, note = audit(sys.argv[1])

    if problems is None:
        print(note)
        return 0
    if not problems:
        print(note)
        return 0

    print("STALE FONT SUBSET:")
    for name, missing in problems:
        chars = "".join(chr(c) for c in missing)
        print("  %s is missing %d character(s): %s" % (name, len(missing), chars))
    print("")
    print("These appear in the scripts and would render as empty boxes in")
    print("play. Rebuild with:")
    print("")
    print("  python subset_font.py <project>/game <path-to-master-font.ttf>")
    print("")
    print("It installs the result into game/gui/ itself. The master font")
    print("must live OUTSIDE the project, or a web build ships it whole.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
