"""
projects.py — the VN project registry (projects.json, gitignored: it holds
project names and local paths, and the repo is public).

A project entry:
{
  "name": "...",
  "game_dir": "...\\vn\\<slug>\\game",      # the Ren'Py game/ folder — scripts + assets
  "state_dir": "...\\vn\\<slug>",           # vn_state.json, sprites.json, previews/
  "characters_bible": "...characters.json"  # optional link to character-panel bible
}

The game_dir is a plain directory of .rpy files and assets — nothing here
requires the Ren'Py SDK to be installed, so the whole toolchain works before
the engine is ever downloaded.
"""

import os
import json
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECTS_PATH = os.path.join(_HERE, "projects.json")


class ProjectError(ValueError):
    pass


def load() -> dict:
    if not os.path.isfile(PROJECTS_PATH):
        return {}
    with open(PROJECTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    tmp = PROJECTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PROJECTS_PATH)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        raise ProjectError(f"Cannot derive a slug from name {name!r}.")
    return slug


def register(
    name: str,
    game_dir: str,
    slug: str | None = None,
    characters_bible: str | None = None,
    state_dir: str | None = None,
) -> tuple[str, dict]:
    slug = slug or _slugify(name)
    if not re.fullmatch(r"[a-z0-9_]+", slug):
        raise ProjectError(f"Slug must be lowercase [a-z0-9_]: {slug!r}")
    game_dir = os.path.abspath(game_dir)
    state_dir = os.path.abspath(state_dir) if state_dir else os.path.dirname(game_dir)
    if characters_bible and not os.path.isfile(characters_bible):
        raise ProjectError(f"characters_bible not found: {characters_bible}")
    os.makedirs(os.path.join(game_dir, "scenes"), exist_ok=True)
    os.makedirs(os.path.join(game_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(game_dir, "audio"), exist_ok=True)
    data = load()
    entry = {
        "name": name,
        "game_dir": game_dir,
        "state_dir": state_dir,
    }
    if characters_bible:
        entry["characters_bible"] = os.path.abspath(characters_bible)
    data[slug] = entry
    _save(data)
    return slug, entry


def resolve(slug: str) -> dict:
    data = load()
    if slug not in data:
        raise ProjectError(
            f"Unknown project {slug!r}. Registered: {', '.join(sorted(data)) or 'none'}."
        )
    return data[slug]
