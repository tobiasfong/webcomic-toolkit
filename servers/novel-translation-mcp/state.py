"""
state.py — the translation state file, next to the manuscript (same pattern as the
background generator's world.json): chapter status + glossary, in one JSON file, so
resuming a session costs a status readout instead of re-deriving context.

Schema:
{
  "schema": 1,
  "chapters": {
    "v1c19": {"title_en": "...", "volume": 1, "chapter": 19,
              "lang": {"ja": {"status": "draft", "file": "translations/ja/v1_ch19.txt",
                              "updated": "2026-07-13T..."}}}
  },
  "glossary": {
    "approved": [{"term": "reincarnator", "translation": "転生者", "note": "..."}],
    "staged":   [{"term": "...", "translation": "...", "note": "...", "proposed": "2026-07-13T..."}]
  }
}

Chapter keys are "v{volume}c{number}", not the bare chapter number — Volume 2
restarts chapter numbering at 1, same as a real published novel volume, so
chapter identity is always (volume, chapter), never chapter number alone.
This only matters for languages with NO registered master docx (tracked via
translations/<lang>/ export files); a master-backed language's status is
derived by parsing that volume's docx directly, never from this file.

Human-in-the-loop enforcement point: nothing in this module ever moves an entry from
`staged` to `approved`. That move is a deliberate manual edit of the JSON file (or an
explicit instruction to make one) — there is no code path that does it automatically.
"""

import os
import json
import datetime

STATE_FILENAME = "translation_state.json"


class StateError(RuntimeError):
    pass


def _manifest_path(state_dir: str) -> str:
    return os.path.join(state_dir, STATE_FILENAME)


def load(state_dir: str) -> dict:
    path = _manifest_path(state_dir)
    if not os.path.isfile(path):
        return {"schema": 1, "chapters": {}, "glossary": {"approved": [], "staged": []}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise StateError(f"Could not read state file {path}: {e}") from e


def save(state_dir: str, data: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    path = _manifest_path(state_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def chapter_key(volume: int, number: int) -> str:
    return f"v{volume}c{number}"


def chapter_record(data: dict, volume: int, number: int) -> dict:
    return data["chapters"].setdefault(
        chapter_key(volume, number),
        {"title_en": "", "volume": volume, "chapter": number, "lang": {}},
    )


def set_translation_status(data: dict, volume: int, number: int, lang: str, status: str, file_rel: str) -> None:
    rec = chapter_record(data, volume, number)
    rec.setdefault("lang", {})[lang] = {
        "status": status,
        "file": file_rel,
        "updated": now(),
    }


def stage_glossary_term(data: dict, term: str, translation: str, note: str = "") -> dict:
    entry = {"term": term, "translation": translation, "note": note, "proposed": now()}
    data.setdefault("glossary", {"approved": [], "staged": []}).setdefault("staged", []).append(entry)
    return entry
