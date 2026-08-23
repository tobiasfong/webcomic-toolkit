"""
sprites.py — the sprite manifest (sprites.json) and its Ren'Py emission.

Architecture (decided 2026-08-16, character-panel session): each character is
ONE matted body render plus small hand-drawn face patches (eyes/brows/mouth
deltas). Bodies must be pixel-identical across expressions or the sprite
jitters mid-conversation — so expressions are never separate renders; they
are overlays composited by the engine at runtime.

The manifest is the single source of truth; sprites_generated.rpy is EMITTED
from it and must never be hand-edited. Patches are registered as small crops
with a pixel offset; emit() pads each one onto a transparent canvas the exact
size of the body, so every layeredimage layer is same-size and offsets are
baked in — the jitter-proof representation.

sprites.json:
{
  "schema": 1,
  "screen_height": 1080,
  "characters": {
    "<character_id>": {
      "tag": "pc",                       # the Ren'Py image tag
      "body": "images/sprites/<character_id>/body.png",   # relative to game_dir
      "target_height": 0.85,               # body height as fraction of screen
      "mirror_ok": true,                   # false when costume detail is asymmetric
      "notes": "...",
      "expressions": {
        "worried": {"patch": "images/sprites/.../expr_worried.png",
                    "offset": [412, 188]}   # top-left px of patch on body canvas
      }
    }
  }
}
"""

import os
import json
import struct

MANIFEST_FILENAME = "sprites.json"
GENERATED_RPY = "sprites_generated.rpy"


class SpriteError(ValueError):
    pass


def _path(state_dir: str) -> str:
    return os.path.join(state_dir, MANIFEST_FILENAME)


def load(state_dir: str) -> dict:
    path = _path(state_dir)
    if not os.path.isfile(path):
        return {"schema": 1, "screen_height": 1080, "characters": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(state_dir: str, data: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    path = _path(state_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def png_size(path: str) -> tuple[int, int]:
    """Width/height from the PNG IHDR — no image library needed."""
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise SpriteError(f"Not a PNG: {path}")
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def _copy_into_game(src: str, game_dir: str, rel_dest: str) -> str:
    """Copy an asset into the game tree (Ren'Py loads only from there).
    Refuses to clobber a different existing file."""
    dest = os.path.join(game_dir, rel_dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.abspath(src) != os.path.abspath(dest):
        with open(src, "rb") as f:
            blob = f.read()
        if os.path.isfile(dest):
            with open(dest, "rb") as f:
                if f.read() != blob:
                    raise SpriteError(
                        f"{rel_dest} already exists in the game tree with different "
                        "content. Remove or rename it first — this tool never "
                        "silently overwrites art."
                    )
        else:
            with open(dest, "wb") as f:
                f.write(blob)
    return rel_dest


def register_character(manifest: dict, game_dir: str, character: str, body_path: str,
                       tag: str | None = None, target_height: float | None = None,
                       mirror_ok: bool = True, notes: str = "",
                       height_cm: float | None = None) -> dict:
    if not os.path.isfile(body_path):
        raise SpriteError(f"Body PNG not found: {body_path}")
    w, h = png_size(body_path)
    rel = _copy_into_game(body_path, game_dir, f"images/sprites/{character}/body.png")
    entry = manifest["characters"].setdefault(character, {"expressions": {}})
    entry.update({
        "tag": tag or entry.get("tag") or character.split("_")[0],
        "body": rel,
        "body_size": [w, h],
        "mirror_ok": mirror_ok,
        "notes": notes or entry.get("notes", ""),
    })
    if target_height is not None:
        entry["target_height"] = target_height
    if height_cm is not None:
        entry["height_cm"] = height_cm
        # First character with a height defines the reference, so absolute
        # sizing stays stable as the cast grows; only ratios matter after.
        manifest.setdefault("scale", {
            "ref_height_cm": height_cm,
            "ref_screen_fraction": target_height or entry.get("target_height") or 0.85,
        })
    return entry


def register_expression(manifest: dict, game_dir: str, character: str,
                        expression: str, patch_path: str,
                        offset_x: int, offset_y: int) -> dict:
    if character not in manifest["characters"]:
        raise SpriteError(f"Register the character body first: {character}")
    if not os.path.isfile(patch_path):
        raise SpriteError(f"Patch PNG not found: {patch_path}")
    entry = manifest["characters"][character]
    pw, ph = png_size(patch_path)
    bw, bh = entry["body_size"]
    if offset_x < 0 or offset_y < 0 or offset_x + pw > bw or offset_y + ph > bh:
        raise SpriteError(
            f"Patch {pw}x{ph} at ({offset_x},{offset_y}) does not fit inside "
            f"the {bw}x{bh} body canvas."
        )
    rel = _copy_into_game(
        patch_path, game_dir, f"images/sprites/{character}/expr_{expression}.png"
    )
    entry["expressions"][expression] = {
        "patch": rel, "size": [pw, ph], "offset": [offset_x, offset_y],
    }
    return entry["expressions"][expression]


def _pad_patch(game_dir: str, character: str, expression: str,
               patch_rel: str, offset: list, body_size: list) -> str:
    """Pad a face patch onto a transparent body-sized canvas (jitter-proof
    layer). Idempotent: rewrites only when inputs changed is not tracked —
    the write is cheap and deterministic."""
    from PIL import Image
    out_rel = f"images/sprites/{character}/_gen/{expression}_full.png"
    out = os.path.join(game_dir, out_rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    patch = Image.open(os.path.join(game_dir, patch_rel)).convert("RGBA")
    canvas = Image.new("RGBA", tuple(body_size), (0, 0, 0, 0))
    canvas.paste(patch, tuple(offset))
    canvas.save(out)
    return out_rel


def screen_fraction(manifest: dict, entry: dict) -> float | None:
    """How much of the screen height this character's figure should occupy.

    Preferred: derived from `height_cm` against the manifest's `scale`
    reference, so relative heights across the cast are correct by
    construction and a new character only needs a height. Falls back to an
    explicit `target_height` for entries registered before heights existed.

    NOTE: the figure is measured to its ALPHA BBOX, which includes hair. A
    tall hairstyle (a high topknot) therefore eats into the body height and
    makes that character read slightly short. Adjust their height_cm down a
    little if it shows.
    """
    scale = manifest.get("scale")
    if scale and entry.get("height_cm"):
        return scale["ref_screen_fraction"] * entry["height_cm"] / scale["ref_height_cm"]
    return entry.get("target_height")


def emit(manifest: dict, game_dir: str) -> dict:
    """Write sprites_generated.rpy (layeredimage per character) and the padded
    expression layers. Returns what was written."""
    lines = [
        "# GENERATED by visual-novel-mcp from sprites.json — do not edit by hand.",
        "# Re-run emit_sprites after any register_sprite / register_expression.",
        "",
    ]
    written_layers = []
    screen_h = manifest.get("screen_height", 1080)
    for character, entry in sorted(manifest["characters"].items()):
        if "body" not in entry:
            continue
        tag = entry["tag"]
        zoom = None
        frac = screen_fraction(manifest, entry)
        if frac:
            zoom = round(screen_h * frac / entry["body_size"][1], 4)
        # The `at` clause must go INSIDE the block — `layeredimage <tag> at ...:`
        # is a syntax error ("expected ':' not found"), confirmed by renpy lint
        # 8.5.3 on 2026-08-22. Do not move this back onto the header line.
        lines.append(f"layeredimage {tag}:")
        if zoom:
            lines.append(f"    at Transform(zoom={zoom})")
        lines.append("    always:")
        lines.append(f'        "{entry["body"]}"')
        if entry["expressions"]:
            lines.append("    group expression:")
            lines.append("        attribute neutral default Null()")
            for name, ex in sorted(entry["expressions"].items()):
                full_rel = _pad_patch(
                    game_dir, character, name, ex["patch"], ex["offset"], entry["body_size"]
                )
                written_layers.append(full_rel)
                lines.append(f'        attribute {name} "{full_rel}"')
        lines.append("")

    out_path = os.path.join(game_dir, GENERATED_RPY)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, out_path)
    return {
        "rpy": GENERATED_RPY,
        "characters": [c for c, e in manifest["characters"].items() if "body" in e],
        "padded_layers": written_layers,
    }


def preview(manifest: dict, game_dir: str, state_dir: str,
            character: str, expression: str) -> dict:
    """Composite body + one expression patch over magenta and save a preview
    PNG — the alignment check for hand-drawn patches."""
    from PIL import Image
    entry = manifest["characters"].get(character)
    if not entry or "body" not in entry:
        raise SpriteError(f"No registered body for {character}.")
    ex = entry["expressions"].get(expression)
    if not ex:
        raise SpriteError(
            f"No expression {expression!r} for {character}. "
            f"Registered: {', '.join(sorted(entry['expressions'])) or 'none'}."
        )
    body = Image.open(os.path.join(game_dir, entry["body"])).convert("RGBA")
    patch = Image.open(os.path.join(game_dir, ex["patch"])).convert("RGBA")
    canvas = Image.new("RGBA", body.size, (255, 0, 255, 255))
    canvas.alpha_composite(body)
    canvas.alpha_composite(patch, tuple(ex["offset"]))
    out_dir = os.path.join(state_dir, "previews")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{character}_{expression}.png")
    canvas.convert("RGB").save(out)
    x, y = ex["offset"]
    pw, ph = ex["size"]
    return {"preview": out, "patch_box": [x, y, x + pw, y + ph], "body_size": list(body.size)}


def tags(manifest: dict) -> set[str]:
    return {e["tag"] for e in manifest["characters"].values() if "tag" in e}
