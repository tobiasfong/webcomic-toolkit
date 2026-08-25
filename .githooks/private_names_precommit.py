#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pre-commit gate: refuse a commit that ADDS a private name to this public repo.

Tracked deliberately, so a fresh clone is protected the moment `core.hooksPath`
is set -- see .githooks/README.md. The earlier version of this lived in
~/.claude/hooks, which meant the guard existed only on one machine and vanished
with a reclone.

Why a commit-time gate exists at all, when a PostToolUse hook already checks
writes: that hook only sees Write/Edit. Prose written by script, sed or heredoc
walks straight past it. That is not hypothetical -- a 63-line block went into
CLAUDE.md through a Python script and the write-time hook never saw it. This
runs where nothing can route around it.

Two deliberate behaviors:

  * BLOCKS (exit 1) rather than reporting. A PostToolUse hook advises a model
    that can still fix the line; at commit time, reporting and shipping are the
    same thing.
  * Reads ADDED LINES ONLY. The tracked tree already carries a project name or
    two from before this existed, and a whole-file check would refuse every
    commit until they were scrubbed -- which is how a hook gets disabled. What
    matters is not adding more.

  * FAILS OPEN on its own bugs. A guard that fails closed on an internal error
    trains you to reach for --no-verify by reflex, and then it protects nothing.

Escape hatch: `git commit --no-verify`, for the near-never case where a name
genuinely must be committed. Say so out loud rather than quietly.

NOTE ON THE NAME LIST. It is read from the character bibles at run time, so a
character registered today is covered today and there is no list to maintain --
and no private name is stored in this public file. Where ~/.claude/hooks/
private_names.py is present (the authoring machine) its loader is imported, so
the write-time hook and this one share ONE definition of private. On a fresh
clone that file will not exist, so an equivalent loader is embedded below. Keep
the two in step if the rules for what counts as a name ever change.
"""
import glob
import io
import json
import os
import re
import subprocess
import sys

CHECKED = {'.md', '.markdown', '.txt', '.py', '.js', '.mjs', '.ts', '.tsx',
           '.json', '.yml', '.yaml', '.html', '.rpy', '.toml', '.cfg', '.ini'}
SKIP_DIRS = ('node_modules', '.git', 'dist', 'build', 'vendor')
MAX_HITS = 40


def repo_root():
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return r.stdout.decode("utf-8", "replace").strip() or "."
    except Exception:
        return "."


def bible_glob():
    """Bibles located RELATIVE TO THE REPO, not an absolute home path.

    The write-time hook hardcodes one machine's path. That is fine for a
    personal hook and useless in a tracked one, so this derives the location
    from the repo it is guarding.
    """
    return os.environ.get("WEBCOMIC_BIBLE_GLOB") or os.path.join(
        repo_root(), "servers", "character-panel-mcp", "characters", "*",
        "characters.json")


def _embedded_load_names():
    """Fallback loader -- see the module docstring.

    Only DISTINCTIVE tokens count. A bare family name is a real word or a common
    substring, and a hook that cries wolf gets ignored, which is worse than no
    hook. A lone given name qualifies only if hyphenated and long enough to be
    unmistakable.
    """
    full, part, ids = set(), set(), set()
    for f in glob.glob(bible_glob()):
        # Throwaway scratch projects are not private, and naming one HERE would
        # publish the very kind of slug this hook exists to catch. Match them by
        # shape instead of by name -- this file must stay free of real slugs.
        slug = os.path.basename(os.path.dirname(f))
        scratch = slug in ("test", "demo") or slug.endswith(("_test", "_demo"))
        if len(slug) >= 3 and not scratch:
            ids.add(slug)
        try:
            data = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for cid, entry in data.items():
            if isinstance(cid, str) and "_" in cid and len(cid) >= 8:
                ids.add(cid)
            name = (entry or {}).get("name") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name.strip():
                continue
            name = name.strip()
            if len(name.split()) >= 2:
                full.add(name)
            for tok in name.split():
                if "-" in tok and len(tok) >= 5:
                    part.add(tok)
    return full, part, ids


def _embedded_build_rx(full, part, ids):
    alts = [re.escape(s) for s in sorted(full | part | ids, key=len, reverse=True)]
    if not alts:
        return None
    # A word boundary is NOT enough for ids: underscore IS a word character, so
    # it never fires between "met_" and an id. Require a non-word, non-hyphen
    # neighbor on each side -- letters and digits only, NOT underscore, since
    # the underscore is precisely what an id hides behind in a compound.
    return re.compile('(?<![0-9A-Za-z])(?:%s)(?![0-9A-Za-z])' % '|'.join(alts),
                      re.IGNORECASE)


def get_checker():
    """Prefer the shared loader; fall back to the embedded one.

    private_names.py calls main() at module scope and that main() blocks on
    json.load(sys.stdin), so importing it naively HANGS FOREVER -- which in a
    pre-commit hook means every commit hangs, the worst failure available to a
    guard meant to be unobtrusive. Feeding it an empty stdin makes that load
    raise, which its own `except Exception: return` swallows, so it returns at
    once with no side effects.
    """
    shared = os.path.expanduser(os.path.join("~", ".claude", "hooks"))
    if os.path.isfile(os.path.join(shared, "private_names.py")):
        saved_in, saved_path = sys.stdin, list(sys.path)
        sys.stdin = io.StringIO("")
        sys.path.insert(0, shared)
        try:
            import private_names as pn
            return pn.load_names, pn.build_rx
        except Exception:
            pass
        finally:
            sys.stdin, sys.path = saved_in, saved_path
    return _embedded_load_names, _embedded_build_rx


def staged_added_lines():
    """[(path, lineno, text)] for every line this commit ADDS.

    -U0 keeps the diff to changed lines alone, so a context line carrying a
    legacy name never trips the check.
    """
    try:
        r = subprocess.run(["git", "diff", "--cached", "--no-color", "-U0",
                            "--diff-filter=ACMR"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    out, path, lineno = [], None, 0
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            if path:
                out.append((path, lineno, line[1:]))
            lineno += 1
    return out


def main():
    try:
        load_names, build_rx = get_checker()
        rx = build_rx(*load_names())
    except Exception as e:
        sys.stderr.write("private-names pre-commit: checker unavailable (%s); "
                         "allowing commit.\n" % e)
        return 0
    if rx is None:
        return 0

    hits, seen = [], set()
    for path, lineno, text in staged_added_lines():
        if os.path.splitext(path)[1].lower() not in CHECKED:
            continue
        if any(("/%s/" % s) in ("/%s" % path) for s in SKIP_DIRS):
            continue
        if path.replace("\\", "/").startswith(".githooks/"):
            continue                      # this file describes the check itself
        m = rx.search(text)
        if m:
            seen.add(m.group(0))
            hits.append("  %s:%d  %s   |  %s"
                        % (path, lineno, m.group(0), text.strip()[:90]))
        if len(hits) >= MAX_HITS:
            break
    if not hits:
        return 0

    sys.stderr.write(
        "\nCOMMIT BLOCKED -- private names in added lines.\n\n"
        "This repo is public. The bibles are gitignored, but that protects the\n"
        "data files, not a name typed into tracked prose.\n\n"
        "Found: %s\n%s\n\n"
        "Rewrite each with a neutral descriptor (\"one character\", \"another\n"
        "character's costume\", \"the martial-arts test scene\"). The rule\n"
        "almost always reads fine without the name.\n\n"
        "If a name genuinely must be committed: git commit --no-verify\n\n"
        % (", ".join(sorted(seen)), "\n".join(hits)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
