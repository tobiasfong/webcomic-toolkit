"""Keep the skill's vendored pipeline identical to this server's tools.

    python sync_skill.py            # copy server tools -> skill pipeline
    python sync_skill.py --check    # exit 1 if they differ, without copying

WHY A COPY EXISTS AT ALL
------------------------
The anime-production SKILL installs by copying its `assets/` into a separate
Remotion project (SKILL.md, step 3). Anything under `assets/` must therefore
work with nothing else around it, so the pipeline modules cannot be imported
from this server -- they have to be shipped with the skill. That makes a
second copy unavoidable.

WHY THIS SCRIPT EXISTS
----------------------
The copy was made by hand and then forgotten. Three weeks later it was five
files behind, missing a whole function, and SKILL.md was still promising
"same code either way". Nobody edited the skill; the server got fixed and the
skill silently fell behind -- which is how every hand-maintained copy ends.

A comment saying "keep in sync" does not survive contact with a busy week.
A check that FAILS does. `--check` belongs in the verification sequence, so
drift is a red line in a report rather than a discovery months later.

THE SERVER IS CANONICAL. It is the side that gets used and therefore fixed,
so edits go here and flow outward. Editing the skill's copy directly is the
mistake this script exists to make visible: the next sync overwrites it.
"""
import filecmp
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "tools")
DST = os.path.join(HERE, "..", "anime-production-skill", "assets", "tools", "pipeline")

# The module set is explicit rather than "everything in tools/": the skill
# ships the pure-Python pipeline only. The GPU-driving half (LTX, Kontext)
# lives beside it as standalone scripts and is deliberately not duplicated.
MODULES = ["__init__.py", "artifacts.py", "assemble.py", "effects.py",
           "framing.py", "motion.py", "subs.py"]


def main(argv):
    check = "--check" in argv
    dst = os.path.normpath(DST)
    if not os.path.isdir(dst):
        sys.exit("skill pipeline directory not found: %s" % dst)

    stale = []
    for name in MODULES:
        s, d = os.path.join(SRC, name), os.path.join(dst, name)
        if not os.path.exists(s):
            sys.exit("missing from server tools/: %s" % name)
        if not os.path.exists(d) or not filecmp.cmp(s, d, shallow=False):
            stale.append(name)

    if check:
        if stale:
            print("sync_skill: skill pipeline is BEHIND the server in %d file(s):"
                  % len(stale))
            for n in stale:
                print("  " + n)
            print("run `python sync_skill.py` to bring it current.")
            return 1
        print("sync_skill: skill pipeline matches the server (%d files)."
              % len(MODULES))
        return 0

    for name in stale:
        shutil.copyfile(os.path.join(SRC, name), os.path.join(dst, name))
        print("  synced " + name)
    if not stale:
        print("sync_skill: already current.")
    else:
        print("sync_skill: %d file(s) synced." % len(stale))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
