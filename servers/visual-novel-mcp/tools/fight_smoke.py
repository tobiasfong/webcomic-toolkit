# -*- coding: utf-8 -*-
"""Start the game's first fight in a real run and report any crash.

    python fight_smoke.py <project-dir>

WHY THE OTHER CHECKS DID NOT CATCH THIS
---------------------------------------
On 2026-10-11 a refactor of the battle engine left a table entry holding a
lambda in a store variable, and every fight in the game died at its first
checkpoint save ("Can't pickle <function <lambda>>") -- from the prologue
bandits onward. Every step of the verification sequence was green:

  * lint compiles and never saves;
  * the headless combat check plays the fights through the resolver with a
    stub engine, so it never saves either (it pickles the battle variables
    now, but a label's own variable is outside its view);
  * screen_smoke opens the menu screens and never starts a fight.

The author found it by playing. This is the missing check: the REAL engine,
through the real fight label, past the line that saves.

HOW
---
Like screen_smoke, through Ren'Py's test framework (`renpy.exe <project>
test <testcase>`), which runs the game headed and drives it. A throwaway
file defines a `splashscreen` label -- Ren'Py runs it before the main menu,
so nothing has to be clicked to reach it -- that calls the first `battle_*`
label the scenes call, and a testcase that advances through the opening
lines of the fight. The file and its compiled twin are ALWAYS deleted.

What counts: any traceback OTHER than the test runner's own five-second
timeout, which is how a testcase that outlives its advances ends (the fight
is waiting on the command menu by then -- that is the PASS state, and the
checkpoint save is behind it). The fight is played with the game's default
stats, which is the prologue's situation and all the check needs.
"""
import glob
import io
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import renpy_sdk  # noqa: E402

TEMP_NAME = "zz_fight_smoke"
TESTCASE = "fight_smoke"
ADVANCES = 8


def first_fight(project):
    """The first battle label a scene calls, in file order."""
    for f in sorted(glob.glob(os.path.join(project, "game", "scenes", "*.rpy"))):
        src = io.open(f, encoding="utf-8", errors="replace").read()
        m = re.search(r"^\s*call\s+(battle_\w+)\s*$", src, re.M)
        if m:
            return m.group(1), os.path.basename(f)
    return None, None


def run(project):
    label, where = first_fight(project)
    if not label:
        print("fight_smoke: no scene calls a battle_* label; nothing to check")
        return 0
    game = os.path.join(project, "game")
    path = os.path.join(game, TEMP_NAME + ".rpy")
    tb = os.path.join(project, "traceback.txt")
    log = os.path.join(project, TEMP_NAME + ".log")
    try:
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# TEMPORARY -- written and deleted by fight_smoke.py.\n"
                    "label splashscreen:\n    call %s\n    return\n\n"
                    "testcase %s:\n    pause 2\n%s    pause 2\n"
                    % (label, TESTCASE, "    advance\n" * ADVANCES))
        if os.path.exists(tb):
            os.remove(tb)
        with open(log, "w", encoding="utf-8") as fh:
            proc = subprocess.Popen([renpy_sdk.launcher(), project, "test", TESTCASE],
                                    stdout=fh, stderr=subprocess.STDOUT)
            t0 = time.time()
            status = None
            while time.time() - t0 < 150:
                time.sleep(0.5)
                text = io.open(log, encoding="utf-8", errors="replace").read()
                if "Status:" in text or os.path.exists(tb) or proc.poll() is not None:
                    time.sleep(1.0)
                    status = io.open(log, encoding="utf-8", errors="replace").read()
                    break
            if proc.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True)
                else:
                    proc.kill()
                proc.wait()
        err = ""
        if os.path.exists(tb):
            text = io.open(tb, encoding="utf-8", errors="replace").read()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            errs = [l for l in lines if re.match(r"^[\w.]+(Error|Exception)\b", l)]
            err = errs[0] if errs else (lines[-1] if lines else "")
            if "RenpyTestTimeoutError" in err:
                err = ""            # the runner outliving its advances: the pass state
        if status is None:
            print("fight_smoke: %s (%s) gave no result in 150 s" % (label, where))
            return 2
        if err:
            m = re.findall(r'File "(game/[^"]+)", line (\d+)',
                           io.open(tb, encoding="utf-8", errors="replace").read())
            print("fight_smoke: CRASH in %s (%s): %s%s"
                  % (label, where, err, (" (%s:%s)" % m[-1]) if m else ""))
            return 1
        print("fight_smoke: %s (%s) starts and reaches its command menu without a crash"
              % (label, where))
        return 0
    finally:
        for p in (path, path + "c", tb, log):
            if os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python fight_smoke.py <project-dir>")
    sys.exit(run(os.path.abspath(sys.argv[1])))
