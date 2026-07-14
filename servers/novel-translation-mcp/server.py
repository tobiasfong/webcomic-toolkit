"""
Novel Translation MCP
======================
A local MCP server that answers narrow, targeted questions about a novel
manuscript instead of ever putting the whole document in context. Built to fix
a specific, measured problem: translating a novel chapter-by-chapter in chat
was burning 20-30% of a usage window per session on re-reading/re-explaining
the full manuscript before any real translation work started.

Multi-project: one server instance serves every novel in your library. Each
project (a slug like "rxr" or "absolute_zero") maps to its own manuscript(s) +
its own translation_state.json (chapter status + glossary, isolated per
project — see projects.py). Register a new novel with `register_project`;
everything else takes a `project` argument to say which one you mean.

Multi-volume: a project can have more than one volume per language (Volume
1's docx, Volume 2's docx, ...). Volumes RESTART chapter numbering — Volume 2
chapter 1 is a different chapter from Volume 1 chapter 1, same as a real
published novel — so every per-chapter tool takes a `volume` argument
(defaults to 1) alongside `number`/`chapter`. The glossary and register bible
stay shared across a project's volumes on purpose: it's still the same
characters and world.

Multi-manuscript per project/volume: a language can have a REAL master docx
for a given volume, not just the source language. Any (language, volume) with
a registered master is read from that docx directly — never from a
translations/<lang>/ export file — so the tool can never read text that has
silently drifted from what the author actually wrote. `save_translation`
refuses to write for such a (language, volume): the author's docx is the only
writable artifact for it, and the author writes it, not the model.

Twelve tools:
  list_projects, register_project, add_manuscript_volume,
  list_chapters, get_chapter, get_context, search_manuscript,
  get_glossary, propose_glossary_term, save_translation,
  lint_chapter

Human-in-the-loop by design: propose_glossary_term stages a term, it never
auto-commits. Approval is a manual edit of the project's translation_state.json
(move the entry from "staged" to "approved") — there is no tool that does this
for you. Likewise lint_chapter only flags mechanical issues; it never rewrites
text, and a clean lint result is not a substitute for actually reading the
chapter (see TRANSLATION-LESSONS.md §2.7). See WORKFLOW.md (served as this
server's `instructions`) for the full collaborative review loop.

Runs locally over stdio. No network access, no publishing/EPUB pipeline (that's
deferred — see ARCHITECTURE.md §7).
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
import manuscript
import state
import projects
import lint as lint_module

# WORKFLOW.md is the single source of truth for the collaborative translation
# loop this server is built for. Passing its content as `instructions` puts it
# in the MCP protocol's own initialize handshake, so ANY connecting client
# gets it automatically — the workflow travels with the tool, not with one
# model's chat memory. Edit WORKFLOW.md, not this string.
_WORKFLOW_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "WORKFLOW.md")
with open(_WORKFLOW_PATH, "r", encoding="utf-8") as _f:
    _WORKFLOW_INSTRUCTIONS = _f.read()

mcp = FastMCP("novel-translation-mcp", instructions=_WORKFLOW_INSTRUCTIONS)

# Convenience default so calls that omit `project` keep working for whichever
# novel is the "current" one — but every response echoes back the resolved
# project slug, so it's never ambiguous which manuscript you actually hit.
DEFAULT_PROJECT = os.environ.get("NOVEL_MCP_DEFAULT_PROJECT", "rxr")


def _resolve(project: str | None) -> tuple[str, dict]:
    slug = project or DEFAULT_PROJECT
    return slug, projects.resolve(slug)


def _volume_path(entry: dict, lang: str, volume: int) -> str | None:
    return entry.get("manuscripts", {}).get(lang, {}).get(str(volume))


def _all_volumes(entry: dict) -> list[int]:
    """Volume numbers that exist for this project, per its source language
    (every volume must have a source-language manuscript by definition)."""
    source_lang = entry.get("source_lang", "en")
    return sorted(int(v) for v in entry.get("manuscripts", {}).get(source_lang, {}))


def _source_chapters(entry: dict, volume: int) -> dict[int, dict]:
    source_lang = entry.get("source_lang", "en")
    path = _volume_path(entry, source_lang, volume)
    if not path:
        raise ValueError(f"No volume {volume} registered for source lang '{source_lang}'.")
    return manuscript.parse_chapters(path, source_lang)


def _lang_chapters(entry: dict, lang: str, volume: int) -> dict[int, dict] | None:
    """Chapters parsed from THIS language's own master docx for THIS volume,
    or None if no master is registered for it (caller should fall back to
    translations/)."""
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


@mcp.tool()
def list_projects() -> dict:
    """List every registered novel (project slug, display name, chapter count
    per language PER VOLUME). Call this first if you're not sure which
    `project` slug (or which volume) to pass to the other tools."""
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
    """Register a new novel's Volume 1 (or fix Volume 1's paths/metadata for
    an existing project — this never touches any other volume). For Volume 2
    and beyond, use add_manuscript_volume instead.

    `manuscripts` maps language code -> docx path for volume 1, e.g.
    {"en": "C:\\...\\English draft.docx", "ja": "C:\\...\\Japanese master.docx"}.
    ANY language in this map is read from its own docx directly (never from a
    translations/<lang>/ export) — include a language here whenever a real
    master document exists for it, not just for the source language.

    `source_lang` must be a key in `manuscripts` and marks which language is
    being translated FROM. `slug` defaults to a normalized version of `name`
    (e.g. "Absolute Zero" -> "absolute_zero") and is what you pass as `project`
    to every other tool. `state_dir` defaults to the source manuscript's own
    folder.
    """
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
                f"No chapters found for lang '{lang}' with the default heading pattern "
                "(EN: 'Chapter N: Title', JA: '第N話/章　Title'). Check manuscript.py's "
                "heading regexes if this manuscript titles chapters differently."
            )
    return {
        "project": resolved_slug,
        "entry": entry,
        "volume_1_chapter_counts_by_lang": chapter_counts,
        "warnings": warnings or None,
    }


@mcp.tool()
def add_manuscript_volume(project: str, lang: str, path: str, volume: int) -> dict:
    """Register a SPECIFIC volume number's manuscript for an ALREADY-
    registered project/language — e.g. `volume=2` for Volume 2's own docx.
    Volume 2 RESTARTS chapter numbering at 1 (same as a real published novel
    volume) — this is not a continuation of Volume 1's chapter count. Only
    this (lang, volume) pair is changed; every other volume's registration is
    left untouched, so this can never accidentally drop an earlier volume.
    """
    slug, entry = _resolve(project)
    if not os.path.isfile(path):
        raise ValueError(f"Manuscript not found: {path}")
    chapters = manuscript.parse_chapters(path, lang)
    projects.add_volume(slug, lang, path, volume)
    warning = None
    if not chapters:
        warning = (
            "No chapters found with the default heading pattern "
            "(EN: 'Chapter N: Title', JA: '第N話/章　Title'). Check manuscript.py's "
            "heading regexes if this manuscript titles chapters differently."
        )
    return {"project": slug, "lang": lang, "volume": volume, "chapter_count": len(chapters), "warning": warning}


@mcp.tool()
def list_chapters(lang: str = "ja", project: str | None = None, volume: int = 1) -> dict:
    """List every chapter IN ONE VOLUME with its title and translation status.
    Returns a compact per-chapter summary (NOT chapter text) — this is the
    tool to call when resuming work, instead of re-reading the manuscript.
    Chapter numbers restart at 1 per volume, so this is always scoped to one
    `volume` (default 1).

    `lang`: which translation's status to report. The project's source
    language is always listed as "source". A language with its own registered
    master docx FOR THIS VOLUME shows "approved" (present in that master) or
    "not_started" (absent) — there's no draft/reviewed state for a
    master-backed volume, since the author's docx IS the state. A language
    with no master for this volume shows draft/reviewed/approved/not_started
    from translation_state.json instead.
    """
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
def get_chapter(number: int, lang: str = "en", project: str | None = None, volume: int = 1) -> dict:
    """Return ONE chapter's text — never the whole manuscript. This is the
    primary tool for doing translation work: fetch exactly the chapter you're
    translating or reviewing, nothing more. Chapter numbers restart at 1 per
    volume, so specify `volume` (default 1) alongside `number`.

    If `lang` has its own registered master docx for THIS volume, this reads
    directly from THAT docx — always the author's real, current text, never
    a possibly-stale export. Otherwise it reads a saved translation file for
    that chapter/lang/volume; if none exists yet, this reports that clearly
    instead of erroring. Italic runs are marked with *asterisks* (this
    manuscript uses italics for internal thought — TRANSLATION-LESSONS.md §1.5).
    """
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
        return {
            "project": slug, "volume": volume, "number": number, "lang": lang,
            "title": source_chapters[number]["title"],
            "status": "approved",
            "text": text,
            "word_count": manuscript.word_count(text),
            "char_count": manuscript.char_count(text),
        }

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
    return {
        "project": slug, "volume": volume, "number": number, "lang": lang,
        "title": source_chapters[number]["title"],
        "status": lang_rec.get("status", "draft"),
        "text": text,
        "char_count": manuscript.char_count(text),
    }


@mcp.tool()
def get_context(chapter: int, lang: str = "ja", project: str | None = None, volume: int = 1) -> dict:
    """Composite call for STARTING work on a chapter: the source-language text
    for this chapter, the previous chapter's translation (for register/voice/
    plot continuity — TRANSLATION-LESSONS.md §6.2), and the current glossary
    (approved + staged). Replaces the 3-4 separate round-trips (get_chapter x2
    + get_glossary) that starting a chapter used to need.

    "Previous chapter" crosses a volume boundary correctly: for chapter 1 of
    a volume > 1, it pulls the LAST chapter of the PREVIOUS volume (continuity
    matters most right at a volume break, not less), rather than reporting
    "no previous chapter."
    """
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

    glossary = get_glossary(project=slug)

    return {
        "project": slug,
        "volume": volume,
        "chapter": chapter,
        "lang": lang,
        "source": source,
        "previous_chapter_translation": previous,
        "glossary": glossary,
    }


@mcp.tool()
def search_manuscript(query: str, lang: str = "en", project: str | None = None, volume: int | None = None, max_results: int = 15) -> dict:
    """Grep-like search WITHOUT loading the whole document into context —
    returns matching (volume, chapter) + a short snippet per hit, capped at
    `max_results`. Case-insensitive substring search.

    `volume`: search just one volume, or omit to search EVERY registered
    volume (each hit is tagged with which volume it came from). If `lang` has
    its own registered master for a given volume, that volume is searched
    directly from its docx; otherwise saved translation files for that
    language/volume are searched instead.
    """
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
    """Return the approved glossary (names/honorifics/recurring terms) for
    this project, plus any staged terms awaiting human approval, clearly
    separated. Staged terms are visible here so you know what's pending, but
    they are NOT usable as approved translations until a human moves them to
    "approved" in that project's translation_state.json. Glossaries are
    per-project (shared across all of a project's volumes on purpose) — a
    term approved in one novel has no effect on another."""
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
    """STAGE a glossary term proposal for this project. This never
    auto-commits — the term is appended to the project's translation_state.json
    "staged" list and is NOT usable as an approved translation until a human
    explicitly moves it into "approved". Use this whenever you (or the model)
    want to suggest a new term, rather than silently deciding one mid-translation."""
    slug, entry = _resolve(project)
    data = state.load(entry["state_dir"])
    entry_out = state.stage_glossary_term(data, term, translation, note)
    state.save(entry["state_dir"], data)
    return {"project": slug, "staged": entry_out, "message": "Staged for human review — not yet approved."}


@mcp.tool()
def save_translation(chapter: int, lang: str, text: str, status: str = "draft", project: str | None = None, volume: int = 1) -> dict:
    """Write a chapter's translation to disk and update its status
    (draft|reviewed|approved) in the project's translation_state.json.
    Chapter numbers restart at 1 per volume, so specify `volume` (default 1)
    alongside `chapter`.

    Refuses to write if `lang` has its own registered master docx for THIS
    volume — for such a (language, volume), the author's docx is the ONLY
    writable artifact, and the author writes it directly, not this tool. This
    is deliberate: a fallback export file that can silently drift out of sync
    with the real master is exactly the class of bug that leads the tool to
    audit stale text. Call this only for a (language, volume) with NO
    registered master.
    """
    slug, entry = _resolve(project)
    if _volume_path(entry, lang, volume):
        raise ValueError(
            f"Project '{slug}' volume {volume} has a registered master docx for lang '{lang}' "
            f"({_volume_path(entry, lang, volume)}). That docx is the only writable artifact "
            "for this language/volume — edit it directly; this tool will not write a "
            "parallel export that could drift out of sync with it."
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
def lint_chapter(text: str) -> dict:
    """Run deterministic mechanical checks on a chunk of Japanese prose:
    orthography (達/何故/貴方 kanji rules), bracket balance + the "drop 。
    before ）" rule, a watchlist of confirmed non-words/bad compounds, Latin-
    script leakage, and 僕 pronoun density.

    This is a FLAG-ONLY tool — it never rewrites text, and none of its
    findings should be auto-applied. It also is NOT a substitute for actually
    reading the chapter: it catches mechanical issues, not meaning-flips,
    register drift, or wordplay problems, which need a real read
    (TRANSLATION-LESSONS.md §2.3-2.9, §2.7's "verification theater" warning).
    """
    return lint_module.lint(text)


if __name__ == "__main__":
    mcp.run()
