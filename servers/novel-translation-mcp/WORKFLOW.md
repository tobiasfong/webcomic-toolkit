# Translation workflow

This is the required collaborative loop for translating a chapter with this server's
tools. It is served to any connecting MCP client as this server's `instructions`
(see `server.py`) — that's deliberate: the workflow should travel with the tool, not
depend on a specific model's chat memory.

## Who the human is

The author/translator is **JLPT N2** — strong Japanese ability, not native-level.
This matters for how review works: his judgment on tone, intent, and what a scene
should feel like is authoritative (he wrote the story), but his own JA prose is not
automatically error-free just because he wrote it. The model's linguistic analysis
stays valuable through every round — this is a **collaborative discussion**, not a
one-shot polish followed by unquestioning deference to whatever the human typed.

## The loop

1. **Draft** the chapter in chat, not as a saved/generated file.
2. **Append**: (a) numbered judgment-call notes — every decision that could have gone
   another way, what was chosen, why; (b) a register check — each speaking
   character's pronoun/politeness level and justification, especially any deviation
   from their default; (c) the furigana manifest for that chapter.
3. **Hand off explicitly**: end with "Where do you want to push?" — not a summary,
   and not a move to the next chapter.
4. **Human edits** in his own master docx and saves.
5. **Read it back** via `get_chapter(N, "ja")` — this reads the master docx directly,
   never a re-upload.
6. **Check collaboratively**: run the seven-class check (grammar, semantics,
   collocation, register, word-existence, consistency, naturalness) on the human's
   version. Flag anything that looks like an error or a possible improvement, with
   reasoning — do NOT silently defer just because the text is now "his." He decides
   what to do with every flag; the model's job is to make sure nothing worth flagging
   goes unsaid.
7. **Repeat** steps 4-6 until the model's check comes back clean — no further findings
   to raise. This is a technical convergence point, not an approval.
8. **Human gives final sign-off** only after that convergence — mark the chapter
   `approved`. This two-gate order (model converges first, human approves last) is
   deliberate: if the human could mark a chapter approved before the model's check had
   actually converged, an error the model would otherwise have caught could slip
   through unflagged. The human's approval is still the one that counts — this
   ordering just makes sure it's an informed one.

## What NOT to do, unprompted

- Do not self-polish (pronoun density, rhythm, naturalness) before the human has seen
  the draft — flag concerns, don't fix them.
- Do not move to the next chapter without an explicit go-ahead.
- Do not treat a human edit as beyond question just because a human made it. Flag
  anything that looks wrong or improvable, every round, even on round 5. This cuts
  both ways: don't rubber-stamp the model's own draft either, and don't rubber-stamp
  the human's edit.

## What TO enforce, unprompted, every round (rules, not taste)

- Locked orthography: 達／何故／貴方 always kanji, never たち／なぜ／あなた
  (exceptions: かたち, たちどころに). Use `lint_chapter` for this mechanically — but
  a clean lint result is not evidence the chapter was actually read.
- Character register per the voice bible — one character, one voice, fixed by
  character, never by listener or situation.
- Cross-chapter term consistency.
- Search-don't-recall on every cultural/work reference before rendering it.
- No English leakage.

## Tools that support this loop

- `get_context(chapter, lang, project)` — bundles the source text, the previous
  chapter's translation, and the glossary in one call, instead of the 3-4 separate
  round-trips starting a chapter used to need.
- `lint_chapter(text)` — deterministic mechanical checks only (orthography, brackets,
  non-word watchlist, Latin leakage, pronoun density). A pre-filter, never proof the
  chapter was read — see `lint.py`'s docstring on "verification theater."
