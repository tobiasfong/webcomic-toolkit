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
import io
import os
import re

import docx
import script_diff
import vnrich


def span(docx_path, name, start, end, include_end=False):
    """The paragraphs one emitter owns -- bounded at BOTH ends.

        p = emitlib.span(DOCX, "emit_scene_b",
                         lambda l: "last line of the scene before" in l,
                         lambda l: "first line of the scene after" in l)

    `start` and `end` are predicates over a paragraph's text. The result is
    every non-empty paragraph strictly after the first paragraph `start`
    accepts, up to the first later one `end` accepts -- exclusive, or
    inclusive of that end paragraph with `include_end`.

    ⚠ AN END ANCHOR IS NOT OPTIONAL, and this is the history of why. Three
    emitters each carried their own copy of this loader, and each copy had
    once run unbounded -- everything after its start to the end of the
    document -- which was harmless only while the scene was the last thing
    written. The moment the author added a later chapter, the emitter
    swallowed it: one reported 371 paragraphs where it owned 86 and rewrote
    a scene belonging to another emitter with 671 lines of someone else's
    chapter, and another would have done the same to two scenes with the
    380-paragraph chapter that followed. Nothing failed loudly. The files
    were written, the tool printed its usual summary, and only script_diff
    noticed -- as six differing regions and a DROPPED line, which reads like
    the author cut something. Every emitter is a span, so every emitter
    names where it stops; this function makes it impossible not to.

    A missing anchor fails with the emitter's name rather than a bare
    StopIteration, which is the other thing the three copies got wrong.
    """
    paras = [vnrich.rich(p, strip=False) for p in docx.Document(docx_path).paragraphs]
    i = next((n for n, l in enumerate(paras) if start(l)), None)
    if i is None:
        raise SystemExit("%s: start anchor not found in the docx" % name)
    j = next((n for n, l in enumerate(paras) if n > i and end(l)), None)
    if j is None:
        raise SystemExit("%s: end anchor not found after paragraph %d" % (name, i))
    return [l for l in paras[i + 1:j + (1 if include_end else 0)] if l.strip()]


def strip_note(t):
    """Drop an author-to-implementer parenthetical from the END of a line.

    ⚠ The sentence's FULL STOP CAN SIT AFTER THE BRACKET -- "...and sets
    it down (the sword, if he took one)." -- so anchoring the pattern at the
    end of the string silently matches nothing and the note ships in the
    game text. Allow the trailing punctuation and put it back.

    This was pasted into two emitters; sync_cards.strip_notes() is the
    different case -- INLINE parentheticals anywhere in a card body, opt-in
    -- and stays where it is.
    """
    return re.sub(r"\s*\([^)]*\)\s*([.!?\u2026]?)\s*$", r"\1", t).strip()


def row(tag, i, n, behind=None):
    """The `show` line that seats one figure in slot i of an n-slot row.

    Two emitters each defined this locally, identically; `behind` names a
    figure to be drawn beneath it.
    """
    return ("    show %s at row(%d, %d)" % (tag, i, n)
            + (" behind %s" % behind if behind else ""))


def locate_project(project_dir=None, _depth=1):
    """Where one project's manuscript, scenes folder and game folder are --
    and nothing else. No patterns are assigned and no paragraph is read.

        P = emitlib.locate_project()
        docx.Document(P.docx); P.out; P.game; P.project_dir; P.root

    For the emitters that do their OWN paragraph processing (a different
    vnrich.rich() mode, no prose mask) and so cannot take load_project's
    paragraphs, but still must not hard-code a machine's paths. `project_dir`
    defaults to the CALLING emitter's <project>/tools/ parent. The docx is
    found as load_project documents: project.json "docx", else the one
    *.docx beside the project folder, else in servers/visual-novel-mcp/.
    """
    import glob, inspect, json, types
    if project_dir is None:
        caller = inspect.stack()[_depth].frame.f_globals.get("__file__")
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(caller)))
    root = os.path.dirname(os.path.dirname(project_dir))
    docx_path = None
    cfg = os.path.join(project_dir, "project.json")
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8") as f:
            docx_path = json.load(f).get("docx")
        if docx_path:
            docx_path = os.path.join(root, docx_path)   # absolute stays absolute
    if not docx_path:
        for where in (os.path.dirname(project_dir),
                      os.path.join(root, "servers", "visual-novel-mcp")):
            # "~$" files are Word's lock files while the document is open
            found = [p for p in glob.glob(os.path.join(where, "*.docx"))
                     if not os.path.basename(p).startswith("~$")]
            if len(found) > 1:
                raise SystemExit("load_project: more than one script .docx in %s" % where)
            if found:
                docx_path = found[0]
                break
        else:
            raise SystemExit("load_project: no script .docx beside %s or in "
                             "servers/visual-novel-mcp/" % project_dir)
    game = os.path.join(project_dir, "game")
    return types.SimpleNamespace(
        project_dir=project_dir, root=root, docx=docx_path, game=game,
        out=os.path.join(game, "scenes"))


def load_project(project_dir=None):
    """Paths and the parsed script for ONE emitter, in one call.

        P = emitlib.load_project()
        paras, prose = P.paras, P.prose      # P.out is the scenes folder

    WHY: 32 emitters each opened with the same twenty lines -- an absolute
    sys.path insert, three absolute path constants, the load_patterns
    assignment, the docx read and the prose mask -- so moving the repo, or
    teaching one of them a new step, meant editing all 32 and hoping none
    drifted. The absolute paths were also the one thing tying every emitter
    to a single machine.

    `project_dir` is vn/<project>; by default it is derived from the CALLING
    emitter's __file__, since emitters live in <project>/tools/. The docx is
    `<project>/project.json` key "docx" (absolute, or relative to the repo
    root) when present, else the one *.docx BESIDE the project folder (in
    vn/, gitignored with the game), else -- where it lived before
    2026-10-18 -- the one *.docx in servers/visual-novel-mcp/.

    ⚠ This also ASSIGNS the speaker/spec/annotation patterns into
    script_diff, exactly as the emitters did by hand: `say()` strips
    annotations through script_diff.ANNOTATION, so it must run before any
    line is emitted. Call it once, at the top of main().
    """
    import types
    L = locate_project(project_dir, _depth=2)
    project_dir, docx_path = L.project_dir, L.docx
    patterns = os.path.join(project_dir, "game", "patterns.json")
    (script_diff.SPEAKER, script_diff.SPEC_START, script_diff.SPEC_LINE,
     script_diff.ANNOTATION) = script_diff.load_patterns(patterns)
    paras = [vnrich.rich(p) for p in docx.Document(docx_path).paragraphs]
    return types.SimpleNamespace(
        docx=docx_path, out=L.out,
        patterns=patterns, paras=paras, prose=script_diff.prose_mask(paras))


def load_expressions(project_dir=None):
    """The face changes, keyed by the opening of the paragraph they precede.

    `<project>/expressions.json`:
        {"anchors": [{"text": "first ~40 characters of the paragraph",
                      "prev": "same, of the paragraph before it (optional)",
                      "tag": "pc", "face": "anger"}, ...]}

    ⚠ `prev` EXISTS BECAUSE SOME PARAGRAPHS ARE THEIR OWN OPENING. A bare
    ellipsis is 30 separate lines in one manuscript, and an anchor on the
    text alone would change the face on all 30. The author, 2026-09-20, on
    being offered the obvious workaround: "You can't seriously change the
    expression on a neighboring line, that defeats the purpose... How can
    the character look shocked AFTER the dialogue?" He is right -- a face
    belongs to its line. So a short line is pinned by the line BEFORE it,
    which is the same device `find()` already uses for verbatim repeats in
    the docx. A pair anchor wins over a plain one.

    One list for every emitter, read here, so a face change is staging in
    the same sense a `show` is: anchored on the prose, emitted before the
    line, never typed into a scene file. Keyed on the paragraph's opening
    rather than its index because the document moves. A face persists until
    the next entry for that tag; `scene` resets everyone to neutral, so an
    entry with face "neutral" is only needed mid-scene. Missing file: no
    faces, which is what every project starts with.
    """
    import json, sys
    if project_dir is None:
        # emitters live in <project>/tools/, and run as scripts
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
    path = os.path.join(project_dir, "expressions.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ## ⚠ KEYED BY LINE AND TAG, AND EVERY MATCH IS EMITTED. Keyed by line
    ## alone, two characters changing on the same paragraph collided and one
    ## silently replaced the other -- the author lost a scowl he had
    ## recorded, to a second anchor for a different character on the very
    ## same line, and the only symptom was a face that would not stick.
    ## More than one of the cast reacting to the same beat is ordinary, so
    ## the table holds a list.
    table = {}
    for a in data.get("anchors", []):
        key = ((a.get("prev") or "").strip(), a["text"].strip())
        table.setdefault(key, {})[a["tag"]] = a["face"]
    return table


EXPRESSIONS = load_expressions()
ANCHOR_LEN = 40
# the opening of the paragraph `say` emitted last, for pair anchors. Scenes
# are emitted paragraph by paragraph in order, so this is exactly the
# context the note was taken against.
_PREV = [""]


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
             .replace("{", "{{").replace("%", "%%")
        # A literal % is a format code to Ren'Py (a line reading "50%, or"
        # lints as the unknown code '%,'); doubled, it prints as one.
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
        # ⚠ A LINE ALREADY IN CJK CORNER BRACKETS MUST NOT GAIN ASCII QUOTES.
        # Every speaking character carries what_prefix='"' and what_suffix='"'
        # (characters.rpy), on the reasoning that a name plate alone does not
        # read as speech. That is right for English and wrong for Japanese,
        # where 「」 already IS the quotation mark -- the author, seeing a sung
        # line in play: 'why the " " when we already have speech brackets for
        # Japanese?' It rendered as " 「...」 ".
        #
        # The prefix is applied by the Character at runtime, so the emitter
        # cannot strip it by changing the text. Ren'Py does accept per-say
        # character arguments, which is exactly the escape hatch: this suppresses
        # the pair for this ONE line and leaves every English line alone.
        quoted = len(body) >= 2 and body[0] in "「『" and body[-1] in "」』"
        tail = ' (what_prefix="", what_suffix="")' if (who and quoted) else ""
        line = (indent + ('%s "%s"' % (who, esc(body)) if who else '"%s"' % esc(body))
                + tail)
        # keyed on the spoken BODY's opening, quotes stripped and before escaping,
        # which is exactly what the engine holds in _last_say_what: a note taken
        # in play and an entry written by hand land on the same key
        key = body[:ANCHOR_LEN].strip()
        faces = {}
        if EXPRESSIONS:
            # a plain anchor first, so a PAIR anchor for the same tag wins
            faces.update(EXPRESSIONS.get(("", key)) or {})
            faces.update(EXPRESSIONS.get((_PREV[0], key)) or {})
        _PREV[0] = key
        for tag in sorted(faces):
            line = indent + "show %s %s" % (tag, faces[tag]) + chr(10) + line
        return line

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


# --- Shared staging helpers -------------------------------------------------
# Each of these was pasted into three or four emitters. They emit the same
# generic Ren'Py lines everywhere, so there is one copy here.

SFX = "audio/sfx/sfx_%s.wav"      # a sound effect's file, by its short name
SHAKE = ["    with vpunch"]


def sound(name):
    """The line that plays one sound effect, by its short name."""
    return ['    play sound "%s"' % (SFX % name)]


def flash(plate, sound=None, motion=None, hold=0.06, trailing_blank=False):
    """One impact flash, Fate/stay night style: the sound, the plate cut in
    for a beat, then dissolved away.

    A plate that TRAVELS takes `motion`, one of the game's plate transforms,
    and holds long enough for the move to register: a hit is a still, a wave
    or a breath moves. `trailing_blank` appends an empty spacer line after
    the dissolve, for an emitter whose staging lists want one."""
    out = ['    play sound "%s"' % (SFX % sound)] if sound else []
    at = " at %s" % motion if motion else ""
    return out + ["    show fx %s%s" % (plate, at),
                  "    with Dissolve(0.05)",
                  "    pause %s" % hold,
                  "    hide fx %s" % plate,
                  "    with Dissolve(0.4)"] + ([""] if trailing_blank else [])


def sweep(plate, sound, trailing_blank=False):
    """A flash whose plate sweeps in (a wave, a breath)."""
    return flash(plate, sound, "fx_sweep_in", 0.24, trailing_blank)


def twist(plate, sound, trailing_blank=False):
    """A flash whose plate twists in."""
    return flash(plate, sound, "fx_twist_in", 0.32, trailing_blank)


def stage(*figs, move=True):
    """A whole row, left to right: tags seated in an n-slot row."""
    n = len(figs)
    out = [row(t, i, n) for i, t in enumerate(figs)]
    return out + (["    with move"] if move else [])


def scene(bg, *figs):
    """Clear the page, set the background and seat a row of figures."""
    return (["    nvl clear", "    scene %s" % bg]
            + stage(*figs, move=False) + ["    with Dissolve(0.8)"])


def first_para(paras, needle, name="emitter"):
    """Index of the first paragraph containing `needle`, searched from the
    top. Exits with a message naming the emitter and the phrase when the
    document no longer has it, instead of a bare StopIteration.

    Use it to find a scene's START before bind_scene(), so the scene's other
    anchors can be searched from there (floor=, clamp=True) rather than from
    paragraph 0, where a phrase that repeats earlier would capture one."""
    for k, t in enumerate(paras):
        if needle in t:
            return k
    raise SystemExit("%s: not in docx: %r" % (name, needle))


def mark(paras, prefix, lo, name="emitter", hi=None):
    """Index of the first paragraph at or after `lo` (and before `hi`, when
    given) that opens with `prefix`. Stops with a message naming the emitter
    and the prefix when the document no longer has it, instead of a bare
    StopIteration."""
    for k in range(lo, len(paras) if hi is None else hi):
        if paras[k].strip().startswith(prefix):
            return k
    raise SystemExit("%s: no paragraph from %d on opens with %r. The "
                     "document has probably changed there."
                     % (name, lo, prefix))


def mark_eq(paras, text, lo, name="emitter", hi=None):
    """Like mark(), for a paragraph that IS `text` (compared stripped) -- a
    marker line such as a combat cue, where a prefix would also match prose
    that merely begins with it."""
    for k in range(lo, len(paras) if hi is None else hi):
        if paras[k].strip() == text:
            return k
    raise SystemExit("%s: no paragraph from %d on is exactly %r. The "
                     "document has probably changed there."
                     % (name, lo, text))


def write(out_dir, name, body):
    """Write one generated file (LF newlines, utf-8) and log it."""
    io.open(os.path.join(out_dir, name), "w", encoding="utf-8",
            newline="\n").write("\n".join(body))
    print("  wrote %-22s %3d lines" % (name, len(body)))
