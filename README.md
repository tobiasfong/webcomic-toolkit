# webcomic-toolkit

A monorepo of local MCP servers and agent skills for solo webcomic and novel
production — see `servers/*` for individually-installable pieces. Each has its own
`README.md` and dependency file, and runs independently: install only what you need.

## Servers & skills

- [`servers/webcomic-background-mcp`](servers/webcomic-background-mcp/README.md) —
  ComfyUI + Stable Diffusion background generator for comic panels: character-first
  plates, World Builder (a persistent location canon), Metropolis Mode (a persistent
  3D city), and depth-parallax clips for promo videos. The first server built in this
  ecosystem; consolidated into the monorepo from its original standalone repo.
- [`servers/anime-production-skill`](servers/anime-production-skill/README.md) — a
  portable agent skill (Claude Code, Codex, Antigravity, Gemini CLI, Cursor, or any
  AGENTS.md-aware harness) that turns finished illustrations + a music track into a
  vertical teaser/MV, rendered locally with Remotion. Also consolidated from its own
  original repo.
- [`servers/novel-translation-mcp`](servers/novel-translation-mcp/README.md) — narrow
  query tools over novel manuscripts (docx) so translation work in chat never
  re-reads the whole document. Multi-project (one server, many novels); publishing/EPUB
  assembly is deferred to a future Publication MCP server.
- [`servers/music-generation-mcp`](servers/music-generation-mcp/README.md) — local BGM
  and vocal theme songs via ComfyUI's native ACE-Step support, returning a lossless
  FLAC and a Remotion-ready MP3 plus a beat grid for downbeat-synced cuts. Closes the
  last outsourced step in the video pipeline: the anime-production skill could always
  play a track but never generate one.
- [`servers/character-panel-mcp`](servers/character-panel-mcp/README.md) — for writers
  who aren't artists: register existing character reference art as a Character Bible,
  generate consistent poses (Tier 1 of a three-tier design), and composite panels onto
  `webcomic-background-mcp` plates. Built directly in the monorepo.

## Conventions

- Each server folder is independently runnable (own `requirements.txt`/`package.json`,
  own `README`).
- Scoped git tags once a server ships: `<server-name>@vX.Y.Z`. Full commit history for
  `webcomic-background-mcp` and `anime-production-skill` (including their pre-
  consolidation releases) is preserved in this repo's git log via `git subtree`.
- Python servers use FastMCP over stdio, matching `webcomic-background-mcp`'s skeleton.
