"""
state.py — vn_state.json, the story-side state (same pattern as the novel
server's translation_state.json).

DESIGN RULE: the .rpy scripts are the single source of truth for the branch
graph — labels, jumps, menus, and flag reads/writes are DERIVED by parsing
them (rpy_parse.py), never stored here. This file holds only what a script
cannot express:

{
  "schema": 1,
  "scenes": {
    "s01_awakening": {
      "title": "...", "synopsis": "...",
      "status": "planned|drafted|reviewed|approved",
      "file": "scenes/s01_awakening.rpy",   # relative to game_dir; null while planned
      "label": "s01_awakening",             # entry label; defaults to the scene id
      "location": "...", "characters": ["<character_id>", ...],
      "after": ["s00_prologue"],            # advisory ordering, used before a script
                                            # exists; once drafted the graph wins
      "updated": "..."
    }
  },
  "flags": { "met_cheon_ma": {"meaning": "...", "added": "..."} },
  "notes": [ {"note": "...", "scene": "s01_awakening"|null, "added": "..."} ]
}

Approval is the human's: nothing here moves a scene to "approved" except an
explicit status passed by the author's instruction, and check_story flags any
approved scene whose file has since changed.
"""

import os
import json
import hashlib
import datetime

STATE_FILENAME = "vn_state.json"
STATUSES = ("planned", "drafted", "reviewed", "approved")


class StateError(RuntimeError):
    pass


def _path(state_dir: str) -> str:
    return os.path.join(state_dir, STATE_FILENAME)


def load(state_dir: str) -> dict:
    path = _path(state_dir)
    if not os.path.isfile(path):
        return {"schema": 1, "scenes": {}, "flags": {}, "notes": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise StateError(f"Could not read state file {path}: {e}") from e


def save(state_dir: str, data: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    path = _path(state_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def file_digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:16]


def scene_record(data: dict, scene_id: str) -> dict:
    return data["scenes"].setdefault(
        scene_id,
        {
            "title": "", "synopsis": "", "status": "planned",
            "file": None, "label": scene_id,
            "location": None, "characters": [], "after": [],
            "updated": now(),
        },
    )


def add_note(data: dict, note: str, scene: str | None = None) -> dict:
    entry = {"note": note, "added": now()}
    if scene:
        entry["scene"] = scene
    data.setdefault("notes", []).append(entry)
    return entry


def define_flag(data: dict, name: str, meaning: str) -> dict:
    entry = {"meaning": meaning, "added": now()}
    data.setdefault("flags", {})[name] = entry
    return entry
