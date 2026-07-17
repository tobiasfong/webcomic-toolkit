"""
projects.py — the project registry: maps a short slug (e.g. "my_novel") to
manuscripts per language PER VOLUME, plus a state directory.

Registry file: projects.json, next to this server's code — same idea as
world.py's WORLD_ROOT living inside the background-mcp repo. Gitignored: it's
user-specific data (story titles, personal file paths), not shipped code.

Each entry:
{
  "name":        "My Novel",
  "manuscripts": {
    "en": {"1": "C:\\...\\Vol1 EN.docx", "2": "C:\\...\\Vol2 EN.docx"},
    "ja": {"1": "C:\\...\\Vol1 JA.docx"}
  },
  "state_dir":   "C:\\...\\",
  "source_lang": "en"
}

Volumes restart chapter numbering — Volume 2 chapter 1 is a DIFFERENT chapter
from Volume 1 chapter 1, same as a real published novel volume. Chapter
identity in this server is therefore always (volume, chapter number), never
chapter number alone, once more than one volume exists. Each volume is ONE
docx file per language; there is no cross-file chapter merging within a
volume.

register() always sets/updates ONLY volume "1" for the languages given —
it's what first creates a project, and safe to call again later (e.g. to fix
a typo'd path) without touching any other volume. add_volume() sets/updates
any specific volume number (2, 3, ... or 1) for an ALREADY-registered project
— the tool for growing a project across volumes deliberately, without an
accidental wholesale-overwrite risk.

Glossary and chapter status are per-project (not per-volume) on purpose —
volumes of the same novel share one glossary/register bible, since it's still
the same characters and world.
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
    migrated = {}
    for slug, entry in data.items():
        try:
            migrated[slug] = _migrate(entry)
        except ProjectError:
            raise
        except Exception as e:
            # Anything unexpected here (a raw KeyError from a shape _migrate()
            # doesn't recognize, a non-dict entry, etc.) is a schema problem,
            # not something a caller should ever see as a bare traceback —
            # this is exactly the situation a long-running MCP server process
            # hits after `projects.py` is updated underneath it without a
            # restart: it may still be a genuinely old, unmigrated entry, or
            # the registry may have been hand-edited into a shape this
            # version doesn't expect. Either way, re-registering is the fix.
            raise ProjectError(
                f"Project '{slug}' could not be read from the registry ({type(e).__name__}: {e}). "
                "This usually means either the server process is stale (fully quit and relaunch "
                "your MCP client so a fresh process picks up the current code) or this project's "
                "registry entry predates a schema change this version doesn't auto-migrate. Fix: "
                "register_project(name=..., manuscripts={'en': '...', ...}) to re-register it."
            ) from e
    return migrated


def _migrate(entry: dict) -> dict:
    """Three schema generations to upgrade in memory on load:
    (1) a single top-level `manuscript` string (oldest — single-volume,
        source-language-only),
    (2) `manuscripts[lang]` as a bare path string (single volume, explicit
        per-language masters),
    (3) `manuscripts[lang]` as a flat list of paths (a brief "continuing
        chapter numbers across volumes" model, since abandoned — real
        published volumes restart chapter numbering, they don't continue it).
    All upgrade to `manuscripts[lang][str(volume_number)] = path`, treating a
    bare string or list as volume 1, 2, 3... in order. Idempotent on an
    already-current entry. `save()` always writes the current schema.
    """
    entry = dict(entry)
    if "manuscripts" not in entry and "manuscript" in entry:
        entry["manuscripts"] = {entry.get("source_lang", "en"): entry.pop("manuscript")}
    migrated = {}
    for lang, value in entry.get("manuscripts", {}).items():
        if isinstance(value, str):
            migrated[lang] = {"1": value}
        elif isinstance(value, list):
            migrated[lang] = {str(i + 1): p for i, p in enumerate(value)}
        elif isinstance(value, dict):
            migrated[lang] = {str(k): v for k, v in value.items()}
        else:
            raise ProjectError(f"Unrecognized manuscripts entry for lang '{lang}': {value!r}")
    entry["manuscripts"] = migrated
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
    """Create a new project (or update an existing one's volume-1 paths and
    top-level metadata) — ALWAYS volume "1" for the languages given. Never
    touches any other volume number an existing project might already have.
    Use add_volume() for volume 2+, or to intentionally re-point a different
    volume.
    """
    if source_lang not in manuscripts:
        raise ProjectError(f"source_lang '{source_lang}' must be a key in manuscripts {list(manuscripts)}")
    for lang, path in manuscripts.items():
        if not os.path.isfile(path):
            raise ProjectError(f"Manuscript not found for lang '{lang}': {path}")

    resolved_slug = slug or slugify(name)
    data = load()
    entry = data.get(resolved_slug, {"manuscripts": {}})
    entry["name"] = name
    entry["source_lang"] = source_lang
    entry["state_dir"] = state_dir or entry.get("state_dir") or os.path.dirname(manuscripts[source_lang])
    for lang, path in manuscripts.items():
        entry["manuscripts"].setdefault(lang, {})["1"] = path
    data[resolved_slug] = entry
    save(data)
    return resolved_slug, entry


def add_volume(slug: str, lang: str, path: str, volume: int) -> dict:
    """Set/replace a SPECIFIC volume number's manuscript for an existing
    project/language — the tool for growing a project across volumes (or
    fixing one volume's path). Only the given (lang, volume) pair changes;
    every other volume's registration is left untouched."""
    data = load()
    if slug not in data:
        available = ", ".join(sorted(data)) or "(none registered yet)"
        raise ProjectError(f"No project '{slug}' registered. Available: {available}")
    if not os.path.isfile(path):
        raise ProjectError(f"Manuscript not found: {path}")
    if volume < 1:
        raise ProjectError("volume must be >= 1")
    entry = data[slug]
    entry.setdefault("manuscripts", {}).setdefault(lang, {})[str(volume)] = path
    save(data)
    return entry
