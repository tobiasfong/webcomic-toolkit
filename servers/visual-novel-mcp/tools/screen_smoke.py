"""Open every menu screen in a real run of the game and report any crash.

    python screen_smoke.py <project-dir>

WHY LINT IS NOT ENOUGH
----------------------
Ren'Py's lint compiles screens but does not RESOLVE the names inside them.
A button whose action names a function that does not exist -- a
`TogglePersistent`, which Ren'Py never had -- compiles, lints clean, and
crashes the game the moment the screen is displayed. One did exactly that to
Preferences for six days (2026-09-20 to 2026-09-26) with every step of the
verification sequence green, and it was found by opening the screen in a
scripted run. This is that run, made standard.

HOW
---
Ren'Py's test framework (`renpy.exe <project> test <testcase>`) runs the real
game headed and executes a `testcase` block. This writes a throwaway file of
testcases -- one per screen, each: wait for the main menu, open the screen,
hold it -- runs them one at a time, and reads `traceback.txt`, which Ren'Py
writes on any uncaught exception. The file and its compiled twin are ALWAYS
deleted, crash or not, so nothing temporary can ship in a build.

WHICH SCREENS: every `ShowMenu("...")` target in the game's scripts, found by
reading them, so a new menu is covered the day it is added. `save` is left
out: it cannot be opened from the main menu, where there is nothing to save,
and the test only waits out its timer.

A TIMEOUT IS NOT A CRASH. Ren'Py's test runner gives a testcase five seconds;
a screen that is merely slow to open is reported separately from one that
raised, so a slow machine cannot fail the step.
"""
import glob
import io
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import renpy_sdk  # noqa: E402

SKIP = {"save"}
TEMP_NAME = "zz_screen_smoke"


def menu_screens(project):
    names = set()
    for f in glob.glob(os.path.join(project, "game", "**", "*.rpy"), recursive=True):
        if os.path.basename(f).startswith(TEMP_NAME):
            continue
        src = io.open(f, encoding="utf-8", errors="replace").read()
        names.update(re.findall(r'ShowMenu\(\s*["\'](\w+)["\']', src))
    return sorted(names - SKIP)


def _run_test(project, testcase, limit=120):
    """Run one testcase and return its output, or None if it never reported.

    ⚠ THE TEST RUNNER DOES NOT EXIT. It prints its "Status:" line and then
    leaves the game running, so waiting for the process to end waits
    forever -- the first version of this tool waited out its two-minute
    limit on every screen and reported all five as hung while every one had
    in fact passed. So the output goes to a file, the file is watched for
    the status line, and the game is killed once it appears.
    """
    import tempfile
    import time
    log = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
    log.close()
    with open(log.name, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen([renpy_sdk.launcher(), project, "test", testcase],
                                stdout=fh, stderr=subprocess.STDOUT)
        out = None
        t0 = time.time()
        while time.time() - t0 < limit:
            time.sleep(0.5)
            text = io.open(log.name, encoding="utf-8", errors="replace").read()
            if "Status:" in text or proc.poll() is not None:
                time.sleep(0.5)     # let the traceback finish writing
                out = io.open(log.name, encoding="utf-8", errors="replace").read()
                break
        if proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True)
            else:
                proc.kill()
            proc.wait()
    os.remove(log.name)
    return out


def run(project):
    screens = menu_screens(project)
    game = os.path.join(project, "game")
    path = os.path.join(game, TEMP_NAME + ".rpy")
    tb = os.path.join(project, "traceback.txt")
    results = []
    try:
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# TEMPORARY -- written and deleted by screen_smoke.py.\n")
            for s in screens:
                f.write('testcase smoke_%s:\n    pause 1\n    run ShowMenu("%s")\n'
                        '    pause 1\n\n' % (s, s))
        for s in screens:
            if os.path.exists(tb):
                os.remove(tb)
            out = _run_test(project, "smoke_" + s)
            if out is None:
                results.append((s, "hung", "no result in 120 s"))
                continue
            err = ""
            if os.path.exists(tb):
                text = io.open(tb, encoding="utf-8", errors="replace").read()
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                errs = [l for l in lines if re.match(r"^\w+(Error|Exception)\b", l)]
                err = errs[0] if errs else lines[-1]
            if "Status: PASSED" in out and not err:
                results.append((s, "ok", ""))
            elif "TimeoutError" in err or "timed out" in err:
                results.append((s, "slow", err))
            else:
                where = ""
                if os.path.exists(tb):
                    m = re.findall(r'File "(game/[^"]+)", line (\d+)', io.open(
                        tb, encoding="utf-8", errors="replace").read())
                    if m:
                        where = " (%s:%s)" % m[-1]
                results.append((s, "CRASH", (err or "no traceback") + where))
    finally:
        for p in (path, path + "c", tb):
            if os.path.exists(p):
                os.remove(p)
    return results


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python screen_smoke.py <project-dir>")
    res = run(sys.argv[1])
    for s, st, msg in res:
        print("  %-18s %-6s %s" % (s, st, msg))
    crashed = [r for r in res if r[1] in ("CRASH", "hung")]
    print("screen_smoke: %d screen(s), %d crashed, %d slow"
          % (len(res), len(crashed), sum(1 for r in res if r[1] == "slow")))
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(main())
