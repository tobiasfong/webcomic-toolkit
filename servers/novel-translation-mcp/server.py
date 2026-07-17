"""
Novel Translation MCP
======================
A local MCP server that answers narrow, targeted questions about a novel
manuscript instead of ever putting the whole document in context.

Design notes live in README.md (multi-project/multi-volume model, master-docx
correctness rule, human-in-the-loop enforcement). WORKFLOW.md is served to
clients as this server's `instructions` — edit that file, not a string here.

Token-economy note: tool DESCRIPTIONS below are deliberately terse. Every
connected client re-sends every tool schema with every single message, so
each docstring here is paid for thousands of times per session. Long-form
explanation belongs in README.md, which costs nothing per-request.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
import manuscript
import state
import projects
import lint as lint_module

_WORKFLOW_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "WORKFLOW.md")
with open(_WORKFLOW_PATH, "r", encoding="utf-8") as _f:
    _WORKFLOW_INSTRUCTIONS = _f.read()

mcp = FastMCP("novel-translation-mcp", instructions=_WORKFLOW_INSTRUCTIONS)

DEFAULT_PROJECT = os.environ.get("NOVEL_MCP_DEFAULT_PROJECT", "rxr")


def _resolve(project: str | None) -> tuple[str, dict]:
    slug = project or DEFAULT_PROJECT
    return slug, projects.resolve(slug)


def _volume_path(entry: dict, lang: str, volume: int) -> str | None:
    return entry.get("manuscripts", {}).get(lang, {}).get(str(volume))


def _all_volumes(entry: dict) -> list[int]:
    source_lang = entry.get("source_lang", "en")
    return sorted(int(v) for v in entry.get("manuscripts", {}).get(source_lang, {}))


def _source_chapters(entry: dict, volume: int) -> dict[int, dict]:
    source_lang = entry.get("source_lang", "en")
    path = _volume_path(entry, source_lang, volume)
    if not path:
        raise ValueError(f"No volume {volume} registered for source lang '{source_lang}'.")
    return manuscript.parse_chapters(path, source_lang)


def _lang_chapters(entry: dict, lang: str, volume: int) -> dict[int, dict] | None:
    path = _volume_path(entry, lang, volume)
    if not path:
        return None
    return manuscript.parse_chapters(path, lang)


def _translations_dir(state_dir: str, lang: str) -> str:
    return os.path.join(state_dir, "translations", lang)


def _translation_file(state_dir: str, volume: int, number: int, lang: str) -> str:
    return os.path.join(_translations_dir(state_dir, lang), f"v{volume}_ch{number:02d}.txt")


def _translation_file_rel(volume: int, number: int, lang: str) -> str:
    return f"translations/{lang}/v{volume}_ch{number:02d}.txt"


def _slice_paragraphs(text: str, start: int | None, end: int | None) -> tuple[str, int, bool]:
    """Slice text to a 1-indexed inclusive paragraph range. Returns
    (text, total_paragraph_count, was_sliced)."""
    paras = [p for p in text.split("\n\n") if p.strip()]
    total = len(paras)
    if start is None and end is None:
        return text, total, False
    lo = max(1, start or 1)
    hi = min(total, end or total)
    return "\n\n".join(paras[lo - 1:hi]), total, True


@mcp.tool()
def list_projects() -> dict:
    """List registered novels: slug, name, source language, chapter counts per
    language per volume."""
    data = projects.load()
    out = []
    for slug, entry in sorted(data.items()):
        counts_by_lang = {}
        error = None
        for lang, vol_map in entry.get("manuscripts", {}).items():
            counts = {}
            for vol_str, path in sorted(vol_map.items(), key=lambda kv: int(kv[0])):
                try:
                    counts[vol_str] = len(manuscript.parse_chapters(path, lang))
                except manuscript.ManuscriptError as e:
                    counts[vol_str] = None
                    error = error or str(e)
            counts_by_lang[lang] = counts
        out.append({
            "project": slug,
            "name": entry["name"],
            "source_lang": entry.get("source_lang", "en"),
            "chapter_counts_by_lang_and_volume": counts_by_lang,
            "error": error,
        })
    return {"projects": out}


@mcp.tool()
def register_project(
    name: str,
    manuscripts: dict[str, str],
    source_lang: str = "en",
    state_dir: str | None = None,
    slug: str | None = None,
) -> dict:
    """Register a new novel's Volume 1 (or fix Volume 1's paths). `manuscripts`
    maps lang -> docx path; every language listed is read from its own docx
    directly. `source_lang` must be one of its keys. For volume 2+ use
    add_manuscript_volume."""
    resolved_slug, entry = projects.register(
        name=name, manuscripts=manuscripts, source_lang=source_lang,
        state_dir=state_dir, slug=slug,
    )
    chapter_counts = {}
    warnings = []
    for lang, path in manuscripts.items():
        chapters = manuscript.parse_chapters(path, lang)
        chapter_counts[lang] = len(chapters)
        if not chapters:
            warnings.append(
                f"No chapters found for lang '{lang}' — expected headings like "
                "'Chapter N: Title' (EN) or '第N話/章　Title' (JA)."
            )
    return {
        "project": resolved_slug,
        "entry": entry,
        "volume_1_chapter_counts_by_lang": chapter_counts,
        "warnings": warnings or None,
    }


@mcp.tool()
def add_manuscript_volume(project: str, lang: str, path: str, volume: int) -> dict:
    """Register volume N's docx for an existing project/language. Volumes
    restart chapter numbering at 1. Only the given (lang, volume) slot is
    touched — other volumes are never affected."""
    slug, entry = _resolve(project)
    if not os.path.isfile(path):
        raise ValueError(f"Manuscript not found: {path}")
    chapters = manuscript.parse_chapters(path, lang)
    projects.add_volume(slug, lang, path, volume)
    warning = None
    if not chapters:
        warning = ("No chapters found — expected headings like 'Chapter N: Title' (EN) "
                   "or '第N話/章　Title' (JA).")
    return {"project": slug, "lang": lang, "volume": volume, "chapter_count": len(chapters), "warning": warning}


@mcp.tool()
def list_chapters(lang: str = "ja", project: str | None = None, volume: int = 1) -> dict:
    """Titles + translation status for one volume's chapters (compact — no
    text). The tool to call when resuming work."""
    slug, entry = _resolve(project)
    source_lang = entry.get("source_lang", "en")
    source_chapters = _source_chapters(entry, volume)
    lang_master_chapters = _lang_chapters(entry, lang, volume) if lang != source_lang else None
    data = state.load(entry["state_dir"]) if lang_master_chapters is None and lang != source_lang else None

    out = []
    for number in sorted(source_chapters):
        title = source_chapters[number]["title"]
        if lang == source_lang:
            out.append({"number": number, "title": title, "status": "source"})
        elif lang_master_chapters is not None:
            out.append({"number": number, "title": title, "status": "approved" if number in lang_master_chapters else "not_started"})
        else:
            rec = data["chapters"].get(state.chapter_key(volume, number), {})
            lang_rec = rec.get("lang", {}).get(lang)
            out.append({"number": number, "title": title, "status": lang_rec["status"] if lang_rec else "not_started"})
    return {"project": slug, "volume": volume, "lang": lang, "chapters": out}


@mcp.tool()
def get_chapter(
    number: int,
    lang: str = "en",
    project: str | None = None,
    volume: int = 1,
    paragraph_start: int | None = None,
    paragraph_end: int | None = None,
) -> dict:
    """One chapter's text — never the whole manuscript. Master-backed languages
    read the author's docx directly. Optional paragraph_start/paragraph_end
    (1-indexed, inclusive) fetch a slice — use for follow-up discussion of
    specific passages; a full read is only needed for the review-check round.
    Italics are marked *like this*."""
    slug, entry = _resolve(project)
    source_chapters = _source_chapters(entry, volume)
    if number not in source_chapters:
        raise ValueError(f"No chapter {number} found in project '{slug}' volume {volume}.")

    lang_master_chapters = _lang_chapters(entry, lang, volume)
    if lang_master_chapters is not None:
        if number not in lang_master_chapters:
            return {
                "project": slug, "volume": volume, "number": number, "lang": lang,
                "title": source_chapters[number]["title"],
                "status": "not_started", "text": None,
            }
        text = manuscript.chapter_text(lang_master_chapters[number])
        status = "approved"
    else:
        path = _translation_file(entry["state_dir"], volume, number, lang)
        if not os.path.isfile(path):
            return {
                "project": slug, "volume": volume, "number": number, "lang": lang,
                "title": source_chapters[number]["title"],
                "status": "not_started", "text": None,
            }
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        data = state.load(entry["state_dir"])
        lang_rec = data["chapters"].get(state.chapter_key(volume, number), {}).get("lang", {}).get(lang, {})
        status = lang_rec.get("status", "draft")

    text, total_paras, sliced = _slice_paragraphs(text, paragraph_start, paragraph_end)
    result = {
        "project": slug, "volume": volume, "number": number, "lang": lang,
        "title": source_chapters[number]["title"],
        "status": status,
        "text": text,
        "char_count": manuscript.char_count(text),
        "total_paragraphs": total_paras,
    }
    if sliced:
        result["paragraph_range"] = [paragraph_start or 1, paragraph_end or total_paras]
    return result


@mcp.tool()
def get_context(chapter: int, lang: str = "ja", project: str | None = None, volume: int = 1, previous_paragraphs: int = 10) -> dict:
    """Chapter-start bundle in ONE call: full source text + the TAIL of the
    previous chapter's translation (last `previous_paragraphs` paragraphs, for
    voice/continuity; crosses volume boundaries) + glossary. Call once per
    chapter, not per turn."""
    slug, entry = _resolve(project)
    source_lang = entry.get("source_lang", "en")

    source = get_chapter(number=chapter, lang=source_lang, project=slug, volume=volume)

    previous = None
    if chapter > 1:
        source_chapters = _source_chapters(entry, volume)
        if (chapter - 1) in source_chapters:
            previous = get_chapter(number=chapter - 1, lang=lang, project=slug, volume=volume)
    elif volume > 1:
        prev_volumes = _all_volumes(entry)
        if (volume - 1) in prev_volumes:
            prev_source_chapters = _source_chapters(entry, volume - 1)
            if prev_source_chapters:
                last_num = max(prev_source_chapters)
                previous = get_chapter(number=last_num, lang=lang, project=slug, volume=volume - 1)

    if previous and previous.get("text"):
        tail, total, sliced = _slice_paragraphs(
            previous["text"],
            max(1, previous["total_paragraphs"] - previous_paragraphs + 1) if previous["total_paragraphs"] > previous_paragraphs else None,
            None,
        )
        if sliced:
            previous["text"] = tail
            previous["truncated_to_last_paragraphs"] = previous_paragraphs
            previous["note"] = "Tail only, for voice/continuity. Fetch the full chapter with get_chapter if genuinely needed."

    glossary = get_glossary(project=slug)
    notes = state.load(entry["state_dir"]).get("notes", [])

    return {
        "project": slug,
        "volume": volume,
        "chapter": chapter,
        "lang": lang,
        "source": source,
        "previous_chapter_translation": previous,
        "glossary": glossary,
        "session_notes": notes,
    }


@mcp.tool()
def search_manuscript(query: str, lang: str = "en", project: str | None = None, volume: int | None = None, max_results: int = 15) -> dict:
    """Case-insensitive substring search; returns (volume, chapter) + a short
    snippet per hit, capped at max_results. Omit `volume` to search every
    volume. Use this instead of reading chapters to hunt for a term/scene."""
    slug, entry = _resolve(project)
    query_l = query.lower()
    hits = []
    volumes_to_search = [volume] if volume is not None else _all_volumes(entry)

    for vol in volumes_to_search:
        if len(hits) >= max_results:
            break
        lang_chapters = _lang_chapters(entry, lang, vol)
        if lang_chapters is not None:
            for number in sorted(lang_chapters):
                for para in lang_chapters[number]["paragraphs"]:
                    if query_l in para.lower():
                        snippet = para if len(para) <= 220 else para[:220] + "…"
                        hits.append({"volume": vol, "chapter": number, "title": lang_chapters[number]["title"], "snippet": snippet})
                        if len(hits) >= max_results:
                            break
                if len(hits) >= max_results:
                    break
        else:
            tdir = _translations_dir(entry["state_dir"], lang)
            prefix = f"v{vol}_ch"
            if os.path.isdir(tdir):
                for fname in sorted(os.listdir(tdir)):
                    if not (fname.startswith(prefix) and fname.endswith(".txt")):
                        continue
                    number = int(fname[len(prefix):len(prefix) + 2])
                    with open(os.path.join(tdir, fname), "r", encoding="utf-8") as f:
                        content = f.read()
                    idx = content.lower().find(query_l)
                    if idx != -1:
                        start = max(0, idx - 60)
                        end = min(len(content), idx + len(query) + 60)
                        hits.append({"volume": vol, "chapter": number, "snippet": "…" + content[start:end] + "…"})
                        if len(hits) >= max_results:
                            break

    return {"project": slug, "query": query, "lang": lang, "hit_count": len(hits), "hits": hits}


@mcp.tool()
def get_glossary(project: str | None = None) -> dict:
    """Approved glossary + staged terms awaiting human review (clearly
    separated — staged terms are NOT usable until a human approves them in
    translation_state.json). Shared across a project's volumes."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    glossary = data.get("glossary", {"approved": [], "staged": []})
    return {
        "project": slug,
        "approved": glossary.get("approved", []),
        "staged_pending_review": glossary.get("staged", []),
    }


@mcp.tool()
def propose_glossary_term(term: str, translation: str, note: str = "", project: str | None = None) -> dict:
    """Stage a glossary term for human review. Never auto-commits — approval
    is a manual edit of translation_state.json, by design."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    entry_out = state.stage_glossary_term(data, term, translation, note)
    state.save(entry["state_dir"], data)
    return {"project": slug, "staged": entry_out, "message": "Staged for human review — not yet approved."}


@mcp.tool()
def save_translation(chapter: int, lang: str, text: str, status: str = "draft", project: str | None = None, volume: int = 1) -> dict:
    """Write a chapter's translation + status (draft|reviewed|approved) — ONLY
    for a (lang, volume) with no master docx. Refuses if a master is
    registered: the author's docx is the only writable artifact there."""
    slug, entry = _resolve(project)
    if _volume_path(entry, lang, volume):
        raise ValueError(
            f"Project '{slug}' volume {volume} has a registered master docx for lang '{lang}' "
            f"({_volume_path(entry, lang, volume)}). Edit that docx directly — this tool will "
            "not write a parallel export that could drift out of sync with it."
        )
    source_chapters = _source_chapters(entry, volume)
    if chapter not in source_chapters:
        raise ValueError(f"No chapter {chapter} found in project '{slug}' volume {volume}.")
    if status not in ("draft", "reviewed", "approved"):
        raise ValueError("status must be one of: draft, reviewed, approved")

    path = _translation_file(entry["state_dir"], volume, chapter, lang)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

    data = state.load(entry["state_dir"])
    rec = state.chapter_record(data, volume, chapter)
    rec["title_en"] = source_chapters[chapter]["title"]
    state.set_translation_status(data, volume, chapter, lang, status, _translation_file_rel(volume, chapter, lang))
    state.save(entry["state_dir"], data)

    return {
        "project": slug,
        "volume": volume,
        "chapter": chapter,
        "lang": lang,
        "status": status,
        "char_count": manuscript.char_count(text),
        "file": _translation_file_rel(volume, chapter, lang),
    }


@mcp.tool()
def record_note(note: str, project: str | None = None, volume: int | None = None, chapter: int | None = None) -> dict:
    """Persist a translation agreement/decision (judgment call, style
    agreement, JA-authoritative line) to disk so future fresh chats inherit it
    via get_context. Keep each note to one or two sentences. Pruning is a
    manual edit of translation_state.json."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    note_entry = state.add_note(data, note, volume=volume, chapter=chapter)
    state.save(entry["state_dir"], data)
    return {"project": slug, "recorded": note_entry, "total_notes": len(data["notes"])}


@mcp.tool()
def lint_chapter(text: str) -> dict:
    """Deterministic mechanical checks on JA prose: orthography (達・何故・貴方
    kanji rules), bracket balance + 。before ）, non-word watchlist, Latin
    leakage, 僕 density. Flags only — never rewrites, and never a substitute
    for actually reading the prose."""
    return lint_module.lint(text)


if __name__ == "__main__":
    mcp.run()
