# webcomic-toolkit

A monorepo of local MCP servers for solo webcomic and novel production — see
`servers/*` for individually-installable servers. Each has its own `README.md` and
`requirements.txt`, and runs independently: install only what you need.

Sibling projects that shipped before this monorepo existed live in their own repos:
[`webcomic-background-mcp`](https://github.com/tobiasfong/webcomic-background-mcp)
(ComfyUI comic-panel backgrounds) and
[`anime-production-skill`](https://github.com/tobiasfong/anime-production-skill)
(Remotion teaser/MV renderer).

## Servers

- [`servers/novel-translation-mcp`](servers/novel-translation-mcp/README.md) — narrow
  query tools over novel manuscripts (docx) so translation work in chat never
  re-reads the whole document. Multi-project (one server, many novels); publishing/EPUB
  assembly is deferred to a future Publication MCP server.

## Conventions

- Each server folder is independently runnable (own `requirements.txt`, own `README`).
- Scoped git tags once a server ships: `<server-name>@vX.Y.Z`.
- Python servers use FastMCP over stdio, matching `webcomic-background-mcp`'s skeleton.
