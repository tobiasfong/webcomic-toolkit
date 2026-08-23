"""
Visual Novel MCP
================
Branching visual-novel production server: scene database, branch-graph
validation derived from the Ren'Py scripts themselves, cross-session
continuity, and the one-body-plus-face-patch sprite manifest.

Design notes in README.md. WORKFLOW.md is served as `instructions`.
Tool descriptions are deliberately terse — every client re-sends every
schema on every message (see novel-translation-mcp for the reasoning).
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import re

from mcp.server.fastmcp import FastMCP
import projects
import state
import graph as graph_module
import sprites as sprites_module

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "WORKFLOW.md"), "r", encoding="utf-8") as _f:
    _INSTRUCTIONS = _f.read()

mcp = FastMCP("visual-novel-mcp", instructions=_INSTRUCTIONS)

DEFAULT_PROJECT = os.environ.get("VN_MCP_DEFAULT_PROJECT")

_SCENE_ID_RE = re.compile(r"^[a-z0-9_]+$")


def _resolve(project: str | None) -> tuple[str, dict]:
    slug = project or DEFAULT_PROJECT
    if not slug:
        registered = sorted(projects.load())
        if len(registered) == 1:
            slug = registered[0]
        else:
            raise ValueError(
                f"No `project` given and {'no projects are' if not registered else 'multiple projects are'} "
                f"registered ({', '.join(registered) or 'none'}). Pass project=... "
                "or set VN_MCP_DEFAULT_PROJECT."
            )
    return slug, projects.resolve(slug)


def _bible_names(entry: dict) -> dict:
    """char_id -> {name, notes} from the linked character bible, if any."""
    path = entry.get("characters_bible")
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        bible = json.load(f)
    return {cid: {"name": c.get("name", cid), "notes": c.get("notes", "")}
            for cid, c in bible.items()}


def _analysis(entry: dict) -> graph_module.Analysis:
    return graph_module.Analysis(entry["game_dir"])


def _scene_labels(data: dict) -> dict:
    """label -> scene_id for every scene that names one."""
    return {rec.get("label") or sid: sid for sid, rec in data["scenes"].items()}


def _check(entry: dict, data: dict, manifest: dict) -> dict:
    analysis = _analysis(entry)
    report = analysis.check(
        sprite_tags=sprites_module.tags(manifest),
        documented_flags=set(data.get("flags", {})),
    )
    # scene bookkeeping checks
    stale_approved, missing_files, orphan_labels = [], [], []
    label_to_scene = _scene_labels(data)
    for sid, rec in sorted(data["scenes"].items()):
        if rec.get("file"):
            fpath = os.path.join(entry["game_dir"], rec["file"])
            if not os.path.isfile(fpath):
                missing_files.append({"scene": sid, "file": rec["file"]})
            elif rec.get("status") == "approved":
                digest = state.file_digest(fpath)
                if rec.get("approved_digest") and digest != rec["approved_digest"]:
                    stale_approved.append({"scene": sid, "file": rec["file"]})
        label = rec.get("label") or sid
        if rec.get("status") != "planned" and label not in analysis.labels:
            missing_files.append({"scene": sid, "missing_label": label})
    for label in sorted(analysis.labels):
        if label in graph_module.ENGINE_ENTRY_LABELS or label.startswith("_"):
            continue
        if label not in label_to_scene:
            orphan_labels.append({"label": label, **analysis.labels[label]})
    report["scenes_missing_file_or_label"] = missing_files
    report["approved_scenes_changed_since_approval"] = stale_approved
    report["labels_not_tracked_as_scenes"] = orphan_labels
    report["counts"]["problems"] += len(missing_files) + len(stale_approved)
    return report


@mcp.tool()
def list_projects() -> dict:
    """Registered VN projects with scene counts by status."""
    out = []
    for slug, entry in sorted(projects.load().items()):
        data = state.load(entry["state_dir"])
        by_status = {}
        for rec in data["scenes"].values():
            by_status[rec.get("status", "planned")] = by_status.get(rec.get("status", "planned"), 0) + 1
        out.append({"project": slug, "name": entry["name"],
                    "game_dir": entry["game_dir"], "scenes_by_status": by_status})
    return {"projects": out}


@mcp.tool()
def register_project(name: str, game_dir: str, slug: str | None = None,
                     characters_bible: str | None = None) -> dict:
    """Register a VN project. `game_dir` is the Ren'Py game/ folder (created
    if absent, with scenes/, images/, audio/). `characters_bible` links a
    character-panel characters.json for name lookups. Game content must live
    under a gitignored path — the repo is public."""
    resolved, entry = projects.register(
        name=name, game_dir=game_dir, slug=slug, characters_bible=characters_bible,
    )
    return {"project": resolved, "entry": entry}


@mcp.tool()
def get_story_state(project: str | None = None) -> dict:
    """The resume tool: every scene with status + synopsis line, flags with
    meanings, note count, and the current check summary."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    manifest = sprites_module.load(entry["state_dir"])
    report = _check(entry, data, manifest)
    scenes = [
        {"scene": sid, "title": rec.get("title", ""), "status": rec.get("status"),
         "synopsis": rec.get("synopsis", ""), "file": rec.get("file"),
         "after": rec.get("after", [])}
        for sid, rec in sorted(data["scenes"].items())
    ]
    sprite_summary = {
        c: {"tag": e.get("tag"), "expressions": sorted(e.get("expressions", {}))}
        for c, e in sorted(manifest["characters"].items())
    }
    return {
        "project": slug, "scenes": scenes,
        "flags": data.get("flags", {}),
        "note_count": len(data.get("notes", [])),
        "sprites": sprite_summary,
        "check_counts": report["counts"],
        "problems_detail_tool": "check_story" if report["counts"]["problems"] else None,
    }


@mcp.tool()
def plan_scene(scene_id: str, title: str, synopsis: str,
               location: str | None = None,
               characters: list[str] | None = None,
               after: list[str] | None = None,
               project: str | None = None) -> dict:
    """Create or update a scene's plan (no script yet, or updating metadata).
    `after` lists the scene ids this follows — advisory until the script's
    own jumps exist. scene_id is the label and filename: [a-z0-9_]."""
    if not _SCENE_ID_RE.fullmatch(scene_id):
        raise ValueError("scene_id must be lowercase [a-z0-9_].")
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    rec = state.scene_record(data, scene_id)
    rec.update({"title": title, "synopsis": synopsis, "updated": state.now()})
    if location is not None:
        rec["location"] = location
    if characters is not None:
        rec["characters"] = characters
    if after is not None:
        unknown = [a for a in after if a not in data["scenes"] and a != scene_id]
        rec["after"] = after
        if unknown:
            rec["after_unknown"] = unknown
    state.save(entry["state_dir"], data)
    return {"project": slug, "scene": scene_id, "record": rec}


@mcp.tool()
def get_scene(scene_id: str, project: str | None = None) -> dict:
    """One scene's record + script text."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    if scene_id not in data["scenes"]:
        raise ValueError(f"Unknown scene {scene_id!r}.")
    rec = data["scenes"][scene_id]
    text = None
    if rec.get("file"):
        fpath = os.path.join(entry["game_dir"], rec["file"])
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                text = f.read()
    return {"project": slug, "scene": scene_id, "record": rec, "script": text}


@mcp.tool()
def get_scene_context(scene_id: str, project: str | None = None) -> dict:
    """Scene-start bundle in ONE call: the scene record + script, direct
    predecessor/successor scenes with synopses, flags set by predecessors,
    documented flag meanings, the scene's characters with names and
    registered expressions, and relevant notes. Call once per scene."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    if scene_id not in data["scenes"]:
        raise ValueError(
            f"Unknown scene {scene_id!r}. Plan it first with plan_scene, or "
            "check get_story_state for the id."
        )
    rec = data["scenes"][scene_id]
    label = rec.get("label") or scene_id
    analysis = _analysis(entry)
    label_to_scene = _scene_labels(data)

    preds, succs = set(), set()
    for src, edges in analysis.edges.items():
        for e in edges:
            if e["target"] == label and src in label_to_scene:
                preds.add(label_to_scene[src])
            if src == label and e["target"] in label_to_scene:
                succs.add(label_to_scene[e["target"]])
    # advisory ordering covers scenes whose scripts don't exist yet
    preds.update(a for a in rec.get("after", []) if a in data["scenes"])
    for sid, other in data["scenes"].items():
        if scene_id in other.get("after", []):
            succs.add(sid)
    preds.discard(scene_id)
    succs.discard(scene_id)

    def brief(sid):
        r = data["scenes"][sid]
        return {"scene": sid, "title": r.get("title"), "status": r.get("status"),
                "synopsis": r.get("synopsis")}

    flags_by_pred = {}
    for sid in sorted(preds):
        plabel = data["scenes"][sid].get("label") or sid
        names = sorted({
            name for name, sets in analysis.flags_set.items()
            for s in sets if s["label"] == plabel and s["via"] == "$"
        })
        if names:
            flags_by_pred[sid] = names

    bible = _bible_names(entry)
    manifest = sprites_module.load(entry["state_dir"])
    characters = {}
    for cid in rec.get("characters", []):
        sp = manifest["characters"].get(cid, {})
        characters[cid] = {
            "name": bible.get(cid, {}).get("name", cid),
            "notes": bible.get(cid, {}).get("notes", ""),
            "sprite_tag": sp.get("tag"),
            "expressions": sorted(sp.get("expressions", {})) if sp else [],
            "mirror_ok": sp.get("mirror_ok"),
        }

    notes = [n for n in data.get("notes", [])
             if "scene" not in n or n["scene"] == scene_id]

    script = None
    if rec.get("file"):
        fpath = os.path.join(entry["game_dir"], rec["file"])
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                script = f.read()

    return {
        "project": slug, "scene": scene_id, "record": rec, "script": script,
        "predecessors": [brief(s) for s in sorted(preds)],
        "successors": [brief(s) for s in sorted(succs)],
        "flags_set_by_predecessors": flags_by_pred,
        "flag_meanings": data.get("flags", {}),
        "characters": characters,
        "notes": notes,
        "deeper_flag_analysis": "trace_paths(to_label=...) enumerates start-to-here paths with flag order",
    }


@mcp.tool()
def save_scene(scene_id: str, script: str, status: str = "drafted",
               project: str | None = None) -> dict:
    """Write a scene's .rpy (game/scenes/<id>.rpy), update its record, and
    parse it immediately — reports the labels found, outgoing jumps, flags
    touched, and anything unresolved, while context is warm. Refuses to
    silently demote an approved scene."""
    if not _SCENE_ID_RE.fullmatch(scene_id):
        raise ValueError("scene_id must be lowercase [a-z0-9_].")
    if status not in state.STATUSES:
        raise ValueError(f"status must be one of: {', '.join(state.STATUSES)}")
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    rec = state.scene_record(data, scene_id)
    if rec.get("status") == "approved" and status != "approved":
        raise ValueError(
            f"Scene {scene_id} is approved. Overwriting an approved scene needs "
            "the author's explicit instruction — pass status='approved' after he "
            "confirms, or have him change the status first."
        )
    rel = f"scenes/{scene_id}.rpy"
    fpath = os.path.join(entry["game_dir"], rel)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    tmp = fpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(script)
    os.replace(tmp, fpath)

    rec.update({"file": rel, "status": status, "updated": state.now()})
    if status == "approved":
        rec["approved_digest"] = state.file_digest(fpath)

    manifest = sprites_module.load(entry["state_dir"])
    analysis = _analysis(entry)
    import rpy_parse
    scan = rpy_parse.scan_file(fpath)
    labels_here = [l["name"] for l in scan.labels]
    label = rec.get("label") or scene_id
    warnings = []
    if label not in labels_here:
        warnings.append(
            f"Script does not define the scene's entry label {label!r} "
            f"(found: {', '.join(labels_here) or 'none'})."
        )
    dangling = [j["target"] for j in scan.jumps
                if j["target"] and not j["dynamic"] and j["target"] not in analysis.labels]
    undocumented = sorted(
        {f["name"] for f in scan.flags_set + scan.flags_read}
        - set(data.get("flags", {})) - analysis.defines
    )
    tags = sprites_module.tags(manifest) | {n[0] for n in analysis.image_names if n}
    unresolved_shows = [" ".join(s["words"]) for s in scan.shows
                        if s["words"] and s["words"][0] not in tags]
    state.save(entry["state_dir"], data)
    return {
        "project": slug, "scene": scene_id, "file": rel, "status": status,
        "labels": labels_here,
        "outgoing_targets": sorted({j["target"] for j in scan.jumps if j["target"]}),
        "dangling_targets": sorted(set(dangling)),
        "menus": len(scan.menus),
        "choices": sum(len(m["choices"]) for m in scan.menus),
        "flags_set": sorted({f["name"] for f in scan.flags_set}),
        "flags_read": sorted({f["name"] for f in scan.flags_read}),
        "undocumented_flags": undocumented,
        "unresolved_displayables": sorted(set(unresolved_shows)),
        "hint": "define_flag for each undocumented flag; dangling targets are fine only if that scene is next to be written",
    }


@mcp.tool()
def check_story(project: str | None = None) -> dict:
    """Full validation: dangling jumps, unreachable labels, duplicate labels,
    flags read-never-set / set-never-read / undocumented, unresolved show and
    scene displayables, missing audio files, scenes whose file or label is
    missing, approved scenes changed since approval, untracked labels."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    manifest = sprites_module.load(entry["state_dir"])
    report = _check(entry, data, manifest)
    return {"project": slug, **report}


@mcp.tool()
def trace_paths(to_label: str, start: str = "start", max_paths: int = 12,
                project: str | None = None) -> dict:
    """Enumerate simple paths start -> label with flags set along each, for
    continuity reasoning ('what has the player seen when they arrive here').
    Bounded; heavy branching returns a sample and says so."""
    slug, entry = _resolve(project)
    analysis = _analysis(entry)
    result = analysis.trace_paths(to_label, start=start, max_paths=max_paths)
    return {"project": slug, **result}


@mcp.tool()
def define_flag(name: str, meaning: str, project: str | None = None) -> dict:
    """Document a story flag's meaning. Every flag a script touches should
    have one — check_story flags the undocumented."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    entry_out = state.define_flag(data, name, meaning)
    state.save(entry["state_dir"], data)
    return {"project": slug, "flag": name, "record": entry_out}


@mcp.tool()
def record_note(note: str, scene: str | None = None,
                project: str | None = None) -> dict:
    """Persist a continuity decision or judgment call so future fresh chats
    inherit it via get_scene_context. One or two sentences."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    entry_out = state.add_note(data, note, scene=scene)
    state.save(entry["state_dir"], data)
    return {"project": slug, "recorded": entry_out, "total_notes": len(data["notes"])}


@mcp.tool()
def forget_scene(scene_id: str, delete_file: bool = False,
                 project: str | None = None) -> dict:
    """Drop a scene from the database. Refuses approved scenes — those are the
    author's, same rule as FINAL_* panels. The .rpy is left on disk unless
    delete_file=True, and even then an approved script is never touched."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    if scene_id not in data["scenes"]:
        raise ValueError(f"Unknown scene {scene_id!r}.")
    rec = data["scenes"][scene_id]
    if rec.get("status") == "approved":
        raise ValueError(
            f"Scene {scene_id} is approved. Approved scenes are not deleted by "
            "tooling — change its status first, on the author's instruction."
        )
    removed_file = None
    if delete_file and rec.get("file"):
        fpath = os.path.join(entry["game_dir"], rec["file"])
        if os.path.isfile(fpath):
            os.remove(fpath)
            removed_file = rec["file"]
    del data["scenes"][scene_id]
    state.save(entry["state_dir"], data)
    return {"project": slug, "forgot": scene_id, "deleted_file": removed_file,
            "remaining_scenes": len(data["scenes"])}


@mcp.tool()
def register_sprite(character: str, body_path: str, tag: str | None = None,
                    target_height: float | None = None, mirror_ok: bool = True,
                    notes: str = "", height_cm: float | None = None,
                    project: str | None = None) -> dict:
    """Register a character's matted body PNG (copied into the game tree).
    PREFER `height_cm` — relative cast heights then come out right by
    construction, and the first one registered fixes the screen reference.
    `target_height` (fraction of screen) is the fallback for characters with
    no canonical height. Set mirror_ok=False for asymmetric costumes."""
    slug, entry = _resolve(project)
    manifest = sprites_module.load(entry["state_dir"])
    rec = sprites_module.register_character(
        manifest, entry["game_dir"], character, body_path,
        tag=tag, target_height=target_height, mirror_ok=mirror_ok, notes=notes,
        height_cm=height_cm,
    )
    sprites_module.save(entry["state_dir"], manifest)
    return {"project": slug, "character": character, "record": rec,
            "next": "register_expression per hand-drawn patch, then emit_sprites"}


@mcp.tool()
def register_expression(character: str, expression: str, patch_path: str,
                        offset_x: int, offset_y: int,
                        project: str | None = None) -> dict:
    """Register a hand-drawn face patch at a pixel offset on the body canvas.
    Validates the patch fits. Run preview_expression to eyeball alignment,
    then emit_sprites."""
    slug, entry = _resolve(project)
    manifest = sprites_module.load(entry["state_dir"])
    rec = sprites_module.register_expression(
        manifest, entry["game_dir"], character, expression, patch_path,
        offset_x, offset_y,
    )
    sprites_module.save(entry["state_dir"], manifest)
    return {"project": slug, "character": character, "expression": expression, "record": rec}


@mcp.tool()
def preview_expression(character: str, expression: str,
                       project: str | None = None) -> dict:
    """Composite body + patch over magenta and save a preview PNG — the
    alignment check for hand-drawn patches. Look at it; do not trust offsets
    numerically."""
    slug, entry = _resolve(project)
    manifest = sprites_module.load(entry["state_dir"])
    result = sprites_module.preview(
        manifest, entry["game_dir"], entry["state_dir"], character, expression,
    )
    return {"project": slug, **result}


@mcp.tool()
def emit_sprites(project: str | None = None) -> dict:
    """Regenerate sprites_generated.rpy (one layeredimage per character,
    zoom from target_height) and the padded expression layers. Run after any
    register_* call. Never hand-edit the generated file."""
    slug, entry = _resolve(project)
    manifest = sprites_module.load(entry["state_dir"])
    result = sprites_module.emit(manifest, entry["game_dir"])
    return {"project": slug, **result}


if __name__ == "__main__":
    mcp.run()
