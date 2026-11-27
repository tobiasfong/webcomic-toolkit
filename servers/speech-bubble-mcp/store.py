"""
store.py — where project settings, lettering specs and outputs live.

STATE (gitignored, because dialogue carries character names and the repo is
public): `state/projects.json` holds each project's lettering style, and
`state/lettering/<project>/<name>.json` holds every lettered page or shot --
the bubbles as written, the language, and what was produced. The spec is the
source of truth: re-lettering a page in another language, or after moving one
bubble, is a re-render of the spec, never a redo by hand.

OUTPUTS follow the toolkit's rule of one folder per kind of file, so the author
finds them where he finds everything else:
  images -> servers/character-panel-mcp/output/<project>/lettered/
  videos -> servers/anime-production-mcp/output/<project>/lettered/
A server installed on its own, without those siblings, writes to its own
output/ instead. SPEECH_BUBBLE_STATE, SPEECH_BUBBLE_IMAGE_OUT and
SPEECH_BUBBLE_VIDEO_OUT override each location.
"""

from __future__ import annotations

import json
import os
import re
import time

BASE = os.path.dirname(os.path.abspath(__file__))
SERVERS = os.path.dirname(BASE)


def state_dir() -> str:
    return os.environ.get("SPEECH_BUBBLE_STATE") or os.path.join(BASE, "state")


def _sibling_output(name: str, env: str) -> str:
    if os.environ.get(env):
        return os.environ[env]
    sib = os.path.join(SERVERS, name, "output")
    return sib if os.path.isdir(sib) else os.path.join(BASE, "output")


def image_root() -> str:
    return _sibling_output("character-panel-mcp", "SPEECH_BUBBLE_IMAGE_OUT")


def video_root() -> str:
    return _sibling_output("anime-production-mcp", "SPEECH_BUBBLE_VIDEO_OUT")


def image_out(project: str) -> str:
    d = os.path.join(image_root(), safe(project), "lettered")
    os.makedirs(d, exist_ok=True)
    return d


def video_out(project: str) -> str:
    d = os.path.join(video_root(), safe(project), "lettered")
    os.makedirs(d, exist_ok=True)
    return d


def safe(name: str) -> str:
    s = re.sub(r"[^\w\-.]+", "_", str(name).strip())
    if not s or s in (".", ".."):
        raise ValueError(f"Not a usable name: {name!r}")
    return s


def _read(path, default):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --- projects -------------------------------------------------------------------

def projects() -> dict:
    return _read(os.path.join(state_dir(), "projects.json"), {})


def get_project(project: str) -> dict:
    return projects().get(project, {})


def update_project(project: str, changes: dict) -> dict:
    allp = projects()
    cur = allp.get(project, {})
    for k, v in changes.items():
        if v is None:
            continue
        if k == "fonts" and isinstance(v, dict):
            cur.setdefault("fonts", {}).update(v)
        else:
            cur[k] = v
    allp[project] = cur
    _write(os.path.join(state_dir(), "projects.json"), allp)
    return cur


# --- lettering specs --------------------------------------------------------------

def spec_path(project: str, name: str) -> str:
    return os.path.join(state_dir(), "lettering", safe(project), safe(name) + ".json")


def save_spec(project: str, name: str, spec: dict) -> str:
    spec = dict(spec, updated=time.strftime("%Y-%m-%d %H:%M:%S"))
    path = spec_path(project, name)
    _write(path, spec)
    return path


def load_spec(project: str, name: str) -> dict:
    path = spec_path(project, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No saved lettering '{name}' in project '{project}'.")
    return _read(path, {})


def list_specs(project: str) -> list[dict]:
    d = os.path.join(state_dir(), "lettering", safe(project))
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            s = _read(os.path.join(d, fn), {})
            out.append({"name": fn[:-5], "mode": s.get("mode"), "source": s.get("source"),
                        "bubbles": len(s.get("bubbles", [])),
                        "languages": sorted(s.get("outputs", {})), "updated": s.get("updated")})
    return out
