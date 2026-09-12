# -*- coding: utf-8 -*-
"""The whole verification sequence, in one command, stopping at the first failure.

    python verify_all.py <project-dir> <master.docx> [--slug NAME] [--skip-lint]

Run it with the visual-novel-mcp venv's python: the steps need python-docx,
pyflakes and the server's own modules.

WHY ONE COMMAND
---------------
The sequence is nine steps, and every one of them exists because it caught a
real bug that none of the others could see. Run by hand they get skipped,
run out of order, or -- the case that produced this file -- filtered wrong:
a lint check that grepped for `game/x.rpy:42` reported a clean sheet while
the game would not compile, because a parse error prints in a different
shape. This script does not grep lint's output at all. It deletes
`errors.txt` and checks whether Ren'Py writes it back, which is a signal
that cannot be filtered wrong.

Each step prints one line and the run stops at the first failure, with that
step's output. A green run is the whole sequence, in order, with nothing
skipped -- the only kind of green worth reporting.

THE STEPS
---------
  1  emit       <project>/tools/emit_all.py, if present -- every scene from the docx
  2  diff       script_diff: the docx against the emitted scenes, "in sync"
  3  lint       Ren'Py lint; FAILS if errors.txt comes back, or on any finding
  4  sprites    sprite_audit: no speaker without a sprite, beyond the documented gaps
  5  slots      slot_audit: no two sprites in one slot, across scene boundaries
  6  spec       spec_check: the author's numbers against the engine's
  7  sound      every impact plate has a sound in the three lines before it, and is declared
  8  story      check_story: no dangling jumps, unresolved images, missing audio
  9  nvl        no NVL page taller than the screen, measured with the real font
 10  pyflakes   the server's tools and the project's
 11  skill      sync_skill --check, when this repository has it
"""
import glob
import io
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SERVER))
sys.path.insert(0, HERE)
sys.path.insert(0, SERVER)

PY = sys.executable


class Fail(Exception):
    pass


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ------------------------------------------------------------------ steps

def step_emit(project, docx):
    tool = os.path.join(project, "tools", "emit_all.py")
    if not os.path.exists(tool):
        return "no emit_all.py -- scenes are not generated here"
    code, out = run([PY, tool])
    if code:
        raise Fail(out)
    return out.strip().splitlines()[-1]


def step_diff(project, docx):
    scenes = os.path.join(project, "game", "scenes")
    patterns = os.path.join(project, "game", "patterns.json")
    code, out = run([PY, os.path.join(HERE, "script_diff.py"), docx, scenes, patterns])
    if "in sync" not in out:
        raise Fail(out)
    # ⚠ AN UNCLOSED FENCE OPENER IS NOT A FAILURE, deliberately. The author
    # writes one-line "(To Claude Code: ...)" notes routinely and they have no
    # closer by nature, so failing here would block every run forever. What
    # protects the case that matters -- a REAL card block whose closer was
    # forgotten -- is that its copy is then prose on the docx side and absent
    # from the scenes, so it lands in this same diff as NEW blocks and fails
    # right here. script_diff prints the openers it found for the record.
    blocks = re.search(r"rpy\s*:\s*(\d+) blocks", out)
    return "in sync%s" % (" at %s blocks" % blocks.group(1) if blocks else "")


def step_lint(project, docx):
    import renpy_sdk
    errors = os.path.join(project, "errors.txt")
    if os.path.exists(errors):
        os.remove(errors)
    code, out = run([renpy_sdk.launcher(), project, "lint"])
    if os.path.exists(errors):
        raise Fail("Ren'Py wrote errors.txt -- the script does not compile:\n"
                   + io.open(errors, encoding="utf-8", errors="replace").read())
    findings = [l for l in out.splitlines() if re.match(r"^game/.*\.rpy:\d+", l)]
    if findings:
        raise Fail("\n".join(findings))
    return "compiles, no findings"


def step_sprites(project, docx):
    code, out = run([PY, os.path.join(HERE, "sprite_audit.py"), project])
    m = re.search(r"UNINTENDED gaps \((\d+)\)", out)
    if m or "NO SPRITE REGISTERED" in out:
        raise Fail(out)
    return "no unintended gaps"


def step_slots(project, docx):
    code, out = run([PY, os.path.join(HERE, "slot_audit.py"), project])
    if code:
        raise Fail(out)
    return out.strip().splitlines()[-1]


def step_spec(project, docx):
    code, out = run([PY, os.path.join(HERE, "spec_check.py"), docx, project])
    if code:
        raise Fail(out)
    m = re.search(r"agree with the engine\s*:\s*(\d+)", out)
    return "no disagreements%s" % (", %s claims agree" % m.group(1) if m else "")


AMBIENT = ("snow", "fog", "rain", "ember", "dust", "petal", "aura", "mist", "glow")


def step_sound(project, docx):
    bad = []
    for f in sorted(glob.glob(os.path.join(project, "game", "scenes", "*.rpy"))):
        L = io.open(f, encoding="utf-8").read().splitlines()
        for i, ln in enumerate(L):
            m = re.match(r"\s*show (fx .+?)(?: as .+)?$", ln)
            if not m or any(a in m.group(1) for a in AMBIENT):
                continue
            if "play sound" not in "\n".join(L[max(0, i - 3):i]):
                bad.append("%s:%d  %s" % (os.path.basename(f), i + 1, m.group(1)))
    if bad:
        raise Fail("impact plates with no sound in the three lines before:\n  "
                   + "\n  ".join(bad))

    # ⚠ AND EVERY PLATE IS DECLARED. Ren'Py defines an image for every file
    # under images/ by itself -- fx/slash_gray.png becomes `fx slash gray` --
    # so a plate nobody declared still resolves, check_story is satisfied,
    # lint is satisfied, and the fight draws it at its NATIVE size in the
    # middle of the frame: 1280x720 on a 1080p screen. Two of the assassins'
    # plates ran that way for a month (found 2026-09-11). The declarations
    # in presentation.rpy exist precisely to state the full-screen transform,
    # so a plate that is only automatic is a bug by definition.
    used = set()
    for f in glob.glob(os.path.join(project, "game", "scenes", "*.rpy")):
        for m in re.finditer(r"^\s*show (fx [a-z0-9 ]+?)(?: as .+)?\s*$",
                             io.open(f, encoding="utf-8").read(), re.M):
            used.add(m.group(1).strip())
    combat = os.path.join(project, "game", "combat.rpy")
    if os.path.exists(combat):
        used.update(re.findall(r'"(fx [a-z0-9 ]+)"',
                               io.open(combat, encoding="utf-8").read()))
    declared = set()
    for f in glob.glob(os.path.join(project, "game", "*.rpy")):
        for m in re.finditer(r"^image (fx [a-z0-9 ]+?)\s*[=:]",
                             io.open(f, encoding="utf-8").read(), re.M):
            declared.add(m.group(1).strip())
    auto = sorted(used - declared)
    if auto:
        raise Fail("plates the game shows but nothing declares -- Ren'Py is "
                   "drawing these at native size from the file name alone; "
                   "declare each in presentation.rpy with the full-screen "
                   "Transform:\n  " + "\n  ".join(auto))
    return "every impact plate has its sound, and %d plates are declared" % len(used)


def step_story(project, docx, slug=None):
    try:
        import server
    except Exception as e:                       # noqa: BLE001
        return "skipped -- server not importable here (%s)" % e.__class__.__name__
    r = server.check_story(slug or os.path.basename(os.path.normpath(project)))
    hard = {k: r.get(k) for k in ("dangling_targets", "unreachable_labels",
                                  "duplicate_labels", "unresolved_displayables",
                                  "missing_audio_files",
                                  "scenes_missing_file_or_label",
                                  "approved_scenes_changed_since_approval")}
    broken = {k: v for k, v in hard.items() if v}
    if broken:
        raise Fail("\n".join("%s: %r" % kv for kv in broken.items()))
    return "no dangling, unresolved or missing references"


def _gui_int(gui_text, name, default):
    m = re.search(r"^define gui\.%s\s*=\s*gui\.scale\((\d+)\)" % re.escape(name),
                  gui_text, re.M)
    if not m:
        m = re.search(r"^define gui\.%s\s*=\s*(\d+)" % re.escape(name), gui_text, re.M)
    return int(m.group(1)) if m else default


def step_nvl(project, docx):
    """No NVL page may run under the quick menu. Measured, not assumed.

    Uses the SAME page model paginate_nvl.py places the breaks with
    (nvlpage.py): story order across files, branches followed as the game
    follows them. That shared definition is also the caveat -- a fault in
    the model is invisible to both -- so the model is kept simple, and the
    final check is playing it.
    """
    try:
        import nvlpage
        import renpy_sdk
        import script_diff
    except Exception as e:                       # noqa: BLE001
        return "skipped -- %s" % e
    scenes = os.path.join(project, "game", "scenes")
    files = [f for f in script_diff.scene_order(scenes) if os.path.exists(f)]
    metrics = nvlpage.Metrics(project, renpy_sdk.sdk_dir())
    _, tallest, _ = nvlpage.walk(files, metrics, insert=False)
    worst, f, line, n = tallest
    where = "%s:%d (%d entries)" % (os.path.basename(f or "?"), line + 1, n)
    auto = sum(io.open(x, encoding="utf-8").read().count(nvlpage.MARK) for x in files)
    if worst > metrics.screen_h - 20:
        raise Fail("tallest page %d px at %s -- runs off a %d px screen"
                   % (worst, where, metrics.screen_h))
    if worst > metrics.limit:
        raise Fail("tallest page %d px at %s -- its text reaches the quick menu "
                   "(limit %d)" % (worst, where, metrics.limit))
    return "tallest page %d px of %d at %s; %d automatic breaks" % (
        worst, metrics.limit, where, auto)


def step_pyflakes(project, docx):
    files = glob.glob(os.path.join(HERE, "*.py")) + glob.glob(os.path.join(project, "tools", "*.py"))
    code, out = run([PY, "-m", "pyflakes"] + files)
    if out.strip():
        raise Fail(out)
    return "%d files clean" % len(files)


def step_skill(project, docx):
    tool = os.path.join(REPO, "servers", "anime-production-mcp", "sync_skill.py")
    if not os.path.exists(tool):
        return "skipped -- no sync_skill.py in this repository"
    code, out = run([PY, tool, "--check"])
    if code:
        raise Fail(out)
    return out.strip().splitlines()[-1]


STEPS = [
    ("emit", step_emit), ("diff", step_diff), ("lint", step_lint),
    ("sprites", step_sprites), ("slots", step_slots), ("spec", step_spec),
    ("sound", step_sound), ("story", step_story), ("nvl", step_nvl),
    ("pyflakes", step_pyflakes), ("skill", step_skill),
]


def _utf8_stdout():
    """Make stdout survive the author's prose.

    ⚠ A failure message often QUOTES THE DOCX -- the tail cap prints the last
    paragraph in range, emitters print the anchor they could not find -- and
    that prose carries curly quotes and ellipses. On Windows this process
    writes to a cp1252 console, so printing the message raised
    UnicodeEncodeError from inside the except branch and the REAL error was
    never shown: the run looked like a crash in the checker rather than the
    guard doing its job. Fixed 2026-09-11, after the Act 2 tail cap fired and
    its explanation was swallowed.
    """
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv):
    _utf8_stdout()
    if len(argv) < 2:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    project, docx = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    slug = None
    skip = set()
    for a in argv[2:]:
        if a.startswith("--slug="):
            slug = a.split("=", 1)[1]
        elif a.startswith("--skip-"):
            skip.add(a[7:])
    t0 = time.time()
    for name, fn in STEPS:
        if name in skip:
            print("  %-9s skipped" % name)
            continue
        t = time.time()
        try:
            msg = fn(project, docx) if name != "story" else fn(project, docx, slug)
        except Fail as e:
            print("  %-9s FAIL  (%.0fs)\n" % (name, time.time() - t))
            print(str(e).rstrip())
            print("\nverify_all: stopped at step %r after %.0fs. Fix that, then rerun."
                  % (name, time.time() - t0))
            return 1
        print("  %-9s ok    %s  (%.0fs)" % (name, msg, time.time() - t))
    print("\nverify_all: every step passed in %.0fs." % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
