# -*- coding: utf-8 -*-
"""Paragraph text WITH the author's emphasis kept.

WHY THIS EXISTS
---------------
Every emitter read paragraphs as `p.text`, which is python-docx's plain
concatenation of the runs and throws away every formatting flag on them. The
author writes a character's unvoiced thought in italics, and all of it was
being emitted as ordinary narration -- 24 paragraphs of the script, silently,
from the first emitter onward. It surfaced as "this line isn't in italics for
some reason", which is exactly how a systemic loss looks from inside the game:
like one line being wrong.

Lives HERE, next to the path every emitter already puts on sys.path, so an
emitter needs one import rather than a copy of the logic. A copy is what the
docx and diff sides of prose_mask were nearly reduced to, and the note there
applies equally: one implementation is the only way two callers cannot
disagree.

WHAT IT DOES NOT DO
-------------------
Bold, underline and color are NOT carried. The script uses italics and
nothing else, and a converter that guesses at markup the author never used
invents typography rather than preserving it. Add a case here when a case
actually appears in the document.
"""


def rich(p, strip=True):
    """One paragraph as Ren'Py text, with italic runs wrapped in {i}...{/i}.

    Adjacent italic runs are merged into ONE span. A word processor splits a
    run at every edit boundary, so a single italic sentence commonly arrives
    as four runs -- emitting {i}...{/i} around each would quadruple the tags
    and, worse, make the emitted line differ from the same sentence typed in
    one go. Merging keeps the output a function of what the text LOOKS like
    rather than of how it was typed.
    """
    out = []
    italic = False
    for r in p.runs:
        if not r.text:
            continue
        want = bool(r.italic)
        # Whitespace between two italic runs must not close the span: the
        # space after a word is frequently its own non-italic run, and
        # closing there produces {/i} {i} in the middle of a phrase.
        if not r.text.strip() and italic:
            out.append(r.text)
            continue
        if want != italic:
            out.append("{i}" if want else "{/i}")
            italic = want
        out.append(r.text)
    if italic:
        out.append("{/i}")
    t = "".join(out)
    return t.strip() if strip else t.rstrip()


def plain(t):
    """`t` with Ren'Py text tags removed.

    For ANCHORS. An emitter that matches a paragraph by substring is
    unaffected by markup, but one that compares for EQUALITY is not: the
    author's time cards ("The next day", "Twelve hours later") are italic, so
    they arrive as {i}The next day{/i} and an == test against the bare words
    silently stops matching. That failure is loud -- StopIteration -- which is
    the only reason it was cheap to find.
    """
    import re
    return re.sub(r"\{/?[a-z][^}]*\}", "", t)
