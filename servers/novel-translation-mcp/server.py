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

Multi-manuscript per project: a language can have a REAL master docx (not
just the source language) — e.g. an author who maintains a proper JA master
alongside the EN one, not loose per-chapter export files. Any language present
in a project's `manuscripts` map is read from its own docx directly, so the
tool can never read text that has silently drifted from what the author
actually wrote. `save_translation` refuses to write for such a language — the
author's docx is the only writable artifact for it, and the author writes it,
not the model. Languages with no master fall back to translations/<lang>/
export files, as before.

Ten tools:
  list_projects, register_project,
  list_chapters, get_chapter, get_context, search_manuscript,
  get_glossary, propose_glossary_term, save_translation,
  lint_chapter

Human-in-the-loop by design: propose_glossary_term stages a term, it never
auto-commits. Approval is a manual edit of the project's translation_state.json
(move the entry from "staged" to "approved") — there is no tool that does this
for you. Likewise lint_chapter only flags mechanical issues; it never rewrites
text, and a clean lint result is not a substitute for actually reading the
chapter (see TRANSLATION-LESSONS.md §2.7).

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


def _translations_dir(state_dir: str, lang: str) -> str:
    return os.path.join(state_dir, "translations", lang)


def _translation_file(state_dir: str, number: int, lang: str) -> str:
    return os.path.join(_translations_dir(state_dir, lang), f"ch{number:02d}.txt")


def _translation_file_rel(number: int, lang: str) -> str:
    return f"translations/{lang}/ch{number:02d}.txt"


def _source_chapters(entry: dict) -> dict[int, dict]:
    """The EN (or whatever source_lang is) chapters — the backbone list of
    chapter numbers/titles every other language's status is checked against."""
    source_lang = entry.get("source_lang", "en")
    return manuscript.parse_chapters(entry["manuscripts"][source_lang], source_lang)


def _lang_chapters(entry: dict, lang: str) -> dict[int, dict] | None:
    """Chapters parsed from THIS language's own master docx, or None if no
    master is registered for it (caller should fall back to translations/)."""
    path = entry.get("manuscripts", {}).get(lang)
    if not path:
        return None
    return manuscript.parse_chapters(path, lang)


@mcp.tool()
def list_projects() -> dict:
    """List every registered novel (project slug, display name, languages with
    a real master docx, chapter counts per language). Call this first if
    you're not sure which `project` slug to pass to the other tools."""
    data = projects.load()
    out = []
    for slug, entry in sorted(data.items()):
        lang_counts = {}
        error = None
        for lang, path in entry.get("manuscripts", {}).items():
            try:
                lang_counts[lang] = len(manuscript.parse_chapters(path, lang))
            except manuscript.ManuscriptError as e:
                lang_counts[lang] = None
                error = error or str(e)
        out.append({
            "project": slug,
            "name": entry["name"],
            "source_lang": entry.get("source_lang", "en"),
            "chapter_counts_by_lang": lang_counts,
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
    """Register a new novel (or update an existing one's paths). This is the
    ONLY way to point the server at new manuscripts — there's no tool that
    guesses a project from context, on purpose.

    `manuscripts` maps language code -> docx path, e.g.
    {"en": "C:\\...\\English draft.docx", "ja": "C:\\...\\Japanese master.docx"}.
    ANY language in this map is read from its own docx directly (never from a
    translations/<lang>/ export) — include a language here whenever a real
    master document exists for it, not just for the source language.

    `source_lang` must be a key in `manuscripts` and marks which language is
    being translated FROM. `slug` defaults to a normalized version of `name`
    (e.g. "Absolute Zero" -> "absolute_zero") and is what you pass as `project`
    to every other tool. `state_dir` defaults to the source manuscript's own
    folder. Re-registering an existing slug updates its paths but never
    touches its existing translation_state.json.
    """
    resolved_slug, entry = projects.register(
        name=name, manuscripts=manuscripts, source_lang=source_lang,
        state_dir=state_dir, slug=slug,
    )
    chapter_counts = {}
    warnings = []
    for lang, path in entry["manuscripts"].items():
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
        "chapter_counts_by_lang": chapter_counts,
        "warnings": warnings or None,
    }


@mcp.tool()
def list_chapters(lang: str = "ja", project: str | None = None) -> dict:
    """List every chapter with its title and translation status. Returns a
    compact per-chapter summary (NOT chapter text) — this is the tool to call
    when resuming work, instead of re-reading the manuscript.

    `lang`: which translation's status to report. The project's source
    language is always listed as "source". A language with its own registered
    master docx shows "approved" (present in that master) or "not_started"
    (absent) — there's no draft/reviewed state for a master-backed language,
    since the author's docx IS the state, not a status field. A language with
    no master shows draft/reviewed/approved/not_started from
    translation_state.json instead.
    """
    slug, entry = _resolve(project)
    source_lang = entry.get("source_lang", "en")
    source_chapters = _source_chapters(entry)
    lang_master_chapters = _lang_chapters(entry, lang) if lang != source_lang else None
    data = state.load(entry["state_dir"]) if lang_master_chapters is None else None

    out = []
    for number in sorted(source_chapters):
        title = source_chapters[number]["title"]
        if lang == source_lang:
            out.append({"number": number, "title": title, "status": "source"})
        elif lang_master_chapters is not None:
            out.append({"number": number, "title": title, "status": "approved" if number in lang_master_chapters else "not_started"})
        else:
            rec = data["chapters"].get(str(number), {})
            lang_rec = rec.get("lang", {}).get(lang)
            out.append({"number": number, "title": title, "status": lang_rec["status"] if lang_rec else "not_started"})
    return {"project": slug, "lang": lang, "chapters": out}


@mcp.tool()
def get_chapter(number: int, lang: str = "en", project: str | None = None) -> dict:
    """Return ONE chapter's text — never the whole manuscript. This is the
    primary tool for doing translation work: fetch exactly the chapter you're
    translating or reviewing, nothing more.

    If `lang` has its own registered master docx (see register_project), this
    reads directly from THAT docx — always the author's real, current text,
    never a possibly-stale export. Otherwise it reads a saved translation file
    for that chapter/lang; if none exists yet, this reports that clearly
    instead of erroring. Italic runs are marked with *asterisks* (this
    manuscript uses italics for internal thought — TRANSLATION-LESSONS.md §1.5).
    """
    slug, entry = _resolve(project)
    source_chapters = _source_chapters(entry)
    if number not in source_chapters:
        raise ValueError(f"No chapter {number} found in project '{slug}'.")

    lang_master_chapters = _lang_chapters(entry, lang)
    if lang_master_chapters is not None:
        if number not in lang_master_chapters:
            return {
                "project": slug, "number": number, "lang": lang,
                "title": source_chapters[number]["title"],
                "status": "not_started", "text": None,
            }
        text = manuscript.chapter_text(lang_master_chapters[number])
        return {
            "project": slug, "number": number, "lang": lang,
            "title": source_chapters[number]["title"],
            "status": "approved",
            "text": text,
            "word_count": manuscript.word_count(text),
            "char_count": manuscript.char_count(text),
        }

    path = _translation_file(entry["state_dir"], number, lang)
    if not os.path.isfile(path):
        return {
            "project": slug, "number": number, "lang": lang,
            "title": source_chapters[number]["title"],
            "status": "not_started", "text": None,
        }
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    data = state.load(entry["state_dir"])
    lang_rec = data["chapters"].get(str(number), {}).get("lang", {}).get(lang, {})
    return {
        "project": slug, "number": number, "lang": lang,
        "title": source_chapters[number]["title"],
        "status": lang_rec.get("status", "draft"),
        "text": text,
        "char_count": manuscript.char_count(text),
    }


@mcp.tool()
def get_context(chapter: int, lang: str = "ja", project: str | None = None) -> dict:
    """Composite call for STARTING work on a chapter: the source-language text
    for this chapter, the previous chapter's translation (for register/voice/
    plot continuity — TRANSLATION-LESSONS.md §6.2 on why cross-chapter context
    matters), and the current glossary (approved + staged). Replaces the 3-4
    separate round-trips (get_chapter x2 + get_glossary) that starting a
    chapter used to need.
    """
    slug, entry = _resolve(project)
    source_lang = entry.get("source_lang", "en")

    source = get_chapter(number=chapter, lang=source_lang, project=slug)

    previous = None
    if chapter > 1:
        source_chapters = _source_chapters(entry)
        if (chapter - 1) in source_chapters:
            previous = get_chapter(number=chapter - 1, lang=lang, project=slug)

    glossary = get_glossary(project=slug)

    return {
        "project": slug,
        "chapter": chapter,
        "lang": lang,
        "source": source,
        "previous_chapter_translation": previous,
        "glossary": glossary,
    }


@mcp.tool()
def search_manuscript(query: str, lang: str = "en", project: str | None = None, max_results: int = 15) -> dict:
    """Grep-like search across the manuscript WITHOUT loading the whole
    document into context — returns matching chapters + a short snippet of
    surrounding text per hit, capped at `max_results`.

    Case-insensitive substring search. If `lang` has its own registered master
    docx, searches that docx directly; otherwise searches saved translation
    files for that language.
    """
    slug, entry = _resolve(project)
    query_l = query.lower()
    hits = []

    lang_master_chapters = _lang_chapters(entry, lang)
    if lang_master_chapters is not None:
        for number in sorted(lang_master_chapters):
            for para in lang_master_chapters[number]["paragraphs"]:
                if query_l in para.lower():
                    snippet = para if len(para) <= 220 else para[:220] + "…"
                    hits.append({"chapter": number, "title": lang_master_chapters[number]["title"], "snippet": snippet})
                    if len(hits) >= max_results:
                        break
            if len(hits) >= max_results:
                break
    else:
        tdir = _translations_dir(entry["state_dir"], lang)
        if os.path.isdir(tdir):
            for fname in sorted(os.listdir(tdir)):
                if not fname.endswith(".txt"):
                    continue
                number = int(fname[2:4])
                with open(os.path.join(tdir, fname), "r", encoding="utf-8") as f:
                    content = f.read()
                idx = content.lower().find(query_l)
                if idx != -1:
                    start = max(0, idx - 60)
                    end = min(len(content), idx + len(query) + 60)
                    hits.append({"chapter": number, "snippet": "…" + content[start:end] + "…"})
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
    per-project — a term approved in one novel has no effect on another."""
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
def save_translation(chapter: int, lang: str, text: str, status: str = "draft", project: str | None = None) -> dict:
    """Write a chapter's translation to disk and update its status
    (draft|reviewed|approved) in the project's translation_state.json.

    Refuses to write if `lang` has its own registered master docx — for such a
    language, the author's docx is the ONLY writable artifact, and the author
    writes it directly (in their own document, in their own editor), not this
    tool. This is deliberate: a fallback export file that can silently drift
    out of sync with the real master is exactly the class of bug that leads
    the tool to audit stale text (see register_project's docstring). Call this
    only for a language with NO registered master.
    """
    slug, entry = _resolve(project)
    if entry.get("manuscripts", {}).get(lang):
        raise ValueError(
            f"Project '{slug}' has a registered master docx for lang '{lang}' "
            f"({entry['manuscripts'][lang]}). That docx is the only writable artifact "
            "for this language — edit it directly; this tool will not write a "
            "parallel export that could drift out of sync with it."
        )
    source_chapters = _source_chapters(entry)
    if chapter not in source_chapters:
        raise ValueError(f"No chapter {chapter} found in project '{slug}'.")
    if status not in ("draft", "reviewed", "approved"):
        raise ValueError("status must be one of: draft, reviewed, approved")

    path = _translation_file(entry["state_dir"], chapter, lang)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

    data = state.load(entry["state_dir"])
    rec = state.chapter_record(data, chapter)
    rec["title_en"] = source_chapters[chapter]["title"]
    state.set_translation_status(data, chapter, lang, status, _translation_file_rel(chapter, lang))
    state.save(entry["state_dir"], data)

    return {
        "project": slug,
        "chapter": chapter,
        "lang": lang,
        "status": status,
        "char_count": manuscript.char_count(text),
        "file": _translation_file_rel(chapter, lang),
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
