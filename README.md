# Anime Production Skill

A self-contained [Claude Code](https://claude.com/claude-code) **agent skill** that turns finished
illustrations and comic pages into vertical (9:16) anime-style teaser videos /
MVs — Ken Burns camera motion, crossfades, ambient particle effects, bilingual
credits text, and a music track, rendered programmatically with
[Remotion](https://www.remotion.dev/).

Part of a [webcomic/anime production ecosystem](https://tobiasfong.github.io/)
built with Claude Code — companion to the
**webcomic-background-generator** MCP server, whose depth-parallax clips drop
straight into this pipeline as animated panels.

## What it does

Give the agent a folder of artwork and a song; it assembles and renders a
YouTube-Shorts-style video:

- 🎥 **Per-panel camera motion** — zoom/pan (Ken Burns) over stills; tall
  webtoon pages get the scroll-down effect (`panDown`)
- 🎞️ **Video panels** — drop in animated clips (image-to-video output,
  depth-parallax renders); auto-detected by file extension, played as-is
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

## Install (Claude Code)

```
git clone https://github.com/tobiasfong/anime-production-skill.git
# copy the folder to your personal skills directory:
#   ~/.claude/skills/anime-production/
```

Then ask Claude Code to "make an anime video" — the skill walks the agent
through everything else (Node, Remotion project, engine install, render).

## Credits

- Engine (`assets/*`): built with Claude Code for Tanaka Tomoyuki's projects
- Baseline Remotion project: [nyanko3141592/remotion-voicevox-template](https://github.com/nyanko3141592/remotion-voicevox-template) (MIT)
- Original skill listing: [mcpmarket.com/tools/skills/anime-production](https://mcpmarket.com/tools/skills/anime-production)

## License

MIT
