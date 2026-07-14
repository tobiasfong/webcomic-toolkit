"""
projects.py — the project registry: maps a short slug (e.g. "rxr",
"absolute_zero") to a manuscript path (or paths, per language) + a state
directory, so ONE server instance serves every story in the Stories folder
instead of needing a separate MCP server registration per novel.

Registry file: projects.json, next to this server's code — same idea as
world.py's WORLD_ROOT living inside the background-mcp repo. Gitignored: it's
user-specific data (story titles, personal file paths), not shipped code.

Each entry:
{
  "name":        "Reincarnator x Regressor",   # display name
  "manuscripts": {"en": "C:\\...\\draft 2.docx", "ja": "C:\\...\\JA master.docx"},
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
    """Old schema had a single `manuscript` string (source language only).
    Upgrade in memory on load so old registry files (and old code that hasn't
    been updated) don't break; `save()` always writes the new schema."""
    if "manuscripts" not in entry and "manuscript" in entry:
        entry = dict(entry)
        entry["manuscripts"] = {entry.get("source_lang", "en"): entry.pop("manuscript")}
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
    manuscripts: dict[str, str],
    source_lang: str = "en",
    state_dir: str | None = None,
    slug: str | None = None,
) -> tuple[str, dict]:
    """Add or update a project entry. `manuscripts` maps language code -> docx
    path; any language present here is read from ITS master docx directly
    (never from translations/<lang>/ exports — see module docstring).
    `source_lang` must be a key in `manuscripts` and marks which language is
    being translated FROM.

    Re-registering an existing slug overwrites its paths (e.g. if a manuscript
    moved) but never touches its translation_state.json — that lives at
    state_dir independently.
    """
    if source_lang not in manuscripts:
        raise ProjectError(f"source_lang '{source_lang}' must be a key in manuscripts {list(manuscripts)}")
    for lang, path in manuscripts.items():
        if not os.path.isfile(path):
            raise ProjectError(f"Manuscript not found for lang '{lang}': {path}")
    resolved_slug = slug or slugify(name)
    entry = {
        "name": name,
        "manuscripts": dict(manuscripts),
        "state_dir": state_dir or os.path.dirname(manuscripts[source_lang]),
        "source_lang": source_lang,
    }
    data = load()
    data[resolved_slug] = entry
    save(data)
    return resolved_slug, entry
