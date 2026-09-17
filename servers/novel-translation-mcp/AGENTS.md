# novel-translation-mcp — agent notes

Answers narrow, targeted questions about a novel manuscript so a chapter can
be translated without the whole document ever entering context: chapters,
glossary, search, lint, and notes that persist between sessions.

- **`WORKFLOW.md` beside this file is the manual.** The per-chapter loop, the
  two review gates in their order, the locked orthography, the
  one-character-one-voice rule, and the token discipline the server exists
  for: a fresh chat per chapter, state restored from disk, never a
  multi-day chat. The repo's root `AGENTS.md` governs the rest, including
  the spelling and review rules.
- The author's judgment on story and intent is final; his prose still gets
  full scrutiny. Never self-polish before he reads a draft, and flag rather
  than fix, on the source text as much as on the translation. The lint tool
  is a pre-filter, never proof that the prose was read.
- After editing anything under this folder: `python -m pyflakes` over what
  you edited, and read its output after editing, not before.
