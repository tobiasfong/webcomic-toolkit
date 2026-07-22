# Translation workflow

Served to every connecting MCP client as this server's `instructions`. To customize
(your translator profile, house style, language pair), create `WORKFLOW.local.md`
next to this file — it's gitignored and overrides this one when present.

The human translator's judgment on story/intent is final (they are the author or
the author's translator); their prose still gets full scrutiny every round — this
is a collaborative discussion, not deference in either direction.

## Loop (per chapter)

1. `get_context` once → this returns the source-language chapter.
2. Proofread the source chapter first: flag grammar, vocabulary, spelling, and
   contextual/continuity issues in the source itself, same flag-don't-fix rule as
   the target-language check below. Source errors should surface before they get
   translated, not carried through silently.
3. Draft the target-language translation IN CHAT (never a file), with numbered
   judgment-call notes, a per-character register check, and any reading-gloss
   manifest.
4. End with an explicit handoff — never auto-advance to the next chapter.
5. Human edits their master docx directly (target language, and source if step 2
   flagged anything).
6. Read their version back via `get_chapter` — never ask for a re-upload. Run the
   seven-class check (grammar, semantics, collocation, register, word-existence,
   consistency, naturalness) on the full prose. Flag errors AND improvements, with
   reasoning.
7. Repeat 5-6 until the check converges clean; only then does the human mark the
   chapter approved. Two gates, in that order.

## Never / always

- Never self-polish before the human reads the draft — flag, don't fix. This
  applies to the source-language proofread (step 2) too, not just the translation.
- Never rubber-stamp either side's text.
- Always: the project's locked orthography and register rules (see `lint_chapter`
  and the glossary); one character = one voice, fixed by character not listener;
  cross-chapter term consistency; search-don't-recall on cultural references; no
  source-language leakage. `lint_chapter` is a pre-filter, never proof the prose
  was read.

## Token discipline (this server exists to SAVE usage)

- Start a FRESH chat per chapter — state lives on disk; `get_context` restores it.
  Never continue a multi-day mega-chat.
- When an agreement/decision is reached mid-session, persist it with `record_note`
  — that's how fresh chats inherit it.
- In review rounds, quote ONLY the lines under discussion. Never re-print a full
  chapter the human already has.
- Use `get_chapter`'s paragraph range for follow-ups on specific passages; a full
  read is only needed for the review-check round.
- Call `get_context` once per chapter, not per turn.
