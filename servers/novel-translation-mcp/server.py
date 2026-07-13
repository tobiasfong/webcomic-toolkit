"""
Novel Translation MCP
======================
A local MCP server that answers narrow, targeted questions about a novel
manuscript instead of ever putting the whole document in context. Built to fix
a specific, measured problem: translating a novel chapter-by-chapter in chat
was burning 20-30% of a usage window per session on re-reading/re-explaining
the full manuscript before any real translation work started.

Multi-project: one server instance serves every novel in your library. Each
project (a slug like "rxr" or "absolute_zero") maps to its own manuscript +
its own translation_state.json (chapter status + glossary, isolated per
project — see projects.py). Register a new novel with `register_project`;
everything else takes a `project` argument to say which one you mean.

Eight tools:
  list_projects, register_project,
  list_chapters, get_chapter, search_manuscript,
  get_glossary, propose_glossary_term, save_translation

Human-in-the-loop by design: propose_glossary_term stages a term, it never
auto-commits. Approval is a manual edit of the project's translation_state.json
(move the entry from "staged" to "approved") — there is no tool that does this
for you.

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

mcp = FastMCP("novel-translation-mcp")

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


@mcp.tool()
def list_projects() -> dict:
    """List every registered novel (project slug, display name, source
    language, chapter count). Call this first if you're not sure which
    `project` slug to pass to the other tools."""
    data = projects.load()
    out = []
    for slug, entry in sorted(data.items()):
        try:
            chapters = manuscript.parse_chapters(entry["manuscript"], entry.get("source_lang", "en"))
            chapter_count = len(chapters)
            error = None
        except manuscript.ManuscriptError as e:
            chapter_count = None
            error = str(e)
        out.append({
            "project": slug,
            "name": entry["name"],
            "source_lang": entry.get("source_lang", "en"),
            "chapter_count": chapter_count,
            "error": error,
        })
    return {"projects": out}


@mcp.tool()
def register_project(
    name: str,
    manuscript_path: str,
    source_lang: str = "en",
    state_dir: str | None = None,
    slug: str | None = None,
) -> dict:
    """Register a new novel (or update an existing one's paths). This is the
    ONLY way to point the server at a new manuscript — there's no tool that
    guesses a project from context, on purpose.

    `slug` defaults to a normalized version of `name` (e.g. "Absolute Zero" ->
    "absolute_zero") and is what you pass as `project` to every other tool.
    `state_dir` defaults to the manuscript's own folder — translation_state.json
    and translations/ will live there, isolated from every other project.
    Re-registering an existing slug updates its paths but never touches its
    existing translation_state.json.
    """
    resolved_slug, entry = projects.register(
        name=name, manuscript=manuscript_path, source_lang=source_lang,
        state_dir=state_dir, slug=slug,
    )
    chapters = manuscript.parse_chapters(entry["manuscript"], entry.get("source_lang", "en"))
    warning = None
    if not chapters:
        warning = (
            "No chapters found with the default heading pattern (EN: 'Chapter N: Title', "
            "JA: '第N話/章　Title'). Check manuscript.py's heading regexes if this manuscript "
            "titles chapters differently."
        )
    return {"project": resolved_slug, "entry": entry, "chapter_count": len(chapters), "warning": warning}


@mcp.tool()
def list_chapters(lang: str = "ja", project: str | None = None) -> dict:
    """List every chapter with its title and translation status. Returns a
    compact per-chapter summary (NOT chapter text) — this is the tool to call
    when resuming work, instead of re-reading the manuscript.

    `lang`: which translation's status to report ("ja", "en", etc.). The
    project's source language is always listed as "source"; other languages
    show draft/reviewed/approved/not_started per translation_state.json.
    """
    slug, entry = _resolve(project)
    en_chapters = manuscript.parse_chapters(entry["manuscript"], entry.get("source_lang", "en"))
    data = state.load(entry["state_dir"])
    out = []
    for number in sorted(en_chapters):
        title = en_chapters[number]["title"]
        if lang == entry.get("source_lang", "en"):
            out.append({"number": number, "title": title, "status": "source"})
            continue
        rec = data["chapters"].get(str(number), {})
        lang_rec = rec.get("lang", {}).get(lang)
        out.append({
            "number": number,
            "title": title,
            "status": lang_rec["status"] if lang_rec else "not_started",
        })
    return {"project": slug, "lang": lang, "chapters": out}


@mcp.tool()
def get_chapter(number: int, lang: str = "en", project: str | None = None) -> dict:
    """Return ONE chapter's text — never the whole manuscript. This is the
    primary tool for doing translation work: fetch exactly the chapter you're
    translating or reviewing, nothing more.

    `lang` matching the project's source language reads from the source
    manuscript directly (italic runs are marked with *asterisks* — see
    TRANSLATION-LESSONS.md §1.5 on the italics->internal-thought bracket
    mapping). Any other `lang` reads the saved translation file for that
    chapter; if it hasn't been translated yet, this reports that clearly
    instead of erroring.
    """
    slug, entry = _resolve(project)
    source_lang = entry.get("source_lang", "en")
    en_chapters = manuscript.parse_chapters(entry["manuscript"], source_lang)
    if number not in en_chapters:
        raise ValueError(f"No chapter {number} found in project '{slug}' ({entry['manuscript']}).")

    if lang == source_lang:
        text = manuscript.chapter_text(en_chapters[number])
        return {
            "project": slug,
            "number": number,
            "lang": lang,
            "title": en_chapters[number]["title"],
            "text": text,
            "word_count": manuscript.word_count(text),
        }

    path = _translation_file(entry["state_dir"], number, lang)
    if not os.path.isfile(path):
        return {
            "project": slug,
            "number": number,
            "lang": lang,
            "title": en_chapters[number]["title"],
            "status": "not_started",
            "text": None,
        }
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    data = state.load(entry["state_dir"])
    lang_rec = data["chapters"].get(str(number), {}).get("lang", {}).get(lang, {})
    return {
        "project": slug,
        "number": number,
        "lang": lang,
        "title": en_chapters[number]["title"],
        "status": lang_rec.get("status", "draft"),
        "text": text,
        "char_count": manuscript.char_count(text),
    }


@mcp.tool()
def search_manuscript(query: str, lang: str = "en", project: str | None = None, max_results: int = 15) -> dict:
    """Grep-like search across the manuscript WITHOUT loading the whole
    document into context — returns matching chapters + a short snippet of
    surrounding text per hit, capped at `max_results`.

    Case-insensitive substring search. `lang` matching the project's source
    language searches the source manuscript; any other `lang` searches saved
    translation files for that language.
    """
    slug, entry = _resolve(project)
    source_lang = entry.get("source_lang", "en")
    query_l = query.lower()
    hits = []

    if lang == source_lang:
        en_chapters = manuscript.parse_chapters(entry["manuscript"], source_lang)
        for number in sorted(en_chapters):
            for para in en_chapters[number]["paragraphs"]:
                if query_l in para.lower():
                    snippet = para if len(para) <= 220 else para[:220] + "…"
                    hits.append({"chapter": number, "title": en_chapters[number]["title"], "snippet": snippet})
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
    (draft|reviewed|approved) in the project's translation_state.json. This is
    the only tool that writes translated prose — it never touches the glossary.

    `status` defaults to "draft"; pass "reviewed" or "approved" once the human
    has actually read the prose (see TRANSLATION-LESSONS.md §2.7 — an
    automated pass is not a substitute for reading the chapter)."""
    slug, entry = _resolve(project)
    source_lang = entry.get("source_lang", "en")
    en_chapters = manuscript.parse_chapters(entry["manuscript"], source_lang)
    if chapter not in en_chapters:
        raise ValueError(f"No chapter {chapter} found in project '{slug}' ({entry['manuscript']}).")
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
    rec["title_en"] = en_chapters[chapter]["title"]
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


if __name__ == "__main__":
    mcp.run()
