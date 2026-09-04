r"""Diff an author's docx master against the converted Ren'Py scenes.

The docx is the master and it MOVES -- an author revising spontaneously will
close gaps and change details without saying so, so patching only the change
they mention misses the rest. This compares the WHOLE document every time.

    python script_diff.py <master.docx> <scenes-dir> [patterns.json]

Reports three things:
  CHANGED  a block whose wording differs between docx and script
  NEW      a block in the docx not yet in any script (needs converting)
  DROPPED  a block in a script no longer in the docx (it was cut)

Staging lines -- scene/show/nvl clear/centered/with -- are ignored; only
narration and dialogue are compared, since staging belongs to the adaptation
and prose belongs to the author.

⚠ SPEC BLOCKS. Authors write notes to the implementer inline (combat specs,
localization notes). Those must never be converted as story, so they are
skipped -- but recognizing them needs the project's own vocabulary, which is
story content and therefore CANNOT live in this public file. Put it in a JSON
file beside the game tree:

    {
      "spec_start":  ["^(FIGHT SEQUENCE|To Claude[,:])"],
      "spec_line":   ["^(Sword strike|Uses |Victory!)"],
      "speaker":     "^[A-Z][A-Za-z0-9'#\- ]{0,34}:\s*",
      "annotation":  "\s*\((?:[^()]*version would be[^()]*)\)\s*$"
    }

Every key is optional; the defaults below are generic. Pass the file as the
third argument, or leave `patterns.json` next to the scenes directory.

⚠ A spec block ends when PROSE resumes, and judging that by LINE LENGTH does
not work: once an author writes the combat text properly -- move descriptions,
use lines, a victory line -- those run long, the block looks finished, and the
rest of the spec reports as unconverted story. Match on vocabulary; keep length
only as a backstop for short fragments.
"""
import difflib
import json
import glob
import io
import os
import re
import sys


# Generic defaults. Anything project-specific belongs in patterns.json --
# see the module docstring.
DEFAULTS = {
    # Tolerates numbered mob speakers ("Guard #1:") or their lines read as
    # unconverted forever, because the label never gets stripped before compare.
    "speaker": r"^[A-Z][A-Za-z0-9'#\- ]{0,34}:\s*",
    "spec_start": [r"^(FIGHT SEQUENCE|To Claude[,:]|NOTE TO)"],
    "spec_line": [r"^(Uses |Victory!|\(\d+ damage|\[Opponent)"],
    # Inline notes to self -- a localization aside, a gloss after a name. They
    # never reach the game, so strip them or they read as permanent differences.
    "annotation": r"\s*\((?:[^()]*version would be[^()]*|[A-Za-z ]{2,30})\)\s*$",
}

# Short spec fragments the vocabulary misses. Low enough that it cannot swallow
# a real one-line paragraph of narration.
SPEC_SHORT = 40


def load_patterns(path=None):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with io.open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    def joined(key):
        v = cfg[key]
        return re.compile("|".join(v) if isinstance(v, list) else v, re.I)
    global SKIP_LINE
    SKIP_LINE = [re.compile(x, re.I) for x in cfg.get('skip_line', [])]
    return (re.compile(cfg["speaker"]), joined("spec_start"),
            joined("spec_line"), re.compile(cfg["annotation"]))


# ⚠ SKIP_LINE IS A MODULE GLOBAL SET BY load_patterns AS A SIDE EFFECT, not a
# fifth return value. Eighteen generated emitters unpack this call as a
# 4-tuple, and widening it would break every one of them at once.
SKIP_LINE = []
SPEAKER, SPEC_START, SPEC_LINE, ANNOTATION = load_patterns()


def _speaks(t):
    """True for `Name: something`, false for a bare heading like `Rules:`.

    The speaker pattern alone is not enough to recognize dialogue: a spec
    heading that ends in a colon matches it exactly, since the words before
    the colon are just letters and spaces. What separates them is whether
    anything FOLLOWS the colon -- dialogue has a line after the name, a
    heading has nothing.
    """
    m = SPEAKER.match(t)
    return bool(m) and bool(t[m.end():].strip())


def normalize(t):
    # ⚠ TYPOGRAPHY FIRST, STRUCTURE SECOND. A word processor writes curly
    # apostrophes, so a speaker label like `Keeper of the King’s Seal:` does
    # NOT match a speaker pattern whose character class contains only the
    # straight quote -- the prefix survives, and the block reports as CHANGED
    # forever no matter how correctly it was converted. Stripping the prefix
    # before normalizing the quotes made the fix depend on every project's
    # patterns.json listing both characters; doing it in this order fixes it
    # once, for every name.
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"')):
        t = t.replace(a, b)
    t = SPEAKER.sub("", t).strip()
    t = ANNOTATION.sub("", t).strip()
    t = t.strip("「」")  # Japanese quotation brackets around written text
    t = t.strip('"')
    return " ".join(t.split())


def bind_interpolations(scr_text, doc):
    """Let a line containing a Ren'Py substitution match the paragraph it came from.

    WHY THIS EXISTS
    ---------------
    Some lines differ by a single word depending on the player's choices --
    "I lower my hand" against "I lower my sword". That is ONE paragraph of
    story and two presentations of it, so it belongs in the document once and
    in the script once, as `I lower my [_limb]`.

    Compared literally that never matches, and the block reports as CHANGED
    forever. The two ways out without this function are both bad, and both
    were tried: duplicate the paragraph in the AUTHOR'S master, which puts an
    implementation detail into the story and is a chore he has to repeat; or
    emit two nearly identical script lines, which trades a permanent CHANGED
    for a permanent extra block. The author objected to being handed the first
    one, correctly -- the document is the master of the story, not of how the
    engine renders it.

    So a substitution is treated as a wildcard matching one word. The
    paragraph stays single, the script line stays single, and the two agree.

    Lines carrying `[[` are skipped: that is an ESCAPED literal bracket in the
    author's own text, not a tag, and treating it as one would silently match
    the wrong paragraph.
    """
    out = []
    for t in scr_text:
        if "[" not in t or "[[" in t:
            out.append(t)
            continue
        parts = re.split(r"\[[^\]]+\]", t)
        rx = re.compile("^" + r"\S+".join(re.escape(p) for p in parts) + "$")
        hits = [d for d in doc if rx.match(d)]
        # First match wins. If the author has ALSO duplicated the paragraph,
        # the spare one is left to report as unconverted -- which is the right
        # signal: it says the duplicate is no longer needed.
        out.append(hits[0] if hits else t)
    return out


def prose_mask(paras):
    """Which paragraphs are PROSE, as opposed to spec notes, choice cards and
    scenario headers -- the same state machine read_docx uses, exposed so an
    emitter can skip exactly what the diff skips. Anything else drifts: an
    emitter that skips by its own rule will one day emit a note the diff
    ignores, and the two will disagree about whether the game is in sync.

    Takes the raw paragraph list (already stripped) and returns a list of
    bools of the same length.
    """
    mask = []
    in_spec = False
    for t in paras:
        t = t.strip()
        if not t or t.lower() in ("prologue",):
            mask.append(False)
            continue
        # A standalone marker: skipped, but it does NOT open a spec region.
        # The difference matters -- an author's structural note can sit
        # directly above a short line of real prose, and starting a block
        # would eat it on the length rule.
        if any(rx.match(t) for rx in SKIP_LINE):
            mask.append(False)
            continue
        if SPEC_START.match(t):
            in_spec = True
            mask.append(False)
            continue
        if in_spec:
            if not _speaks(t) and (SPEC_LINE.match(t) or len(t) < SPEC_SHORT):
                mask.append(False)
                continue
            in_spec = False
        mask.append(True)
    return mask


def read_docx(path):
    """The document's prose blocks, normalized.

    ⚠ USES prose_mask RATHER THAN ITS OWN COPY OF THE STATE MACHINE. It had
    one until 2026-09-05, and the two promptly diverged: `skip_line` was added
    to prose_mask for standalone markers and not here, so an emitter correctly
    omitted "(scenarios converge)" while this function still counted it, and
    the diff reported a phantom empty block that no scene could ever satisfy.
    One implementation, used by both, is the only way they cannot disagree.

    A paragraph that normalizes to nothing is dropped: an author annotation
    that IS the whole paragraph strips to an empty string, and an empty block
    can never be matched by a scene.
    """
    import docx
    paras = [p.text.strip() for p in docx.Document(path).paragraphs]
    keep = prose_mask(paras)
    out = []
    for t, ok in zip(paras, keep):
        if not ok:
            continue
        n = normalize(t)
        if n.strip():
            out.append(n)
    return out

def scene_order(scenes_dir):
    """Scene files in STORY order, by following the jump chain.

    ⚠ NOT alphabetical. Filenames encode whatever the author found readable at
    the time -- a prologue numbered p00..p08 and then a chapter named c01a
    sorts the chapter FIRST, which silently misaligns the whole comparison and
    reports every converted block as missing. The jump chain is the real order
    and it cannot drift, because it is what the engine executes.

    ⚠ BRANCHES ARE FOLLOWED, and the traversal has to be the right one. This
    used to give up whenever a file had more than one jump, fall back to
    alphabetical, and report ~235 blocks unconverted with nothing actually
    missing. That cost an evening of trusting a broken drift check, because
    the warning prints at the TOP and the total prints at the bottom, and a
    `tail` on the output shows only the reassuring half.

    DEPTH-FIRST IS THE WRONG ALGORITHM and looks right until you try it.
    Branches in a visual novel RECONVERGE: three scenarios all jump to one
    convergence scene. Depth-first walks the first branch straight through the
    join and out the far side, so the convergence lands before the second and
    third branches -- while the author wrote all three scenarios first and the
    convergence after them.

    TOPOLOGICAL order is what matches the document: a scene is emitted only
    once every path into it has been emitted, so a join waits for all of its
    branches. With the queue kept in discovery order rather than sorted, the
    branches come out in the order the story jumps to them, which is the order
    they were written.

    Falls back to alphabetical only when the graph genuinely cannot be
    ordered -- no single entry point, a cycle, or files nothing reaches -- and
    says so on stderr.
    """
    files = sorted(glob.glob(os.path.join(scenes_dir, "*.rpy")))
    label_of, out_edges = {}, {}
    for f in files:
        src = io.open(f, encoding="utf-8").read()
        labels = re.findall(r"^label\s+([A-Za-z_]\w*)\s*:", src, re.M)
        jumps = re.findall(r"^\s*jump\s+([A-Za-z_]\w*)\s*$", src, re.M)
        if len(labels) != 1:
            # Still unresolvable, and for the reason that has not changed: a
            # jump target resolves to a file BY NAME, so two labels in one
            # file leave a target that cannot be placed.
            sys.stderr.write(
                "script_diff: %s has %d labels, so the story order cannot be\n"
                "  followed and the scenes are being compared in ALPHABETICAL "
                "order instead.\n"
                "  That silently misaligns everything -- expect converted "
                "blocks to report as\n"
                "  missing. Give each scene file ONE label matching its name.\n"
                % (os.path.basename(f), len(labels)))
            return files
        label_of[labels[0]] = f
        # Order preserved, duplicates dropped: a scene that jumps to the same
        # target twice is ONE edge. Counted twice, the join never unblocks and
        # everything after it silently drops out of the order.
        seen_t, edges = set(), []
        for t in jumps:
            if t not in seen_t:
                seen_t.add(t)
                edges.append(t)
        out_edges[labels[0]] = edges

    # Only jumps to scenes can be ordered. A jump into game/ -- a battle label,
    # say -- is a real edge in the engine but not one between scene files.
    for lab in out_edges:
        out_edges[lab] = [t for t in out_edges[lab] if t in label_of]

    indeg = {lab: 0 for lab in label_of}
    for lab, targets in out_edges.items():
        for t in targets:
            indeg[t] += 1

    heads = [l for l in label_of if indeg[l] == 0]
    if len(heads) != 1:
        # The THIRD silent exit, and the one an ordinary authoring slip hits:
        # a scene nothing jumps to yet is a second head, and two heads mean no
        # single entry point. Naming them is the whole message -- either one is
        # the real start and the others need chaining in, or a jump is missing.
        sys.stderr.write(
            "script_diff: found %d possible starting scenes, so the story "
            "order cannot be\n"
            "  followed and the scenes are being compared in ALPHABETICAL "
            "order instead.\n"
            "  candidates: %s\n"
            "  Exactly one scene should have nothing jumping to it. The rest "
            "are either\n"
            "  unchained yet, or something that should jump to them does not.\n"
            % (len(heads), ", ".join(sorted(heads)) or "(none)"))
        return files                           # no single entry point

    # Kahn's algorithm. The queue stays in discovery order rather than being
    # sorted, so branches emerge in the order the story jumps to them.
    order, queue, deg = [], list(heads), dict(indeg)
    while queue:
        cur = queue.pop(0)
        order.append(label_of[cur])
        for t in out_edges.get(cur, []):
            deg[t] -= 1
            if deg[t] == 0:
                queue.append(t)

    if len(order) == len(files):
        return order
    missed = [os.path.basename(p) for p in files if p not in order]
    sys.stderr.write(
        "script_diff: the jump graph reached %d of %d scene files, so they are\n"
        "  being compared in ALPHABETICAL order.\n"
        "  unreached: %s\n"
        "  Either nothing jumps to them yet, or there is a cycle -- a scene\n"
        "  inside a loop never has all its incoming paths resolved, so it can\n"
        "  never be placed.\n"
        % (len(order), len(files), ", ".join(missed) or "(none)"))
    return files


def read_scenes(scenes_dir):
    """Prose blocks in story order, with the file each came from."""
    blocks = []
    for f in scene_order(scenes_dir):
        for ln in io.open(f, encoding="utf-8").read().split("\n"):
            s = ln.strip()
            if s.startswith("#"):
                continue
            # Character prefixes may contain digits (numbered mob speakers).
            m = re.match(r'^(?:[a-z_][a-z0-9_]* )?"(.*)"$', s)
            if not m:
                continue
            t = m.group(1).replace('\\"', '"')
            # Ren'Py text tags are presentation, not prose -- {size=+18} and
            # friends must not read as a difference from the docx.
            t = re.sub(r"\{/?[^{}]*\}", "", t)
            blocks.append((normalize(t), os.path.basename(f)))
    return blocks


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: python script_diff.py <master.docx> <scenes-dir> "
                 "[patterns.json]\n"
                 "Paths are deliberately not stored in this repository.")
    docx_path, scenes = sys.argv[1], sys.argv[2]

    # ⚠ ACCEPT THE GAME DIRECTORY TOO, because being handed it instead of
    # scenes/ produces GARBAGE RATHER THAN AN ERROR, and the garbage is
    # convincing. game/ globs to combat.rpy, gui.rpy, screens.rpy and the rest,
    # so style names and hex colors get read as dialogue blocks and reported as
    # rewritten prose. The block counts look plausible, every line of the diff
    # is nonsense, and nothing says which. It cost a wrong conclusion that this
    # tool was broken when the argument was simply one level too high.
    #
    # vnpaths.game_dir already accepts either spelling for the same reason.
    if os.path.isdir(os.path.join(scenes, "scenes")):
        scenes = os.path.join(scenes, "scenes")

    global SPEAKER, SPEC_START, SPEC_LINE, ANNOTATION
    # Look beside the scenes, then up the tree -- the natural homes are the
    # game directory and the project directory, and guessing only one of them
    # fails silently by falling back to the generic defaults, which reports
    # the author's spec notes as unconverted story.
    if len(sys.argv) > 3:
        patterns = sys.argv[3]
    else:
        here = os.path.abspath(scenes)
        for _ in range(3):
            candidate = os.path.join(here, "patterns.json")
            if os.path.exists(candidate):
                break
            here = os.path.dirname(here)
        patterns = candidate
    SPEAKER, SPEC_START, SPEC_LINE, ANNOTATION = load_patterns(patterns)
    doc = read_docx(docx_path)
    scr = read_scenes(scenes)
    scr_text = bind_interpolations([t for t, _ in scr], doc)

    print(f"docx : {len(doc)} blocks  ({os.path.basename(docx_path)})")
    print(f"rpy  : {len(scr_text)} blocks  ({len(set(f for _, f in scr))} scene files)")
    print()

    sm = difflib.SequenceMatcher(None, scr_text, doc, autojunk=False)
    findings = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        findings += 1
        if tag == "replace":
            print(f"CHANGED  (in {scr[i1][1] if i1 < len(scr) else '?'})")
            for k in range(i1, i2):
                print(f"    was: {scr_text[k][:130]}")
            for k in range(j1, j2):
                print(f"    now: {doc[k][:130]}")
        elif tag == "insert":
            after = scr[i1 - 1][1] if 0 < i1 <= len(scr) else "(start)"
            print(f"NEW      {j2 - j1} block(s), after {after} -- not yet converted")
            for k in range(j1, j2):
                print(f"    + {doc[k][:130]}")
        elif tag == "delete":
            print(f"DROPPED  {i2 - i1} block(s) from {scr[i1][1]}")
            for k in range(i1, i2):
                print(f"    - {scr_text[k][:130]}")
        print()

    print("in sync" if not findings else f"{findings} region(s) differ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
