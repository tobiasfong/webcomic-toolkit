"""
projects.py — the project registry: maps a short slug (e.g. "rxr",
"absolute_zero") to manuscript path(s) per language + a state directory, so
ONE server instance serves every story in the Stories folder instead of
needing a separate MCP server registration per novel.

Registry file: projects.json, next to this server's code — same idea as
world.py's WORLD_ROOT living inside the background-mcp repo. Gitignored: it's
user-specific data (story titles, personal file paths), not shipped code.

Each entry:
{
  "name":        "Reincarnator x Regressor",   # display name
  "manuscripts": {"en": ["C:\\...\\Vol1 draft.docx", "C:\\...\\Vol2 draft.docx"],
                  "ja": ["C:\\...\\Vol1 JA master.docx"]},
  "state_dir":   "C:\\...\\",                  # translation_state.json + translations/ live here
  "source_lang": "en"
}

Multiple languages can have a real master docx — NOT just the source
language. This matters when a translator maintains a proper master document in
the target language too (as opposed to loose per-chapter export files): a
language present in `manuscripts` is read from ITS OWN docx directly, never
from translations/<lang>/ exports, so there is no way for the tool to read
stale text that has drifted from what the author actually wrote. A language
absent from `manuscripts` falls back to translations/<lang>/chNN.txt as
before — that fallback exists for languages with no master document at all.

Each language maps to a LIST of docx files, not a single one — this is what
lets a multi-volume novel (Volume 2's own docx once Volume 1's is already
registered) keep growing without becoming a new project: chapter numbering
continues across the files (see manuscript.parse_chapters_multi), and the
glossary/register bible stays shared since it's still the same story. Use
add_volume() to grow an existing project's file list safely; register() always
overwrites `manuscripts` wholesale, so it's for first-time registration or a
deliberate full replacement, not for adding a volume.

Glossary and chapter status are per-project on purpose (each novel's
translation_state.json is isolated) — the same English term can legitimately
get a different translation in a different novel's register/voice.
"""

import os
import re
import json

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECTS_FILE = os.environ.get("NOVEL_MCP_PROJECTS_FILE", os.path.join(_HERE, "projects.json"))


class ProjectError(RuntimeError):
    pass


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return s or "untitled"


def load() -> dict:
    if not os.path.isfile(PROJECTS_FILE):
        return {}
    try:
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ProjectError(f"Could not read project registry {PROJECTS_FILE}: {e}") from e
    return {slug: _migrate(entry) for slug, entry in data.items()}


def _migrate(entry: dict) -> dict:
    """Two schema generations to upgrade in memory on load, so old registry
    files don't break: (1) the original single top-level `manuscript` string,
    and (2) `manuscripts` values that were a bare path string instead of a
    list. `save()` always writes the current schema (manuscripts: dict[lang,
    list[path]]); this function is idempotent on an already-current entry."""
    entry = dict(entry)
    if "manuscripts" not in entry and "manuscript" in entry:
        entry["manuscripts"] = {entry.get("source_lang", "en"): entry.pop("manuscript")}
    entry["manuscripts"] = {
        lang: (paths if isinstance(paths, list) else [paths])
        for lang, paths in entry.get("manuscripts", {}).items()
    }
    return entry


def save(data: dict) -> None:
    tmp = PROJECTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PROJECTS_FILE)


def resolve(slug: str) -> dict:
    data = load()
    if slug not in data:
        available = ", ".join(sorted(data)) or "(none registered yet — use register_project() first)"
        raise ProjectError(f"No project '{slug}' registered. Available: {available}")
    return data[slug]


def register(
    name: str,
    manuscripts: dict[str, str | list[str]],
    source_lang: str = "en",
    state_dir: str | None = None,
    slug: str | None = None,
) -> tuple[str, dict]:
    """Add or update a project entry. `manuscripts` maps language code -> one
    docx path or a list of them (multi-volume); any language present here is
    read from ITS master docx/docxs directly (never from translations/<lang>/
    exports — see module docstring). `source_lang` must be a key in
    `manuscripts` and marks which language is being translated FROM.

    Re-registering an existing slug OVERWRITES `manuscripts` wholesale (e.g.
    if a manuscript moved) but never touches translation_state.json — that
    lives at state_dir independently. To ADD a volume to an existing project
    without risking dropping an already-registered file, use add_volume()
    instead of calling register() again.
    """
    if source_lang not in manuscripts:
        raise ProjectError(f"source_lang '{source_lang}' must be a key in manuscripts {list(manuscripts)}")
    normalized: dict[str, list[str]] = {}
    for lang, paths in manuscripts.items():
        path_list = paths if isinstance(paths, list) else [paths]
        for p in path_list:
            if not os.path.isfile(p):
                raise ProjectError(f"Manuscript not found for lang '{lang}': {p}")
        normalized[lang] = path_list
    resolved_slug = slug or slugify(name)
    entry = {
        "name": name,
        "manuscripts": normalized,
        "state_dir": state_dir or os.path.dirname(normalized[source_lang][0]),
        "source_lang": source_lang,
    }
    data = load()
    data[resolved_slug] = entry
    save(data)
    return resolved_slug, entry


def add_volume(slug: str, lang: str, path: str) -> dict:
    """Append a new manuscript file to an existing project's language list —
    e.g. adding a Volume 2 docx once a Volume 1 docx is already registered for
    that language. Never replaces or drops an already-registered file (unlike
    register(), which overwrites `manuscripts` wholesale) — this is the safe
    way to grow a project across volumes without risking losing the reference
    to an earlier one."""
    data = load()
    if slug not in data:
        available = ", ".join(sorted(data)) or "(none registered yet)"
        raise ProjectError(f"No project '{slug}' registered. Available: {available}")
    if not os.path.isfile(path):
        raise ProjectError(f"Manuscript not found: {path}")
    entry = data[slug]
    paths = entry.setdefault("manuscripts", {}).setdefault(lang, [])
    if path in paths:
        raise ProjectError(f"{path} is already registered for lang '{lang}' in project '{slug}'.")
    paths.append(path)
    save(data)
    return entry
