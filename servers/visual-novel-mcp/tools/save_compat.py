# -*- coding: utf-8 -*-
"""Check that the game can still load the saves its players already have.

    python save_compat.py <project-dir>            # check; exit 1 on a problem
    python save_compat.py <project-dir> --record   # check, then add today's
                                                   # state to the manifest

WHY
---
A Ren'Py save is a pickle of the store: every `default` variable, and every
object those variables hold. Loading one puts those values back BY NAME and
rebuilds those objects BY CLASS NAME, with only the attributes they had when
they were saved. So code that a fresh game runs perfectly can still break
every existing save, and no other check here can see it -- lint never loads
a save, and a smoke test starts a new game. On 2026-10-11 a cleanup reused
the name of an old `default` for a function; loading any older save put the
saved number over the function, and the next fight died with "'int' object
is not callable". The author found it in play.

WHAT IT CHECKS, against a manifest of what saves have ever been able to hold
(<project>/save_manifest.json, cumulative -- a name is never dropped from it,
because a save made the day it existed can be loaded any day after):

  1. A SAVED NAME REUSED. A name that was ever a `default` is now a function,
     a class, a `define`, or a module-level name in an init-python block.
     Loading an old save puts the old value back over it.
  2. A CLASS GONE. A class whose objects saves have held no longer exists:
     those saves cannot be loaded at all.
  3. A NEW ATTRIBUTE WITH NO FALLBACK. A class sets an attribute in __init__
     that it did not set when an older save was made, and the class body has
     no default for it: an object restored from that save simply lacks it,
     and the first read is an AttributeError. The fix is a class-level
     default (`mark = 0.0` in the class body), which old objects fall back on.

A REMOVED `default` is not a problem and is not reported: old saves keep the
stale value under a name nothing reads.

NOT COVERED, said so it is not mistaken for a guarantee: a `default` whose
VALUE changes type (an int that becomes an object), and saves whose
position is a label that no longer exists (generated scenes change every
emit; Ren'Py rolls such a load back to the nearest statement it can find).

Generic: names nothing in any project; the manifest lives in the project.
"""
import ast
import glob
import io
import json
import os
import re
import sys
import textwrap

MANIFEST = "save_manifest.json"
RE_DEFAULT = re.compile(r"^default\s+([A-Za-z_]\w*)\s*=", re.M)
RE_DEFINE = re.compile(r"^define\s+([A-Za-z_]\w*)\s*=", re.M)
RE_INIT_PY = re.compile(r"^(?:init(?:\s+-?\d+)?\s+python|python\s+early)\b[^:\n]*:\s*$")


def python_blocks(src):
    """The code of every init-python block in one .rpy file, dedented."""
    lines = src.split("\n")
    out, i = [], 0
    while i < len(lines):
        if RE_INIT_PY.match(lines[i]):
            body = []
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in " \t#"):
                body.append("" if lines[i][:1] == "#" else lines[i])
                i += 1
            out.append(textwrap.dedent("\n".join(body)))
            continue
        i += 1
    return out


def scan(game_dir):
    """(defaults, other store names, {class: {"init": attrs, "body": names}})"""
    defaults, others, classes, problems = set(), {}, {}, []
    for f in sorted(glob.glob(os.path.join(game_dir, "**", "*.rpy"), recursive=True)):
        src = io.open(f, encoding="utf-8", errors="replace").read()
        rel = os.path.relpath(f, game_dir).replace("\\", "/")
        defaults.update(RE_DEFAULT.findall(src))
        for n in RE_DEFINE.findall(src):
            others.setdefault(n, "define (%s)" % rel)
        for code in python_blocks(src):
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                problems.append("%s: an init-python block did not parse (%s)" % (rel, e.msg))
                continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    others.setdefault(node.name, "function (%s)" % rel)
                elif isinstance(node, ast.ClassDef):
                    others.setdefault(node.name, "class (%s)" % rel)
                    body, init = set(), set()
                    for b in node.body:
                        if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            body.add(b.name)
                            if b.name == "__init__":
                                for sub in ast.walk(b):
                                    if (isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Store)
                                            and isinstance(sub.value, ast.Name) and sub.value.id == "self"):
                                        init.add(sub.attr)
                        elif isinstance(b, ast.Assign):
                            body.update(t.id for t in b.targets if isinstance(t, ast.Name))
                        elif isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name):
                            body.add(b.target.id)
                    classes[node.name] = {"init": sorted(init), "body": sorted(body)}
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            others.setdefault(t.id, "module-level name (%s)" % rel)
    return defaults, others, classes, problems


def load_manifest(project):
    p = os.path.join(project, MANIFEST)
    if not os.path.exists(p):
        return None
    return json.load(io.open(p, encoding="utf-8"))


def check(project):
    game = os.path.join(project, "game")
    defaults, others, classes, problems = scan(game)
    man = load_manifest(project)
    if man is None:
        problems.append("no %s yet: run with --record once to start one "
                        "(seed it from the game's history if saves predate it)" % MANIFEST)
        return problems, (defaults, others, classes)
    for name in sorted(man.get("saved", [])):
        if name in others and name not in defaults:
            problems.append("SAVED NAME REUSED: `%s` was a saved variable and is now a %s. "
                            "Loading an older save puts the old value back over it. "
                            "Rename the new thing." % (name, others[name]))
    for cname, past in sorted(man.get("classes", {}).items()):
        if cname not in classes:
            problems.append("CLASS GONE: `%s` is no longer defined, and saves have held its "
                            "objects -- they cannot be loaded. Keep the class (or an alias)." % cname)
            continue
        now = classes[cname]
        had = set(past.get("init", []))
        fallback = set(now["body"])
        for attr in now["init"]:
            if attr not in had and attr not in fallback:
                problems.append("NO FALLBACK: `%s.%s` is set in __init__ but older saved objects "
                                "were made without it, and the class body gives no default. Add "
                                "`%s = <default>` to the class body." % (cname, attr, attr))
    return problems, (defaults, others, classes)


def record(project, state):
    defaults, _others, classes = state
    man = load_manifest(project) or {"saved": [], "classes": {}}
    man["saved"] = sorted(set(man["saved"]) | defaults)
    for cname, now in classes.items():
        past = man["classes"].setdefault(cname, {"init": []})
        past["init"] = sorted(set(past.get("init", [])) | set(now["init"]))
    man["_comment"] = ("Cumulative: every name a save has been able to hold, and every "
                       "attribute each class's saved objects have been made with. Written "
                       "by save_compat.py --record; never remove entries.")
    io.open(os.path.join(project, MANIFEST), "w", encoding="utf-8", newline="\n").write(
        json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    project = os.path.abspath(argv[0])
    problems, state = check(project)
    for p in problems:
        print("  " + p)
    if problems:
        print("save_compat: %d problem(s) -- an existing save may fail to load" % len(problems))
        return 1
    if "--record" in argv:
        record(project, state)
    man = load_manifest(project) or {}
    print("save_compat: old saves stay loadable (%d saved names, %d classes checked)"
          % (len(man.get("saved", [])), len(man.get("classes", {}))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
