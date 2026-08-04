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

## Optional: local image-to-video (LTX-2.3)

The skill assembles video; it does not generate motion. If the user wants shots
that actually move, `ltx-setup.md` documents running **LTX-2.3 locally in
ComfyUI** — no subscription — and `assets/tools/ltx_run.py` is a working driver
(builds the ComfyUI API graph, submits, polls). Verified on a 6 GB card:
25 frames @ 832x576 in ~161 s.

Read `ltx-setup.md` before attempting it. The one that wastes the most time:
**a GGUF text encoder cannot load through ComfyUI's core `LTXAVTextEncoderLoader`**
— it reads `models/checkpoints/`, and `.gguf` is not in ComfyUI's supported
extensions, so the file will never appear however you move it. Use city96's
`DualCLIPLoaderGGUF(..., type="ltxv")` with the encoder in `models/text_encoders/`.

Generated clips drop back into the pipeline as ordinary video panels.

## Repo layout

- `SKILL.md` — full agent-executable setup + usage guide (start here)
- `assets/Manhwa.tsx` — the Remotion composition → copy to `<project>/src/Manhwa.tsx`
- `assets/Effects.tsx` — particle effects → copy to `<project>/src/effects/Effects.tsx`
- `assets/manhwa-panels.ts` — panel/BGM config, the ONLY file edited per video
  → copy to `<project>/src/data/manhwa-panels.ts`
- `assets/tools/` — helper scripts: `extract-beats.mjs` (beat map),
  `repair_depth.py` (depth-map cleanup, environments only),
  `fetch-ltx.sh` + `ltx_run.py` (optional local image-to-video)
- `ltx-setup.md` — local LTX-2.3 setup, 6 GB settings, and its gotchas

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
