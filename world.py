"""
world.py — the World Builder "bible": a persistent, accumulating model of the
established environments in a comic, so panels of the same place stay consistent.

The hard problem in AI backgrounds isn't making one good image — it's making
panel 12 and panel 40 of "the same street" look like the same street. Generation
is stateless; each call reinvents the scene. The bible fixes that: every approved
environment becomes permanent canon, and future panels of that place are generated
*against* the canon instead of from scratch.

Storage (mirrors how a novel grows in one file):
  world/                     <- canonical PNGs you approved (you own these)
  world/world.json           <- manifest: metadata pointing at each canonical image

A location entry:
  {
    "name":        "Saint Selena Cathedral district",
    "canonical":   "world/saint_selena_district.png",   (path, relative to repo)
    "description": "Grimdark gothic cathedral, twin spires, fog",
    "palette":     ["#2b3a4a", "#8a9bb0", "#d4c9a8"],
    "tags":        ["exterior", "cathedral", "hive"],
    "panel":       "ch1_p27",          (where it was first established; free-form)
    "added":       "2026-06-25T..."
  }

This module is pure data/IO — it never talks to ComfyUI. The generate() pipeline
reads a location's `canonical` image and uses it as an img2img reference.
"""

import os
import re
import json
import shutil
import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
WORLD_DIR = os.environ.get("WEBCOMIC_BG_WORLD", os.path.join(_HERE, "world"))
MANIFEST = os.path.join(WORLD_DIR, "world.json")


class WorldError(RuntimeError):
    pass


def _slug(text: str) -> str:
    """A filesystem/key-safe id from free text."""
    s = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return s or "location"


def _load() -> dict:
    if not os.path.isfile(MANIFEST):
        return {}
    try:
        with open(MANIFEST, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise WorldError(f"Could not read world manifest {MANIFEST}: {e}") from e


def _save(data: dict) -> None:
    os.makedirs(WORLD_DIR, exist_ok=True)
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MANIFEST)


def _extract_palette(image_path: str, n: int = 5) -> list[str]:
    """Best-effort dominant colours as hex, for the manifest. Empty list if PIL
    isn't available — the palette is descriptive metadata, not load-bearing."""
    try:
        from PIL import Image
    except ImportError:
        return []
    im = Image.open(image_path).convert("RGB").resize((128, 128))
    # adaptive palette = perceptual-ish quantisation to n colours
    pal = im.quantize(colors=n, method=Image.FASTOCTREE).convert("RGB")
    counts = pal.getcolors(128 * 128) or []
    counts.sort(reverse=True)  # most frequent first
    return ["#%02x%02x%02x" % rgb for _, rgb in counts[:n]]


def register_location(
    image_path: str,
    location_id: str | None = None,
    name: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
    panel: str = "",
    palette: list[str] | None = None,
) -> dict:
    """Add (or update) a canonical environment in the bible.

    Copies `image_path` into world/ as the location's canonical image and records
    its metadata. If `palette` is omitted it's auto-extracted from the image. If
    `location_id` is omitted it's slugged from `name` or the filename. Re-registering
    an existing id overwrites its canonical image and merges metadata.
    """
    if not os.path.isfile(image_path):
        raise WorldError(f"Image not found: {image_path}")

    base = os.path.splitext(os.path.basename(image_path))[0]
    loc_id = _slug(location_id or name or base)
    name = name or base.replace("_", " ").title()

    os.makedirs(WORLD_DIR, exist_ok=True)
    canonical_rel = os.path.join("world", f"{loc_id}.png")
    canonical_abs = os.path.join(_HERE, canonical_rel)

    # Normalise to PNG in the world folder.
    try:
        from PIL import Image
        Image.open(image_path).convert("RGB").save(canonical_abs)
    except ImportError:
        shutil.copyfile(image_path, canonical_abs)

    if palette is None:
        palette = _extract_palette(canonical_abs)

    data = _load()
    entry = data.get(loc_id, {})
    entry.update({
        "name": name,
        "canonical": canonical_rel.replace("\\", "/"),
        "description": description or entry.get("description", ""),
        "palette": palette,
        "tags": tags if tags is not None else entry.get("tags", []),
        "panel": panel or entry.get("panel", ""),
        "added": entry.get("added", datetime.datetime.now().isoformat(timespec="seconds")),
    })
    data[loc_id] = entry
    _save(data)
    return {"id": loc_id, **entry}


def get_location(location_id: str) -> dict | None:
    """Return a location entry (with an absolute `canonical_path`), or None."""
    entry = _load().get(_slug(location_id))
    if entry is None:
        return None
    entry = dict(entry)
    entry["canonical_path"] = os.path.join(_HERE, entry["canonical"])
    return entry


def list_locations() -> dict:
    """All location entries, keyed by id."""
    return _load()


def forget_location(location_id: str, delete_image: bool = False) -> bool:
    """Remove a location from the bible. Returns True if it existed."""
    loc_id = _slug(location_id)
    data = _load()
    entry = data.pop(loc_id, None)
    if entry is None:
        return False
    if delete_image:
        img = os.path.join(_HERE, entry.get("canonical", ""))
        if os.path.isfile(img):
            os.remove(img)
    _save(data)
    return True
