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
import shutil
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
        row = {
            "id": t["id"],
            "project": t["project"],
            "title": t["title"],
            "created": t["created"],
            "duration": t["recipe"].get("duration"),
            "mp3": t["files"].get("mp3"),
        }
        # Surface approval in the terse listing — it decides whether a take is
        # protected from forget_track, so hiding it here made a wrong flag easy
        # to miss. One word; worth the schema cost.
        if t.get("approved"):
            row["approved"] = True
            row["published_as"] = (t.get("published") or {}).get("mp3")
        out.append(row)
    return sorted(out, key=lambda r: r["created"], reverse=True)


def projects() -> list[str]:
    return sorted({t["project"] for t in _load()["tracks"]})


def approve(track_id: str, slug: str | None = None) -> dict:
    """Mark a track as the project's canon and publish it under a STABLE name.

    Two jobs, and the second is the point. Track ids carry a timestamp so
    auditioning cannot overwrite a good take — but that makes them useless as a
    handle for downstream tools, which should not have to know that
    `full_bminor_107s_20260807_004333` is "the theme song". This copies the
    approved take to `FINAL_<slug>.{mp3,flac}` (plus its beat grid) at the
    project root, so the video pipeline has one obvious target.

    The `FINAL_` prefix is deliberate: it is the same convention the panel
    pipeline uses, and the repo's standing rule is that generated attempts under
    output/ may be bulk-deleted freely but an approved FINAL_ never is. Naming it
    this way makes that protection apply automatically.
    """
    data = _load()
    entry = next((t for t in data["tracks"] if t["id"] == track_id), None)
    if entry is None:
        raise ValueError(f"No such track: {track_id}")

    slug = slugify(slug or entry["title"], "final")
    dest_dir = os.path.join(OUTPUT_ROOT, slugify(entry["project"], "default"))
    os.makedirs(dest_dir, exist_ok=True)

    published: dict[str, str] = {}
    for key in ("mp3", "flac", "beats"):
        src = entry["files"].get(key)
        if not src or not os.path.isfile(src):
            continue
        ext = "json" if key == "beats" else key
        name = f"FINAL_{slug}_beats.json" if key == "beats" else f"FINAL_{slug}.{ext}"
        dst = os.path.join(dest_dir, name)
        shutil.copy2(src, dst)
        published[key] = dst

    # Approval is NOT exclusive across the library. It was written that way
    # first — `t["approved"] = (t["id"] == track_id)` for every track — and
    # approving a 30 s short silently un-approved the project's full theme song,
    # stripping the delete-guard from a finished, canon track. A project has
    # many songs; identity is the SLUG, not "the one approved take".
    #
    # What is exclusive is the published name: approving a second take under an
    # existing slug replaces those FINAL_ files, which is the intended way to
    # supersede a take. Any prior holder of this slug is demoted, nothing else.
    for t in data["tracks"]:
        if t["id"] != track_id and t.get("published") and t.get("slug") == slug:
            t["approved"] = False
            t.pop("published", None)
    entry["approved"] = True
    entry["slug"] = slug
    entry["published"] = published
    _save(data)

    d = track_dir(entry["project"], track_id)
    with open(os.path.join(d, f"{track_id}.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
    return entry


def forget(track_id: str) -> bool:
    """Delete a track's folder and its manifest entry. Refuses an approved one —
    losing the canon take to a cleanup pass is the expensive mistake."""
    data = _load()
    entry = next((t for t in data["tracks"] if t["id"] == track_id), None)
    if entry is None:
        return False
    if entry.get("approved"):
        raise ValueError(
            f"{track_id} is the approved canon track. Approve a different take "
            f"first if you really mean to remove this one."
        )
    d = os.path.dirname(entry["files"].get("flac") or entry["files"].get("mp3", ""))
    if d and os.path.isdir(d):
        shutil.rmtree(d)
    data["tracks"] = [t for t in data["tracks"] if t["id"] != track_id]
    _save(data)
    return True


def prune() -> dict:
    """Drop manifest entries whose audio is gone from disk.

    Exists because the library is only a record of what generation produced —
    files get deleted outside it (a manual cleanup, a stray rm), and a manifest
    that points at missing audio makes `list_tracks` lie. Reports what it
    removed rather than doing it silently, since a prune that quietly ate a
    track you meant to keep is worse than a stale row.

    Approved entries are pruned too if their audio is genuinely gone — the
    delete-guard protects against `forget_track`, not against reality.
    """
    data = _load()
    kept, dropped = [], []
    for t in data["tracks"]:
        audio = t["files"].get("flac") or t["files"].get("mp3")
        if audio and os.path.isfile(audio):
            kept.append(t)
        else:
            dropped.append({"id": t["id"], "approved": bool(t.get("approved")),
                            "missing": audio})
    if dropped:
        data["tracks"] = kept
        _save(data)
    return {"pruned": dropped, "remaining": len(kept)}


def attach(track_id: str, key: str, path: str) -> dict | None:
    """Attach a derived artefact (e.g. beats.json) to an existing track."""
    data = _load()
    for t in data["tracks"]:
        if t["id"] == track_id:
            t["files"][key] = path
            _save(data)
            return t
    return None
