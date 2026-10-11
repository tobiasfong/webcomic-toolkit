"""Report sprites that stand on top of each other, and say who is buried.

    python sprite_overlap.py <path-to-game-dir> [min-coverage-percent]

WHY THIS EXISTS
---------------
A visual novel places figures with `xalign`, which positions a sprite as a
FRACTION of the leftover screen width -- so two figures at fixed slots move
apart or together depending on how wide their matted bodies happen to be. A
narrow character and a wide one at neighboring slots overlap; the same two
slots with two narrow bodies do not. Nothing in the engine warns about it,
and lint has no opinion, so it is invisible until somebody looks at the game
and says a character seems to be hiding behind another one.

Which is exactly how it was found here: adjacent slots sat ~310 px apart while
matted bodies ran 368-700 px wide, and the protagonist came out 53% covered by
his own retainer in three separate scenes. The staging was not wrong -- the
figures are meant to read as a row -- but WHO ended up in front was decided by
nothing more deliberate than which `show` line came first.

WHAT IT DOES NOT DECIDE
-----------------------
Overlap is not automatically a bug. Figures in a crowd SHOULD overlap. This
reports coverage and z-order and stops there; whether a given pair is wrong is
a judgment about the scene. Read it as a list of places to look, not a list of
defects.

Two ways to act on a real one:

  * `config.tag_zorder = {"<tag>": 10}` raises a character above everyone,
    everywhere, whatever order scenes show them in. This is the fix when the
    positions are right and only the layering is wrong.
  * Move one figure to a wider slot. This is the fix when they are genuinely
    too close, and it costs a re-emit of whichever scene stages them.

HOW IT READS THE PROJECT
------------------------
Everything is derived from the game itself, so no cast names live here:

  * `xalign` for every transform, parsed out of the project's own .rpy files,
    plus the engine's built-in left/center/right.
  * displayed width = the body's pixel width from sprites.json, times the zoom
    that emit_sprites wrote into sprites_generated.rpy. Both are needed -- the
    zoom is what normalizes a cast to a common height, and it changes width
    by the same factor.
  * the stage is tracked ACROSS a file: `show` adds, `hide` removes, `scene`
    clears. A figure shown on line 12 is still standing on line 300.
  * parameterized placements (`row(i, n)`, `fireside(x)`) are evaluated from
    the transform's own `xpos`/`xanchor`/`xalign` expressions, and
    `show A at P behind B` layers A just under B, as the engine does.

BRANCHES AND Z-ORDER, BOTH OF WHICH IT USED TO GET WRONG
--------------------------------------------------------
Two false-positive sources, each of which put a 100% pair at the top of the
report on a stage that was actually fine:

  * CONDITIONAL BRANCHES. A `show` indented inside an `if` does not coexist
    with one inside the matching `else`, but a flat scan sees both standing.
    Indentation is tracked, and a figure shown deeper than the current line is
    dropped when that block closes -- so the two sides of a branch are never
    compared against each other.

  * config.tag_zorder. The engine consults that dict on every show, so a
    character listed there is in front regardless of who was shown last. It is
    parsed out of the project and used to decide who is buried; without it,
    every pair a project has already FIXED still reports as broken.

⚠ Still approximate. Indentation is not a parser: a `show` inside a `while`,
or one reached by a jump from elsewhere, is beyond it. Read a surprising pair
in the file before believing it.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir  # noqa: E402

# The engine's own placements, which a project may use without defining them.
BUILTIN = {"left": 0.0, "center": 0.5, "truecenter": 0.5, "right": 1.0}

# `show TAG at POS` where POS is a bare transform (`slot_left`) or a call
# (`row(2, 5)`, `fireside(0.36)`), optionally followed by `behind OTHER`.
SHOW = re.compile(r"^\s*show\s+([a-z0-9_]+)\s+at\s+([a-z0-9_]+)(?:\(([^)]*)\))?"
                  r"(?:\s+behind\s+([a-z0-9_]+))?\s*$")
HIDE = re.compile(r"^\s*hide\s+([a-z0-9_]+)")
SCENE = re.compile(r"^\s*scene\b")


def read_transforms(game):
    """Placement for every `transform NAME:` block in the project, plus the
    engine's built-ins.

    A plain transform resolves to {"xalign": float}. A PARAMETERIZED one --
    `transform row(i, n):` -- keeps its `xalign` / `xpos` / `xanchor` as
    EXPRESSION STRINGS over its parameter names, evaluated per `show` in
    `left_edge()`. The two families this project uses: `row(i, n)` places
    the i-th of n figures by `xpos` with `xanchor 0.5`, and `fireside(x)` is
    `xalign x`. Until 2026-10-11 these were skipped outright, so four scenes
    staged entirely with `row()` were never checked while the step reported ok.
    """
    out = {k: {"xalign": v} for k, v in BUILTIN.items()}
    for root, _dirs, files in os.walk(game):
        for fn in files:
            if not fn.endswith(".rpy"):
                continue
            name = None
            for line in io.open(os.path.join(root, fn), encoding="utf-8",
                                errors="replace"):
                m = re.match(r"^transform\s+([a-z0-9_]+)\s*(?:\(([^)]*)\))?\s*:", line)
                if m:
                    name = m.group(1)
                    params = [p.strip() for p in (m.group(2) or "").split(",") if p.strip()]
                    out[name] = {"params": params}
                    continue
                if name:
                    m = re.match(r"^\s+(xalign|xpos|xanchor)\s+(.+?)\s*$", line)
                    if m:
                        out[name][m.group(1)] = m.group(2)
                    elif line.strip() and not line.startswith((" ", "\t")):
                        name = None
    # a plain transform's xalign is a number; keep the old shape for those
    for t in out.values():
        if not t.get("params") and "xalign" in t and not isinstance(t["xalign"], float):
            try:
                t["xalign"] = float(t["xalign"])
            except ValueError:
                pass
    return out


_SAFE_EXPR = re.compile(r"^[0-9a-z_+\-*/(). ]+$")


def _num(expr, env):
    """Evaluate an arithmetic transform expression, e.g.
    `(0.08 + 0.84 * (i + 0.5) / n)`, with the transform's parameters bound.
    Only numbers, names and + - * / ( ) get through."""
    if isinstance(expr, float):
        return expr
    expr = str(expr).strip()
    if not _SAFE_EXPR.match(expr):
        return None
    try:
        return float(eval(expr, {"__builtins__": {}}, dict(env)))
    except Exception:
        return None


def left_edge(t, args, W, aw):
    """Pixel x of a sprite's left edge under transform `t` with call `args`,
    or None if the transform does not place horizontally in a way this
    understands."""
    env = {}
    params = t.get("params") or []
    if params:
        if len(args) != len(params):
            return None
        for k, v in zip(params, args):
            n = _num(v, {})
            if n is None:
                return None
            env[k] = n
    if "xalign" in t:
        xa = _num(t["xalign"], env)
        return None if xa is None else xa * (W - aw)
    if "xpos" in t:
        xp = _num(t["xpos"], env)
        if xp is None:
            return None
        xp = xp * W if 0.0 <= xp <= 1.0 else xp           # a fraction, or pixels
        anchor = _num(t.get("xanchor", "0.0"), env) or 0.0
        anchor = anchor * aw if 0.0 <= anchor <= 1.0 else anchor
        return xp - anchor
    return None


def read_zorder(game):
    """tag -> zorder, from the project's config.tag_zorder dict."""
    out = {}
    for root, _dirs, files in os.walk(game):
        for fn in files:
            if not fn.endswith(".rpy"):
                continue
            text = io.open(os.path.join(root, fn), encoding="utf-8",
                           errors="replace").read()
            m = re.search(r"config\.tag_zorder\s*=\s*\{(.*?)\}", text, re.S)
            if not m:
                continue
            for tag, z in re.findall(r'["\']([a-z0-9_]+)["\']\s*:\s*(-?\d+)',
                                     m.group(1)):
                out[tag] = int(z)
    return out


def read_widths(game):
    """tag -> displayed pixel width (body width * the emitted zoom).

    Also fills HEIGHTS the same way, for the low-figure rule in main()."""
    zooms, tag = {}, None
    gen = os.path.join(game, "sprites_generated.rpy")
    if os.path.exists(gen):
        for line in io.open(gen, encoding="utf-8"):
            m = re.match(r"layeredimage\s+([a-z0-9_]+):", line)
            if m:
                tag = m.group(1)
            m = re.search(r"zoom=([0-9.]+)", line)
            if m and tag:
                zooms[tag] = float(m.group(1))

    # sprites.json lives beside the game directory, not inside it.
    manifest = os.path.join(os.path.dirname(game.rstrip("/\\")), "sprites.json")
    widths = {}
    if not os.path.exists(manifest):
        return widths
    data = json.load(io.open(manifest, encoding="utf-8"))
    for c in data.get("characters", {}).values():
        t, size = c.get("tag"), c.get("body_size")
        if t and size:
            widths[t] = size[0] * zooms.get(t, 1.0)
            HEIGHTS[t] = size[1] * zooms.get(t, 1.0)
    return widths


HEIGHTS = {}

# A figure in front that stands well below the one behind it cannot cover
# that figure's face or shoulders, whatever the widths say: the metric is
# horizontal, and this is the vertical fact it lacks. A low, wide beast beside
# a standing character scored 89-100% on width alone in two approved scenes
# and sat at the top of every report, above the two staging faults the report
# exists to surface. 0.70 is a geometric floor, not a tuned one -- below it
# the front figure ends around the buried figure's waist.
LOW_FRONT = 0.70


def main(argv):
    if not argv:
        sys.exit("usage: python sprite_overlap.py <game-dir> [min-percent]")
    game = game_dir(argv)
    floor = float(argv[1]) / 100.0 if len(argv) > 1 else 0.15

    xalign = read_transforms(game)
    width = read_widths(game)
    zorder = read_zorder(game)
    if not width:
        sys.exit("sprite_overlap: no sprites.json beside %s" % game)

    scenes = os.path.join(game, "scenes")
    if not os.path.isdir(scenes):
        scenes = game

    # Screen width: from the project's gui.init(w, h) if it says, else 1920.
    W = 1920
    g = os.path.join(game, "gui.rpy")
    if os.path.exists(g):
        m = re.search(r"gui\.init\((\d+)", io.open(g, encoding="utf-8").read())
        if m:
            W = int(m.group(1))

    files = [f for f in sorted(os.listdir(scenes)) if f.endswith(".rpy")]

    rows = []

    def flush(stage, pending, fn):
        """Compare every figure (re)shown in the batch against the stage as it
        stands NOW. A row is emitted once per pair per batch."""
        done = set()
        for tag, n in pending.items():
            ax, myseq, _l, _i = stage[tag]
            aw = width[tag]
            for other, (ox, oseq, otf, oind) in stage.items():
                if other == tag or frozenset((tag, other)) in done:
                    continue
                done.add(frozenset((tag, other)))
                ow = width[other]
                lo, hi = max(ax, ox), min(ax + aw, ox + ow)
                if hi <= lo:
                    continue
                ## Who is in front: the engine reads config.tag_zorder first
                ## and falls back to show order only within the same zorder.
                za, zo = zorder.get(tag, 0), zorder.get(other, 0)
                if za != zo:
                    buried, front = (other, tag) if zo < za else (tag, other)
                else:
                    buried, front = (other, tag) if oseq < myseq else (tag, other)
                if HEIGHTS.get(front, 1e9) < LOW_FRONT * HEIGHTS.get(buried, 0):
                    continue
                rows.append(((hi - lo) / width[buried], fn, n, buried,
                             stage[buried][2], front, stage[front][2],
                             int(hi - lo)))

    for fn in files:
        stage, seq, pending = {}, 0, {}
        for n, line in enumerate(io.open(os.path.join(scenes, fn),
                                         encoding="utf-8"), 1):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())

            ## A figure shown deeper than the current line belongs to a block
            ## that has now closed -- the other side of an if/else, most often
            ## -- so it is no longer standing. Without this the two branches of
            ## one choice get compared against each other and report as a
            ## totally buried pair that can never actually co-occur.
            for t in [t for t, v in stage.items() if v[3] > indent]:
                del stage[t]
                pending.pop(t, None)

            if SCENE.match(line):
                flush(stage, pending, fn)
                stage, pending = {}, {}
                continue
            m = HIDE.match(line)
            if m:
                stage.pop(m.group(1), None)
                pending.pop(m.group(1), None)
                continue
            m = SHOW.match(line)
            if not m:
                ## ⚠ A BATCH OF SHOWS IS ONE MOMENT. The emitters re-place a
                ## whole row before a single `with move`; the engine shows all
                ## of those at once, so a figure that passes through another's
                ## slot on the way is never on screen there. Judged line by
                ## line, every such batch reported a 100% pair that nobody can
                ## see. So the stage is only compared when a line that is NOT
                ## a show/hide arrives -- the `with`, the say, anything else.
                if pending and line.strip():
                    flush(stage, pending, fn)
                    pending = {}
                continue
            tag, tf, argstr, behind = m.group(1), m.group(2), m.group(3), m.group(4)
            if tag not in width or tf not in xalign:
                continue
            aw = width[tag]
            args = [p.strip() for p in argstr.split(",")] if argstr else []
            ax = left_edge(xalign[tf], args, W, aw)
            if ax is None:
                continue
            seq += 1
            ## `show A at P behind B` puts A just under B in the draw order
            ## instead of on top of everyone, so it takes a seq a hair below
            ## B's. Without this, every figure an emitter deliberately tucked
            ## behind the protagonist reported as covering him.
            ## Two figures both tucked behind the same one: the later show
            ## sits directly under it, above the earlier -- hence the tiny
            ## seq-ordered offset.
            myseq = (stage[behind][1] - 0.5 + seq * 1e-4) if (behind and behind in stage) else seq
            label = tf + ("(%s)" % ", ".join(args) if args else "")
            stage[tag] = (ax, myseq, label, indent)
            pending[tag] = n
        flush(stage, pending, fn)

    rows.sort(reverse=True)
    shown = [r for r in rows if r[0] >= floor]

    print("sprite_overlap: %d scene files, %d sprites, screen %d px wide"
          % (len(files), len(width), W))
    print("%d overlapping pairs, %d at or above %.0f%% coverage\n"
          % (len(rows), len(shown), floor * 100))

    if not shown:
        print("  nothing above the threshold.")
        return 0

    print("%-6s %-26s %-6s %s" % ("COVER", "file", "line", "buried / in front"))
    for frac, fn, n, buried, btf, front, ftf, px in shown:
        print("%5.0f%% %-26s %-6d %s (%s) behind %s (%s), %d px"
              % (frac * 100, fn, n, buried, btf, front, ftf, px))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
