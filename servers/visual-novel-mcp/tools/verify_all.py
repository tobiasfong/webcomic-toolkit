# -*- coding: utf-8 -*-
"""The whole verification sequence, in one command, stopping at the first failure.

    python verify_all.py <project-dir> <master.docx> [--slug NAME] [--skip-<step>]

Run it with the visual-novel-mcp venv's python: the steps need python-docx,
pyflakes and the server's own modules. `--slug NAME` and `--slug=NAME` both
work; `--skip-<step>` takes any step name below and anything else is an
error. If the two positional arguments come in the other order (the first
ends in .docx) they are swapped, and the run says so.

WHY ONE COMMAND
---------------
The sequence is twenty steps, and every one of them exists because it caught a
real bug that none of the others could see. Run by hand they get skipped,
run out of order, or -- the case that produced this file -- filtered wrong:
a lint check that grepped for `game/x.rpy:42` reported a clean sheet while
the game would not compile, because a parse error prints in a different
shape. This script does not grep lint's output alone. It deletes
`errors.txt` and checks whether Ren'Py writes it back, which is a signal
that cannot be filtered wrong.

Each step prints one line and the run stops at the first failure, with that
step's output. A green run is the whole sequence, in order -- and a step that
could not run because something it needs is missing prints `skip` with the
reason, never `ok`.

HOW A STEP DECIDES (the rule that replaced "grep the text")
-----------------------------------------------------------
Every child process is judged on three things, in this order: its exit code
(non-zero, or killed, is a FAIL with its output shown), whether its output
holds a Python traceback (a FAIL even when the code is 0), and then the
step's own positive evidence -- the line that only a real pass prints. A
step passes on evidence, never on the absence of a complaint: a checker that
read nothing, or died before printing, has not said "fine". Tools that use
their exit code as a finding count (sprite_audit, slot_audit, static_audit)
fail on any non-zero code, so the count and the report both reach the screen.

THE STEPS
---------
Everything that needs no window first, so a static failure stops the run
before any game window opens on the author's screen; the two steps that open
the game come last.

  1  emit       <project>/tools/emit_all.py, if present -- every scene from the docx
  2  diff       script_diff: the docx against the emitted scenes; the LAST line is "in sync"
  3  speaker    no dialogue reached a scene as narration with its label in it
  4  font       the installed CJK subset covers every CJK character in the scripts
  5  lint       Ren'Py lint; FAILS on errors.txt, a non-zero code, a finding, or no Statistics footer
  6  saves      save_compat: nothing a save holds was renamed, removed or left without a fallback
  7  sprites    sprite_audit: no speaker without a sprite, none left in narration, no stale exemption
  8  slots      slot_audit: no two sprites in one slot, across scene boundaries
  9  spec       spec_check: the author's numbers against the engine's (zero claims read FAILS)
 10  combat     every combat spec is reachable and anchored
 11  sim        <project>/tools/combat_sim.py, when present -- every fight played headless
 12  static     images, names, registry, defines and docs all resolve
 13  overlap    sprites that cover each other, reported not failed
 14  sound      every impact plate has a sound in the three lines before it, and is declared
 15  story      check_story: no dangling jumps, unresolved images, missing audio
 16  nvl        no NVL page taller than the screen, measured with the real font
 17  pyflakes   the server's modules and tools, and the project's tools
 18  skill      sync_skill --check, when this repository has it
 19  screens    screen_smoke: every menu screen opened in a real run (OPENS A WINDOW)
 20  fight      fight_smoke: the first fight started in a real run (OPENS A WINDOW)

⚠ This list is written by hand and went stale once: three steps were added
to STEPS without being added here, and the numbering ran 3, 4, 4. If you add
a step, add it in both places.
"""
import glob
import io
import os
import re
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SERVER))
sys.path.insert(0, HERE)
sys.path.insert(0, SERVER)

PY = sys.executable

TRACEBACK = "Traceback (most recent call last)"


class Fail(Exception):
    pass


class Skip(Exception):
    """A step that could not run because something it needs is missing.
    Printed as `skip` with the reason -- never as `ok`."""


def run(cmd, cwd=None):
    """Run a child and return (exit code, stdout + stderr as text).

    ⚠ THE CHILD IS TOLD TO WRITE UTF-8, AND WE READ IT AS UTF-8. Several tools
    print the manuscript's own text (a curly quote, an ellipsis, CJK). Piped to
    a Windows parent, a child defaults to cp1252 and either dies with
    UnicodeEncodeError mid-report or hands back mojibake; PYTHONUTF8 and
    PYTHONIOENCODING make every Python child agree with the decode below.
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _last_line(out):
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return lines[-1] if lines else ""


def clean(code, out, what):
    """The two judgments every child gets before any step-specific one."""
    if code != 0:
        raise Fail("%s exited with code %s\n%s" % (what, code, out))
    if TRACEBACK in out:
        raise Fail("%s printed a traceback (exit code 0)\n%s" % (what, out))


# ------------------------------------------------------------------ judges
# Pure functions of a child's (exit code, output): no files, no processes, so
# they can be fed made-up outputs and tested.

def judge_emit(code, out):
    clean(code, out, "emit_all.py")
    return _last_line(out) or "emitted (the tool printed nothing)"


def judge_diff(code, out):
    clean(code, out, "script_diff")
    # ⚠ THE FINAL LINE, EXACTLY. "in sync" used to be looked for anywhere in
    # the text, which a report quoting the phrase inside a block of changed
    # prose satisfied. script_diff ends on this line only when nothing differs.
    if _last_line(out) != "in sync":
        raise Fail("script_diff did not END on 'in sync':\n" + out)
    # ⚠ AN UNCLOSED FENCE OPENER IS NOT A FAILURE, deliberately. The author
    # writes one-line "(To Claude Code: ...)" notes routinely and they have no
    # closer by nature, so failing here would block every run forever. What
    # protects the case that matters -- a REAL card block whose closer was
    # forgotten -- is that its copy is then prose on the docx side and absent
    # from the scenes, so it lands in this same diff as NEW blocks and fails
    # right here. script_diff prints the openers it found for the record.
    blocks = re.search(r"rpy\s*:\s*(\d+) blocks", out)
    return "in sync%s" % (" at %s blocks" % blocks.group(1) if blocks else "")


def judge_speaker(code, out):
    # ⚠ THIS SITS NEXT TO diff BECAUSE IT ANSWERS WHAT diff CANNOT.
    # script_diff compares what is SAID and reports "in sync" on a scene whose
    # dialogue has lost its speaker, because the text is genuinely identical.
    # See speaker_audit.py's header for why sprite_audit is blind to it too.
    clean(code, out, "speaker_audit")
    if "DIALOGUE EMITTED AS NARRATION" in out:
        raise Fail(out)
    return "no dialogue emitted as narration"


FONT_SKIPS = ("no game/ directory", "no CJK subset installed", "no CJK in the scripts")


def judge_font(code, out):
    # ⚠ THIS IS ABOUT GLYPHS, WHICH IS WHY EVERY OTHER STEP MISSES IT. The
    # scripts can be in sync, compile, lint clean and still render empty
    # boxes, because the installed CJK subset is cut to the characters the
    # script used LAST time it was built. Nothing says it is stale; the
    # author finds out in play.
    clean(code, out, "font_audit")
    last = _last_line(out)
    if any(last.startswith(s) for s in FONT_SKIPS):
        raise Skip(last)
    if "all present in" not in last:
        raise Fail("font_audit gave no recognizable verdict:\n" + (out or "(no output)"))
    return last


def judge_lint(code, out, errors_text=None, log_text=""):
    """`errors_text` is errors.txt if Ren'Py wrote it; `log_text` is the
    project's log.txt, where Ren'Py on Windows writes the lint report even when
    nothing reaches stdout."""
    if errors_text is not None:
        raise Fail("Ren'Py wrote errors.txt -- the script does not compile:\n"
                   + errors_text)
    clean(code, out, "Ren'Py lint")
    seen = out + "\n" + log_text
    findings = [l for l in seen.splitlines() if re.match(r"^game/.*\.rpy:\d+", l)]
    if findings:
        raise Fail("\n".join(findings))
    # The report ends with a Statistics section on a real run. Without it lint
    # never got as far as reporting, whatever the exit code said.
    if "Statistics:" not in seen:
        raise Fail("lint printed no Statistics footer -- it did not finish a report:\n"
                   + (out or "(no output)"))
    return "compiles, no findings"


def judge_saves(code, out):
    clean(code, out, "save_compat")
    if "old saves stay loadable" not in out:
        raise Fail("save_compat did not say saves stay loadable:\n" + out)
    return out.strip().splitlines()[-1].replace("save_compat: ", "")


SPRITE_FAILS = ("UNINTENDED gaps (", "NO SPRITE REGISTERED", "STALE exemptions",
                "SPEAKER PREFIX LEFT IN NARRATION", "sprite_audit: missing")


def judge_sprites(code, out):
    # sprite_audit uses its exit code as a finding count, and exits with a
    # "missing <file>" message when an input is absent -- both are failures.
    clean(code, out, "sprite_audit")
    if any(f in out for f in SPRITE_FAILS):
        raise Fail(out)
    if "sprite_audit:" not in out or "UNINTENDED gaps: none." not in out:
        raise Fail("sprite_audit did not reach its verdict:\n" + (out or "(no output)"))
    return "no unintended gaps, no stale exemptions, no speaker left in narration"


def judge_slots(code, out):
    clean(code, out, "slot_audit")
    if _last_line(out) != "no two sprites share a slot.":
        raise Fail(out)
    return "no two sprites share a slot"


def judge_spec(code, out):
    clean(code, out, "spec_check")
    m = re.search(r"spec_check: (\d+) numeric claim", out)
    if not m:
        raise Fail("spec_check printed no claim count:\n" + (out or "(no output)"))
    if int(m.group(1)) == 0:
        raise Fail("spec_check read ZERO claims from the spec -- a vacuous pass. "
                   "The document or the region markers have moved.\n" + out)
    bad = re.search(r"DISAGREE\s*:\s*(\d+)", out)
    if bad and int(bad.group(1)):
        raise Fail(out)
    ok = re.search(r"agree with the engine\s*:\s*(\d+)", out)
    return "no disagreements, %s of %s claims agree" % (
        ok.group(1) if ok else "?", m.group(1))


def judge_combat(code, out, calls_in_scenes=None):
    """`calls_in_scenes` is how many `call battle_*` lines the scenes hold, when
    known. A manuscript with no combat markers is fine only if the game really
    has no fights."""
    clean(code, out, "combat_calls")
    if "no (Combat sequence) markers" in out:
        if calls_in_scenes:
            raise Fail("the manuscript has 0 combat markers but the scenes call "
                       "%d fight(s) -- the markers moved or were renamed" % calls_in_scenes)
        return "0 combat markers in the manuscript, 0 fights called (nothing to check)"
    m = re.search(r"combat_calls: (\d+) spec\(s\) across (\d+) scene file", out)
    if not m:
        raise Fail("combat_calls gave no recognizable verdict:\n" + (out or "(no output)"))
    if int(m.group(1)) == 0 and calls_in_scenes:
        raise Fail("combat_calls read 0 specs but the scenes call %d fight(s)"
                   % calls_in_scenes)
    return _last_line(out).replace("combat_calls: ", "")


def judge_sim(code, out):
    clean(code, out, "combat_sim")
    if "CRASH" in out:
        raise Fail(out)
    lines = out.splitlines()
    cut = next((i for i, l in enumerate(lines) if l.startswith("--- distinct")), None)
    if cut is None:
        raise Fail("combat_sim did not reach its summary:\n" + (out[-2000:] or "(no output)"))
    rows = [l for l in lines[:cut] if l.strip()]
    return "%d outcome rows; %s" % (len(rows), lines[cut].lstrip("- ").strip())


def judge_static(code, out):
    clean(code, out, "static_audit")
    if _last_line(out) != "static_audit: 0 finding(s).":
        raise Fail(out)
    return "images, names, registry, defines, docs all resolve"


def judge_overlap(code, out):
    """A REPORT, never a failure of the staging. Coverage is width-only and a
    crowd is meant to overlap, so no threshold separates staging the author has
    approved from staging he has rejected -- both this week's rejections
    scored 30-43%, and approved crowd scenes score 57-100%. What the number
    IS good for is being seen: the reunion was fixed the day someone
    looked at it. So the top pair is printed on every green run. A CRASH of
    the tool, however, is a failure: it used to read as "no pair"."""
    clean(code, out, "sprite_overlap")
    if "sprite_overlap:" not in out or "overlapping pairs" not in out:
        raise Fail("sprite_overlap printed no report:\n" + (out or "(no output)"))
    rows = [l for l in out.splitlines() if re.match(r"\s*\d+%", l)]
    if not rows:
        return "no pair at or above 30% (report only)"
    top = re.sub(r"\s+", " ", rows[0].strip())
    return "%d pair(s) at or above 30%%; top: %s (report only)" % (len(rows), top)


def judge_story(r):
    need = ("dangling_targets", "unreachable_labels", "duplicate_labels",
            "unresolved_displayables", "missing_audio_files",
            "scenes_missing_file_or_label", "approved_scenes_changed_since_approval")
    if not isinstance(r, dict):
        raise Fail("check_story returned %r, not a report" % (r,))
    # ⚠ A RENAMED KEY USED TO READ AS EMPTY. r.get(k) is None for a key the
    # report no longer has, and None is falsy, so the check passed forever.
    missing = [k for k in need if k not in r]
    if missing:
        raise Fail("check_story's report lacks key(s) %s -- the report changed "
                   "and this step was not told: %s" % (missing, sorted(r)))
    broken = {k: r[k] for k in need if r[k]}
    if broken:
        raise Fail("\n".join("%s: %r" % kv for kv in broken.items()))
    return "no dangling, unresolved or missing references"


def judge_pyflakes(code, out, nfiles):
    if code != 0 or out.strip():
        raise Fail("pyflakes exited with code %s\n%s" % (code, out))
    if nfiles == 0:
        raise Fail("pyflakes was given no files")
    return "%d files clean" % nfiles


def judge_skill(code, out):
    clean(code, out, "sync_skill")
    return _last_line(out) or "in sync"


def judge_screens(code, out):
    clean(code, out, "screen_smoke")
    m = re.search(r"screen_smoke: (\d+) screen\(s\), (\d+) crashed, (\d+) slow", out)
    if not m:
        raise Fail("screen_smoke printed no summary:\n" + (out or "(no output)"))
    n, crashed, slow = (int(x) for x in m.groups())
    if crashed:
        raise Fail(out)
    if n == 0:
        raise Fail("screen_smoke found no menu screens to open -- a vacuous pass")
    return "%d menu screens open without a crash%s" % (
        n, " (%d slow, not a crash)" % slow if slow else "")


def judge_fight(code, out):
    clean(code, out, "fight_smoke")
    if "nothing to check" in out and "reaches its command menu" not in out:
        raise Skip(_last_line(out).replace("fight_smoke: ", ""))
    if "reaches its command menu" not in out:
        raise Fail("fight_smoke gave no pass evidence:\n" + (out or "(no output)"))
    return _last_line(out).replace("fight_smoke: ", "")


# ------------------------------------------------------------------ steps

def step_emit(project, docx):
    tool = os.path.join(project, "tools", "emit_all.py")
    if not os.path.exists(tool):
        raise Skip("no emit_all.py -- scenes are not generated here")
    return judge_emit(*run([PY, tool]))


def step_diff(project, docx):
    scenes = os.path.join(project, "game", "scenes")
    patterns = os.path.join(project, "game", "patterns.json")
    return judge_diff(*run([PY, os.path.join(HERE, "script_diff.py"), docx, scenes, patterns]))


def step_speaker(project, docx):
    return judge_speaker(*run([PY, os.path.join(HERE, "speaker_audit.py"), project]))


def step_font(project, docx):
    return judge_font(*run([PY, os.path.join(HERE, "font_audit.py"), project]))


def step_lint(project, docx):
    try:
        import renpy_sdk
    except Exception as e:                       # noqa: BLE001
        raise Skip("renpy_sdk not importable (%s)" % e.__class__.__name__)
    errors = os.path.join(project, "errors.txt")
    if os.path.exists(errors):
        os.remove(errors)
    code, out = run([renpy_sdk.launcher(), project, "lint"])
    err_text = None
    if os.path.exists(errors):
        err_text = io.open(errors, encoding="utf-8", errors="replace").read()
    log = os.path.join(project, "log.txt")
    log_text = io.open(log, encoding="utf-8", errors="replace").read() \
        if os.path.exists(log) else ""
    return judge_lint(code, out, err_text, log_text)


def step_saves(project, docx):
    """Old saves stay loadable (save_compat.py), then record today's state.

    A cleanup reused an old saved variable's name for a function, and every
    save made before it crashed the next fight (2026-10-11) -- with every
    other step green, because none of them loads a save. Recording only
    after a PASS keeps the manifest to states that were verified."""
    return judge_saves(*run([PY, os.path.join(HERE, "save_compat.py"), project, "--record"]))


def step_sprites(project, docx):
    return judge_sprites(*run([PY, os.path.join(HERE, "sprite_audit.py"), project]))


def step_slots(project, docx):
    return judge_slots(*run([PY, os.path.join(HERE, "slot_audit.py"), project]))


def step_spec(project, docx):
    return judge_spec(*run([PY, os.path.join(HERE, "spec_check.py"), docx, project]))


def _fight_calls(project):
    n = 0
    for f in glob.glob(os.path.join(project, "game", "scenes", "*.rpy")):
        n += len(re.findall(r"^\s*call\s+battle_\w+\s*$",
                            io.open(f, encoding="utf-8", errors="replace").read(), re.M))
    return n


def step_combat(project, docx):
    """Every specified fight is actually entered.

    Separate from step_spec on purpose: that one proves the NUMBERS in a
    combat fence match the engine, which a fight nobody calls satisfies
    perfectly. This one proves the fight happens.
    """
    code, out = run([PY, os.path.join(HERE, "combat_calls.py"), docx, project])
    return judge_combat(code, out, _fight_calls(project))


def step_sim(project, docx):
    """The project's own headless combat check, when it has one. No window."""
    tool = os.path.join(project, "tools", "combat_sim.py")
    if not os.path.exists(tool):
        raise Skip("no tools/combat_sim.py in this project")
    return judge_sim(*run([PY, tool], cwd=os.path.join(project, "tools")))


def step_static(project, docx):
    """Cheap file-level checks nothing else runs: image paths, show names,
    the sprite registry, duplicate defines, and file names in the docs."""
    return judge_static(*run([PY, os.path.join(HERE, "static_audit.py"), project]))


def step_overlap(project, docx):
    return judge_overlap(*run([PY, os.path.join(HERE, "sprite_overlap.py"),
                               os.path.join(project, "game"), "30"]))


## "barrier" (2026-11-09): a standing ward seen as scenery -- faded in, held
## behind the cast for a whole passage -- is set dressing, not a hit. A
## barrier raised IN a fight takes its sound from the fight's PLATE_SFX, which
## the second half of this step checks separately.
AMBIENT = ("snow", "fog", "rain", "ember", "dust", "petal", "aura", "mist", "glow",
           "barrier")


def is_ambient(plate):
    """True when a plate name is scenery. Matches a word that STARTS with an
    ambient stem (so `embers` counts, `fx slash` never does) rather than a
    stem anywhere in the name, which exempted any plate that merely contained
    one."""
    words = re.split(r"[\s_]+", plate)
    return any(w.startswith(a) for w in words for a in AMBIENT)


def step_sound(project, docx):
    bad = []
    files = sorted(glob.glob(os.path.join(project, "game", "scenes", "*.rpy")))
    if not files:
        raise Fail("no scene files under game/scenes -- nothing was checked")
    for f in files:
        L = io.open(f, encoding="utf-8").read().splitlines()
        for i, ln in enumerate(L):
            m = re.match(r"\s*show (fx .+?)(?: as .+)?$", ln)
            if not m or is_ambient(m.group(1)):
                continue
            # a commented-out `play sound` does not make a sound
            window = [x for x in L[max(0, i - 3):i] if not x.lstrip().startswith("#")]
            if "play sound" not in "\n".join(window):
                bad.append("%s:%d  %s" % (os.path.basename(f), i + 1, m.group(1)))
    if bad:
        raise Fail("impact plates with no sound in the three lines before:\n  "
                   + "\n  ".join(bad))

    # ⚠ AND EVERY PLATE IS DECLARED. Ren'Py defines an image for every file
    # under images/ by itself -- fx/slash_gray.png becomes `fx slash gray` --
    # so a plate nobody declared still resolves, check_story is satisfied,
    # lint is satisfied, and the fight draws it at its NATIVE size in the
    # middle of the frame: 1280x720 on a 1080p screen. Two plates ran that
    # way for a month (found 2026-09-11). The declarations
    # in presentation.rpy exist precisely to state the full-screen transform,
    # so a plate that is only automatic is a bug by definition.
    used = set()
    for f in glob.glob(os.path.join(project, "game", "scenes", "*.rpy")):
        for m in re.finditer(r"^\s*show (fx [a-z0-9 ]+?)(?: as .+)?\s*$",
                             io.open(f, encoding="utf-8").read(), re.M):
            used.add(m.group(1).strip())
    combat = os.path.join(project, "game", "combat.rpy")
    if os.path.exists(combat):
        src = io.open(combat, encoding="utf-8").read()
        used.update(re.findall(r'"(fx [a-z0-9 ]+)"', src))
        # ⚠ AND EVERY PLATE A FIGHT THROWS HAS A SOUND. The check above reads
        # SCENE files only, and a fight's sound comes from the PLATE_SFX
        # table instead -- so two attacks ran silent for weeks with this step
        # green (found 2026-09-26: an area attack and a palm strike). A move's
        # `plate="fx ..."` must be a key of that table.
        table = re.search(r"define PLATE_SFX = \{(.*?)\n\}", src, re.S)
        if table:
            keyed = set(re.findall(r'"(fx [a-z0-9 ]+)"\s*:', table.group(1)))
            thrown = set(re.findall(r'plate="(fx [a-z0-9 ]+)"', src))
            silent = sorted(thrown - keyed)
            if silent:
                raise Fail("fight plates with no sound in PLATE_SFX -- the "
                           "attack flashes in silence:\n  "
                           + "\n  ".join(silent))
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
        raise Skip("server not importable here (%s)" % e.__class__.__name__)
    return judge_story(server.check_story(slug or os.path.basename(os.path.normpath(project))))


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
        raise Skip("a dependency is missing (%s)" % e)
    scenes = os.path.join(project, "game", "scenes")
    files = [f for f in script_diff.scene_order(scenes) if os.path.exists(f)]
    if not files:
        raise Fail("no scene files to measure under game/scenes")
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
    files = (glob.glob(os.path.join(SERVER, "*.py")) + glob.glob(os.path.join(HERE, "*.py"))
             + glob.glob(os.path.join(project, "tools", "*.py")))
    code, out = run([PY, "-m", "pyflakes"] + files)
    return judge_pyflakes(code, out, len(files))


def step_skill(project, docx):
    tool = os.path.join(REPO, "servers", "anime-production-mcp", "sync_skill.py")
    if not os.path.exists(tool):
        raise Skip("no sync_skill.py in this repository")
    return judge_skill(*run([PY, tool, "--check"]))


def step_screens(project, docx):
    """Open every menu screen in a real run of the game (screen_smoke.py).

    Lint compiles screens but never resolves the names inside them, so an
    action naming a function that does not exist passes lint and crashes the
    game on display. That kept Preferences crashing for six days with every
    other step green (2026-09-20 to 26)."""
    return judge_screens(*run([PY, os.path.join(HERE, "screen_smoke.py"), project]))


def step_fight(project, docx):
    """Start the first fight in a real run of the game (fight_smoke.py).

    A refactor left a lambda in a store variable and every fight died at
    its checkpoint save with the whole sequence green (2026-10-11): lint
    never saves, the headless combat check never saves, and screen_smoke
    never fights. The author found it by playing. One fight only: each
    launch opens a window."""
    return judge_fight(*run([PY, os.path.join(HERE, "fight_smoke.py"), project]))


# Window-free steps first; the two that open the game last.
STEPS = [
    ("emit", step_emit), ("diff", step_diff), ("speaker", step_speaker),
    ("font", step_font), ("lint", step_lint), ("saves", step_saves),
    ("sprites", step_sprites), ("slots", step_slots), ("spec", step_spec),
    ("combat", step_combat), ("sim", step_sim), ("static", step_static),
    ("overlap", step_overlap), ("sound", step_sound), ("story", step_story),
    ("nvl", step_nvl), ("pyflakes", step_pyflakes), ("skill", step_skill),
    ("screens", step_screens), ("fight", step_fight),
]
STEP_NAMES = [n for n, _ in STEPS]


def leftover_smoke_files(project):
    """Temp files a killed smoke run left in game/ (they are deleted in a
    `finally`, which a hard kill skips). One of them defines a splashscreen
    that calls a fight, so the game would open straight into a battle."""
    game = os.path.join(project, "game")
    return sorted(glob.glob(os.path.join(game, "zz_*smoke*")))


def parse_args(argv):
    """Returns (project, docx, slug, skip, notes). Raises SystemExit on misuse."""
    usage = __doc__.strip().splitlines()[2].strip()
    pos, slug, skip, notes = [], None, set(), []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--slug="):
            slug = a.split("=", 1)[1]
        elif a == "--slug":
            i += 1
            if i >= len(argv):
                raise SystemExit("--slug needs a name\n" + usage)
            slug = argv[i]
        elif a.startswith("--skip-"):
            if a[7:] not in STEP_NAMES:
                raise SystemExit("unknown step in %r -- valid steps: %s"
                                 % (a, ", ".join(STEP_NAMES)))
            skip.add(a[7:])
        elif a.startswith("--"):
            raise SystemExit("unknown option %r\n%s" % (a, usage))
        else:
            pos.append(a)
        i += 1
    if len(pos) != 2:
        raise SystemExit(usage)
    if pos[0].lower().endswith(".docx") and not pos[1].lower().endswith(".docx"):
        pos.reverse()
        notes.append("the two arguments were in the other order (the first ended "
                     "in .docx); swapped them: project=%s docx=%s" % tuple(pos))
    return os.path.abspath(pos[0]), os.path.abspath(pos[1]), slug, skip, notes


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
    project, docx, slug, skip, notes = parse_args(argv)
    for n in notes:
        print("verify_all: " + n)
    if not os.path.isdir(project):
        print("verify_all: no such project folder: %s" % project)
        return 2
    if not os.path.isfile(docx):
        print("verify_all: no such manuscript: %s" % docx)
        return 2
    left = leftover_smoke_files(project)
    if left:
        print("verify_all: REFUSING TO START. A killed smoke run left temporary "
              "files in the game folder; one of them makes the game open "
              "straight into a fight. Delete exactly these, then rerun:\n")
        for p in left:
            print("  " + p)
        return 2
    t0 = time.time()
    skipped = []
    for name, fn in STEPS:
        if name in skip:
            print("  %-9s skip  (--skip-%s)" % (name, name))
            skipped.append(name)
            continue
        t = time.time()
        try:
            msg = fn(project, docx) if name != "story" else fn(project, docx, slug)
        except Skip as e:
            print("  %-9s skip  %s  (%.0fs)" % (name, e, time.time() - t))
            skipped.append(name)
            continue
        except Fail as e:
            print("  %-9s FAIL  (%.0fs)\n" % (name, time.time() - t))
            print(str(e).rstrip())
            print("\nverify_all: stopped at step %r after %.0fs. Fix that, then rerun."
                  % (name, time.time() - t0))
            return 1
        except Exception:                        # noqa: BLE001 -- a checker crash is a FAIL
            print("  %-9s FAIL  (%.0fs)\n" % (name, time.time() - t))
            print("the step itself crashed:\n" + traceback.format_exc().rstrip())
            print("\nverify_all: stopped at step %r after %.0fs. Fix that, then rerun."
                  % (name, time.time() - t0))
            return 1
        print("  %-9s ok    %s  (%.0fs)" % (name, msg, time.time() - t))
    ran = len(STEPS) - len(skipped)
    print("\nverify_all: %d of %d steps ran and passed in %.0fs.%s"
          % (ran, len(STEPS), time.time() - t0,
             " Skipped (NOT verified): %s." % ", ".join(skipped) if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
