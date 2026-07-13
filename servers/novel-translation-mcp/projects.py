"""
projects.py — the project registry: maps a short slug (e.g. "rxr",
"absolute_zero") to a manuscript path + state directory, so ONE server instance
serves every story in the Stories folder instead of needing a separate MCP
server registration per novel (the original MVP only knew about one hardcoded
manuscript — this is the generalization requested once a second novel came up).

Registry file: projects.json, next to this server's code — same idea as
world.py's WORLD_ROOT living inside the background-mcp repo. Gitignored: it's
user-specific data (story titles, personal file paths), not shipped code.

Each entry:
{
  "name":        "Reincarnator x Regressor",   # display name
  "manuscript":  "C:\\...\\draft 2.docx",      # source-language manuscript
  "state_dir":   "C:\\...\\",                  # translation_state.json + translations/ live here
  "source_lang": "en"
}

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
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ProjectError(f"Could not read project registry {PROJECTS_FILE}: {e}") from e


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
    manuscript: str,
    source_lang: str = "en",
    state_dir: str | None = None,
    slug: str | None = None,
) -> tuple[str, dict]:
    """Add or update a project entry. Re-registering an existing slug overwrites
    its paths (e.g. if the manuscript moved) but never touches its
    translation_state.json — that lives at state_dir independently."""
    if not os.path.isfile(manuscript):
        raise ProjectError(f"Manuscript not found: {manuscript}")
    resolved_slug = slug or slugify(name)
    entry = {
        "name": name,
        "manuscript": manuscript,
        "state_dir": state_dir or os.path.dirname(manuscript),
        "source_lang": source_lang,
    }
    data = load()
    data[resolved_slug] = entry
    save(data)
    return resolved_slug, entry
