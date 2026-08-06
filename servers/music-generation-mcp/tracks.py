"""
tracks.py — the track library.

Per-project namespacing from day one. The background server had to retrofit it
at v1.2.0 and ARCHITECTURE.md §8b.1 flags "don't repeat that" explicitly.

Layout mirrors the sibling servers:

    output/<project>/<track_id>/
        <track_id>.flac        lossless keep
        <track_id>.mp3         Remotion drop-in
        <track_id>.json        the recipe (§ace_workflow.recipe)
        beats.json             optional, written by extract_beats

    tracks.json                the manifest, one entry per generated track

Nothing here touches ComfyUI or the GPU — this module is pure bookkeeping and is
safe to call when ComfyUI is down.
"""

from __future__ import annotations

import json
import os
import re
import time

BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.environ.get("WEBCOMIC_MUSIC_OUTPUT", os.path.join(BASE, "output"))
MANIFEST = os.path.join(OUTPUT_ROOT, "tracks.json")


def slugify(text: str, fallback: str = "track") -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return (s[:40] or fallback)


def _load() -> dict:
    if not os.path.isfile(MANIFEST):
        return {"schema": 1, "tracks": []}
    with open(MANIFEST, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MANIFEST)   # atomic — a half-written manifest loses the library


def new_track_id(project: str, title: str) -> str:
    """A stable, collision-free id. Includes a timestamp because auditioning
    produces many takes of the same title and they must not overwrite each other
    — one take being silently replaced by a worse one is the expensive failure."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{slugify(title)}_{stamp}"


def track_dir(project: str, track_id: str) -> str:
    return os.path.join(OUTPUT_ROOT, slugify(project, "default"), track_id)


def record(project: str, track_id: str, title: str, recipe: dict,
           files: dict[str, str]) -> dict:
    entry = {
        "id": track_id,
        "project": project,
        "title": title,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": files,
        "recipe": recipe,
    }
    data = _load()
    data["tracks"] = [t for t in data["tracks"] if t["id"] != track_id]
    data["tracks"].append(entry)
    _save(data)

    d = track_dir(project, track_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{track_id}.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
    return entry


def get(track_id: str) -> dict | None:
    for t in _load()["tracks"]:
        if t["id"] == track_id:
            return t
    return None


def listing(project: str | None = None) -> list[dict]:
    """Terse rows only. Returning full recipes here would put every parameter of
    every take into context on a plain 'what have I got' call — the §8a golden
    rule (narrow excerpts, never the whole store) applied to audio."""
    out = []
    for t in _load()["tracks"]:
        if project and t["project"] != project:
            continue
        out.append({
            "id": t["id"],
            "project": t["project"],
            "title": t["title"],
            "created": t["created"],
            "duration": t["recipe"].get("duration"),
            "mp3": t["files"].get("mp3"),
        })
    return sorted(out, key=lambda r: r["created"], reverse=True)


def projects() -> list[str]:
    return sorted({t["project"] for t in _load()["tracks"]})


def attach(track_id: str, key: str, path: str) -> dict | None:
    """Attach a derived artefact (e.g. beats.json) to an existing track."""
    data = _load()
    for t in data["tracks"]:
        if t["id"] == track_id:
            t["files"][key] = path
            _save(data)
            return t
    return None
