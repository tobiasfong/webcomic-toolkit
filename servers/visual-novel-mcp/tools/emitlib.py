# -*- coding: utf-8 -*-
"""The helpers every scene emitter needs, defined ONCE.

    import emitlib
    find, split_speaker, esc, say, block = emitlib.bind(SPEAKERS)

WHY THIS EXISTS
---------------
Before this file, `esc()` was copied into 26 emitters, `say()` and
`split_speaker()` into 25, and `block()`/`find()` into 18 -- about 1,500 of
the emitters' 7,000 lines were the same five functions pasted over and over.
It was tolerable right up until one of them needed to change: teaching `esc()`
to leave the author's {i} tags alone meant patching 25 files with a regex, and
the audit that followed found the copies had quietly drifted into seven
variants of `say()` and `split_speaker()` that differed in WHERE they stripped
the quotation marks, whether they honored a speaker override, and whether they
ran the annotation filter at all.

A copy is a fork. Every one has to be found, understood and re-verified when
the behavior moves, and the day one is missed the generated scenes disagree
with each other about something as basic as escaping. One implementation is
the only arrangement under which they cannot.

WHAT bind() IS FOR
------------------
`say()` and `split_speaker()` need the emitter's SPEAKERS table -- the map from
the docx's speaker labels ("Old Kim") to Ren'Py character variables
("oldkim") -- and every emitter has a different one. Rather than thread it
through every call, `bind()` closes over it once and hands back the five
functions with the table already inside, so the call sites in the emitters
did not change: they still write `say(t)` and `block(paras, prose, ...)`.

The behavior is the SUPERSET of every variant that existed: annotation
stripping, an optional speaker override (`var`), and quotation marks stripped
from the body whether the docx wrote them straight or curly. Every generated
scene was byte-identical before and after the consolidation -- that diff is
the proof, and it is worth re-running any time this file changes.
"""
import re

import script_diff


def bind(speakers):
    """The five helpers, bound to one emitter's SPEAKERS table."""

    def find(paras, needle, frm):
        """A plain anchor is a substring of the target paragraph. A PAIR
        anchor is (context, text): the target contains `text` and the
        previous non-empty paragraph contains `context` -- for lines that
        repeat verbatim in the document."""
        for n in range(frm, len(paras)):
            if isinstance(needle, tuple):
                if needle[1] in paras[n]:
                    prev = next((j for j in range(n - 1, -1, -1) if paras[j]), None)
                    if prev is not None and needle[0] in paras[prev]:
                        return n
            elif needle in paras[n]:
                return n
        raise SystemExit("anchor not found in docx after paragraph %d: %r"
                         % (frm, needle))

    def split_speaker(t):
        """('oldkim', 'text') for a spoken line, (None, text) for narration.

        The label must be in the emitter's table -- a colon alone is not a
        speaker, or every "Description:" and "Rules:" heading would talk.
        """
        m = re.match(r"^([^:]{1,40}):\s*(.*)$", t)
        if not m or m.group(1).strip() not in speakers:
            return None, t
        return speakers[m.group(1).strip()], m.group(2).strip()

    def esc(s):
        # ⚠ THE AUTHOR'S ITALICS SURVIVE THE ESCAPE. A literal brace in his
        # prose must be doubled for Ren'Py, but the {i} tags vnrich inserts
        # are markup this pipeline produced, and doubling those prints "{i}"
        # to the player instead of slanting the line.
        s = s.replace("\\", "\\\\").replace('"', '\\"').replace("[", "[[") \
             .replace("{", "{{")
        return s.replace("{{i}", "{i}").replace("{{/i}", "{/i}")

    def say(t, indent="    ", var=None):
        """One paragraph as a Ren'Py say line.

        `var` overrides the speaker: a string names the character variable,
        an empty string forces narration. None means "whatever the label
        says", which is the common case.
        """
        t = script_diff.ANNOTATION.sub("", t).strip()
        who, body = split_speaker(t)
        if var is not None:
            who = var or None
        body = body.strip()
        if len(body) >= 2 and body[0] in "“\"" and body[-1] in "”\"":
            body = body[1:-1]
        return indent + ('%s "%s"' % (who, esc(body)) if who else '"%s"' % esc(body))

    def block(paras, prose, forced, a, b, resolved):
        """Paragraphs [a, b) as say lines with blank spacers, honoring the
        staging in `resolved`: lines to insert BEFORE a paragraph, a LITERAL
        to emit in its place, an INDENT for a conditional branch, a speaker
        VAR override, and lines (or re-emitted paragraphs) AFTER it."""
        out = []
        for k in range(a, b):
            t = paras[k]
            if not t or (not prose[k] and k not in forced):
                continue
            st = resolved.get(k, {})
            out += st.get("before", [])
            if st.get("literal") is not None:
                out.append(st["literal"])
            else:
                out.append(say(t, st.get("indent") or "    ", st.get("var")))
            out.append("")
            for x in st.get("after", []):
                if isinstance(x, tuple):
                    out.append(say(paras[find(paras, x[2], 0)], x[3] or "    ", x[1]))
                    out.append("")
                else:
                    out.append(x)
        return out

    return find, split_speaker, esc, say, block


def bind_scene(paras, prose, say, name="emitter", floor=0, clamp=False):
    """The two SCENE-LOCAL helpers the hand-written emitters carried.

        find, block = emitlib.bind_scene(paras, prose, say, name="emit_c01yz")

    Seven emitters each defined a `find()` and a `block()` as closures over
    their own paragraph list -- seven `find`s and five `block`s, in as many
    variants. The differences were real but small, and every one is a
    parameter here rather than a copy:

      floor   where find() searches from when no start is given. Two
              emitters searched from the scene's own first paragraph rather
              than from zero, so a phrase that repeats earlier in the
              document cannot capture an anchor.
      clamp   one of those two also refused to search BEFORE the floor even
              when asked to (`max(frm, start)`); this keeps that.
      prose   the prose mask, or None. With a mask, block() skips spec
              paragraphs; without one it skips only empty ones -- the two
              older emitters emit ranges that contain no spec.

    block() takes both `before` and `after` staging maps (each family had
    one), checks the range is not inverted, and refuses to finish if any
    staging anchor never landed -- an anchor keyed to a paragraph outside the
    range, or to one the mask skips, used to be dropped in silence, and that
    is how a boss fight once vanished from the game.

    Verified the same way bind() was: every generated scene byte-identical
    before and after the seven emitters switched over.
    """

    def find(needle, frm=None, start=None):
        f = frm if frm is not None else (start if start is not None else floor)
        if clamp:
            f = max(f, floor)
        for n in range(f, len(paras)):
            if needle in paras[n]:
                return n
        raise SystemExit("%s: not in docx: %r" % (name, needle))

    def block(a, b, before=None, after=None, indent="    "):
        if b < a:
            raise SystemExit(
                "%s: inverted range [%d, %d). An anchor points at a paragraph "
                "earlier than the one before it -- most likely a line moved in "
                "the document." % (name, a, b))
        before, after = before or {}, after or {}
        out, used = [], set()
        for k in range(a, b):
            t = paras[k].strip()
            if not t or (prose is not None and not prose[k]):
                continue
            if k in before:
                out += before[k]
                used.add(k)
            out.append(say(t, indent))
            out.append("")
            if k in after:
                out += after[k]
                used.add(k)
        missing = sorted((set(before) | set(after)) - used)
        if missing:
            raise SystemExit(
                "%s: %d staging anchor(s) never landed in range [%d, %d): %s. "
                "Each names a paragraph outside the range or masked as spec -- "
                "check for a repeated phrase and pass frm=."
                % (name, len(missing), a, b, missing))
        return out

    return find, block
