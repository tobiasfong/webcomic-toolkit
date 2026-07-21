"""
characters.py — the Character Bible: a persistent, accumulating reference set per
character, so panels of the same person stay consistent across a comic.

This is the character-domain sibling of webcomic-background-mcp's World Builder
(world.py) — same idea, one axis different: a location has one canonical image; a
character has a *set* of them (turnarounds, expression sheets, whatever reference
art exists), because identity consistency needs more than one angle to draw from.

Projects:
  Same as World Builder — a single writer may work on several comics/characters at
  once. Each is a separate "project" with its own bible, so a character id like
  "aria" in one comic never collides with a different "aria" in another.

Storage:
  characters/<project>/                    <- one subfolder per character
  characters/<project>/<char_id>/ref_NN.png  <- the reference set (you own these)
  characters/<project>/characters.json     <- manifest: metadata pointing at each ref set

A character entry:
  {
    "name":        "Aria Solstice",
    "description": "17yo mage, silver hair, blue robes",
    "notes":       "signature costume: star pendant, always barefoot indoors",
    "profile":     "who they are — role in the story, standing/affiliation,
                   personality, and (if relevant) Japanese speech patterns:
                   register (丁寧語 vs 普通語, formal/casual shifts by listener)
                   and self-referential pronoun (僕/俺/私/あたし/わし/吾輩/etc.)",
    "abilities":   "short free-text summary of powers/skills/equipment",
    "palette":     ["#1a2b3c", "#8a9bb0", "#d4c9a8"],
    "tags":        ["protagonist", "mage"],
    "refs":        ["starry_knight/aria/ref_01.png", "starry_knight/aria/ref_02.png"],
                   (each relative to CHAR_ROOT; refs[0] is the "primary" reference
                   used as the img2img/IP-Adapter seed)
    "lora":        "character_aria.safetensors",  (optional; set by
                   set_character_lora() once Tier 3 bakes one — a filename in
                   ComfyUI's models/loras/, auto-used by generate_character_pose)
    "added":       "2026-07-18T..."
  }

`profile`/`abilities` are optional free-text fields (unlike `description`,
which drives generation prompts) used only for the composed reference sheet's
text blocks (see server.py's generate_reference_sheet) — modeled on Avery's
hand-composed character sheets, deliberately much shorter than hers (no bio
paragraphs, no quotes). The sheet's third text block, "Appearance," is NOT a
separate field — it's `description` itself, shown on the sheet as well as fed
to generation, specifically so hair/eye color/physical-trait notes (including
ones pulled from an artist's own markdown notes when ingesting their art) are
only ever typed once.

Registering an existing character id APPENDS new refs rather than replacing them —
the reference set is meant to grow over time (more turnarounds, or curated good
generations fed back in as future training data for Tier 3 LoRA baking).

This module is pure data/IO — it never talks to ComfyUI. generate_character_pose()
reads a character's primary ref and uses it as an img2img seed.
"""

import os
import re
import json
import shutil
import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
# Root that holds per-project character folders. Each project is a subfolder.
CHAR_ROOT = os.environ.get("WEBCOMIC_CHAR_ROOT", os.path.join(_HERE, "characters"))
# Project used when a caller doesn't specify one.
DEFAULT_PROJECT = os.environ.get("WEBCOMIC_CHAR_PROJECT", "default")


class CharacterError(RuntimeError):
    pass


def _slug(text: str) -> str:
    """A filesystem/key-safe id from free text."""
    s = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return s or "untitled"


def _project_dir(project: str | None) -> str:
    return os.path.join(CHAR_ROOT, _slug(project or DEFAULT_PROJECT))


def _manifest(project: str | None) -> str:
    return os.path.join(_project_dir(project), "characters.json")


def _character_dir(character_id: str, project: str | None) -> str:
    return os.path.join(_project_dir(project), _slug(character_id))


def _load(project: str | None) -> dict:
    path = _manifest(project)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise CharacterError(f"Could not read character manifest {path}: {e}") from e


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
    pal = im.quantize(colors=n, method=Image.FASTOCTREE).convert("RGB")
    counts = pal.getcolors(128 * 128) or []
    counts.sort(reverse=True)  # most frequent first
    return ["#%02x%02x%02x" % rgb for _, rgb in counts[:n]]


def register_character(
    image_paths: list[str] | str,
    character_id: str | None = None,
    name: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
    notes: str = "",
    profile: str = "",
    abilities: str = "",
    project: str | None = None,
) -> dict:
    """Add (or grow) a character's reference set in a project's bible.

    Copies each of `image_paths` into characters/<project>/<id>/ as ref_NN.png and
    records/updates the character's metadata. If `character_id` is omitted it's
    slugged from `name` or the first image's filename. Re-registering an existing
    id APPENDS the new images to the existing reference set (never replaces it) —
    name/description/tags/notes/profile/abilities are only overwritten if
    explicitly passed, otherwise the existing values are preserved.
    """
    if isinstance(image_paths, str):
        image_paths = [image_paths]
    if not image_paths:
        raise CharacterError("register_character needs at least one image path.")
    missing = [p for p in image_paths if not os.path.isfile(p)]
    if missing:
        raise CharacterError(f"Image(s) not found: {', '.join(missing)}")

    proj = _slug(project or DEFAULT_PROJECT)
    base = os.path.splitext(os.path.basename(image_paths[0]))[0]
    char_id = _slug(character_id or name or base)
    name_given = name  # remember whether the caller explicitly passed a name

    char_dir = _character_dir(char_id, project)
    os.makedirs(char_dir, exist_ok=True)

    data = _load(project)
    entry = data.get(char_id, {})
    existing_refs = entry.get("refs", [])
    start = len(existing_refs)

    new_refs = []
    try:
        from PIL import Image
        has_pil = True
    except ImportError:
        has_pil = False

    for i, image_path in enumerate(image_paths):
        n = start + i + 1
        rel = f"{proj}/{char_id}/ref_{n:02d}.png"
        abs_path = os.path.join(CHAR_ROOT, rel)
        if has_pil:
            Image.open(image_path).convert("RGB").save(abs_path)
        else:
            shutil.copyfile(image_path, abs_path)
        new_refs.append(rel)

    all_refs = existing_refs + new_refs
    palette = entry.get("palette")
    if not palette:
        palette = _extract_palette(os.path.join(CHAR_ROOT, all_refs[0]))

    resolved_name = (name_given or entry.get("name")
                     or base.replace("_", " ").title())
    entry.update({
        "name": resolved_name,
        "description": description or entry.get("description", ""),
        "notes": notes or entry.get("notes", ""),
        "profile": profile or entry.get("profile", ""),
        "abilities": abilities or entry.get("abilities", ""),
        "palette": palette,
        "tags": tags if tags is not None else entry.get("tags", []),
        "refs": all_refs,
        "added": entry.get("added", datetime.datetime.now().isoformat(timespec="seconds")),
    })
    data[char_id] = entry
    _save(project, data)
    return {"id": char_id, "project": proj, **entry}


def get_character(character_id: str, project: str | None = None) -> dict | None:
    """Return a character entry (with absolute `ref_paths`), or None."""
    entry = _load(project).get(_slug(character_id))
    if entry is None:
        return None
    entry = dict(entry)
    entry["ref_paths"] = [os.path.join(CHAR_ROOT, r) for r in entry.get("refs", [])]
    return entry


def primary_ref_path(character_id: str, project: str | None = None) -> str:
    """Absolute path to the character's primary (first-registered) reference
    image — the img2img seed for Tier-1 pose generation."""
    entry = get_character(character_id, project)
    if entry is None:
        raise CharacterError(
            f"No character '{character_id}' in project "
            f"'{_slug(project or DEFAULT_PROJECT)}'. Register it first."
        )
    if not entry["ref_paths"]:
        raise CharacterError(f"Character '{character_id}' has no reference images.")
    return entry["ref_paths"][0]


def list_characters(project: str | None = None) -> dict:
    """All character entries in a project, keyed by id."""
    return _load(project)


def list_projects() -> list[str]:
    """All projects that have a bible (a characters.json), sorted."""
    if not os.path.isdir(CHAR_ROOT):
        return []
    out = []
    for name in os.listdir(CHAR_ROOT):
        if os.path.isfile(os.path.join(CHAR_ROOT, name, "characters.json")):
            out.append(name)
    return sorted(out)


def set_character_lora(character_id: str, lora_filename: str,
                       project: str | None = None) -> dict:
    """Record a baked Tier-3 LoRA on a character's bible entry (the filename as
    placed in ComfyUI's models/loras/, ready for the existing `lora=` mechanism
    in workflow.py). generate_character_pose auto-uses this as the default lora
    once set, unless a caller passes their own `lora=`."""
    char_id = _slug(character_id)
    data = _load(project)
    entry = data.get(char_id)
    if entry is None:
        raise CharacterError(
            f"No character '{character_id}' in project "
            f"'{_slug(project or DEFAULT_PROJECT)}'. Register it first."
        )
    entry["lora"] = lora_filename
    data[char_id] = entry
    _save(project, data)
    return {"id": char_id, **entry}


def forget_character(character_id: str, delete_images: bool = False,
                      project: str | None = None) -> bool:
    """Remove a character from a project's bible. Returns True if it existed."""
    char_id = _slug(character_id)
    data = _load(project)
    entry = data.pop(char_id, None)
    if entry is None:
        return False
    if delete_images:
        char_dir = _character_dir(char_id, project)
        if os.path.isdir(char_dir):
            shutil.rmtree(char_dir)
    _save(project, data)
    return True
