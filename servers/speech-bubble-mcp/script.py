"""
script.py — read a lettering script into bubble entries.

The format is a light screenplay:

    INT. HOTEL BALLROOM - NIGHT          a scene heading
    He sets the glass down.              a visible-action line
    NAME: words                          speech
    NAME (thought): words                a thought bubble
    NAME (shout): words                  any bubble kind works in the parentheses
    CAPTION: words                       a caption box (narration)
    [staging note]                       kept as a note, never lettered

A dialogue line continues onto following lines that are indented. Any other
parenthetical, such as "(quietly)", stays with the line as a `direction` and
does not change the bubble -- the writer's direction is for the reader of the
script, and choosing a whisper balloon for it is a decision to ask about.

The parser never rewrites the words. What comes out is exactly what was
written, so the author's voice survives into the bubble.
"""

from __future__ import annotations

import re

from bubbles import KINDS

_DIALOGUE = re.compile(r"^(?P<name>[^\s:\[\(][^:\[\(]*?)\s*(?:\((?P<paren>[^)]*)\))?\s*:\s*(?P<text>.*)$")
_HEADING = re.compile(r"^(INT\.|EXT\.|INT/EXT\.|SCENE\b|#)", re.I)


def parse(text: str) -> dict:
    entries = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip():
            continue
        s = line.strip()
        if raw[:1] in (" ", "\t") and entries and entries[-1]["type"] == "bubble":
            entries[-1]["text"] += " " + s
            continue
        if s.startswith("[") and s.endswith("]"):
            entries.append({"type": "note", "text": s[1:-1].strip(), "line": n})
            continue
        if _HEADING.match(s):
            entries.append({"type": "heading", "text": s.lstrip("# ").strip(), "line": n})
            continue
        m = _DIALOGUE.match(s)
        if m and m.group("text") and _looks_like_name(m.group("name")):
            name = m.group("name").strip()
            paren = (m.group("paren") or "").strip()
            e = {"type": "bubble", "line": n, "text": m.group("text").strip()}
            if name.upper() in ("CAPTION", "NARRATION", "NARRATOR"):
                e["kind"] = "caption"
            else:
                e["speaker"] = name
                e["kind"] = paren.lower() if paren.lower() in KINDS else "speech"
                if paren and paren.lower() not in KINDS:
                    e["direction"] = paren
            entries.append(e)
            continue
        entries.append({"type": "action", "text": s, "line": n})

    bubbles = [e for e in entries if e["type"] == "bubble"]
    for i, b in enumerate(bubbles, start=1):
        b["id"] = f"l{i}"
    speakers = sorted({b["speaker"] for b in bubbles if "speaker" in b})
    return {"entries": entries, "bubbles": len(bubbles), "speakers": speakers}


def _looks_like_name(s: str) -> bool:
    """A speaker label is short and has no sentence punctuation; this keeps
    'He said it plainly: no.' from being read as a speaker called 'He said it
    plainly'."""
    s = s.strip()
    return 0 < len(s) <= 32 and len(s.split()) <= 4 and not re.search(r"[.,!?;\"]", s)
