"""
world.py — the World Builder "bible": a persistent, accumulating model of the
established environments in a comic, so panels of the same place stay consistent.

The hard problem in AI backgrounds isn't making one good image — it's making
panel 12 and panel 40 of "the same street" look like the same street. Generation
is stateless; each call reinvents the scene. The bible fixes that: every approved
environment becomes permanent canon, and future panels of that place are generated
*against* the canon instead of from scratch.

Projects:
  A single artist may work on several comics at once. Each is a separate "project"
  with its own canon, so a location id like "academy" in one comic never collides
  with a different "academy" in another. References (the shared sketch library) are
  NOT namespaced — they're common input; only the established canon is per-project.

Storage (mirrors how a novel grows in one file):
  world/<project>/                <- canonical PNGs you approved (you own these)
  world/<project>/world.json      <- manifest: metadata pointing at each canonical image

A location entry:
  {
    "name":        "Saint Selena Cathedral district",
    "canonical":   "starry_knight/saint_selena_district.png",  (relative to WORLD_ROOT)
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
# Root that holds per-project canon folders. Each project is a subfolder.
WORLD_ROOT = os.environ.get("WEBCOMIC_BG_WORLD", os.path.join(_HERE, "world"))
# Project used when a caller doesn't specify one.
DEFAULT_PROJECT = os.environ.get("WEBCOMIC_BG_PROJECT", "default")


class WorldError(RuntimeError):
    pass


def _slug(text: str) -> str:
    """A filesystem/key-safe id from free text."""
    s = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return s or "untitled"


def _project_dir(project: str | None) -> str:
    return os.path.join(WORLD_ROOT, _slug(project or DEFAULT_PROJECT))


def _manifest(project: str | None) -> str:
    return os.path.join(_project_dir(project), "world.json")


def _load(project: str | None) -> dict:
    path = _manifest(project)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise WorldError(f"Could not read world manifest {path}: {e}") from e


def _save(project: str | None, data: dict) -> None:
    os.makedirs(_project_dir(project), exist_ok=True)
    path = _manifest(project)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


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


def describe_color(hex_code: str) -> str:
    """Turn '#9b2b1f' into 'deep rust-red' — prompt language, not a hex code.

    Diffusion prompts can't consume hex. Translating the palette into words is
    what actually lets a reference image drive a render's colour, and doing it
    by eye is exactly the step that kept getting skipped."""
    import colorsys
    h = hex_code.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    hue *= 360

    if light < 0.09:
        return "near-black"
    if light > 0.93 and sat < 0.15:
        return "off-white"
    if sat < 0.10:
        return ("charcoal grey" if light < 0.3 else
                "ash grey" if light < 0.6 else "pale grey")

    for lo, hi, base in ((0, 15, "red"), (15, 40, "rust-orange"), (40, 65, "amber"),
                         (65, 95, "olive-yellow"), (95, 150, "green"),
                         (150, 195, "teal"), (195, 240, "steel-blue"),
                         (240, 280, "indigo"), (280, 330, "violet"),
                         (330, 361, "crimson")):
        if lo <= hue < hi:
            name = base
            break
    else:
        name = "grey"

    tone = ("deep " if light < 0.28 else
            "pale " if light > 0.72 else
            "muted " if sat < 0.35 else "")
    return f"{tone}{name}".strip()


def describe_palette(hex_codes: list[str]) -> list[str]:
    """De-duplicated colour words for a palette, in dominance order."""
    seen, out = set(), []
    for c in hex_codes:
        word = describe_color(c)
        if word not in seen:
            seen.add(word)
            out.append(word)
    return out


def register_location(
    image_path: str,
    location_id: str | None = None,
    name: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
    panel: str = "",
    palette: list[str] | None = None,
    project: str | None = None,
) -> dict:
    """Add (or update) a canonical environment in a project's bible.

    Copies `image_path` into world/<project>/ as the location's canonical image and
    records its metadata. If `palette` is omitted it's auto-extracted from the image.
    If `location_id` is omitted it's slugged from `name` or the filename. Re-registering
    an existing id in the same project overwrites its canonical image and merges metadata.
    """
    if not os.path.isfile(image_path):
        raise WorldError(f"Image not found: {image_path}")

    proj = _slug(project or DEFAULT_PROJECT)
    base = os.path.splitext(os.path.basename(image_path))[0]
    loc_id = _slug(location_id or name or base)
    name = name or base.replace("_", " ").title()

    os.makedirs(_project_dir(project), exist_ok=True)
    canonical_rel = f"{proj}/{loc_id}.png"               # relative to WORLD_ROOT
    canonical_abs = os.path.join(WORLD_ROOT, proj, f"{loc_id}.png")

    # Normalise to PNG in the project's world folder.
    try:
        from PIL import Image
        Image.open(image_path).convert("RGB").save(canonical_abs)
    except ImportError:
        shutil.copyfile(image_path, canonical_abs)

    if palette is None:
        palette = _extract_palette(canonical_abs)

    data = _load(project)
    entry = data.get(loc_id, {})
    entry.update({
        "name": name,
        "canonical": canonical_rel,
        "description": description or entry.get("description", ""),
        "palette": palette,
        "tags": tags if tags is not None else entry.get("tags", []),
        "panel": panel or entry.get("panel", ""),
        "added": entry.get("added", datetime.datetime.now().isoformat(timespec="seconds")),
    })
    data[loc_id] = entry
    _save(project, data)
    return {"id": loc_id, "project": proj, **entry}


def get_location(location_id: str, project: str | None = None) -> dict | None:
    """Return a location entry (with an absolute `canonical_path`), or None."""
    entry = _load(project).get(_slug(location_id))
    if entry is None:
        return None
    entry = dict(entry)
    entry["canonical_path"] = os.path.join(WORLD_ROOT, entry["canonical"])
    return entry


def list_locations(project: str | None = None) -> dict:
    """All location entries in a project, keyed by id."""
    return _load(project)


def list_projects() -> list[str]:
    """All projects that have a bible (a world.json), sorted."""
    if not os.path.isdir(WORLD_ROOT):
        return []
    out = []
    for name in os.listdir(WORLD_ROOT):
        if os.path.isfile(os.path.join(WORLD_ROOT, name, "world.json")):
            out.append(name)
    return sorted(out)


# ------------------------------------------------------------ 3D city plans --
# The plan is the project's *growable 3D model*: a JSON list of districts, each
# with its own seed/origin/params. Appending a district grows the city while every
# earlier district re-renders identically (per-district RNG streams). The 2D
# canonical images in the bible are snapshots OF the plan; the plan is the
# structural truth. Stored beside the bible: world/<project>/city_plan.json.

def _city_plan_path(project: str | None) -> str:
    return os.path.join(_project_dir(project), "city_plan.json")


def load_city_plan(project: str | None = None) -> dict | None:
    path = _city_plan_path(project)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise WorldError(f"Could not read city plan {path}: {e}") from e


def save_city_plan(plan: dict, project: str | None = None) -> str:
    os.makedirs(_project_dir(project), exist_ok=True)
    path = _city_plan_path(project)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def add_city_district(
    district_id: str,
    x: float,
    z: float,
    type: str = "block",
    seed: int | None = None,
    project: str | None = None,
    **params,
) -> dict:
    """Append (or update) a district in the project's city plan; create the plan
    if this is the city's first district. Returns the full plan."""
    plan = load_city_plan(project) or {"name": _slug(project or DEFAULT_PROJECT),
                                       "districts": []}
    did = _slug(district_id)
    if seed is None:
        seed = abs(hash((did, len(plan["districts"])))) % 2147483647 or 1
    entry = {"id": did, "type": type, "origin": [x, z], "seed": seed, **params}
    for i, d in enumerate(plan["districts"]):
        if d.get("id") == did:
            entry["seed"] = d.get("seed", seed)   # never reroll an existing district
            plan["districts"][i] = entry
            break
    else:
        plan["districts"].append(entry)
    save_city_plan(plan, project)
    return plan


def forget_location(location_id: str, delete_image: bool = False,
                    project: str | None = None) -> bool:
    """Remove a location from a project's bible. Returns True if it existed."""
    loc_id = _slug(location_id)
    data = _load(project)
    entry = data.pop(loc_id, None)
    if entry is None:
        return False
    if delete_image:
        img = os.path.join(WORLD_ROOT, entry.get("canonical", ""))
        if os.path.isfile(img):
            os.remove(img)
    _save(project, data)
    return True
