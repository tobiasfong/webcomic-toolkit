"""Report speakers who talk with no sprite on screen.

    python sprite_audit.py <project-dir>

The project directory is expected to hold `game/scenes/`, `sprites.json`,
`game/characters.rpy` and a `sprite_audit.json` (see below). Everything that
names a character or a scene lives in that JSON, in the gitignored project
tree -- this tool is public and stays project-agnostic.

WHY THIS IS NOT A ONE-LINER
---------------------------
The naive version -- scan each file alone, reset at the top -- produced
FIFTEEN false positives, because it models the engine wrongly:

  * Sprites SURVIVE A `jump`. Only `scene` clears the screen. A file that
    is jumped into inherits whatever the previous scene showed, so the
    shown set has to be carried ACROSS files.
  * Files therefore have to be walked in STORY order, not alphabetical, and
    story order is TOPOLOGICAL rather than depth-first, because branches
    reconverge. `script_diff.scene_order()` already does that; use it.
  * `scene cg <x>` is a no-sprite state by design -- the CG contains the
    cast. Speaking over one is correct, not a gap.
  * The speaker VARIABLE is not always the sprite TAG, so the map has to be
    looked up, not guessed.

ONE SPEAKER CAN HAVE SEVERAL SPRITES, and the config's `overrides` are
therefore LISTS: a costume change partway through the story, or a back
view, gives one speaker two or more tags, and any of them on stage counts.

  ⚠ THIS IS WHERE THE FIRST VERSION OF THIS TOOL WENT WRONG. It mapped the
  protagonist to ONE tag, taken from a handover note that listed one tag
  per speaker. Every one of his lines before a mid-story costume change
  then reported as a gap -- 61 of them, all correct code. The reflex to
  "fix" that by excusing him from the audit was WRONG TWICE: it silenced a
  whole speaker, and it treated a broken model as a property of the game.
  If a speaker floods this report, doubt the sprite he is being checked
  against before you doubt the scenes.

KNOWN OVER-APPROXIMATION, stated so nobody trusts this further than it goes:
`show` lines inside `if`/`menu` branches count as shown for everything after
them regardless of nesting. That trades false positives for false negatives
on purpose -- a noisy audit gets ignored, and an audit that gets ignored is
worth nothing. It cannot prove a scene is correct; it can only catch the
common bug, which is a speaker with no `show` anywhere before them.

sprite_audit.json
-----------------
    not_on_stage : speakers that are never a figure on stage (narrator, UI)
    overrides    : speaker variable -> list of sprite tags that satisfy it
    deliberate   : "<file>:<speaker>" -> why that gap is intentional.
                   Keyed WITHOUT line numbers, which move on every re-emit.
                   A deliberate gap is still printed, as confirmation.

Exit code is the number of gaps NOT on the deliberate list.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script_diff  # noqa: E402

_SCENE = re.compile(r"^\s*scene\b\s*(.*)$")
_SHOW = re.compile(r"^\s*show\s+([\w]+)(.*)$")
_HIDE = re.compile(r"^\s*hide\s+([\w]+)")
_AS = re.compile(r"\bas\s+([\w]+)")
_SAY = re.compile(r"^\s*([a-z_][\w]*)\s+[\"“]")
_CHARDEF = re.compile(r"^define\s+([a-z_][\w]*)\s*=\s*Character\(")


def load_tags(sprites_json):
    d = json.load(io.open(sprites_json, encoding="utf-8"))
    return {c["tag"] for c in d.get("characters", {}).values()}


def load_speakers(characters_rpy):
    out = set()
    for line in io.open(characters_rpy, encoding="utf-8"):
        m = _CHARDEF.match(line)
        if m:
            out.add(m.group(1))
    return out


def load_config(path):
    cfg = json.load(io.open(path, encoding="utf-8"))
    return (set(cfg.get("not_on_stage", [])),
            {k: set(v) for k, v in cfg.get("overrides", {}).items()},
            cfg.get("deliberate", {}))


def main(argv):
    if len(argv) != 1:
        sys.exit("usage: python sprite_audit.py <project-dir>")
    proj = argv[0]
    scenes_dir = os.path.join(proj, "game", "scenes")
    sprites_json = os.path.join(proj, "sprites.json")
    characters_rpy = os.path.join(proj, "game", "characters.rpy")
    config = os.path.join(proj, "sprite_audit.json")
    for p in (scenes_dir, sprites_json, characters_rpy, config):
        if not os.path.exists(p):
            sys.exit("sprite_audit: missing %s" % p)

    tags = load_tags(sprites_json)
    speakers = load_speakers(characters_rpy)
    not_on_stage, overrides, deliberate = load_config(config)
    order = script_diff.scene_order(scenes_dir)

    shown = set()
    in_cg = False
    gaps, no_sprite, deliberate_hit = [], [], []

    for path in order:
        name = os.path.basename(path)
        for lineno, line in enumerate(io.open(path, encoding="utf-8"), 1):
            m = _SCENE.match(line)
            if m:
                shown.clear()
                in_cg = m.group(1).strip().startswith("cg")
                continue
            m = _SHOW.match(line)
            if m:
                alias = _AS.search(m.group(2))
                shown.add(alias.group(1) if alias else m.group(1))
                continue
            m = _HIDE.match(line)
            if m:
                shown.discard(m.group(1))
                continue
            m = _SAY.match(line)
            if not m:
                continue
            var = m.group(1)
            if var not in speakers or var in not_on_stage:
                continue
            want = overrides.get(var, {var})
            label = "/".join(sorted(want))
            if not (want & tags):
                no_sprite.append((name, lineno, var, label))
            elif not (want & shown) and not in_cg:
                key = "%s:%s" % (name, var)
                (deliberate_hit if key in deliberate else gaps).append(
                    (name, lineno, var, label))

    print("sprite_audit: %d scene files in story order, %d sprite tags\n"
          % (len(order), len(tags)))
    if no_sprite:
        print("SPEAKERS WITH NO SPRITE REGISTERED (%d) -- not gaps, missing "
              "assets:" % len(no_sprite))
        for n, l, v, t in no_sprite:
            print("  %s:%d  %s (tag %s)" % (n, l, v, t))
        print()
    if deliberate_hit:
        print("DELIBERATE gaps, confirmed present (%d):" % len(deliberate_hit))
        for n, l, v, _ in deliberate_hit:
            print("  %s:%d  %s" % (n, l, v))
        print()
    if gaps:
        print("UNINTENDED gaps (%d) -- a speaker with no sprite shown:"
              % len(gaps))
        for n, l, v, t in gaps:
            print("  %s:%d  %s speaks, tag %r not shown" % (n, l, v, t))
    else:
        print("UNINTENDED gaps: none.")
    return len(gaps)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
