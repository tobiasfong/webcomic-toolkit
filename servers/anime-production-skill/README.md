# Anime Production Skill

*Anime teaser, ad & MV maker for AI coding agents.*

A self-contained **agent skill** that turns finished illustrations and comic
pages into vertical (9:16) anime-style teaser / marketing videos and MVs —
Ken Burns camera motion, crossfades, ambient particle effects, bilingual
credits text, and a music track, rendered programmatically with
[Remotion](https://www.remotion.dev/).

Built and tested with [Claude Code](https://claude.com/claude-code); works
with **any harness that reads `AGENTS.md`** (OpenAI Codex, Google Antigravity,
Gemini CLI, Cursor, …) — the instructions are plain markdown and the engine is
plain Remotion/React with no harness-specific dependencies.

Part of a [webcomic/anime production ecosystem](https://tobiasfong.github.io/)
built with Claude Code — companion to the
**webcomic-background-generator** MCP server, whose depth-parallax clips drop
straight into this pipeline as animated panels.

## What it does

Give the agent a folder of artwork and a song; it assembles and renders a
YouTube-Shorts-style video:

- 🥁 **Beat-synced editing** — a dependency-free analysis pass extracts tempo,
  beat grid and loudness envelope from your track, then every cut lands exactly
  on a downbeat. Panels are timed in *bars*, not seconds
- 🎨 **Anime grade** — highlight-thresholded bloom/halation, film grain,
  vignette, white impact flashes and zoom punches on downbeats, with bloom
  riding the music's loudness envelope
- 🎥 **Per-panel camera motion** — zoom/pan (Ken Burns) over stills; tall
  webtoon pages get the scroll-down effect (`panDown`)
- 🧊 **Depth camera (2.5D)** — give a still its depth map and it becomes a
  displaced mesh with a real 3D camera moving through it: genuine perspective
  and occlusion, and because the move is computed at edit time it retimes
  automatically when you change a shot's length
- 🎞️ **Video panels** — drop in animated clips (image-to-video output,
  pre-baked parallax renders); auto-detected by file extension, played as-is
- 🖼️ **Any aspect ratio, no cropping** — art is shown complete over a blurred
  self-fill (the YouTube-Shorts letterbox look)
- ✨ **Particle effects** — twinkling stars, shooting stars, sparkles, embers,
  falling petals; deterministic, layered over the art
- 📇 **Text overlays** — credits / dates / CTAs in the margin bands, Japanese
  supported; plus a white-background **showcase mode** for cover shots
  (Kadokawa light-novel-ad style, drop-shadowed art + clean dark credits)
- 🎵 **BGM** with automatic fade-out
- 🚫 **No watermark** — everything renders locally through Remotion

## Why it exists

The original `anime-production` skill listing shipped as a bare markdown file:
a list of tool names, a reference to a private guide that doesn't exist
publicly, and no setup instructions. Making it actually run took a full
setup-and-debug session (Node install, project scaffolding, a silently
half-extracted headless browser, font-loading pitfalls, Windows PowerShell
quirks).

This package bakes all of that in, so an AI harness can go from
*nothing installed* to *rendered video* on its own:

- **`SKILL.md`** — agent-executable setup (with every known gotcha and its
  fix), the full panel-config schema, render commands, and production guidance
- **`assets/`** — the complete engine source (`Manhwa.tsx`, `Effects.tsx`,
  `manhwa-panels.ts` template), copied into any Remotion project in 3 files

## Use with your AI agent

**Claude Code** — this skill lives in the `webcomic-toolkit` monorepo; clone it and
copy just this folder into your personal skills directory:

```
git clone https://github.com/tobiasfong/webcomic-toolkit.git
# → copy webcomic-toolkit/servers/anime-production-skill/ to ~/.claude/skills/anime-production/
```

Then ask Claude Code to "make an anime video" — the skill walks the agent
through everything else (Node, Remotion project, engine install, render).

**Codex / Antigravity / Gemini CLI / Cursor / others** — clone the repo and
point your agent at it. [`AGENTS.md`](AGENTS.md) (the cross-harness
convention) is the entry point and routes the agent to
[`SKILL.md`](SKILL.md) for full setup and usage. Alternatively, copy
`SKILL.md` + `assets/` into your harness's own instructions/knowledge
location.

## Credits

- Engine (`assets/*`): built with Claude Code for Tanaka Tomoyuki's projects
- Baseline Remotion project: [nyanko3141592/remotion-voicevox-template](https://github.com/nyanko3141592/remotion-voicevox-template) (MIT)
- Original skill listing: [mcpmarket.com/tools/skills/anime-production](https://mcpmarket.com/tools/skills/anime-production)

## License

MIT
