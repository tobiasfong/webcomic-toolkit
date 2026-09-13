# -*- coding: utf-8 -*-
r"""Cheap static checks over a project that nothing else in the sequence runs.

    python static_audit.py <project-dir> [--repo <repo-root>]

WHY THIS EXISTS
---------------
Written 2026-09-14 during a full audit, from the checks that were being run
BY HAND that day and had been run by hand on every previous audit too. A
check that lives in a session transcript is a check that gets skipped, run
with a typo, or -- the case that prompted this -- written with a regex that
the shell mangles and then trusted anyway. Everything here is a few lines of
pure file inspection: no engine, no GPU, no document. It runs in a second.

WHAT IT CHECKS, and what each one has caught or would have
----------------------------------------------------------
  images     every literal "images/..." or "gui/..." path in the .rpy files
             resolves on disk. Ren'Py only complains when the image is DRAWN,
             so a broken path in a screen nobody opened in testing ships.
             Two shapes are exempt because they are the engine's own:
             `[prefix_]` substitution, and a Frame([a, b]) list, where the
             engine falls through to `b` when `a` is absent.
  names      every `show X` / `scene X` name in the scenes resolves to an
             `image`, a `layeredimage`, or a file under images/. An
             undeclared file-derived name is legal, which is exactly why a
             typo in one is silent.
  registry   sprites.json's tags, sprites_generated.rpy's layeredimages, the
             sprite folders on disk, and the speakers in characters.rpy all
             agree with each other. A registered tag with no generated
             image, a folder nobody references, a speaker with no sprite and
             no audit config -- each is a class of bug that has happened.
  defines    no name is `define`d or `default`ed twice. gui.rpy runs at init
             offset -2 and a stock-template define at 0 silently WINS over
             the deliberate value; lint calls it "already defined", which
             reads as ignorable and is not.
  plates     every `image bg X` / `image cg X` whose file is not screen-sized
             goes through a Transform that fits it. A bare path renders at
             native size in the middle of the frame -- the two-thirds-screen
             failure -- while the file exists, the name resolves, and every
             other checker stays green.
  docs       every `file.ext` named in backticks in the project's HANDOVER.md
             and ROUTES.md and the repo's CLAUDE.md exists somewhere it could
             plausibly mean. A note naming a file that is gone is how the
             sword art was handed back to the author as unfinished three
             days after he finished it.

WHAT IT DOES NOT CHECK, and where that lives instead
----------------------------------------------------
  labels and jumps       check_story (the MCP), and script_diff's scene order
  plates a scene names   verify_all's `sound` step
  sprites on stage       sprite_audit.py, slot_audit.py, sprite_overlap.py
  the docx vs the game   script_diff.py, spec_check.py, combat_calls.py

PUBLIC AND PROJECT-AGNOSTIC. Nothing here names a character or a project;
the docs list is derived from the project directory.
"""
import glob
import io
import os
import re
import sys

IMG = re.compile(r'"((?:images|gui)/[^"]+\.(?:png|jpg|jpeg|webp))"')
FRAME_LIST = re.compile(r'Frame\(\s*\[\s*"([^"]+)"\s*,\s*"([^"]+)"')
SHOWN = re.compile(r'^\s*(?:show|scene)\s+([a-z][a-z0-9_ ]*?)'
                   r'(?:\s+(?:at|with|as|behind|onlayer|zorder)\b|\s*$)')
DECL = re.compile(r'^\s*(?:image|layeredimage)\s+([a-z][a-z0-9_ ]*?)\s*[:=]', re.M)
DEFN = re.compile(r'^\s*(define|default)\s+([A-Za-z_][A-Za-z0-9_.]*)\s*=', re.M)
GONE_WORDS = ("deleted", "removed", "renamed", "folded", "merged into",
              "superseded", "since gone", "no longer exists")
DOCREF = re.compile(r'`([A-Za-z0-9_./\-]+\.(?:py|rpy|json|md|png|txt|ogg|wav))`')


def _read(p):
    return io.open(p, encoding="utf-8").read()


def rpy_files(project):
    return sorted(glob.glob(os.path.join(project, "game", "**", "*.rpy"),
                            recursive=True))


def check_images(project):
    bad = []
    fallbacks = set()
    for f in rpy_files(project):
        t = _read(f)
        for m in FRAME_LIST.finditer(t):
            fallbacks.add(m.group(1))      # the engine falls through to group(2)
        for n, ln in enumerate(t.splitlines(), 1):
            for m in IMG.finditer(ln):
                p = m.group(1)
                if p in fallbacks:
                    continue
                # `[prefix_]` is the engine's own substitution: idle_, hover_,
                # selected_idle_, selected_hover_, insensitive_. A path using
                # it exists if its idle_ form does -- and four of the twelve
                # broken small-screen lines found on 2026-09-14 wore it, so
                # exempting the whole shape would have hidden a third of them.
                # The engine's prefix search ends with the EMPTY prefix, so a
                # `[prefix_]` path is satisfied by either its idle_ form or
                # its bare form -- check_[prefix_]foreground.png resolves to
                # check_foreground.png. Mirror that, or the stock check and
                # radio buttons report as broken while working perfectly.
                if "[prefix_]" in p:
                    forms = [p.replace("[prefix_]", "idle_"), p.replace("[prefix_]", "")]
                    if any(os.path.exists(os.path.join(project, "game", q)) for q in forms):
                        continue
                    p = forms[1]
                if not os.path.exists(os.path.join(project, "game", p)):
                    bad.append("%s:%d  %s" % (os.path.relpath(f, project), n, p))
    return bad


def check_names(project):
    declared = set()
    for f in rpy_files(project):
        declared |= {m.group(1).strip() for m in DECL.finditer(_read(f))}
    root = os.path.join(project, "game", "images")
    for d, _, files in os.walk(root):
        for fn in files:
            rel = os.path.relpath(os.path.join(d, fn), root).replace("\\", "/")
            stem = os.path.splitext(rel)[0]
            declared.add(stem.replace("/", " ").replace("_", " "))
            declared.add(os.path.basename(stem).replace("_", " "))
    bad = []
    for f in sorted(glob.glob(os.path.join(project, "game", "scenes", "*.rpy"))):
        for n, ln in enumerate(_read(f).splitlines(), 1):
            m = SHOWN.match(ln)
            if not m:
                continue
            name = m.group(1).strip()
            if name == "black" or name.startswith("screen ") or name in declared:
                continue
            # a layeredimage tag may be followed by attributes: "jeon smile"
            if name.split()[0] in declared:
                continue
            bad.append("%s:%d  %s" % (os.path.basename(f), n, name))
    return bad


def check_registry(project):
    import json
    bad = []
    sj_path = os.path.join(project, "sprites.json")
    gen_path = os.path.join(project, "game", "sprites_generated.rpy")
    if not (os.path.exists(sj_path) and os.path.exists(gen_path)):
        return ["sprites.json or sprites_generated.rpy missing -- nothing to compare"]
    sj = json.load(io.open(sj_path, encoding="utf-8")).get("characters", {})
    tags_json = {v.get("tag") for v in sj.values() if v.get("tag")}
    gen = _read(gen_path)
    tags_gen = set(re.findall(r"^layeredimage (\w+):", gen, re.M))
    for t in sorted(tags_json - tags_gen):
        bad.append("registered tag %r has no layeredimage -- run emit_sprites" % t)
    for t in sorted(tags_gen - tags_json):
        bad.append("layeredimage %r is not in sprites.json" % t)
    for k, v in sj.items():
        if not v.get("height_cm"):
            bad.append("sprites.json entry %r has no height_cm (the scaler reads it)" % k)
    for p in re.findall(r'"(images/sprites/[^"]+)"', gen):
        if not os.path.exists(os.path.join(project, "game", p)):
            bad.append("sprites_generated.rpy names a missing file: %s" % p)
    sdir = os.path.join(project, "game", "images", "sprites")
    if os.path.isdir(sdir):
        on_disk = {d for d in os.listdir(sdir) if os.path.isdir(os.path.join(sdir, d))}
        used = set(re.findall(r'images/sprites/([^/"]+)/', gen))
        for d in sorted(on_disk - used):
            bad.append("sprite folder on disk referenced by nothing: %s" % d)
    chars_path = os.path.join(project, "game", "characters.rpy")
    cfg_path = os.path.join(project, "sprite_audit.json")
    if os.path.exists(chars_path) and os.path.exists(cfg_path):
        chars = re.findall(r"^define (\w+) = Character\(", _read(chars_path), re.M)
        cfg = json.load(io.open(cfg_path, encoding="utf-8"))
        covered = tags_gen | set(cfg.get("overrides", {})) | set(cfg.get("not_on_stage", []))
        for c in chars:
            if c not in covered:
                bad.append("speaker %r has no sprite tag and no sprite_audit.json entry" % c)
    return bad


PLATE = re.compile(r'^\s*image\s+((?:bg|cg)\s+[a-z0-9_ ]+?)\s*=\s*(.+)$', re.M)
BARE = re.compile(r'^"(images/[^"]+)"\s*$')


def check_plates(project):
    """A plate that is not screen-sized must be declared through a Transform
    that fits it. A bare path renders at its native size in the middle of
    the frame -- the two-thirds-screen failure -- and every other checker
    stays green, because the file exists and the name resolves."""
    try:
        from PIL import Image
    except ImportError:
        return []
    gui = os.path.join(project, "game", "gui.rpy")
    screen = (1920, 1080)
    if os.path.exists(gui):
        m = re.search(r"gui\.init\(\s*(\d+)\s*,\s*(\d+)", _read(gui))
        if m:
            screen = (int(m.group(1)), int(m.group(2)))
    bad = []
    for f in rpy_files(project):
        for m in PLATE.finditer(_read(f)):
            name, rhs = m.group(1).strip(), m.group(2).strip()
            b = BARE.match(rhs)
            if not b:
                continue                       # a Transform, Solid, etc.
            path = os.path.join(project, "game", b.group(1))
            if not os.path.exists(path):
                continue                       # check_images reports that
            try:
                size = Image.open(path).size
            except Exception:
                continue
            if size != screen:
                bad.append("%s is %dx%d but declared as a bare path; wrap it in "
                           "Transform(..., fit=\"cover\") or it renders undersized"
                           % (name, size[0], size[1]))
    return bad


def check_defines(project):
    seen = {}
    for f in rpy_files(project):
        for m in DEFN.finditer(_read(f)):
            seen.setdefault(m.group(2), []).append(
                "%s (%s)" % (os.path.relpath(f, project), m.group(1)))
    return ["%s defined %d times: %s" % (k, len(v), ", ".join(v))
            for k, v in sorted(seen.items()) if len(v) > 1]


def check_docs(project, repo):
    docs = [os.path.join(project, "HANDOVER.md"), os.path.join(project, "ROUTES.md")]
    if repo:
        docs.append(os.path.join(repo, "CLAUDE.md"))
    roots = [project, os.path.join(project, "game"), os.path.join(project, "tools"),
             os.path.join(project, "game", "scenes"), os.path.join(project, "game", "images", "fx")]
    if repo:
        roots += [repo] + glob.glob(os.path.join(repo, "servers", "*")) \
                 + glob.glob(os.path.join(repo, "servers", "*", "tools")) \
                 + glob.glob(os.path.join(repo, "servers", "*", "assets", "tools"))
    bad = []
    for d in docs:
        if not os.path.exists(d):
            continue
        text = _read(d)
        lines = text.splitlines()
        for m in DOCREF.finditer(text):
            p = m.group(1)
            # A file REPORTED AS GONE is not a claim that it exists. Notes
            # say "X.py deleted", "folded into", "renamed to", "superseded
            # by" -- and forcing those to drop their backticks was tried for
            # a day and bit the next note written. The sentence usually wraps,
            # so one line either side is read as well as the line itself.
            ln = text.count(chr(10), 0, m.start())
            near = " ".join(lines[max(0, ln - 1):ln + 2]).lower()
            if any(w in near for w in GONE_WORDS):
                continue
            if "<" in p or "*" in p or p.startswith("path/"):
                continue
            # files inside another program, named so a reader can find them
            if p.startswith(("comfy/", "comfy_extras/", "ComfyUI/")):
                continue
            # engine-owned or transient files the docs legitimately name
            if os.path.basename(p) in ("errors.txt", "traceback.txt", "log.txt"):
                continue
            if any(os.path.exists(os.path.join(r, p)) for r in roots) \
                    or any(os.path.exists(os.path.join(r, os.path.basename(p))) for r in roots):
                continue
            bad.append("%s names %s, which exists nowhere it could mean"
                       % (os.path.basename(d), p))
    return sorted(set(bad))


def main(argv):
    if not argv:
        sys.exit("usage: python static_audit.py <project-dir> [--repo <repo-root>]")
    project = argv[0]
    repo = None
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    else:
        # vn/<project> sits two levels under the repo root by convention
        cand = os.path.abspath(os.path.join(project, "..", ".."))
        if os.path.exists(os.path.join(cand, "CLAUDE.md")):
            repo = cand

    total = 0
    for name, fn in (("images", lambda: check_images(project)),
                     ("names", lambda: check_names(project)),
                     ("registry", lambda: check_registry(project)),
                     ("defines", lambda: check_defines(project)),
                     ("plates", lambda: check_plates(project)),
                     ("docs", lambda: check_docs(project, repo))):
        bad = fn()
        total += len(bad)
        print("%-9s %s" % (name, "ok" if not bad else "%d finding(s)" % len(bad)))
        for b in bad:
            print("           %s" % b)
    print()
    print("static_audit: %d finding(s)." % total)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
