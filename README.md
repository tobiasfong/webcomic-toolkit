# webcomic-toolkit

Monorepo for the not-yet-shipped pieces of Tobias Fong's webcomic/novel production
ecosystem — see `servers/*` for individually-installable MCP servers. Each server has
its own `README.md`, `requirements.txt`, and is runnable/installable independently.

Already-shipped repos (`webcomic-background-mcp`, `anime-production-skill`) stay
standalone and are **not** part of this monorepo. See the architecture plan
(`ARCHITECTURE.md` §2.5, kept outside this repo) for the reasoning.

## Servers

- [`servers/novel-translation-mcp`](servers/novel-translation-mcp/README.md) — narrow
  query tools over a novel manuscript (docx) so translation work in chat never re-reads
  the whole document. MVP scope; publishing/EPUB assembly is deferred.

## Conventions

- Each server folder is independently runnable (own `requirements.txt`, own `README`).
- Scoped git tags once a server ships: `<server-name>@vX.Y.Z`.
- Python servers use FastMCP over stdio, matching `webcomic-background-mcp`'s skeleton.
