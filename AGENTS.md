# AGENTS.md — Anime Production Skill

This repository is a self-contained **agent skill**: instructions plus bundled
source that let an AI coding agent — Claude Code, OpenAI Codex, Google
Antigravity, Gemini CLI, Cursor, or any harness that can read files and run
shell commands — turn a user's finished illustrations and music into a
vertical (9:16) anime teaser / marketing video, rendered locally with
[Remotion](https://www.remotion.dev/). No watermark, no cloud render service.

**Read `SKILL.md` first — it is the single source of truth.** It contains:

- One-time environment setup (Node.js install, Remotion project, engine install)
- Known gotchas WITH fixes (silent headless-browser half-extraction, font
  loading, Windows PowerShell quirks) — check there before debugging
- The panel-config schema (camera motion, particle effects, text overlays,
  showcase cover mode, video panels, BGM with fade-out)
- Render commands and production guidance

## Repo layout

- `SKILL.md` — full agent-executable setup + usage guide (start here)
- `assets/Manhwa.tsx` — the Remotion composition → copy to `<project>/src/Manhwa.tsx`
- `assets/Effects.tsx` — particle effects → copy to `<project>/src/effects/Effects.tsx`
- `assets/manhwa-panels.ts` — panel/BGM config, the ONLY file edited per video
  → copy to `<project>/src/data/manhwa-panels.ts`

The engine is plain Remotion + React + TypeScript — no harness-specific
dependencies anywhere.

## Harness notes

- **Claude Code**: install by copying this folder to
  `~/.claude/skills/anime-production/`; the skill then triggers on
  "make an anime video / teaser / manhwa short" (EN/JP).
- **Codex / Antigravity / Gemini CLI / Cursor / others**: nothing to install —
  this file is your entry point. Follow `SKILL.md` from the repo, or copy
  `SKILL.md` + `assets/` into your own instructions/knowledge location.

## Rules

- Treat `assets/` as a template library: copy files into the user's Remotion
  project and do per-video editing there (`src/data/manhwa-panels.ts`), not here.
- Media handling, licensing notes (AI music/video tool terms), and watermark
  guidance are in SKILL.md's "Production guidance" — follow them.
