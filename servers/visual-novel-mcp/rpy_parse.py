"""
rpy_parse.py — a line-based scanner for Ren'Py scripts.

Deliberately NOT a full Ren'Py parser: it extracts exactly what the story
checks need — labels, jumps/calls, menu choices, flag writes and reads,
image/audio references, and definitions. Ren'Py's own `lint` remains the
authority on syntax; this module exists so the branch graph can be DERIVED
from the scripts instead of stored in a second place that would drift.

Known simplifications, all conservative (they under-claim, never invent):
- `jump expression` / `call expression` targets are recorded as dynamic and
  excluded from dangling-target checks.
- Flag reads are identifier extraction from `if`/`elif`/`while`/`menu`-choice
  conditions and `[name]` text interpolations; attribute chains (a.b) are
  reduced to their root name.
- A label "falls through" to the next label unless its body's last
  top-level statement is `return` or an unconditional `jump`.
"""

import os
import re
import keyword
from dataclasses import dataclass, field

_PY_KEYWORDS = set(keyword.kwlist) | {
    "True", "False", "None", "renpy", "persistent", "store", "config",
    "len", "int", "str", "float", "abs", "min", "max", "range", "_return",
}

_LABEL_RE = re.compile(r"^(\s*)label\s+([A-Za-z_.][\w.]*)\s*(?:\([^)]*\))?\s*:")
_JUMP_RE = re.compile(r"^\s*jump\s+(expression\s+)?([\w.]+)")
_CALL_RE = re.compile(r"^\s*call\s+(expression\s+)?([\w.]+)")
_MENU_RE = re.compile(r"^(\s*)menu(?:\s+[\w.]+)?\s*:")
_CHOICE_RE = re.compile(r'^(\s*)"((?:[^"\\]|\\.)*)"\s*(?:if\s+(.+?))?\s*:\s*$')
_SET_RE = re.compile(r"^\s*\$\s*([A-Za-z_]\w*)\s*(?:=|\+=|-=)\s*")
_DEFAULT_RE = re.compile(r"^\s*default\s+([A-Za-z_][\w.]*)\s*=")
_DEFINE_RE = re.compile(r"^\s*define\s+([A-Za-z_][\w.]*)\s*=")
_COND_RE = re.compile(r"^\s*(?:if|elif|while)\s+(.+?)\s*:\s*$")
_SHOW_RE = re.compile(r"^\s*show\s+(?!screen\b|expression\b)([a-zA-Z0-9_ ]+)")
_SCENE_RE = re.compile(r"^\s*scene\s+(?!black\b|white\b)([a-zA-Z0-9_ ]+)")
_AUDIO_RE = re.compile(r'^\s*(?:play|queue)\s+(music|sound|audio|voice)\s+"([^"]+)"')
_VOICE_RE = re.compile(r'^\s*voice\s+"([^"]+)"')
_IMAGE_RE = re.compile(r"^\s*image\s+([a-zA-Z0-9_ ]+?)\s*[=:]")
_LAYERED_RE = re.compile(r"^\s*layeredimage\s+([A-Za-z_]\w*)")
_INTERP_RE = re.compile(r"\[([A-Za-z_]\w*)[\]!.:]")
_IDENT_RE = re.compile(r"\b([A-Za-z_]\w*)\b")
_CLAUSE_WORDS = {"at", "with", "behind", "as", "onlayer", "zorder"}


@dataclass
class FileScan:
    path: str
    labels: list = field(default_factory=list)        # {name, line}
    jumps: list = field(default_factory=list)         # {target, line, from_label, kind, dynamic}
    menus: list = field(default_factory=list)         # {line, from_label, choices: [{text, line, condition}]}
    flags_set: list = field(default_factory=list)     # {name, line, from_label, via}
    flags_read: list = field(default_factory=list)    # {name, line, from_label}
    defines: list = field(default_factory=list)       # root names of `define`d values
    images: list = field(default_factory=list)        # {name: tuple of words, line}
    shows: list = field(default_factory=list)         # {words: tuple, line, from_label, stmt}
    audio: list = field(default_factory=list)         # {channel, file, line, from_label}
    fallthrough: list = field(default_factory=list)   # label names that may fall through


def _read_names(condition: str) -> set[str]:
    names = set()
    # strip string literals so words inside quotes are not read as flags
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', "", condition)
    for m in _IDENT_RE.finditer(stripped):
        name = m.group(1)
        # only the root of an attribute chain is a store name
        if stripped[m.start() - 1: m.start()] == ".":
            continue
        if name not in _PY_KEYWORDS:
            names.add(name)
    return names


def _display_words(raw: str) -> tuple[str, ...]:
    words = []
    for w in raw.strip().split():
        if w in _CLAUSE_WORDS:
            break
        words.append(w)
    return tuple(words)


def scan_file(path: str) -> FileScan:
    scan = FileScan(path=path)
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    current_label = None
    current_indent = 0
    body_indent = None
    # last significant statement at the top level of the current label's body,
    # used for the fallthrough heuristic
    last_stmt = None
    menu_stack = []  # (indent, menu_record)

    def close_label():
        if current_label is not None and last_stmt not in ("return", "jump"):
            scan.fallthrough.append(current_label)

    for lineno, rawline in enumerate(lines, 1):
        line = rawline.rstrip("\n")
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        if not code.strip():
            continue
        indent = len(code) - len(code.lstrip())

        while menu_stack and indent <= menu_stack[-1][0]:
            menu_stack.pop()

        m = _LABEL_RE.match(code)
        if m:
            close_label()
            current_label = m.group(2)
            current_indent = indent
            body_indent = None
            last_stmt = None
            scan.labels.append({"name": current_label, "line": lineno})
            continue

        if current_label is not None and indent <= current_indent:
            # dedented out of the label body (screens, defines at top level…)
            close_label()
            current_label = None
            body_indent = None
            last_stmt = None

        if current_label is not None and body_indent is None:
            body_indent = indent
        body_top = current_label is not None and indent == body_indent

        m = _JUMP_RE.match(code)
        if m:
            scan.jumps.append({
                "target": None if m.group(1) else m.group(2),
                "line": lineno, "from_label": current_label,
                "kind": "jump", "dynamic": bool(m.group(1)),
            })
            if body_top:
                last_stmt = "jump"
            continue

        m = _CALL_RE.match(code)
        if m:
            scan.jumps.append({
                "target": None if m.group(1) else m.group(2),
                "line": lineno, "from_label": current_label,
                "kind": "call", "dynamic": bool(m.group(1)),
            })
            if body_top:
                last_stmt = "call"
            continue

        if code.strip() == "return" or code.strip().startswith("return "):
            if body_top:
                last_stmt = "return"
            continue

        m = _MENU_RE.match(code)
        if m:
            record = {"line": lineno, "from_label": current_label, "choices": []}
            scan.menus.append(record)
            menu_stack.append((indent, record))
            if body_top:
                last_stmt = "menu"
            continue

        if menu_stack:
            m = _CHOICE_RE.match(code)
            if m and indent > menu_stack[-1][0]:
                menu_stack[-1][1]["choices"].append(
                    {"text": m.group(2), "line": lineno, "condition": m.group(3)}
                )
                if m.group(3):
                    for name in _read_names(m.group(3)):
                        scan.flags_read.append(
                            {"name": name, "line": lineno, "from_label": current_label}
                        )
                continue

        m = _SET_RE.match(code)
        if m:
            scan.flags_set.append({
                "name": m.group(1), "line": lineno,
                "from_label": current_label, "via": "$",
            })
            if body_top:
                last_stmt = "set"
            continue

        m = _DEFAULT_RE.match(code)
        if m:
            scan.flags_set.append({
                "name": m.group(1).split(".")[0], "line": lineno,
                "from_label": current_label, "via": "default",
            })
            continue

        m = _DEFINE_RE.match(code)
        if m:
            scan.defines.append(m.group(1).split(".")[0])
            continue

        m = _COND_RE.match(code)
        if m:
            for name in _read_names(m.group(1)):
                scan.flags_read.append(
                    {"name": name, "line": lineno, "from_label": current_label}
                )
            if body_top:
                last_stmt = "if"
            continue

        m = _LAYERED_RE.match(code)
        if m:
            scan.images.append({"name": (m.group(1),), "line": lineno})
            continue

        m = _IMAGE_RE.match(code)
        if m:
            scan.images.append({"name": tuple(m.group(1).strip().split()), "line": lineno})
            continue

        m = _SHOW_RE.match(code)
        if m:
            scan.shows.append({
                "words": _display_words(m.group(1)), "line": lineno,
                "from_label": current_label, "stmt": "show",
            })
            if body_top:
                last_stmt = "show"
            continue

        m = _SCENE_RE.match(code)
        if m:
            scan.shows.append({
                "words": _display_words(m.group(1)), "line": lineno,
                "from_label": current_label, "stmt": "scene",
            })
            if body_top:
                last_stmt = "scene"
            continue

        m = _AUDIO_RE.match(code)
        if m:
            scan.audio.append({
                "channel": m.group(1), "file": m.group(2),
                "line": lineno, "from_label": current_label,
            })
            if body_top:
                last_stmt = "audio"
            continue

        m = _VOICE_RE.match(code)
        if m:
            scan.audio.append({
                "channel": "voice", "file": m.group(1),
                "line": lineno, "from_label": current_label,
            })
            continue

        # dialogue and narration: harvest [flag] interpolations
        if '"' in code:
            for name in _INTERP_RE.findall(code):
                if name not in _PY_KEYWORDS:
                    scan.flags_read.append(
                        {"name": name, "line": lineno, "from_label": current_label}
                    )

        if body_top:
            last_stmt = "other"

    close_label()
    return scan


# Ren'Py's stock GUI/engine files, copied verbatim from the SDK template into
# every project. They are never story, and scanning them buries real findings:
# screens.rpy's screen-language locals (prefix_, who, main_menu) read as
# undocumented story flags, and testcases.rpy's labels read as unreachable.
# script.rpy is deliberately NOT here — it is the entry point the author edits.
STOCK_FILES = {
    "gui.rpy", "guisupport.rpy", "options.rpy", "screens.rpy", "testcases.rpy",
}

# Generated translation files under game/tl/ are copies of every dialogue line
# and label in the game. Scanning them would report the whole script as
# duplicate labels the moment a second language is generated.
SKIP_DIRS = {"saves", "cache", "tl"}


def scan_game(game_dir: str) -> list[FileScan]:
    scans = []
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        for fname in sorted(files):
            if fname.endswith(".rpy") and fname not in STOCK_FILES:
                scans.append(scan_file(os.path.join(root, fname)))
    return scans
