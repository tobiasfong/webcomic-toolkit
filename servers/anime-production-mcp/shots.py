"""
shots.py — the shot library.

A "shot" is one animated take of one illustration. Auditioning produces many
takes of the same shot (the seed hunt lands roughly 1 in 3), so ids carry a
timestamp and nothing overwrites anything.

Per-project namespacing from day one — the background server had to retrofit it
and ARCHITECTURE.md §8b.1 flags "don't repeat that" explicitly.

    output/<project>/<shot_id>/
        <shot_id>.webp          the take, as ComfyUI wrote it (24fps)
        <shot_id>_12fps.webp    retimed for viewing — ALWAYS judge this one
        <shot_id>.json          the recipe, enough to reproduce the take

    shots.json                  the manifest, one entry per take

Nothing here touches ComfyUI or the GPU — pure bookkeeping, safe to call when
ComfyUI is down.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time

BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.environ.get("WEBCOMIC_ANIME_OUTPUT", os.path.join(BASE, "output"))
MANIFEST = os.path.join(OUTPUT_ROOT, "shots.json")


def slugify(text: str, fallback: str = "shot") -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return (s[:40] or fallback)


def _load() -> dict:
    if not os.path.isfile(MANIFEST):
        return {"schema": 1, "shots": []}
    with open(MANIFEST, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MANIFEST)   # atomic — a half-written manifest loses the library


def new_shot_id(name: str, seed: int) -> str:
    """Stable, collision-free, and it carries the seed.

    The seed is in the NAME because seeds do not transfer across configs: a seed
    that moved at len 17 can freeze at len 25, so "which seed was that?" is a
    question asked constantly during a hunt and should not require opening JSON.
    """
    return f"{slugify(name)}_s{seed}_{time.strftime('%Y%m%d_%H%M%S')}"


def shot_dir(project: str, shot_id: str) -> str:
    return os.path.join(OUTPUT_ROOT, slugify(project, "default"), shot_id)


def record(project: str, shot_id: str, name: str, recipe: dict,
           files: dict[str, str], metrics: dict | None = None) -> dict:
    entry = {
        "id": shot_id,
        "project": project,
        "name": name,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": files,
        "recipe": recipe,
        "metrics": metrics or {},
    }
    data = _load()
    data["shots"] = [s for s in data["shots"] if s["id"] != shot_id]
    data["shots"].append(entry)
    _save(data)

    d = shot_dir(project, shot_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{shot_id}.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
    return entry


def get(shot_id: str) -> dict | None:
    for s in _load()["shots"]:
        if s["id"] == shot_id:
            return s
    return None


def listing(project: str | None = None, name: str | None = None) -> list[dict]:
    """Terse rows only.

    Returning full recipes here would put every parameter of every take into
    context on a plain "what have I got" call — the §8a golden rule (narrow
    excerpts, never the whole store). A seed hunt generates a lot of takes.
    """
    out = []
    for s in _load()["shots"]:
        if project and s["project"] != project:
            continue
        if name and s["name"] != name:
            continue
        out.append({
            "id": s["id"],
            "project": s["project"],
            "name": s["name"],
            "created": s["created"],
            "seed": s["recipe"].get("seed"),
            "maxdev": s.get("metrics", {}).get("maxdev"),
            "approved": s.get("approved", False),
            "view": s["files"].get("retimed") or s["files"].get("webp"),
        })
    return sorted(out, key=lambda r: r["created"], reverse=True)


def projects() -> list[str]:
    return sorted({s["project"] for s in _load()["shots"]})


def approve(shot_id: str, slug: str | None = None) -> dict:
    """Lock a take as this shot's canon and publish it under a STABLE name.

    Shot ids carry a timestamp so auditioning cannot overwrite a good take — but
    that makes them useless as a handle for the assembler, which should not have
    to know that `rooftop_s412_20260101_004333` is "the rooftop shot".
    Copies the approved take to `FINAL_<slug>.webp` at the project root.

    The `FINAL_` prefix is the ecosystem convention: attempts under output/ may
    be bulk-deleted freely, an approved FINAL_ never is. Naming it this way makes
    that protection automatic.

    Approval is per NAME, not per project — approving a second take of the same
    shot name unapproves the first, but leaves other shots alone. A teaser has
    eight approved shots at once.
    """
    data = _load()
    entry = next((s for s in data["shots"] if s["id"] == shot_id), None)
    if entry is None:
        raise ValueError(f"No such shot: {shot_id}")

    slug = slugify(slug or entry["name"], "final")
    dest_dir = os.path.join(OUTPUT_ROOT, slugify(entry["project"], "default"))
    os.makedirs(dest_dir, exist_ok=True)

    published: dict[str, str] = {}
    src = entry["files"].get("retimed") or entry["files"].get("webp")
    if src and os.path.isfile(src):
        dst = os.path.join(dest_dir, f"FINAL_{slug}.webp")
        shutil.copy2(src, dst)
        published["webp"] = dst

    for s in data["shots"]:
        if s["project"] == entry["project"] and s["name"] == entry["name"]:
            s["approved"] = (s["id"] == shot_id)
    entry["published"] = published
    _save(data)

    d = shot_dir(entry["project"], shot_id)
    with open(os.path.join(d, f"{shot_id}.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
    return entry


def forget(shot_id: str) -> bool:
    """Delete a take's folder and its manifest entry. Refuses an approved one."""
    data = _load()
    entry = next((s for s in data["shots"] if s["id"] == shot_id), None)
    if entry is None:
        return False
    if entry.get("approved"):
        raise ValueError(
            f"{shot_id} is the approved take for '{entry['name']}'. Approve a "
            f"different take first if you really mean to remove this one."
        )
    d = shot_dir(entry["project"], shot_id)
    if os.path.isdir(d):
        shutil.rmtree(d)
    data["shots"] = [s for s in data["shots"] if s["id"] != shot_id]
    _save(data)
    return True


def forget_rejected(project: str, name: str | None = None) -> dict:
    """Bulk-delete every unapproved take, keeping the canon.

    A hunt for eight shots at three seeds each leaves ~16 dead takes at a few MB
    apiece. Clearing them one id at a time is the kind of chore that never gets
    done, so the library grows until someone deletes the whole folder by hand —
    and takes the approved shots with it.
    """
    data = _load()
    doomed = [s for s in data["shots"]
              if s["project"] == project and not s.get("approved")
              and (name is None or s["name"] == name)]
    freed = 0
    for s in doomed:
        d = shot_dir(project, s["id"])
        if os.path.isdir(d):
            for root, _, fs in os.walk(d):
                freed += sum(os.path.getsize(os.path.join(root, f)) for f in fs)
            shutil.rmtree(d)
    kept = {s["id"] for s in doomed}
    data["shots"] = [s for s in data["shots"] if s["id"] not in kept]
    _save(data)
    return {"forgotten": len(doomed), "freed_mb": round(freed / 1e6, 1),
            "ids": [s["id"] for s in doomed]}


def attach(shot_id: str, key: str, path: str) -> dict | None:
    """Attach a derived artefact (a retimed copy, a composite) to a take."""
    data = _load()
    for s in data["shots"]:
        if s["id"] == shot_id:
            s["files"][key] = path
            _save(data)
            return s
    return None


def set_metrics(shot_id: str, metrics: dict) -> dict | None:
    data = _load()
    for s in data["shots"]:
        if s["id"] == shot_id:
            s["metrics"] = {**s.get("metrics", {}), **metrics}
            _save(data)
            return s
    return None
