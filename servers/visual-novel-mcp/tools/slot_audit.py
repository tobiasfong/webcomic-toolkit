# -*- coding: utf-8 -*-
"""Two sprites standing in one slot -- found by walking, not by playing.

    python slot_audit.py <project-dir>

WHY
---
`show a at slot_left` followed by `show b at slot_left` is not an error in
Ren'Py. The second figure is simply drawn over the first, silently, and the
scene plays on with one character invisible for as long as the pair stands
there. Lint says nothing, script_diff says nothing -- the text is all
correct -- and the only way it has ever been caught here is somebody looking
at the frame and asking why a character who is clearly present cannot be
seen. That happened twice in one sitting.

The trap has a second half: slots are INHERITED. A scene that opens without a
`scene` statement keeps whatever the previous scene left standing, so a slot
can be occupied by someone the file never mentions. This walks the story in
jump order and carries the stage across, exactly as sprite_audit does, which
is the only way to see that kind of collision at all.

WHAT IT REPORTS
---------------
COLLISION -- two tags at one slot at the same moment. Always a bug.
UNPLACED  -- `show <tag>` with no `at`, which lands on Ren'Py's default
             position and will sit on anyone else shown the same way.

Effect plates (`fx ...`) are ignored: they are full-frame overlays with their
own z-order, and they are supposed to cover the cast.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script_diff  # noqa: E402

# Tags that are not members of the cast and so cannot "block" anyone:
#   fx     -- full-frame impact and ambient plates, drawn over everyone by design
#   prop   -- insert shots (a sword, a letter), centered on purpose
#   screen -- not an image at all; `show screen X` is the screen statement
NOT_CAST = {"fx", "prop", "screen"}

SHOW = re.compile(r"^\s*show\s+([a-z_0-9]+(?:\s+[a-z_0-9]+)*?)\s*(?:\s+at\s+(.+?))?\s*$")
HIDE = re.compile(r"^\s*hide\s+([a-z_0-9]+)")
SCENE = re.compile(r"^\s*scene\b")


def audit(project):
    scenes_dir = os.path.join(project, "game", "scenes")
    order = script_diff.scene_order(scenes_dir)
    stage = {}                      # tag -> (slot, where it was placed)
    problems = []
    read = 0
    for path in order:
        # ⚠ scene_order RETURNS FULL PATHS. Joining them onto scenes_dir again
        # produced a doubled path that existed nowhere, every file was skipped,
        # and this reported "no two sprites share a slot" having opened NOTHING.
        # A checker that passes by examining zero files is worse than no
        # checker, so the count is asserted below rather than trusted.
        if not os.path.exists(path):
            continue
        read += 1
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        for i, ln in enumerate(lines, 1):
            if SCENE.match(ln):
                stage.clear()
                continue
            m = HIDE.match(ln)
            if m:
                stage.pop(m.group(1), None)
                continue
            m = SHOW.match(ln)
            if not m:
                continue
            tag = m.group(1).split()[0]
            if tag in NOT_CAST:
                continue
            slot = (m.group(2) or "").strip()
            here = "%s:%d" % (name, i)
            if not slot:
                # A bare `show` keeps the tag's current position if it already
                # has one, so only a FIRST appearance is genuinely unplaced.
                if tag not in stage:
                    problems.append(("UNPLACED ", here, tag, ""))
                continue
            for other, (oslot, owhere) in stage.items():
                if other != tag and oslot == slot:
                    problems.append(
                        ("COLLISION", here, "%s over %s at %s" % (tag, other, slot),
                         "%s placed at %s" % (other, owhere)))
            stage[tag] = (slot, here)
    return order, problems, read


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python slot_audit.py <project-dir>")
    order, problems, read = audit(sys.argv[1])
    print("slot_audit: %d scene files in story order, %d read"
          % (len(order), read))
    if read == 0:
        raise SystemExit("slot_audit: read NO scene files -- refusing to report a result. Check the project path.")
    if not problems:
        print("no two sprites share a slot.")
    else:
        print("\n%d PROBLEM(S):" % len(problems))
        for kind, where, what, note in problems:
            print("  %s %-28s %s" % (kind, where, what))
            if note:
                print("      (%s)" % note)
    sys.exit(1 if problems else 0)
