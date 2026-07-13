# Novel Translation MCP

A local [Model Context Protocol](https://modelcontextprotocol.io) server that answers
**narrow, targeted questions about a novel manuscript** instead of ever putting the
whole document in context.

It exists to fix one measured, concrete problem: translating a ~50k-word novel
chapter-by-chapter in chat was burning 20–30% of a usage window per session on
re-reading/re-explaining the full manuscript before any real translation work
started. This server replaces "re-read the whole document" with "ask a targeted
question" — the same fix as the Artist Colony MCP server (`find_available_people`,
`get_resourcing_snapshot`) applied to a raw spreadsheet.

**Golden rule for every tool here: return small, targeted excerpts — never the whole
manuscript.**

**Multi-project:** one server instance serves every novel in your library, not just
one. Each project is a slug (`rxr`, `absolute_zero`, ...) with its own manuscript and
its own isolated `translation_state.json` — register a new one with `register_project`
instead of registering a whole new MCP server per book.

**Scope:** this does NOT build EPUB/CBZ/PDF assembly, covers, or synopsis generation
— that's the Publication MCP server, deferred until after the active translation
backlog is done.

## What it does

Eight tools, all reading/writing a `.docx` manuscript and a per-project JSON state
file next to it:

| Tool | Purpose |
|---|---|
| `list_projects()` | Every registered novel: slug, name, source language, chapter count |
| `register_project(name, manuscript_path, ...)` | Register a new novel (or update an existing one's paths) |
| `list_chapters(lang, project)` | Titles + translation status per chapter — a few dozen tokens, not the manuscript |
| `get_chapter(number, lang, project)` | One chapter's text only (source language or a saved translation) |
| `search_manuscript(query, lang, project)` | Grep-like search, returns chapter + snippet per hit, capped |
| `get_glossary(project)` | Approved glossary terms, plus staged terms clearly marked pending |
| `propose_glossary_term(term, translation, note, project)` | **Stages** a term — never auto-commits |
| `save_translation(chapter, lang, text, status, project)` | Writes a chapter's translation, updates its status |

`project` defaults to `NOVEL_MCP_DEFAULT_PROJECT` (currently `rxr`) when omitted, so
existing single-novel calls keep working — every response echoes back the resolved
`project` slug so it's never ambiguous which manuscript you actually hit.

## Design principle — human-in-the-loop, enforced at the tool level

Translation tooling here is built for **propose → review → revise → approve**, never
fire-and-forget batch translation. This isn't just a prompting convention:
`propose_glossary_term` has no code path that writes to the approved glossary. A
proposed term sits in `translation_state.json`'s `staged` array until a human
explicitly moves it into `approved` — by editing the JSON directly, or asking the
assistant to do so as an explicit, reviewed edit. There is no "approve" MCP tool on
purpose: approval is a deliberate manual act, not a mechanical one.

## Storage layout

Each project's state lives **next to its manuscript**, not inside this repo — same
pattern as the background generator's `world.json` living next to its canon images.
The registry mapping project slugs to those locations (`projects.json`) lives inside
this server's folder and is gitignored (it's your personal library, not shipped code).

```
servers/novel-translation-mcp/
  projects.json                # {"rxr": {...}, "absolute_zero": {...}, ...} — gitignored

<manuscript A's folder>/
  <manuscript>.docx           # source of truth for chapter numbers/titles (you own this)
  translation_state.json      # THIS PROJECT'S chapter status + glossary (approved + staged)
  translations/
    ja/
      ch01.txt … ch18.txt     # already-translated chapters (seeded by bootstrap.py)
      ch19.txt                # written by save_translation as work progresses

<manuscript B's folder>/
  translation_state.json      # a completely separate glossary/status — no cross-talk
  ...
```

Glossaries and chapter statuses are isolated per project on purpose: the same
English term can legitimately need a different translation in a different novel's
voice, and a term approved for one book should never silently leak into another.

No caching: every tool call re-parses the `.docx` fresh. Parsing a ~50k-word
manuscript with `python-docx` takes well under a second, and a stale in-memory copy
is a worse bug than the reparse cost — a prior version of this manuscript's
translation notes (`TRANSLATION-LESSONS.md` §5.5) explicitly flags "verify against the
file on disk" as a lesson learned the hard way.

## Setup

Requirements: Python 3.10+, no GPU needed (CPU-only, matches the rest of the
ecosystem's non-ComfyUI servers).

```
cd servers/novel-translation-mcp
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Adding a new novel

For a brand-new novel with no prior translation, just call the `register_project`
tool from chat (or run it via the MCP inspector) — nothing to seed:

```
register_project(name="Absolute Zero", manuscript_path="C:\...\Absolute Zero.docx")
```

This picks a slug (`absolute_zero`), defaults `state_dir` to the manuscript's own
folder, sanity-checks that the heading regex actually finds chapters, and returns the
chapter count it found. From then on, pass `project="absolute_zero"` to the other
tools (or ask `list_projects()` if you forget the slug).

### One-time bootstrap (only for a novel with pre-existing translated chapters)

RxR specifically had 18 chapters already translated into a separate JA master docx
before this server existed. `bootstrap.py` is what seeded that one:

```
python bootstrap.py
```

It registers the project, splits the existing JA master into `translations/ja/chNN.txt`
files (marked `approved` — they're already-settled prose, not open for revision by
this tool), and seeds the approved glossary from `TRANSLATION-LESSONS.md`'s core
terminology table. Seeding refuses to run if that project's `translation_state.json`
already exists (pass `--force` to re-seed on purpose); registration always re-runs
(idempotent). Pass `--project-slug`/`--project-name`/`--en-manuscript`/`--ja-master`
to point it at a different novel that also has a pre-existing translated draft.

### Configuration (environment variables)

| Var | Default | Purpose |
|---|---|---|
| `NOVEL_MCP_DEFAULT_PROJECT` | `rxr` | Which project a tool call uses when `project` is omitted |
| `NOVEL_MCP_PROJECTS_FILE` | `projects.json` next to this server | Where the project registry lives |

### Register with your MCP client

Add to your Claude Code / Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "novel-translation-mcp": {
      "command": "C:\\Users\\Tomoy\\webcomic-toolkit\\servers\\novel-translation-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\Tomoy\\webcomic-toolkit\\servers\\novel-translation-mcp\\server.py"]
    }
  }
}
```

## Chapter heading conventions this parser recognizes

- **EN:** `Chapter 19: Actually, I'm not the Saintess` (Arabic numerals)
- **JA:** `第十九話　実は聖女ではありません` (kanji numerals; `話` for web serialization
  or `章` for a bound-volume convention — both recognized)

If your manuscript titles chapters differently, adjust the regexes in
`manuscript.py` (`_EN_HEADING_RE` / `_JA_HEADING_RE`) — don't assume a heading style;
per `TRANSLATION-LESSONS.md` §5.5, the author's actual headings don't always match
what was agreed, so this parser matches on plain-text pattern, not a Word "Heading N"
style (this manuscript doesn't use Word heading styles at all — every paragraph in it
is styled `Normal`).

Italic runs in the EN source are wrapped in `*asterisks*` in the returned text — this
manuscript uses italics to mark internal thought, which maps to `（　）` brackets in
the Japanese translation (`TRANSLATION-LESSONS.md` §1.5). Plain-text extraction tools
like `pandoc -t plain` silently drop italics; this parser reads runs directly so that
signal survives.

## What this deliberately does NOT do (v2, not now)

- EPUB/CBZ/PDF assembly, covers, synopsis generation — Publication MCP server, later.
- Automated linting (達/たち, orthography rules, register-per-character profiles,
  dictionary-backed word validation) — real, valuable ideas from
  `TRANSLATION-LESSONS.md`, not yet built. Revisit when refining this server's tool
  set further, per `ARCHITECTURE.md` §8a.
- A glossary "approve" tool — approval is intentionally a manual JSON edit, not a
  mechanical one. See "Design principle" above.

## Troubleshooting

- **Tool doesn't appear in Claude Code:** full quit via tray → Quit (not just close
  window), then relaunch.
- **`get_chapter` returns `"status": "not_started"` with `text: null`:** that
  chapter has no saved translation yet — this is not an error, it's `save_translation`
  never having been called for that chapter/lang pair.
- **A chapter you know exists doesn't show up in `list_chapters`:** the parser found
  no heading match for it in the source manuscript — check that the chapter's heading
  text actually matches `Chapter N: ...` (see "Chapter heading conventions" above).
- **"No project 'X' registered" error:** the slug doesn't exist in `projects.json` yet
  — call `list_projects()` to see what's registered, or `register_project()` to add it.
