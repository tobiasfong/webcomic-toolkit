# Translation workflow

Human: JLPT N2, the author. His judgment on story/intent is final; his JA prose
still gets full scrutiny — collaborative discussion, not deference.

## Loop (per chapter)

1. `get_context` once → draft IN CHAT (never a file), with numbered judgment-call
   notes, a per-character register check, and the chapter's furigana manifest.
2. End with an explicit handoff ("Where do you want to push?") — never auto-advance
   to the next chapter.
3. Human edits his master docx directly.
4. Read his version back via `get_chapter(N, "ja")` — never ask for a re-upload.
   Run the seven-class check (grammar, semantics, collocation, register,
   word-existence, consistency, naturalness) on the full prose. Flag errors AND
   improvements, with reasoning — his edits get the same scrutiny as the draft.
5. Repeat 3-4 until the check converges clean; only then does the human mark the
   chapter approved. Two gates, in that order.

## Never / always

- Never self-polish before the human reads the draft — flag, don't fix.
- Never rubber-stamp either side's text.
- Always: locked orthography (達・何故・貴方 in kanji; exceptions かたち,
  たちどころに); one character = one voice, fixed by character not listener;
  cross-chapter term consistency; search-don't-recall on cultural references; no
  English leakage. `lint_chapter` is a pre-filter, never proof the prose was read.

## Token discipline (this server exists to SAVE usage)

- Start a FRESH chat per chapter — state lives on disk; `get_context` restores it.
  Never continue a multi-day mega-chat.
- When an agreement/decision is reached mid-session (a judgment call, a style
  agreement, a JA-authoritative line), persist it with `record_note` — that's how
  fresh chats inherit it.
- In review rounds, quote ONLY the lines under discussion. Never re-print a full
  chapter the human already has.
- Use `get_chapter`'s paragraph range for follow-ups on specific passages; a full
  read is only needed for the seven-class check round.
- Call `get_context` once per chapter, not per turn.
