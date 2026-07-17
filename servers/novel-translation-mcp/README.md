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
one. Each project is a slug (`my_novel`, `another_novel`, ...) with its own
manuscript(s) and its own isolated `translation_state.json` — register a new one with
`register_project` instead of registering a whole new MCP server per book.

**Multi-manuscript per project/volume:** a language can have a REAL master docx, not
just the source language. If you maintain a proper Japanese master document (not
loose per-chapter export files), register it too — every tool then reads that
language directly from its own docx, so there is no way to audit text that has
silently drifted from what you actually wrote. See "Multi-manuscript design" below.

**Multi-volume:** a project can span more than one volume per language (Volume 1's
docx, Volume 2's docx, ...). Volumes RESTART chapter numbering — Volume 2 chapter 1
is a different chapter from Volume 1 chapter 1, same as a real published novel — so
every per-chapter tool takes a `volume` argument (default 1). The glossary stays
shared across a project's volumes. See "Multi-volume novels" below.

**Scope:** this does NOT build EPUB/CBZ/PDF assembly, covers, or synopsis generation
— that's the Publication MCP server, deferred until after the active translation
backlog is done.

## What it does

Twelve tools:

| Tool | Purpose |
|---|---|
| `list_projects()` | Every registered novel: slug, name, chapter count per language PER VOLUME |
| `register_project(name, manuscripts, ...)` | Register a new novel's Volume 1 — `manuscripts` maps lang -> docx path |
| `add_manuscript_volume(project, lang, path, volume)` | Register a SPECIFIC volume (2, 3, ...) for an existing project/language |
| `list_chapters(lang, project, volume)` | Titles + translation status for one volume's chapters — a few dozen tokens, not the manuscript |
| `get_chapter(number, lang, project, volume, paragraph_start, paragraph_end)` | One chapter's text only — optionally a paragraph slice for follow-up discussion |
| `get_context(chapter, lang, project, volume, previous_paragraphs)` | One-call bundle: source text + previous chapter's TAIL (default last 10 paragraphs; crosses volume boundaries) + glossary |
| `search_manuscript(query, lang, project, volume)` | Grep-like search across one or every volume, returns chapter + snippet per hit, capped |
| `get_glossary(project)` | Approved glossary terms (shared across volumes), plus staged terms clearly marked pending |
| `propose_glossary_term(term, translation, note, project)` | **Stages** a term — never auto-commits |
| `record_note(note, project, volume, chapter)` | Persist a mid-session agreement/decision; fresh chats inherit it via `get_context` |
| `save_translation(chapter, lang, text, status, project, volume)` | Writes a translation — refuses if that language/volume has a master docx |
| `lint_chapter(text)` | Deterministic mechanical checks (orthography, brackets, non-words, Latin leakage, pronoun density) |

When `project` is omitted: `NOVEL_MCP_DEFAULT_PROJECT` wins if set; otherwise, if
exactly one project is registered, that one is used; ambiguity is an error, never a
guess. `volume` defaults to `1`. Every response echoes back the resolved
`project`/`volume` so it's never ambiguous which manuscript you actually hit.

## Multi-manuscript design (the correctness fix, not just ergonomics)

`register_project`'s `manuscripts` parameter maps **language -> docx path (Volume
1)**, e.g.:

```python
register_project(
    name="My Novel",
    manuscripts={"en": "...Vol1 draft.docx", "ja": "...Vol1 JA master.docx"},
    source_lang="en",
)
```

Any language present in `manuscripts` is read from **its own docx directly** by
`get_chapter` and `search_manuscript` — never from a `translations/<lang>/` export
file. A language absent from `manuscripts` (for a given volume) falls back to
`translations/<lang>/v{volume}_ch{NN}.txt` exports written by `save_translation`.

**Why this matters:** an earlier version of this server only tracked one manuscript
(the source language) and treated every other language as export-only text files
written by `save_translation`. For a project where the author maintains a REAL
Japanese master docx (as the motivating project did), that meant the tool was
reading stale exported copies instead of the author's actual, current text. If the master and the exports
ever diverged, the tool would audit the wrong one silently. Reading the master
directly makes that class of bug impossible: there is nothing to drift out of sync
with, because there is only one JA artifact.

**Consequence for `save_translation`:** it now refuses (raises an error, not a silent
no-op) to write for any (language, volume) that has a registered master docx. The
error message says so explicitly. The author's docx is the only writable artifact
for it, and the author writes it — directly, in their own document, in their own
editor — not this tool. This is enforced in code, not by convention.

### Multi-volume novels

A novel can have more than one volume per language — Volume 1's docx, Volume 2's
docx, and so on. **Chapter numbering restarts at 1 for each volume**, exactly like a
real published novel series (Volume 2 chapter 1 is NOT "chapter 22"). Chapter
identity in every tool is therefore always `(volume, chapter number)` together —
that's why every per-chapter tool takes a `volume` argument.

Use `add_manuscript_volume` to register Volume 2 once Volume 1 already exists:

```python
add_manuscript_volume(project="my_novel", lang="en", path="C:\...\Volume 2 EN.docx", volume=2)
add_manuscript_volume(project="my_novel", lang="ja", path="C:\...\Volume 2 JA master.docx", volume=2)
```

This only ever touches the given `(lang, volume)` pair — unlike calling
`register_project` again (which would only ever set Volume 1 anyway; it never drops
other volumes), there's no way to lose an earlier volume's registration by accident.
The glossary and register bible stay shared across all of a project's volumes — it's
still the same characters and world, so there's no reason to re-propose settled terms
per volume.

`get_context` crosses volume boundaries correctly: asking for chapter 1 of Volume 2
pulls in the LAST chapter of Volume 1 as "previous" (continuity matters most right at
a volume break, not less), rather than reporting no previous chapter at all.

If instead a novel just keeps growing in the SAME docx file (chapters simply added to
the existing master as they're written, no separate volume files), nothing needs to
change at all — `list_chapters`/`get_chapter` already pick up new chapters as soon as
they're added to a registered file, and there's no need to touch `volume`.

## Recommended workflow — draft → review → edit → audit, not one-shot polish

This tooling is built for a specific collaborative loop, not fire-and-forget
translation — full loop in **[`WORKFLOW.md`](WORKFLOW.md)**, which is also served
directly to any connecting MCP client as this server's `instructions` (part of the
MCP protocol's own handshake — see `server.py`). That's deliberate: the workflow
travels with the server, not with one model's chat memory.

The short version: draft in chat (not a file) → append judgment-call notes/register
check/furigana manifest → explicit handoff, never auto-advance to the next chapter →
human edits their own master docx → read it back via `get_chapter(N, "ja")` → check
**collaboratively** (the human is JLPT N2, not native — his edits get the same
scrutiny as the model's draft, not silent deference) → repeat until the model's check
converges clean → only then does the human give final approval. See `WORKFLOW.md` for
why that ordering matters and the full list of what to/not to do unprompted.

`get_context` and `lint_chapter` exist to support this loop mechanically — the former
cuts the round-trips needed to start a chapter, the latter moves the purely mechanical
checks out of the model's hands entirely (see `lint_chapter`'s docstring on
"verification theater" — a regex-shaped scan is not a substitute for reading the
prose, and this tool is built so the two are never conflated).

## Design principle — human-in-the-loop, enforced at the tool level

Translation tooling here is built for **propose → review → revise → approve**, never
fire-and-forget batch translation. This isn't just a prompting convention:
`propose_glossary_term` has no code path that writes to the approved glossary. A
proposed term sits in `translation_state.json`'s `staged` array until a human
explicitly moves it into `approved` — by editing the JSON directly, or asking the
assistant to do so as an explicit, reviewed edit. There is no "approve" MCP tool on
purpose: approval is a deliberate manual act, not a mechanical one. `lint_chapter`
follows the same principle: it only flags, it never rewrites.

## Storage layout

Each project's state lives **next to its manuscript(s)**, not inside this repo — same
pattern as the background generator's `world.json` living next to its canon images.
The registry mapping project slugs to those locations (`projects.json`) lives inside
this server's folder and is gitignored (it's your personal library, not shipped code).

```
servers/novel-translation-mcp/
  projects.json                # {"my_novel": {...}, ...} — gitignored (personal paths)
  WORKFLOW.local.md            # optional personal workflow override — gitignored

<manuscript folder>/
  <EN Volume 1>.docx           # source of truth for EN Vol.1 chapter numbers/titles/text
  <JA Volume 1 master>.docx    # source of truth for JA Vol.1 text (if registered — read directly, never exported)
  <EN Volume 2>.docx           # a later volume, if any — registered via add_manuscript_volume
  translation_state.json       # THIS PROJECT'S chapter status + glossary (approved + staged) — shared across volumes
  translations/
    <lang with no master>/
      v1_ch01.txt, v1_ch02.txt, ...  # Volume 1 chapters, only for a language with NO registered master
      v2_ch01.txt, ...                # Volume 2 chapters — same lang, separate namespace (chapter numbers restart)
```

Glossaries are isolated per PROJECT (not per volume) on purpose: the same English
term can legitimately need a different translation in a different novel's voice, and
a term approved for one book should never silently leak into another — but a
project's volumes all share one glossary, since Volume 2 is still the same
characters and world as Volume 1.

No caching: every tool call re-parses each `.docx` fresh. Parsing a ~50k-word
manuscript with `python-docx` takes well under a second, and a stale in-memory copy
is a worse bug than the reparse cost — a prior version of this manuscript's
translation notes (`TRANSLATION-LESSONS.md` §5.5 — the author's private requirements
log from the original translation project, cited throughout this repo for rationale
but not shipped in it) explicitly flags "verify against the file on disk" as a
lesson learned the hard way.

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

For a brand-new novel with no prior translation, just call `register_project` from
chat — nothing to seed:

```
register_project(name="My Novel", manuscripts={"en": "C:\...\My Novel.docx"})
```

If a real master docx already exists for another language too, include it:

```
register_project(
    name="My Novel",
    manuscripts={"en": "C:\...\English.docx", "ja": "C:\...\Japanese master.docx"},
)
```

This picks a slug (`my_novel`), defaults `state_dir` to the source manuscript's
own folder, sanity-checks that the heading regex actually finds chapters in every
registered language, and returns the chapter count per language. From then on, pass
`project="my_novel"` to the other tools (or ask `list_projects()` if you forget
the slug).

### One-time bootstrap (only for a novel with pre-existing translated chapters)

If your novel already has translated chapters in a separate target-language master
docx, `bootstrap.py` registers Volume 1 with both masters in one step, and can seed
an already-decided glossary from a JSON file:

```
python bootstrap.py --project-name "My Novel" \
    --en-manuscript "C:\path\to\English.docx" \
    --ja-master "C:\path\to\Japanese master.docx" \
    --glossary-file glossary.json
```

`--glossary-file` takes a JSON array of `{"term", "translation", "note"}` objects,
imported as already-approved entries (for terms a human has already settled — new
terms should go through `propose_glossary_term`'s staged flow instead). Safe to
re-run: registration is idempotent, and glossary seeding skips terms already present.

### Configuration (environment variables)

| Var | Default | Purpose |
|---|---|---|
| `NOVEL_MCP_DEFAULT_PROJECT` | (unset — falls back to the sole registered project) | Which project a tool call uses when `project` is omitted |
| `NOVEL_MCP_PROJECTS_FILE` | `projects.json` next to this server | Where the project registry lives |

### Register with your MCP client

Add to your Claude Code / Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "novel-translation-mcp": {
      "command": "C:\\path\\to\\webcomic-toolkit\\servers\\novel-translation-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\webcomic-toolkit\\servers\\novel-translation-mcp\\server.py"]
    }
  }
}
```

## Chapter heading conventions this parser recognizes

- **EN:** `Chapter 12: The Long Road` (Arabic numerals)
- **JA:** `第十二話　長い道のり` (kanji numerals; `話` for web serialization
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

## `lint_chapter` — what it checks (and what it deliberately doesn't)

Deterministic, regex-based checks defined in `lint.py`:

- **Orthography:** 達/たち (with かたち/たちどころに exceptions), 何故/なぜ,
  貴方・貴女/あなた — this project's locked kanji-over-kana rules.
- **Brackets:** unbalanced 「」『』（）, and the "drop the trailing 。before ）" rule.
- **Non-word watchlist:** a hardcoded, growing list of confirmed hallucinated
  compounds/non-standard collocations caught in past chapters (`TRANSLATION-LESSONS.md`
  §3.2) — append to `lint.py`'s `_NONWORD_WATCHLIST` as new ones are confirmed.
- **Latin-script leakage:** runs of 2+ Latin letters, likely un-translated English.
- **Pronoun density:** 僕 per 100 characters, flagged above ~0.7 (measured target
  0.3–0.6, per `TRANSLATION-LESSONS.md` §2.2).

It deliberately does **not** check meaning-flips, register drift, wordplay adaptation,
or cultural-reference calibration — those need an actual read, not a scan
(`TRANSLATION-LESSONS.md` §2.3–§2.9, and especially §2.7's "verification theater"
warning: a clean lint result is not evidence the chapter was read).

## What this deliberately does NOT do (v2, not now)

- EPUB/CBZ/PDF assembly, covers, synopsis generation — Publication MCP server, later.
- Register-per-character profiles, dictionary-backed word validation against a real
  JMdict/Weblio API, JA-authoritative line tagging — real, valuable ideas from
  `TRANSLATION-LESSONS.md`, not yet built. Revisit when refining this server's tool
  set further, per `ARCHITECTURE.md` §8a.
- A glossary "approve" tool — approval is intentionally a manual JSON edit, not a
  mechanical one. See "Design principle" above.

## Troubleshooting

- **Tool doesn't appear in Claude Code:** full quit via tray → Quit (not just close
  window), then relaunch.
- **`get_chapter` returns `"status": "not_started"` with `text: null`:** either that
  chapter isn't in the language's master docx yet, or (for a language with no master)
  `save_translation` was never called for that chapter/lang pair. Not an error.
- **`save_translation` raises an error about a "registered master docx":** that
  language is master-backed for this project — edit the author's docx directly
  instead of calling this tool.
- **A chapter you know exists doesn't show up in `list_chapters`:** the parser found
  no heading match for it in that language's manuscript — check that the chapter's
  heading text actually matches the expected pattern (see "Chapter heading
  conventions" above).
- **"No project 'X' registered" error:** the slug doesn't exist in `projects.json` yet
  — call `list_projects()` to see what's registered, or `register_project()` to add it.
- **"No volume N registered" error, or a chapter number seems wrong:** check you're
  passing the `volume` you mean — chapter numbers restart at 1 per volume, so
  `get_chapter(1, ...)` without specifying `volume` always means Volume 1's chapter 1,
  never Volume 2's.
