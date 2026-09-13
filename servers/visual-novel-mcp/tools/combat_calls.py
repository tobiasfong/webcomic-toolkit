# -*- coding: utf-8 -*-
r"""Every combat the document SPECIFIES must be one the player actually fights.

    python combat_calls.py "<master.docx>" <project-dir> [patterns.json]

WHY NOTHING ELSE CATCHES THIS
-----------------------------
Added 2026-09-13, after a fully specified three-enemy fight turned out never
to have been wired. The scene cut from "The three of them lunge forward,
their swords flashing" straight to a man asking how his technique had been
broken: the player won a battle they never fought, and every step of
verify_all was green while it happened.

Each existing check misses it for its own reason, and the reasons describe a
whole class of bug:

  * script_diff  -- the combat spec is FENCED, so the mask drops it from the
                    docx side AND the emitter side. Both sides then agree
                    about nothing, which is the documented hole: a checker
                    sharing a definition with the thing it checks cannot see
                    past that definition.
  * spec_check   -- proves the NUMBERS in the fence match the engine. A fight
                    that is never entered has numbers that agree perfectly.
  * lint         -- a missing `call battle_x` is not a syntax error.
  * sprite audit -- the enemies had sprites. Nobody showed them.

HOW IT COUNTS, AND WHY NOT BY WINDOW
------------------------------------
Per scene file: how many fights the document specifies there against how many
the file calls. The first attempt matched each spec to a line window instead,
and it has to know how far a call may sit from the prose around it -- in
one scene the call is seven lines and five `show` statements clear of the
next spoken line, so three correctly wired fights were reported as
unreached. Counting needs no such constant and still catches the original
bug, where one file specified TWO fights and called ONE.

DELIBERATELY NOT USING THE PROSE MASK TO FIND THE MARKERS. The fence patterns
are exactly what was wrong the last two times -- an unclosed opener swallowed
a scene, and a Scenario pattern never matched the way the author writes the
header -- so markers are found with a raw regex over the raw paragraphs. The
mask is used only to pick the prose ANCHOR that says which file a spec lives
in, where being wrong costs a visible UNANCHORED line rather than a silent
pass.
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script_diff  # noqa: E402

# Raw and generous: "(Combat sequence)", "(combat sequence)", and the
# note-in-the-header form "(Combat sequence - boss battle, use main theme)"
# that broke fence_start once already.
COMBAT = re.compile(r"^\(\s*combat\s+sequence\b", re.I)
CALL = re.compile(r"^\s*call\s+(battle_\w+)")
TAG = re.compile(r"\{[^}]*\}")
SAY = re.compile(r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?"(.*)"\s*$')
SPEAKER = re.compile(r"^[^:]{1,40}:\s*")
QUOTES = u'"\u201c\u201d\u2018\u2019'
MARK = "<<call>>"


def _norm(s):
    s = TAG.sub("", s).replace('\\"', '"')
    return re.sub(r"\s+", " ", s.strip().strip(QUOTES)).strip()


def _docx_norm(t):
    return _norm(SPEAKER.sub("", t))


def index_scenes(project):
    """Every spoken line and every battle call, as (file, lineno, text)."""
    out = []
    d = os.path.join(project, "game", "scenes")
    for f in sorted(os.listdir(d)):
        if not f.endswith(".rpy"):
            continue
        path = os.path.join(d, f)
        for n, ln in enumerate(
                io.open(path, encoding="utf-8").read().splitlines(), 1):
            m = SAY.match(ln)
            if m:
                out.append((f, n, _norm(m.group(1))))
                continue
            m = CALL.match(ln)
            if m:
                out.append((f, n, MARK + m.group(1)))
    return out


def locate(index, probe):
    """Which scene file a docx paragraph landed in. EXACT match only.

    A prefix fallback was tried and removed: a short line prefix-matched
    several paragraphs and anchored a spec in the wrong file. A checker that
    cries wolf is worse than none, so this would rather find nothing and say
    so than guess.
    """
    if len(probe) < 20:
        return None
    for f, n, t in index:
        if t == probe:
            return (f, n)
    return None


def _home(index, paras, prose, i):
    """The scene file a spec belongs to.

    The prose AFTER the spec is the better anchor: a fight is emitted right
    before the scene resumes, while the line before it can be several beats
    and a plate change away.
    """
    for k in range(i + 1, min(i + 40, len(paras))):
        if prose[k] and paras[k]:
            hit = locate(index, _docx_norm(paras[k]))
            if hit:
                return hit
    for j in range(i - 1, max(i - 40, -1), -1):
        if prose[j] and paras[j]:
            hit = locate(index, _docx_norm(paras[j]))
            if hit:
                return hit
    return None


def main(docx_path, project, patterns=None):
    import docx
    script_diff.load_patterns(patterns)
    paras = [p.text.strip() for p in docx.Document(docx_path).paragraphs]
    prose = script_diff.prose_mask(paras)
    index = index_scenes(project)

    marks = [i for i, t in enumerate(paras) if COMBAT.match(t)]
    if not marks:
        print("combat_calls: no (Combat sequence) markers in the document.")
        return 0

    want, homeless = {}, []
    for i in marks:
        hit = _home(index, paras, prose, i)
        if hit is None:
            homeless.append(i)
        else:
            want[hit[0]] = want.get(hit[0], 0) + 1

    have = {}
    for f, n, t in index:
        if t.startswith(MARK):
            have[f] = have.get(f, 0) + 1

    bad = [(f, c, have.get(f, 0)) for f, c in sorted(want.items())
           if have.get(f, 0) < c]
    for f, c, h in bad:
        print("UNREACHED  %s specifies %d fight(s) but calls %d" % (f, c, h))
    for i in homeless:
        print("UNANCHORED docx para %d: %s" % (i, paras[i][:60]))
        print("           no prose near it matched a scene line, so this "
              "spec was NOT checked")
    print("")
    print("combat_calls: %d spec(s) across %d scene file(s), %d unreached, "
          "%d unanchored." % (sum(want.values()), len(want), len(bad),
                              len(homeless)))
    return 1 if (bad or homeless) else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit('usage: python combat_calls.py "<master.docx>" '
                 '<project-dir> [patterns.json]')
    # Same default as spec_check: a project dir is not a patterns file, and
    # load_patterns treats a bad path as a hard error rather than guessing.
    pats = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        sys.argv[2], "game", "patterns.json")
    sys.exit(main(sys.argv[1], sys.argv[2], pats))
