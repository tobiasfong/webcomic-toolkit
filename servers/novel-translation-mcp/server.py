"""
Novel Translation MCP — MVP
============================
A local MCP server that answers narrow, targeted questions about a novel
manuscript instead of ever putting the whole document in context. Built to fix
a specific, measured problem: translating this novel chapter-by-chapter in chat
was burning 20-30% of a usage window per session on re-reading/re-explaining the
full manuscript before any real translation work started.

Exposes six tools (see ARCHITECTURE.md §8a):
  list_chapters, get_chapter, search_manuscript,
  get_glossary, propose_glossary_term, save_translation

Human-in-the-loop by design: propose_glossary_term stages a term, it never
auto-commits. Approval is a manual edit of translation_state.json (move the
entry from "staged" to "approved") — there is no tool that does this for you.

Runs locally over stdio. No network access, no publishing/EPUB pipeline (that's
deferred — see ARCHITECTURE.md §7).
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
import manuscript
import state

mcp = FastMCP("novel-translation-mcp")

# --- Configuration -----------------------------------------------------------
# The EN manuscript is the source of truth for chapter numbers/titles. Point
# this at whichever docx is currently authoritative (per-chapter files vs. a
# compiled draft) — do not assume; verify against the individual chapter files
# if more than one candidate exists (see TRANSLATION-LESSONS.md §5.5).
MANUSCRIPT_PATH = os.environ.get(
    "NOVEL_MCP_MANUSCRIPT",
    r"C:\Users\Tomoy\Documents\Stories (Mine)\Reincarnator x Regressor I inadvertently interfered with the Villainess's second chance at life\Reincarnator x Regressor I inadvertently interfered with the Villainess's second chance at life draft 2.docx",
)
# Where translation_state.json + translations/ live — next to the manuscript,
# same pattern as the background generator's world.json living next to canon.
STATE_DIR = os.environ.get(
    "NOVEL_MCP_STATE_DIR",
    os.path.dirname(MANUSCRIPT_PATH),
)
SOURCE_LANG = os.environ.get("NOVEL_MCP_SOURCE_LANG", "en")


def _translations_dir(lang: str) -> str:
    return os.path.join(STATE_DIR, "translations", lang)


def _translation_file(number: int, lang: str) -> str:
    return os.path.join(_translations_dir(lang), f"ch{number:02d}.txt")


def _translation_file_rel(number: int, lang: str) -> str:
    return f"translations/{lang}/ch{number:02d}.txt"


def _en_chapters() -> dict[int, dict]:
    return manuscript.parse_chapters(MANUSCRIPT_PATH, "en")


@mcp.tool()
def list_chapters(lang: str = "ja") -> dict:
    """List every chapter with its title and translation status. Returns a
    compact per-chapter summary (NOT chapter text) — this is the tool to call
    when resuming work, instead of re-reading the manuscript.

    `lang`: which translation's status to report ("ja", "en", etc.). The source
    language (English) chapters are always listed as "source"; other languages
    show draft/reviewed/approved/not_started per translation_state.json.
    """
    en_chapters = _en_chapters()
    data = state.load(STATE_DIR)
    out = []
    for number in sorted(en_chapters):
        title = en_chapters[number]["title"]
        if lang == SOURCE_LANG:
            out.append({"number": number, "title": title, "status": "source"})
            continue
        rec = data["chapters"].get(str(number), {})
        lang_rec = rec.get("lang", {}).get(lang)
        out.append({
            "number": number,
            "title": title,
            "status": lang_rec["status"] if lang_rec else "not_started",
        })
    return {"lang": lang, "chapters": out}


@mcp.tool()
def get_chapter(number: int, lang: str = "en") -> dict:
    """Return ONE chapter's text — never the whole manuscript. This is the
    primary tool for doing translation work: fetch exactly the chapter you're
    translating or reviewing, nothing more.

    `lang="en"` (or whatever NOVEL_MCP_SOURCE_LANG is) reads from the source
    manuscript directly (italic runs are marked with *asterisks* — see
    TRANSLATION-LESSONS.md §1.5 on the italics→internal-thought bracket
    mapping). Any other `lang` reads the saved translation file for that
    chapter; if it hasn't been translated yet, this reports that clearly
    instead of erroring.
    """
    en_chapters = _en_chapters()
    if number not in en_chapters:
        raise ValueError(f"No chapter {number} found in the manuscript ({MANUSCRIPT_PATH}).")

    if lang == SOURCE_LANG:
        text = manuscript.chapter_text(en_chapters[number])
        return {
            "number": number,
            "lang": lang,
            "title": en_chapters[number]["title"],
            "text": text,
            "word_count": manuscript.word_count(text),
        }

    path = _translation_file(number, lang)
    if not os.path.isfile(path):
        return {
            "number": number,
            "lang": lang,
            "title": en_chapters[number]["title"],
            "status": "not_started",
            "text": None,
        }
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    data = state.load(STATE_DIR)
    lang_rec = data["chapters"].get(str(number), {}).get("lang", {}).get(lang, {})
    return {
        "number": number,
        "lang": lang,
        "title": en_chapters[number]["title"],
        "status": lang_rec.get("status", "draft"),
        "text": text,
        "char_count": manuscript.char_count(text),
    }


@mcp.tool()
def search_manuscript(query: str, lang: str = "en", max_results: int = 15) -> dict:
    """Grep-like search across the manuscript WITHOUT loading the whole
    document into context — returns matching chapters + a short snippet of
    surrounding text per hit, capped at `max_results`.

    Case-insensitive substring search. `lang="en"` searches the source
    manuscript; any other `lang` searches saved translation files for that
    language.
    """
    query_l = query.lower()
    hits = []

    if lang == SOURCE_LANG:
        en_chapters = _en_chapters()
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
        tdir = _translations_dir(lang)
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

    return {"query": query, "lang": lang, "hit_count": len(hits), "hits": hits}


@mcp.tool()
def get_glossary() -> dict:
    """Return the approved glossary (names/honorifics/recurring terms) plus
    any staged terms awaiting human approval, clearly separated. Staged terms
    are visible here so you know what's pending, but they are NOT usable as
    approved translations until a human moves them to "approved" in
    translation_state.json."""
    data = state.load(STATE_DIR)
    glossary = data.get("glossary", {"approved": [], "staged": []})
    return {
        "approved": glossary.get("approved", []),
        "staged_pending_review": glossary.get("staged", []),
    }


@mcp.tool()
def propose_glossary_term(term: str, translation: str, note: str = "") -> dict:
    """STAGE a glossary term proposal. This never auto-commits — the term is
    appended to translation_state.json's "staged" list and is NOT usable as an
    approved translation until a human explicitly moves it into "approved".
    Use this whenever you (or the model) want to suggest a new term, rather
    than silently deciding one mid-translation."""
    data = state.load(STATE_DIR)
    entry = state.stage_glossary_term(data, term, translation, note)
    state.save(STATE_DIR, data)
    return {"staged": entry, "message": "Staged for human review — not yet approved."}


@mcp.tool()
def save_translation(chapter: int, lang: str, text: str, status: str = "draft") -> dict:
    """Write a chapter's translation to disk and update its status
    (draft|reviewed|approved) in translation_state.json. This is the only tool
    that writes translated prose — it never touches the glossary.

    `status` defaults to "draft"; pass "reviewed" or "approved" once the human
    has actually read the prose (see TRANSLATION-LESSONS.md §2.7 — an
    automated pass is not a substitute for reading the chapter)."""
    en_chapters = _en_chapters()
    if chapter not in en_chapters:
        raise ValueError(f"No chapter {chapter} found in the manuscript ({MANUSCRIPT_PATH}).")
    if status not in ("draft", "reviewed", "approved"):
        raise ValueError("status must be one of: draft, reviewed, approved")

    path = _translation_file(chapter, lang)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

    data = state.load(STATE_DIR)
    rec = state.chapter_record(data, chapter)
    rec["title_en"] = en_chapters[chapter]["title"]
    state.set_translation_status(data, chapter, lang, status, _translation_file_rel(chapter, lang))
    state.save(STATE_DIR, data)

    return {
        "chapter": chapter,
        "lang": lang,
        "status": status,
        "char_count": manuscript.char_count(text),
        "file": _translation_file_rel(chapter, lang),
    }


if __name__ == "__main__":
    mcp.run()
