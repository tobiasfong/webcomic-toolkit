# Webcomic Studio — Architecture & Build Plan

> **Status:** Mixed. The core visual pipeline (`webcomic-background-mcp`,
> `character-panel-mcp`, all 3 consistency tiers, Concept Genesis, the 3D
> mannequin, FLUX/Stage 5) is built and shipping — see each server's own
> CHANGELOG.md for what actually landed vs. what's described here as a plan.
> Translation/publication/orchestration pieces below are still in varying
> states of planned-vs-built; check each section rather than assuming.
> Originally lived at `Documents/webcomic-studio-plan/`, outside the repo;
> moved into `webcomic-toolkit/ARCHITECTURE.md` (2026-07-26) since every
> server's CHANGELOG/docstrings already reference it by relative section
> number as if it were a tracked, shared doc.
> **Author of this plan:** Claude (Fable 5), with Tobias Fong (Tanaka Tomoyuki), July 2026.
> **Intended reader:** the AI agent (e.g. Sonnet 5 in Claude Code) that will build this, plus future-Tobias.
> **Working name:** "Webcomic Studio" — rename freely.

---

## 1. What this is

A **single local interface** that unifies Tobias's webcomic/animation ecosystem:

| Piece | Kind | Status | Repo |
|---|---|---|---|
| Webcomic Background Generator (v1.8.0: World Builder, Metropolis, parallax, 3D props) | MCP server (GPU, ComfyUI) | ✅ Shipped | `tobiasfong/webcomic-toolkit` (`servers/webcomic-background-mcp`) |
| Anime Production Skill (Remotion teaser/MV renderer) | Agent skill (markdown + engine) | ✅ Shipped | `tobiasfong/anime-production-skill` |
| Novel Translation server (EN⇄JP novel translation, glossary, register bible) | MCP server (CPU) | ✅ Shipped (§8a) | `tobiasfong/webcomic-toolkit` (`servers/novel-translation-mcp`) |
| Speech Bubble/lettering server | MCP server (CPU) | 🔜 Planned, not built | — |
| Publication server (EPUB/CBZ/PDF/webtoon-strip export) | MCP server (CPU) | 🔜 Planned here (§7) | — |
| Character & Panel server (character bible, consistent characters from references, panel compositing, Concept Genesis, SDXL prototype, 3D mannequin for genuine back views) | MCP server (GPU, ComfyUI) | ✅ Shipped v1.0.0, all 3 tiers + back-view solved (§8b) | `tobiasfong/webcomic-toolkit` (`servers/character-panel-mcp`) |
| Prose → Storyboard adaptation (bridges novel-translation-mcp chapters to panel generation) | Agent skill or new server | 🔜 Planned, not built (§8a.1) | — |
| Orchestration skill ("make a promo short" etc.) | Agent skill | 🔜 Planned (§8) | — |

**Background Generator — next step, 3D props via OBJ import (not yet built):** v1.8.0
shipped `generate_prop_scene` with exactly one parametric mesh (a bicycle), hand-coded the
same way `citygen.py` hand-codes buildings — geometry in 3D, rendered headless to a Canny
sketch, SD only paints over it, never invents it. That fixes diffusion's repeated-object-geometry
failure (fused wheels, cloned "bicycle trains") the same way Metropolis mode fixed it for
skylines. Hand-coding geometry primitive-by-primitive doesn't scale to something as complex
as a mecha or kaiju, though — the next step is an **OBJ import path**: generate an original
mesh externally, then feed that OBJ into the same rasterizer → sketch → paint pipeline
instead of a procedurally-built mesh. Same consistency win, IP-safe (the mesh is
original/AI-generated, not traced from a copyrighted design), and far less work than writing
mecha geometry by hand. This unlocks consistent mecha/kaiju props for Starry Knight, which
was the original motivating case.

**Mesh source: default to TripoSR, not Meshy — this project stays free-to-run.** Meshy
(meshy.ai) is a paid cloud service, same category as Suno/Kling — every other piece of this
stack (background gen, parallax, panel/character gen) runs entirely local on the user's own
GPU with no recurring cost, and this repo is public/free for anyone to clone. Adding a
paid-API dependency for props would break that promise for every downstream user, not just
Tobias. **TripoSR** (Stability AI/Tripo, open-source image-to-3D) is the default path instead
— installed the same way Depth-Anything V2 was for the parallax tool: a downloaded model run
locally via ComfyUI or a standalone script, zero per-call cost. Expect TripoSR mesh quality to
be rougher than Meshy's (may need cleanup before it's rasterizer-ready — retopology, hole
filling); budget time to validate that in the build session rather than assuming parity.
Meshy stays noted only as a manual fallback path (paste in an OBJ you generated yourself) if
TripoSR's output turns out unusable — never the wired-in default, and never something the
server calls automatically on the user's behalf. Not started — flagging here so it doesn't
get lost before the next background-generator build session.

The interface is a **client layer on top of these tools**. It is explicitly **NOT a merge**:
every MCP server remains separate, focused, and independently installable. One broken
dependency must never take down the suite. (This principle is settled — do not revisit it.)

### What it is NOT
- Not a hosted web service. Everything runs on the user's machine (their GPU, their files, their harness subscription).
- Not a replacement chat client. Complex/novel work still belongs in the harness's own UI; this interface covers the visual 80%.
- Not a new AI. It has **zero AI of its own** — all intelligence comes from the user's connected harness.

---

## 2. The core architectural decisions (already made — build to these)

### 2.1 Delivery: localhost web app
A small local server (Node) + browser UI, launched with one command (`npx webcomic-studio` eventually; `npm run dev` during development). Binds to `127.0.0.1` ONLY — never `0.0.0.0`.

Why not the alternatives:
- **Hosted browser app:** impossible — needs the user's local GPU/ComfyUI/Remotion/filesystem/harness CLI.
- **Electron:** heavyweight (~200MB), slower to iterate. Not needed for v1.
- **Tauri desktop app:** the right *eventual* packaging (small, native feel), but wrap it AFTER the web app works. A localhost web app converts to Tauri with minimal rework; the reverse is not true.
- Precedent users already understand: **ComfyUI itself is a localhost web app.**

### 2.2 Harness integration: adapter pattern, subprocess-driven
The interface drives the user's **existing, subscribed harness** as a headless subprocess. It never talks to a model API directly (no API keys stored, no per-token billing surprises — the user's subscription pays, exactly as Tobias envisioned).

- **v1 adapter: Claude Code** — spawn `claude -p "<prompt>" --output-format stream-json` (non-interactive mode). Pass MCP config via `--mcp-config`. Stream events back to the UI. Claude Code's non-interactive mode uses the user's existing login/subscription.
- **Later adapters:** Codex CLI, Gemini CLI — same `HarnessAdapter` interface (see §5.3). Do NOT attempt multi-harness in v1; build the interface so a second adapter is *possible*, then ship with one.
- **Caveat to verify at build time:** CLI flags for non-interactive/streaming modes change between harness versions. The builder must check `claude --help` for the current invocation shape rather than trusting this doc.

### 2.3 Hybrid execution: Direct mode vs Agent mode (the efficiency thesis)
Every action in the UI is classified:

- **Direct mode** (no AI, no tokens, instant): the interface itself acts as an MCP client (via `@modelcontextprotocol/sdk`) and calls tools deterministically. Examples: `list_world`, `list_projects`, browse canon images, re-render a parallax clip with known params, export an EPUB, open output folders.
- **Agent mode** (harness subprocess, costs the user's subscription usage): anything requiring judgment or language. Examples: "generate a rainy alley matching my canon," translating a chapter, composing a teaser, fixing a failed render.

This hybrid is the answer to "why not just use Claude Desktop/Codex directly?" — the interface
saves tokens on the mechanical 80% and adds visual UX (galleries, previews, timelines) that a
chat window cannot provide. If a feature is neither cheaper nor visually better than plain
harness chat, it does not belong in this interface.

Agent mode is also the answer to "can the Studio have a real chat panel without Tobias
paying for API calls?" — yes: the chat IS Agent mode, given a persistent front end backed
by the harness's own session-resume rather than the interface replaying history itself.
Full spec, including the token-burn trap to avoid, in §5.5.

### 2.4 Extensibility: new tools must cost config, not code
Hard requirement from Tobias: the ecosystem WILL grow (the publication server itself was
only conceived mid-planning). The Studio must absorb future MCP servers and skills without
architectural change:

- **Server registry is data, not code.** Connected MCP servers come from config
  (`studio-config.json` + import from the harness's own MCP config). Adding a server = adding
  a config entry, zero Studio code.
- **Generic tool panel.** Any connected server the Studio has no bespoke panel for gets an
  auto-generated panel: tool list + forms rendered from the MCP tool schemas (the SDK exposes
  them) + a generic output/file gallery. Bespoke panels (Backgrounds, World bible…) are
  *enhancements* over this baseline, never prerequisites.
- **Skills registry.** Agent-mode recipes (anime production, orchestration, future skills) are
  listed from a `skills/` config so new recipes appear in the command bar without UI changes.
- **`project.json` is namespaced by tool** (`tools.<toolname>`) so new tools claim their own
  key and subfolder without touching others' schema.

Rule of thumb for the builder: if adding a hypothetical fourth MCP server requires editing
Studio source code (rather than config), the design is wrong — fix the abstraction.

### 2.5 Repository strategy: everything lives in one monorepo (`webcomic-toolkit`)
Important distinction, still true: **where code lives in git is independent of runtime
server architecture.** A monorepo can hold N separate, independently-installable MCP
server processes (each its own folder, own manifest, own README) without becoming the
"single overarching MCP server" anti-pattern rejected elsewhere in this doc — that
rejection was about merging *function* into one process (GPU/CPU conflict, one failure
takes down everything); repo layout is a different axis. A monorepo does NOT make the
Studio technically easier to build — it connects to servers via config regardless of which
repo they came from. The benefits are for Tobias as maintainer: shared code, one clone for
the whole ecosystem, less per-repo upkeep, mirroring the multi-server repo pattern from his
work (AKQA MCP servers repo: DBS, corporate banking, Wiki, Artist Colony, etc.).

**Status: DONE (2026-07, decision reversed from the original plan).** This section
originally argued for leaving the two already-shipped repos (`webcomic-background-mcp`,
`anime-production-skill`) standalone, on the grounds that migrating them cost broken links
for a purely organizational win. Tobias weighed that cost explicitly and asked for the
merge anyway, prioritizing "one place to find, add, and edit everything" over the
portfolio-optics argument for separate repos — a legitimate call once made with the
trade-off in view, not a mistake to talk him out of. It has been executed:

- **Both repos merged into `webcomic-toolkit` via `git subtree add`**, preserving full
  commit history (messages, authors, dates — the "10 commits in one day" story survives,
  even though the commits get new SHAs since their file paths changed under
  `servers/<name>/`). Layout:
  ```
  webcomic-toolkit/
    servers/
      webcomic-background-mcp/    # merged in, full history preserved
      anime-production-skill/     # merged in, full history preserved
      novel-translation-mcp/      # built directly in the monorepo
    README.md                     # lists all three
  ```
- **Scoped tags** created for the current state of each merged server
  (`webcomic-background-mcp@v1.6.0`, `anime-production-skill@v1.0.0`,
  `novel-translation-mcp@v1.0.0`). Historical per-version tags (v1.0.0…v1.5.1 for the
  background generator) were NOT individually replayed as scoped tags — they remain visible
  in the archived original repo's history for anyone who wants to dig; the monorepo carries
  the scoped convention forward from here.
  ⚠️ **Gotcha hit during the merge:** `git fetch <source-repo-remote>` pulls the source
  repo's OWN tags into the local tag namespace too. Pushing `--tags` at that point
  re-publishes those bare, unscoped tags into the monorepo — recreating the exact ambiguity
  this convention exists to prevent. Caught and deleted (`git tag -d` + `git push origin
  --delete`) after the fact. **When merging a future repo in, delete or rename any
  fetched-but-unwanted tags from that remote before running `git push --tags`.**
- **Old repos: archived first, then deleted at Tobias's explicit request.** Each got a
  "this repo has moved" notice prepended to its README before archiving, pointing at the
  new `servers/<name>/` location. Archiving alone would have been fully reversible and cost
  nothing (no storage/hygiene benefit to deleting on top of it — flagged this trade-off
  explicitly before acting); Tobias weighed it and asked for deletion anyway "for hygiene
  purposes." Both `webcomic-background-mcp` and `anime-production-skill` are now gone from
  GitHub entirely — no undelete, any external link/star/clone to the old URLs now 404s.
  Deleting required the `delete_repo` OAuth scope, which `gh`'s stored auth didn't have by
  default; Tobias granted it via `gh auth refresh -h github.com -s delete_repo` (or the
  GitHub Settings → Danger Zone UI) before the CLI could complete it.
- **Every reference updated**: the site's three project pages (`mcp-background.html`,
  `anime-production.html`, `novel-translation.html`) now link to
  `github.com/tobiasfong/webcomic-toolkit/tree/master/servers/<name>` instead of the old
  standalone URLs; each server's own README install instructions repointed at cloning the
  monorepo + `cd`-ing into the right subfolder (this also fixed a **stale link found during
  the merge**: `webcomic-background-mcp`'s README Step 4 still referenced the pre-rename
  `Warhammer40000-background-mcp` clone URL from before an earlier rename — never caught
  until this pass).
- **Publishing status:** none of the three servers had been submitted to any MCP
  marketplace/registry as of this merge, so there was no external listing to also update.
  If that changes before a future repo consolidation, add "update marketplace listing" to
  this checklist.

**Convention going forward:** any new server or skill goes straight into
`webcomic-toolkit/servers/<name>/`, independently runnable, own manifest, own README.
No more standalone repos for new ecosystem pieces — the "existing repos stay put" carve-out
that motivated this section originally no longer applies to anything currently in the
ecosystem.

### 2.6 Data contract: the project folder
One convention shared by every tool, extending the per-project namespacing the background
server already ships (its v1.2.0 `project` argument). A Studio project is a folder:

```
MyComic/
  project.json          # manifest — the single source of truth (schema §6)
  art/                  # finished pages/illustrations (input)
  world/                # World Builder canon (managed by background MCP)
  backgrounds/          # generated plates (output of background MCP)
  clips/                # parallax MP4s (output of parallax tools)
  lettering/            # scripts, bubble layers, translations (speech-bubble MCP)
  video/                # teasers/MVs (anime production skill output)
  publish/              # EPUB/CBZ/PDF deliverables (publication MCP)
```

The interface reads/writes `project.json`; each MCP server keeps owning its own subfolder.
No server reads another server's folder directly — cross-tool flows go through the
orchestrator (harness) or the interface, passing explicit file paths.

---

## 3. System diagram

```
┌─────────────────────────────  Browser (localhost)  ─────────────────────────────┐
│  Studio UI (Vite + React + TS)                                                  │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Projects │ │Backgrounds│ │ World     │ │Lettering│ │  Video   │ │ Publish  │  │
│  │  browser │ │  studio  │ │ bible     │ │ & i18n  │ │  studio  │ │  studio  │  │
│  └──────────┘ └──────────┘ └───────────┘ └─────────┘ └──────────┘ └──────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  Command bar / chat strip (Agent-mode prompts + live harness stream)     │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────┬─────────────────────────────────────────────┘
                                     │ HTTP + SSE (127.0.0.1)
┌────────────────────────────────────▼─────────────────────────────────────────────┐
│  Studio Server (Node + Fastify)                                                  │
│  ├─ Project manager (project.json, file watching)                                │
│  ├─ Job queue (ONE GPU job at a time; CPU jobs parallel)                         │
│  ├─ MCP client pool ─────────────► Direct mode                                   │
│  └─ HarnessAdapter (subprocess) ─► Agent mode                                    │
└──────┬──────────────────┬───────────────────┬───────────────────┬────────────────┘
       │ stdio (MCP)      │ stdio (MCP)       │ stdio (MCP)       │ spawn CLI
┌──────▼──────┐   ┌───────▼───────┐   ┌───────▼───────┐   ┌───────▼────────────────┐
│ background- │   │ speech-bubble │   │ publication   │   │ Claude Code (headless) │
│ mcp (GPU)   │   │ + translation │   │ (EPUB/CBZ/PDF)│   │  → skills: anime-prod, │
│  └─ComfyUI  │   │ MCP (CPU)     │   │ MCP (CPU)     │   │    orchestration       │
└─────────────┘   └───────────────┘   └───────────────┘   └────────────────────────┘
```

Key: the harness subprocess ALSO connects to the same MCP servers (via `--mcp-config`).
Direct mode and Agent mode are two doors into the same tool layer.

---

## 4. Tech stack (chosen — don't relitigate without cause)

- **Frontend:** Vite + React + TypeScript. Plain CSS or Tailwind — builder's choice, keep it light.
- **Server:** Node 20+, Fastify. SSE for streaming job/harness events to the UI (simpler than WebSockets and sufficient — one-directional streams).
- **MCP client:** official `@modelcontextprotocol/sdk` (TypeScript), stdio transport, one client per configured server, lazy-connected.
- **Subprocess:** `execa` for spawning the harness CLI and parsing `stream-json` output.
- **Media in UI:** plain `<img>`/`<video>` served from project folders via sanitized static routes.
- **No database.** `project.json` + the filesystem IS the state. A `studio-config.json` in the user's config dir holds global settings (harness choice, server paths, ComfyUI URL).
- **License/positioning:** MIT, same as the rest of the ecosystem.

---

## 5. Component specs

### 5.1 Studio Server
- `GET /api/projects` / `POST /api/projects` — list/create project folders (a "recent projects" list lives in studio-config).
- `GET /api/projects/:id/manifest` — parsed `project.json`.
- `POST /api/jobs` — enqueue a job `{type: direct|agent, tool/prompt, params, projectId}`; returns job id.
- `GET /api/jobs/:id/events` — SSE stream: `queued → running → (progress|harness-event)* → done|failed`.
- `GET /files/...` — sanitized read-only static serving of project assets. **Path-traversal guard mandatory** (resolve + verify prefix against the project root).
- Job queue rules: max ONE GPU-flagged job at a time (ComfyUI contention); CPU jobs up to N=2; agent jobs serialized per project (two agents editing one project = corruption).

### 5.2 MCP client pool (Direct mode)
- Reads the same MCP server definitions the harness uses (support importing from `.claude.json` / a local `mcp-config.json` so the user configures servers ONCE).
- Connects lazily on first use; surfaces tool schemas so the UI can render forms for direct tool calls (e.g. a "Generate city scene" form maps 1:1 to `generate_city_scene` params).
- If a server is not installed/connectable: the panel shows an install card linking the repo README — the interface degrades per-tool, never as a whole.

### 5.3 HarnessAdapter (Agent mode)
```ts
interface HarnessAdapter {
  id: 'claude-code' | 'codex' | ...;
  available(): Promise<boolean>;          // is the CLI installed + authed?
  run(job: {
    prompt: string;                        // includes project context preamble
    cwd: string;                           // the project folder
    mcpConfig: string;                     // path to mcp servers config
    permissionMode: 'ask' | 'acceptEdits'; // surface to user, default 'ask'
  }): AsyncIterable<HarnessEvent>;         // normalized stream: text|tool_use|result|error
  cancel(jobId: string): void;
}
```
- v1 implements `ClaudeCodeAdapter` only. Events normalized so the UI never knows which harness ran.
- **Prompt preamble** (the adapter injects): project name, key paths, active panel context, and a one-line instruction to prefer the ecosystem's MCP tools. Keep it under ~200 tokens.
- Permission surfacing: when the harness asks for tool permission in `ask` mode, forward to the UI as a modal. Never silently auto-approve destructive actions.

### 5.4 UI panels (v1 scope in bold)
1. **Projects browser** — create/open projects, recent list, manifest summary.
2. **Backgrounds studio** — form-driven direct calls (`generate_background`, `generate_city_scene`), gallery of `backgrounds/`, "iterate with AI" button that escalates to Agent mode with the selected image as context.
3. **World bible** — visual browser of `list_world` / `list_city` (canon images, palettes, districts). Register/forget locations (direct). This is the panel a chat UI can least replicate — make it good.
4. Lettering & i18n — blocked until the speech-bubble server exists. Ship the panel as a stub with an install/roadmap card.
5. Video studio — grid of `clips/`, parallax re-render form (direct), "compose teaser" (agent → anime skill), `<video>` preview of `video/` output.
6. Publish studio — blocked until the publication server exists; stub card.
7. **Command bar / chat** — free-text Agent-mode prompt from anywhere, with live streamed response; the escape hatch that keeps the interface from needing a button for everything. Full spec in §5.5.

### 5.5 The chat layer: harness-passthrough, not a hosted chatbot

**The question this answers:** can the Studio have a real chat panel — the way you'd chat
with Claude Desktop or ChatGPT — without Tobias paying for API calls out of pocket? Yes,
and the answer is a formalization of what §2.2/§2.3/§5.3 already specify, not a new
mechanism: **the "chatbot" is not a separate AI Tobias hosts. It IS the user's own
Agent-mode harness, given a persistent conversational front end.** There is no API key in
this system, no per-message cost to Tobias, and no free-tier-that-runs-out problem — the
user's own Claude Code / Codex / Gemini CLI / etc. subscription pays for its own usage,
exactly as it would if they ran that CLI directly. This is not a workaround; for a personal
open-source tool with no revenue model, it is the *only* sustainable design — a hosted-API
chatbot would either bankrupt Tobias or require building billing infrastructure that is
completely out of scope. Confirmed correct, build to this.

**What's actually new here vs. the existing Agent-mode design:** §5.3's `HarnessAdapter`
was speced around one-shot jobs (a button click → one prompt → one streamed response →
done). A chat panel needs multi-turn, back-and-forth conversation. The naive way to get
that — resend the entire conversation transcript as part of the prompt on every message —
recreates, at the Studio's chat layer, **exactly the token-burn bug already diagnosed and
fixed in `novel-translation-mcp`** (§8a): every turn re-pays for the full history, and cost
grows with conversation length instead of staying flat. That bug is not hypothetical here;
it is proven to happen the first time this pattern gets built carelessly.

**The fix — session resume, not history replay:**
```ts
interface HarnessAdapter {
  // ...existing run()/cancel() from §5.3...
  startSession(cwd: string, mcpConfig: string): Promise<string>;      // returns sessionId
  sendMessage(sessionId: string, message: string): AsyncIterable<HarnessEvent>;
  // sendMessage resumes the harness's OWN on-disk session state (e.g. Claude Code's
  // `--resume <sessionId>` / `--continue`, if/as the CLI exposes it) — the Studio
  // never re-sends prior turns itself. The harness's session storage IS the chat history.
}
```
- **Verify at build time**, same caution as §5.3: confirm the exact resume/continue flag
  and its guarantees for whichever harness CLI version is current — do not trust flag names
  written in a planning doc against a moving target.
- If a harness has no resume capability, the fallback is a *summarized* running context
  (not full replay) injected each turn — worse than native resume, but still not the
  token-burn bug. Prefer harnesses/versions that support real resume.
- One session per chat thread; the Studio tracks `sessionId` per Studio-project (in
  `project.json` or local state), and is responsible for surfacing/cleaning up orphaned
  sessions the user abandons.

**This chat is not "just talk" — it has the ecosystem's tools.** Because Agent-mode
sessions connect through the same `mcpConfig` as Direct mode (§5.2), a chat message like
"generate a rainy alley matching my canon" isn't answered by a generic LLM guessing — the
harness has real tool access to `generate_background`, `list_world`, etc., and can actually
call them. This is the literal mechanism behind Tobias's framing: talking to the interface
*is* talking to your subscribed AI client, but in a layer that hands it the whole
ecosystem's tools, orchestration, and project context — "an actual webcomic production
digital studio with generative capabilities," not a chatbot bolted on the side.

**Honest caveats:**
- **Multi-harness support is a v1-vs-later question, not solved by this design alone.**
  The adapter pattern makes it *possible* to add Codex/Gemini/other chat later, but each
  is real, separate work (different CLI flags, different resume semantics, different event
  formats to normalize). Ship chat with `ClaudeCodeAdapter` only for v1; "whatever the user
  subscribes to" is the north star the architecture is built toward, not a day-one claim.
- **Latency:** spawning/resuming a CLI subprocess per message has real startup overhead —
  this will not feel as instant as a native web chat UI. Set that expectation in the UI
  (a visible "thinking" state) rather than over-promising snappiness.
- **Concurrency:** the existing job-queue rule (§5.1 — agent jobs serialized per project)
  already prevents two chat sessions corrupting one project's state simultaneously; no new
  rule needed, just confirming it covers this case too.

---

## 6. `project.json` schema (v1)

```json
{
  "schema": 1,
  "name": "A Starry Knight",
  "slug": "starry_knight",
  "language": { "source": "en", "targets": ["ja"] },
  "kind": "webtoon",
  "tools": {
    "background": { "project": "starry_knight" },
    "lettering":  { "font_en": "", "font_ja": "", "vertical_ja": true },
    "video":      { "music": "", "credits": { "story": "Tanaka Tomoyuki" } },
    "publish":    { "title": "", "author": "Tanaka Tomoyuki", "formats": ["epub", "cbz"] }
  },
  "pages": [ { "id": "ch1_p01", "art": "art/ch1_p01.png", "status": "colored" } ]
}
```
- `tools.background.project` maps to the background server's `project` argument — the bridge to existing v1.2.0 namespacing.
- `pages[]` is optional in v1 (galleries can just glob folders); it becomes load-bearing for lettering/publication later.

---

## 7. Publication MCP server (new — must be BUILT before its panel)

**Responsibility:** turn finished pages into deliverables. CPU-only. Python, same skeleton as the other servers (FastMCP, stdio).

Tools:
- `assemble_epub(pages[], metadata, mode)` — `mode: fixed-layout` (comics; each page an image spread) or `reflow` (novels; chapters of text). Use `ebooklib`; validate with `epubcheck` if present (bundle the check as optional).
- `assemble_cbz(pages[], metadata)` — trivial zip, huge value for comic readers.
- `assemble_pdf(pages[], metadata)` — print-ready option via Pillow/reportlab.
- `export_webtoon_strip(pages[], max_height)` — stitch pages into vertical strips for webtoon platforms.
- `validate_deliverable(path)` — sanity checks (page order, dimensions, metadata completeness).

**Format guidance:** target **EPUB (fixed-layout) + CBZ + PDF**. Skip MOBI — Amazon deprecated it; KDP ingests EPUB. (Tobias floated "EPub or Mobi"; EPUB covers Kindle now.)

**Input formats (novel path):** the primary real-world input is a **Microsoft Word `.docx`
manuscript + JPEG illustrations** (this is Tobias's actual RxR workflow). Parse with
`python-docx`, map heading styles → chapters, preserve italics/bold, and support illustration
placement markers. Also accept markdown. Target output: technically publish-ready (passes
`epubcheck`, correct metadata/TOC/cover) — with the honest caveat that *editorial*
publish-readiness always needs a human proofing pass; the tool guarantees the container,
not the prose.

**Multi-language editions:** one manuscript → N language editions (e.g. EN + JP) as separate
EPUBs sharing metadata/cover, with language-appropriate typography (vertical-JP support is a
later milestone; ship horizontal first).

**Design principle — assistive, not batch (applies to the translation core everywhere):**
translation tools in this ecosystem are built for a **human-in-the-loop review workflow** —
propose translations with alternatives and notes, maintain an approved glossary
(names/honorifics/terms), and support back-and-forth revision — never a fire-and-forget
batch translate. The intended operator is the author or a professional translator working
*with* the tool. This mirrors the ecosystem's standing philosophy: AI as partner, not
replacement (same stance as the background generator's character-first workflow).

**Scope guard:** if this server starts growing glossary management beyond the translation
core's needs, chapter-level translation memory, or storefront uploads — stop and split.
Packaging only.

---

## 8. Orchestration skill (built AFTER speech-bubble + publication servers)

A portable markdown skill (AGENTS.md/SKILL.md convention, like anime-production) teaching any
harness the cross-tool recipes:

- **"Make a promo short"**: backgrounds → parallax clips → anime-production skill → `video/`.
- **"Localize chapter to Japanese"**: lettering server (extract → translate → re-typeset vertical JP) → `lettering/ja/`.
- **"Publish chapter"**: collect pages → publication server → `publish/`.

Each recipe must include dependency checks ("if the speech-bubble server is not connected,
guide the user to install it from <repo>") — the skill is also the installer-guide.
The Studio's Agent mode simply invokes these recipes; the skill remains fully usable
WITHOUT the Studio (portability is non-negotiable, per the ecosystem's philosophy).

---

## 8a. Novel Translation MCP — MVP ✅ SHIPPED (2026-07-17)

**Status: live.** Built and shipped in one day (10 commits), grew beyond the original MVP
scope during real use, and is now consolidated into `webcomic-toolkit/servers/
novel-translation-mcp/` (§2.5) with its own portfolio page
(`projects/novel-translation.html`). What actually shipped, vs. what follows was the
original plan below:

- **12 tools**, not the 6 originally scoped — real use surfaced needs the MVP plan didn't
  anticipate: multi-project (`register_project`, `list_projects`), multi-volume with correct
  chapter-numbering restart per volume (`add_manuscript_volume` — volumes restart at
  chapter 1, matching how real published books work; this required reworking chapter
  identity to `(volume, chapter)` pairs, including correct continuity across a volume
  boundary), a one-call context bundle (`get_context`), cross-session note persistence
  (`record_note`), and a deterministic linter (`lint_chapter`).
- **A real regression, caught and fixed:** the obvious "return small excerpts" fix
  initially made throughput *worse* (2-3 chapters/session down to <1), because it was used
  inside one long-running chat where every tool call re-sends full history. Fixed by
  shrinking tool-schema overhead (~45% cut via terser docstrings — schemas ride on every
  message of every connected chat) and by changing the served workflow to explicitly teach
  "one fresh chat per chapter, state lives on disk" as the intended usage pattern.
  **Lesson for every future server in this ecosystem:** schema verbosity has a different
  cost profile than README verbosity — it's paid on every turn, not read once — and *how*
  a tool is meant to be used (fresh session vs. long-running) needs to be taught by the
  server's own `instructions` field, not left to be discovered the hard way.
  See `servers/novel-translation-mcp/README.md` for the full numbers.
- **The workflow ships in the MCP protocol's `instructions` field** (a `WORKFLOW.md`,
  gitignored `WORKFLOW.local.md` override for house rules) — confirming the pattern
  recommended for the orchestration skill in §8: the process travels with the tool,
  independent of which model or session is on the other end.
- **Not yet built:** the EPUB/cover/synopsis pipeline is still correctly deferred to §7's
  Publication server, as originally planned.

<details>
<summary>Original MVP plan (for reference — mostly superseded by what actually shipped above)</summary>

**Why out of order:** Tobias hit a real, dated problem translating his RxR web novel (EN↔JP,
50k+ English words / ~120k JP characters — normal for this novel length) by hand in chat:
every session-resume re-reads/re-explains the full manuscript, burning 20-30% of a 5-hour

**Why out of order:** Tobias hit a real, dated problem translating his RxR web novel (EN↔JP,
50k+ English words / ~120k JP characters — normal for this novel length) by hand in chat:
every session-resume re-reads/re-explains the full manuscript, burning 20-30% of a 5-hour
usage window before real translation work starts. This is the exact shape of problem his own
"Artist Colony" MCP server (AKQA repo) already solved at work — replacing a raw-spreadsheet
re-read with narrow query tools (`find_available_people`, `get_resourcing_snapshot`). Same
fix applies here. Build this narrow MVP NOW; defer the full EPUB/cover/synopsis pipeline
(§7) until after the immediate translation backlog (3 chapters, as of this writing) is done.

**Golden rule for every tool in this server:** return small, targeted excerpts — never the
whole manuscript. A `read_manuscript()` tool with no chapter argument recreates the exact
problem this server exists to solve.

**State file** (JSON, next to the manuscript — same pattern as the background server's
`world.json` canon): tracks per-chapter status (`draft|reviewed|approved`) and the approved
glossary. This is what makes "resuming after sleep" cheap: the tool reports status in a few
dozen tokens instead of the harness re-deriving context from scratch.

**MVP tools:**
- `list_chapters(lang)` — titles + status per chapter. (≈ `get_resourcing_snapshot`)
- `get_chapter(number, lang)` — that chapter's text ONLY. (≈ `find_available_people`)
- `search_manuscript(query, lang)` — grep-like search without loading the whole doc.
- `get_glossary()` — approved names/honorifics/recurring terms.
- `propose_glossary_term(term, translation, note)` — STAGES a term; never auto-commits.
  Approval is a separate, explicit human step — enforces the human-in-the-loop principle
  below at the tool-design level, not just in the prompt.
- `save_translation(chapter, lang, text)` — writes the approved chapter, updates status.

**Input parsing:** manuscript source is a Microsoft Word `.docx` (Tobias's actual workflow)
— parse with `python-docx`, map heading styles → chapters. Markdown also acceptable.

**Deferred to v2 (do not build yet):** EPUB/CBZ/PDF/MOBI-equivalent assembly, cover +
back-cover synopsis generation, illustration placement. These live in §7's Publication
server scope.

</details>

**Design principle — this stays live, applies to ALL translation/localization tooling in
this ecosystem, novel or comic, not just the MVP above:** built for propose → review →
revise → approve, with an approved glossary and alternatives-with-notes — never
fire-and-forget batch translation. The intended operator is the author or a professional
translator working *with* the tool. AI is a partner, not a replacement — same stance as the
background generator's character-first workflow. Tool design must enforce this (e.g.
`propose_glossary_term` vs. an auto-committing alternative), not just rely on prompting.
The shipped server's human-in-the-loop review loop (draft → judgment-call notes → human
edit → re-check → approve, with the model checking the human's own edits as scrutinously as
its own draft) is the concrete implementation of this principle — see
`servers/novel-translation-mcp/WORKFLOW.md`.

### 8a.1 Prose → storyboard adaptation — 🔜 PLANNED, NOT BUILT (flagged 2026-07-26)

Tobias's original intent for this whole ecosystem was a webnovel → webcomic pipeline: write
prose in `novel-translation-mcp`, get panel breakdowns out. That bridge doesn't exist yet —
today the only path from a manuscript chapter to a panel is a human manually deciding panel
count, camera/composition, and beat pacing, same as writing a storyboard from scratch.

**Decision for the first real scene (Namgoong Ri Hwa, 2026-07-26): go panel-by-panel by
hand, not prose-first**, specifically to validate the character-consistency pipeline
(reference-sheet lock → Kontext-edit-from-approved-reference, per §8b) across a real
multi-panel sequence before adding an adaptation layer on top that could introduce its own
mismatches (wrong panel count, camera choices that don't match what the author pictured).

When this is eventually built, it's a new tool/skill that sits between `novel-translation-mcp`
(source of approved chapter text) and `character-panel-mcp`/`webcomic-background-mcp`
(panel + background generation) — not a feature of either existing server. Treat it the same
way §7's Publication server is treated: a separate, later piece, not scope-creep into a
server that already has a focused job.

---

## 8b. Character & Panel Generator MCP — ALL THREE TIERS ✅ SHIPPED 2026-07-18

**Status: Tier 1, 2, and 3 all live**, in `webcomic-toolkit/servers/character-panel-mcp/`.
Tier 1 shipped first (bible + img2img + compositing, ten tools total including
`check_status`); Tier 2 (IP-Adapter identity + OpenPose) and Tier 3 (per-character
LoRA baking) shipped in the same-day follow-up this note now describes.

**Tier 2** extends `generate_character_pose` in place (`identity_mode="plus"`/
`"plus_face"`, `pose_ref_path`) rather than adding new tools — additive on top of
Tier 1's img2img, off by default. Uses `cubiq/ComfyUI_IPAdapter_plus`
(`IPAdapterUnifiedLoader`/`IPAdapter`) + the `OpenposePreprocessor` node from
`comfyui_controlnet_aux` (already required by `webcomic-background-mcp`). Ships
`"plus_face"` instead of true FaceID (avoids an InsightFace/`antelopev2` install) —
a conscious substitution, documented in README.md, not a silent gap.

**Tier 3** adds `bake_character_lora` / `check_lora_training` / `cancel_lora_training`,
backed by a new `training.py` module orchestrating `kohya-ss/sd-scripts` as a
**detached background subprocess** (same pattern `workflow.py` uses to auto-launch
ComfyUI) — necessary because a bake takes 30-90 min and can't block an MCP call.
A finished LoRA is auto-installed into ComfyUI's `models/loras/` and recorded on
the character's bible entry, so `generate_character_pose` uses it automatically
from then on — the concrete implementation of this section's "bootstrap loop"
(curated Tier-1/2 renders fed back via `register_character` become training data
for a re-bake). Captions are a fixed trigger-token + class-word template, not
per-image auto-captioning (e.g. BLIP) — a scope decision, not a gap. Tobias
flagged that Tier 3 was expected to bake in the Niji V5 Style LoRA by default
(not a plain checkpoint) — added via sd-scripts' `--base_weights`/
`--base_weights_multiplier` (a verified flag that merges an existing LoRA into
the checkpoint before training starts), defaulting `style_lora` to
`NijiV5Style.safetensors`, overridable/disableable per bake. This matches the
existing per-project style pool this section already describes for background
plates and Tier-1/2 poses — Tier 3 now shares it by default too, instead of
requiring the writer to remember to reapply it.

**Verification — real, not just unit tests.** ComfyUI happened to be running with
both Tier-2 custom nodes already installed at verification time, so this went
further than Tier 1's report: live `generate_character_pose` calls actually ran
end-to-end for Tier 1 alone, Tier 1+IP-Adapter, and all three mechanisms combined
(img2img + IP-Adapter + OpenPose in one graph) — confirmed via ComfyUI's own
`/prompt` schema validation reaching every node cleanly. **A real bug was caught
this way**: the IP-Adapter node's `weight_type` was written as `"linear"` (not a
valid value) — ComfyUI's live validation error surfaced this immediately; fixed
to the verified enum (`"standard"`/`"prompt is more important"`/`"style transfer"`)
and re-confirmed working. The OpenPose branch's wiring validated cleanly too, but
the actual ControlNet model file wasn't downloaded on this machine, so it wasn't
exercised past graph-validation — an environment gap, not a code one, and exactly
what `setup_models.py` (new this release) exists to fix. Tier 3's async job
lifecycle (bake → training → done, and separately → cancelled, plus a double-bake
guard) was verified end-to-end with a stub trainer standing in for kohya-ss/GPU
training — a real kohya-ss install and a real 30-90 min training run were not
exercised (kohya-ss isn't installed in the build environment).

§8b.5a's friend-GPU and Codex-harness questions are still open — unrelated to
this tier work.

**§8b.6 Concept Genesis ✅ SHIPPED 2026-07-19** — see that section below for the
full build report. Three new tools (`generate_character_concept`, `crop_reference`,
`generate_reference_sheet`) plus a behavior-preserving refactor of
`generate_character_pose`. Unit-tested (crop pixel-exactness + error paths, seed-
stepping, view-iteration, unregistered-character guard); live generation not yet
exercised — ComfyUI wasn't running at ship time. The real God/Speed ingestion test
(§8b.6's own verification step 5) is intentionally deferred to a session with
Tobias actually reviewing crop boxes and picking keepers, not run unilaterally.

**Who it's for:** writers who aren't artists. The concrete user is Tobias's writer friends —
they have a story and *existing character concept art* (commissioned artists, or ChatGPT/
Midjourney character sheets), and need consistent panels of those characters without being
able to draw them. Same philosophy as the background generator: **reference-driven, never
generate-from-text-and-pray.** The references are the ground truth for who a character is;
the tool's whole job is making sure they don't drift mid-story.

**Runs on the same stack:** local ComfyUI, SD 1.5 checkpoints, RTX 3060. The Niji V5 Style
LoRA (added to the background server in v1.7.0) is a per-call style option here too —
character style and background style should be pickable from the same LoRA pool so a
project's panels match its plates.

**New server, not a background-server feature.** Characters are a different domain with
different state (a character bible vs. a location bible), different ComfyUI dependencies
(IP-Adapter, OpenPose), and a different failure surface. Sibling folder:
`webcomic-toolkit/servers/character-panel-mcp/` (name open, §12). Python + FastMCP, same
skeleton and README standard as the others.

### 8b.1 The Character Bible (mirror of World Builder)

The background server's proven pattern, re-applied to people:

- `register_character(project, name, ref_images[], notes)` — store the reference set
  (concept art, turnarounds, expression sheets — whatever the writer has), extract the
  palette (reuse the `_extract_palette` approach), record notes (age, build, signature
  costume elements). Storage: `characters/<project>/<name>/` + a `characters.json`
  manifest. Multi-project namespacing from day one (the background server had to retrofit
  it at v1.2.0 — don't repeat that).
- `list_characters(project)` — the bible browser.
- References are **input-format agnostic**: a ChatGPT-generated character sheet is as valid
  as commissioned art. The tool never judges provenance; it consumes pixels.

### 8b.2 Consistency tech — three tiers, ship in order

Character consistency is *the* unsolved-in-general problem of AI comics. Be honest about
that and attack it in tiers:

1. **Tier 1 — img2img from a reference** (weakest, nearly free to build): seed the render
   with the closest reference image, like World Builder's `location_denoise` mode. Good for
   "same character, slightly different angle." Drifts on anything ambitious.
2. **Tier 2 — IP-Adapter identity + ControlNet OpenPose** (the v1 core):
   IP-Adapter (Plus, and FaceID for faces) conditions generation on the reference images'
   *identity*; an OpenPose ControlNet pins the *pose* per panel. Note the history: the
   background server **removed** IP-Adapter in v1.1.0 — but that was for *style* transfer,
   where a style-trained checkpoint was simply better. Identity transfer is what IP-Adapter
   is actually for; the removal there is not an argument against it here.
3. **Tier 3 — per-character LoRA baking** (strongest, the killer feature):
   `bake_character_lora(character)` — train a small SD 1.5 LoRA on the character's
   reference set (kohya-ss backend or ComfyUI trainer nodes). SD 1.5 LoRA training is
   feasible on a 3060 12GB (~30–60 min per character); it's a one-time cost per character
   that buys the best consistency available locally. Needs ~10–20 usable reference images
   (augmentable by generating Tier-2 renders, human-curating the good ones, and feeding
   them back as training data — a bootstrap loop the tool should support explicitly).

New ComfyUI dependencies (add to a `setup_models.py`): IP-Adapter models + CLIP-Vision,
OpenPose ControlNet, optionally rembg/SAM weights for matting (§8b.3), optional trainer.

### 8b.3 Panels are composites, not one-shot generations

Do NOT try to generate a finished panel (characters + background + composition) in a
single diffusion pass — that's where consistency dies. A panel is **layers**:

1. **Background plate** — the existing background server (World Builder canon keeps the
   *location* consistent; that problem is already solved).
2. **Character layer(s)** — `generate_character_pose(project, character, pose, prompt,
   ...)`: render the character alone on a clean backdrop, auto-matte (rembg) to RGBA.
3. **Composition** — `compose_panel(background, layers=[{character, x, y, scale}, ...])`:
   deterministic CPU compositing. Zero tokens, Direct-mode friendly, instant to iterate.
   The background server's v1.6.0 **anchor tool already computes the character's on-screen
   pixel height and feet line** for a spot in the 3D city — that output feeds `scale`/`y`
   directly. The two servers were built to meet at exactly this seam.
4. **Optional harmonization pass** — low-denoise img2img over the flattened composite to
   unify lighting/grain, same trick as the background server's hires pass. Keep denoise
   low (≈0.2–0.35) or it will un-consist the character you just fought to keep consistent.
5. Speech bubbles land on top later (speech-bubble MCP, unbuilt) — panels export with and
   without the harmonization flatten so lettering always has a clean layer to sit on.

State: `panels.json` per project — panel id, script beat, layer recipe (which character,
which pose seed, which plate), and status (`draft|approved`). The recipe makes every panel
**reproducible and revisable**: "redo panel 7 with a sadder expression" re-renders one
layer and re-composites, instead of regenerating a whole page.

### 8b.4 The workflow (and the token-burn question, answered)

The loop the writer runs: describe the scene → the harness (Agent mode) breaks it into
panel beats, picks locations/poses, calls the tools → the writer **looks at the gallery**
→ gives targeted feedback ("panel 3: she should be facing away") → re-render that layer →
approve. Same two-gate shape as the translation workflow.

**Will it burn tokens like the translation did? No — if built to these rules, and here's
why the economics differ.** The translation burn came from *text as the artifact*: the
model had to re-read prose to review it, and history replay re-paid for the manuscript
every turn. Here the artifact is **images, and the reviewer is the human's eyes.** The
model never needs to "re-read" a panel — the writer looks at the gallery and says what's
wrong. Iteration cost is GPU-minutes (free, local), not tokens. The token costs that DO
exist, and their controls:

- **Script breakdown** (scene → panel beats): small, once per scene.
- **Vision** (the model actually looking at generated images to self-check): this is the
  one real burn risk. Make it **opt-in per call**, never the default loop. Default: human
  reviews, model acts on text feedback.
- **Tool schemas:** ride on every turn of every connected chat — keep them terse from day
  one (the §8a lesson, learned the hard way: ~45% schema cut was needed retroactively).
- **Session discipline:** fresh chat per scene/chapter; `panels.json` + the character
  bible ARE the state; a `get_context(project)`-style bundle tool restores it in one call.
  Ship the workflow in the server's `instructions` field, like novel-translation does.

### 8b.5a First real-user constraints (2026-07-18)

The friend interested in this is a genuine candidate first user, testing on **his own
hardware, with Codex** (not Claude Code) — two facts that must be verified/handled before
this goes further:

- **His GPU is unconfirmed.** Every tier in §8b.2 assumes local ComfyUI on an NVIDIA GPU;
  Tier 3 (LoRA baking) specifically assumed 3060-class 12GB VRAM. Check his hardware before
  building — if he lacks a comparable GPU, "runs on your own GPU, no cloud" (the ecosystem's
  core cost model) doesn't hold for him, and this needs a real conversation, not a silent
  scope-down. Do not assume a fallback (cloud GPU, quantized model, CPU inference) without
  discussing the cost/complexity trade-off with Tobias first.
  **Resolved fallback (2026-07-18):** if the friend lacks a suitable GPU, Tobias runs it for
  him on his own hardware — the friend sends references (zip/Drive folder) of his characters,
  Tobias `register_character`s them under a project namespaced to that friend's comic. This
  needs zero new architecture: it's exactly what per-project namespacing (§2.6, and the
  background server's existing `project` argument) already supports — "operator runs it for
  someone else's story" is just another project, not a new mode.
- **Codex is a real second harness, and it's fine for the server itself.** The MCP server
  (`character-panel-mcp`) is client-agnostic — any MCP harness, Codex included, can call its
  tools with zero server-side changes; this is what MCP is for. What is NOT yet built for
  Codex is the **Studio's `HarnessAdapter`** (§5.3, v1 scoped to Claude Code only) — but that
  doesn't block testing this server directly with Codex, no Studio UI required. If Codex
  becomes the primary harness for real usage (not just this friend's test), promote the
  Codex adapter out of "later" in §5.3/§9 and build it alongside, since a prerequisite
  server's only real user running a harness the Studio can't yet drive would stall Phase 1.

### 8b.5 Honest caveats (set the writer friends' expectations)

- **"Consistent enough for a webtoon with curation," not pixel-perfect.** Even Tier 3
  drifts on extreme angles, complex hand poses, and costume details. The writer curates;
  the tool narrows the drift, it doesn't eliminate it.
- **Multi-character interaction panels** (embraces, fights, physical contact) are the
  weakest spot of the layered approach — layers don't interpenetrate. OpenPose multi-person
  conditioning on a single generation is the fallback for those panels, at a consistency
  cost. Be upfront: these panels need the most retries.
- **SD 1.5 faces/hands** at distance are rough; FaceID + a face-detailer pass mitigates.
- **Style provenance:** references generated by ChatGPT/Midjourney are fine as *identity*
  references; if a friend plans commercial publication, that's their platform-ToS question
  to check, not something this tool can answer — note it in the README, once, neutrally.
- This server does **not** write the story, choose panel flow, or replace a storyboard eye.
  The harness proposes; the writer directs. Partner, not replacement — standing philosophy.

### 8b.6 Concept Genesis — ✅ SHIPPED AND LIVE-TESTED 2026-07-19

**Status: built, then genuinely stress-tested against real art the same day.**
All three tools live in `character-panel-mcp/server.py` (`generate_character_concept`,
`crop_reference`, `generate_reference_sheet`), backed by `workflow.generate_concepts()`
and `tools/crop_reference.py`. `generate_character_pose`'s core rendering was
extracted into a shared `_render_pose()` helper so `generate_reference_sheet`
reuses it rather than duplicating Tier 1/2/3 logic — regression-tested against
the exact pre-refactor output strings to confirm zero behavior change.

**The real test (not the God/Speed one — Tobias's own RxR characters instead):**
registered Trevor and Lumiere from Tobias's Reincarnator x Regressor Volume 1
art and ran `generate_reference_sheet` on both. First pass was a genuine
failure, not a rough draft: every "view" came back as a near-identical re-roll
of the source illustration's own busy composition (magic-circle/ice-crystal VFX
for Trevor, fire for Lumiere), completely ignoring the requested angle and the
clean-backdrop prompt — because `ref_denoise=0.7` still anchored heavily on the
source latent, and `ip_adapter_weight=0.8` conditioned IP-Adapter on the
reference's whole scene, not just the character (the two characters had also
been registered with no `description`, so text had nothing to anchor identity
with either — a self-inflicted part of the problem). Tobias also flagged the
output format itself: separate files instead of one sheet like Avery's.

**Both fixed live, in the same session, with real re-tests after each change:**
1. Populated real `description` text for both characters (visual facts only).
2. Built `tools/compose_sheet.py` — deterministic PIL grid layout, no GPU — and
   wired it into `generate_reference_sheet` as `combine=True` by default. This
   was already anticipated and explicitly deferred in this doc's original v1
   scope ("a nice-to-have... deferred until someone actually wants it") — someone
   did, same day.
3. Parameter sweep (4 then 2 more configs, all against real ComfyUI) found
   `ref_denoise=1.0` + `ip_adapter_weight=0.25` fixes the composition-anchoring
   bug — confirmed by inspecting actual output images, not just checking for
   errors. This surfaced a second artifact (SD1.5 occasionally rendering two
   figures at full denoise), fixed with explicit negative terms plus a `solo`
   tag added to `workflow.py`'s clean-backdrop prompt/negative *globally* (not
   sheet-only, since clean single-subject output is Tier 1's whole promise).
   Also found and fixed in passing: `rembg` alone doesn't pull in a working
   inference backend (`onnxruntime` was missing from `requirements.txt` —
   matting had never actually been exercised live before this session, in any
   prior release).
4. Full 14-view/2-character regeneration re-run after each fix, ending with a
   targeted 2-view re-test that confirmed the `solo`-tag fix. See
   `character-panel-mcp/CHANGELOG.md`'s 1.3.0 entry for the complete before/after.

**What's now solid vs. what remains a real, documented limitation:** backdrop
cleanliness and identity consistency across all 7 views are now good for both
characters. **Genuine back-view turnarounds are NOT solved** — "back view"
reliably renders a different 3/4-ish angle, never an actual view from behind,
even with every fix above applied. This reads as a real SD1.5-checkpoint
limitation for non-front angles, distinct from (and not fixed by) the
composition-anchoring bug — `generate_reference_sheet`'s docstring now points at
`pose_ref_path` (OpenPose, structural control from an actual back-facing photo)
as the principled fix rather than more prompt/weight tuning. Not silently
dropped — documented in the tool's own docstring, the README, and here.

**The gap this fills:** everything in §8b assumes the writer already *has* a full
character reference set. In reality there are **three kinds of users, three on-ramps —
converging on one machine** (`generate_reference_sheet`, below):

1. **No art at all** (writer with a story/novel only): txt2img candidate batches
   (`generate_character_concept`) → human picks the winner → registered as ref #1.
   Currently these users can't enter the pipeline at all — `register_character`
   needs image files.
2. **Composite concept sheets** (the friend's case — ChatGPT/Midjourney sheet
   generators): slice into clean single-view crops (`crop_reference`) → register.
3. **The artist's own drawing** (Tobias's case — Reincarnator X Regressor, Starry
   Knight): he draws ONE good illustration of the character, registers it directly
   as ref #1 — no new tool needed, `register_character` already takes any image.
   The pain this kills is real and specific: the turnaround grunt work ("back view,
   front view, hands…" — the character-concept homework every teacher assigns)
   that stands between a finished character design and actually drawing the comic.
   The tool does the *rotational reasoning* — what the back of the outfit looks
   like, how the silhouette reads in profile — so the artist doesn't redraw the
   character six times before page one.

All three converge: ref #1 in the bible → `generate_reference_sheet` grows the
view checklist from it → curated keepers append → Tier 2/3 consume the set. The
nice irony is worth preserving in the README: the same machinery serves the writer
who can't draw at all and the artist who can but shouldn't have to six times.

**One important asymmetry for on-ramp 3 (artist's own art):** for a no-art user,
whatever SD1.5 renders *becomes* the character's canonical look. For an artist, the
hand-drawn style IS the ground truth, and generated views will render in the
checkpoint/LoRA's style, not theirs. So for this on-ramp the generated turnaround is
primarily **reference material to draw from** (answering the spatial questions), not
final art pasted into panels — which happens to be exactly what the concept-homework
use case needs. Practical corollaries for the builder: (a) the existing `lora` param
already covers "don't force Niji onto my personal-style character" (pass `""` or a
closer-matching LoRA); (b) advise clean input — a full-body drawing on a plain
background conditions far better than a busy illustration (matting via the existing
`workflow.matte()` can help); (c) an artist who curates generated views back into the
bible is also quietly assembling a Tier-3 training set of their OWN character —
mention it, don't push it.

**Decision — a feature of `character-panel-mcp`, NOT a new server, NOT a standalone
skill.** Apply §8b's own new-server test in reverse: same domain (characters), same
state (the output IS the character bible — concepts become `refs[]`), same ComfyUI/SD1.5
stack, same failure surface. A separate server would duplicate `workflow.py` for zero
isolation benefit. A skill alone can't do it either, because one genuine tool primitive
is missing (see below) — but the *conversational* part of the flow (interviewing the
user about their character, distilling prose into generation-ready fields) is harness
work, taught through docstrings/README like the rest of this server. If that guidance
outgrows docstrings, promote it to a portable skill later — not v1.

**Squaring this with "reference-driven, never generate-from-text-and-pray" (§8b's core
philosophy):** no contradiction — genesis is the phase that *creates* the ground truth
the philosophy then protects. The flow is gated exactly like translation approval
(§8a): generate candidates → **human picks the winner** → only the picked image is
registered as canon → every subsequent sheet view is generated *from* that canon
(Tier-2 identity machinery, not fresh txt2img) and **individually curated before being
appended**. The human authors the canon; the tool just renders drafts. Note also: the
friend's own sheets were made exactly this way (frontier-model txt2img + his curation) —
this brings that workflow in-house on the user's own GPU.

**What the friend's actual sheets taught us (46 God/Speed sheets reviewed 2026-07-19).**
Each is ONE composite JPEG: full-body hero view + labeled expressions strip + (often) a
back view + action vignettes + heavy text overlay (bio, stats, quotes, domain
mechanics). Three lessons baked into this design:

1. **The multi-view content is exactly right** — expressions strips, back views, and
   pose vignettes are the identity data Tiers 1–3 feed on. The standard "complete
   sheet" checklist below is modeled on what his sheets naturally contain.
2. **A composite sheet is unusable as a direct reference.** img2img/IP-Adapter would
   condition on the *layout* (text blocks, panel borders), not the person. Sheets must
   be **sliced into clean single-view crops** before registering. That's a real tool
   gap — and the immediate blocker for the God/Speed images sitting in
   `Documents/Stories (Mine)/Burning Spirit High/God Speed/` right now.
3. **Most sheet text is story-flavor, not generation data.** Distillation guidance for
   the harness (this is LLM judgment, not tool code):
   - → `description`: ONLY visually renderable identity facts — build, face, hair,
     costume + signature elements, palette words. ("Gaunt, long-nosed, manic grin,
     purple-and-black uniform, white gloves, gold pocket chain" conditions SD;
     "silver-tongued manipulator" does not.)
   - → `notes`: on-model gems and behavior constraints ("never smiles fully",
     "the satchel is her signature weapon — always present").
   - → `tags`: role/genre labels; domains/powers *adapted to the story's genre* land
     here or in notes.
   - → DROPPED from the bible (stays in the user's own story docs): quotes, birthdays,
     biographies, stat blocks, incident lists. The bible is a *generation* asset, not
     the story bible.

**New tools (three, all in `character-panel-mcp`):**

1. `generate_character_concept(description, style_prompt="", negative="", n=4,
   project=..., model=..., width=640, height=896, seed=None, lora=None, ...)` —
   the missing primitive: batch txt2img candidates for a character that does NOT yet
   exist in the bible (`generate_character_pose` requires a registered character; this
   is the only generation path that must not). Implementation is nearly free:
   `workflow.generate()` already does pure txt2img when `ref_path=None` — this tool
   loops it over `n` seeds (one graph submit per seed is fine; GPU-local, no token
   cost), writes to `output/<project>/_concepts/<slug>/`, returns the paths. Clean
   backdrop suffix applies (matting-ready). The human picks a winner and registers it
   via the existing `register_character` — this tool does NOT auto-register anything
   (§8a's `propose_glossary_term` precedent: staging, never auto-commit).
2. `generate_reference_sheet(character, views=None, project=..., ...)` — grows a
   registered character's reference set toward the standard checklist, one Tier-2
   generation per view, seeded from the primary ref with IP-Adapter identity on:
   default view list `["full body, front view", "full body, back view", "full body,
   side profile", "3/4 view", "face close-up, neutral", "face close-up, smiling",
   "face close-up, angry"]` — overridable, or a single view for redo-one-shot
   iteration. Outputs land in `_concepts/` for curation; the human appends keepers via
   `register_character` (existing append semantics — this IS the §8b.2 bootstrap loop,
   now with a front door). Internally this is a thin loop over the existing
   `generate_character_pose` path with `matte=False` defaults (sheets are for
   reference, not compositing). Honest note in the docstring: back/side views of a
   character who exists in one front-view image WILL drift — curate hard, expect
   retries, and consider Tier-3 baking once ~10+ curated refs accumulate.
3. `crop_reference(image_path, boxes, out_dir=None)` — deterministic PIL cropper:
   `boxes` = list of `[x0, y0, x1, y1]`, saves each crop, returns paths ready for
   `register_character`. Zero GPU, Direct-mode friendly, mirrors
   `tools/compose_panel.py`'s CLI+importable shape (`tools/crop_reference.py`). This is
   the sheet-ingestion path for users who arrive with composite sheets (the friend,
   anyone using ChatGPT/Midjourney sheet generators). Crop boxes come from the human
   eyeballing the sheet, or from the harness *looking at it once* (vision — opt-in,
   once per sheet, consistent with §8b.4's vision-cost rule) and proposing boxes for
   approval.

**Explicit non-goals (v1):** generating composite *designed sheets* (text blocks,
layout, logos — the cosmetic artifact the friend's sheets are). Local SD1.5 cannot
match a frontier model's text rendering and layout, and the bible (JSON + ref folder)
already IS the machine-readable sheet. A cosmetic "export printable sheet" (PIL
typesetting of bible data + refs — deterministic, no GPU) is a nice-to-have for
sharing/portfolio, deferred until someone actually wants it. Also out of scope:
auto-registering anything, BLIP/auto-captioning, and any change to the three-tier
generation core.

**Caveats to carry into the build:**
- **Genesis consistency is bootstrapped, not solved.** Candidate #1 is the only ground
  truth at first; every other view is Tier-2 inference from it. The checklist sheet
  will need multiple retries per view. Set expectations in tool output text, same
  honesty bar as the tier notes.
- **SD1.5 + Niji V5 output will not look like the friend's frontier-model sheets.**
  Different aesthetic ceiling. The comparison to set: "good enough to keep a character
  consistent in YOUR webcomic," not "matches ChatGPT sheet art."
- **WhatsApp-compressed references** (the God/Speed images are WhatsApp re-downloads):
  fine for Tier 1/2 identity conditioning; marginal for Tier-3 LoRA training. Get
  original files from the friend before baking his characters' LoRAs.
- Schema discipline (§8a lesson): three new tools = three more schemas riding every
  turn. Keep docstrings tight; the long-form guidance above belongs in README, not in
  every schema.

**Verification (for the builder, same honesty bar as Tiers 1–3):**
1. `py_compile` everything; smoke-test tool listing via the existing `test_client.py`.
2. `crop_reference`: unit-test with a synthetic composite (paste 3 colored rects into
   one image, crop them back out, assert pixel-exact sizes/contents). No GPU needed.
3. `generate_character_concept`: unit-test the loop logic with `workflow.generate`
   monkeypatched (assert n calls, distinct seeds, correct out_dir); live against
   ComfyUI if it's up (it was for the Tier-2 build — same opportunity likely).
4. `generate_reference_sheet`: unit-test view-list iteration the same way; one live
   view if ComfyUI is up.
5. **The real end-to-end test is the God/Speed ingestion** (on-ramp 2): slice one
   friend sheet with `crop_reference`, register the crops, run one Tier-2 pose — but
   do this WITH Tobias reviewing, not as an automated check, and never commit his art
   (it's `characters/`-gitignored anyway; keep it that way).
5b. **On-ramp 3 test, if Tobias supplies a drawing**: register one of his own RxR or
   Starry Knight character illustrations as ref #1 and run `generate_reference_sheet`
   for a back view — the single most useful view for his concept-homework use case.
   Same rules: he reviews, nothing committed.
6. Report explicitly what was and wasn't live-exercised. Update this section's status
   marker and the §1 table row when shipped.

### 8b.7 SDXL prototype + the back-view campaign — ✅ SHIPPED / 📋 DOCUMENTED 2026-07-19

**Why this exists:** the first real end-to-end use of Concept Genesis (Tobias's
own RxR characters) exposed two failures that survived every tuning attempt on
the SD1.5 stack: distorted full-body anatomy ("spider legs") and no genuine back
views. Tobias's call: test SDXL, specifically the Midjourney Manga Art Style
SDXL LoRA (civitai.com/models/185798) — the exact LoRA `webcomic-background-mcp`
v1.7.0 had rejected purely for being SDXL-only. Prototype scoped to
`character-panel-mcp` alone; the background server stays untouched until this
proves out (its upgrade is a separate, later decision).

**What shipped:** `model="mj_manga_sdxl"` as an *additional* model option (no
SD1.5 deletion — reversibility first), `setup_models_sdxl.py` with staged
downloads, automatic trigger-word/clip-skip/resolution handling. **Hardware
reality beat the plan's fear:** the plan warned a 6.94 GB checkpoint on the 6 GB
RTX 3060 Laptop might mean multi-minute offloading-bound generations; measured
reality was ~75s cold / ~30s warm. Anatomy is fixed outright, backdrops clean,
identity strong (validated: ip_adapter_weight≈0.3, ref_denoise=1.0). Staged
verification worked as designed — each stage's failure was diagnosed from
ComfyUI's actual error/history API, including a wrong-local-path bug for the
OpenPose annotator models (the node's `subfolder` logic only applies to the
legacy repo id) and two self-inflicted false download failures (wrong
binary-signature sanity checks — a lesson recorded in CHANGELOG).

**The back-view campaign (the honest core of this section):** ~12 configurations
across both base models — prompt-only, img2img sweeps, IP-Adapter 0.25–0.8, pure
text-to-image, OpenPose ControlNet at strengths 1.0–1.6 with face/hand keypoints
on/off, direction-ambiguous (Bleach reference) and direction-distinctive
(Avery's Barker hands-behind-back) poses, identity on/off. Findings:

- The stack CAN paint back-view bodies — but only ever as extra figures inside
  messy multi-figure/fused compositions (keypoints-ON + no anti-dupe negatives).
- Every configuration that forces a clean single figure (anti-dupe negatives
  and/or body-only skeletons) reverts to front/profile — including with "face,
  profile" in the NEGATIVE prompt at ControlNet strength 1.5.
- Back-ness and cleanliness never co-occurred. This is a checkpoint-level prior,
  not a tuning failure. A hypothesis (face keypoints cause faces) was tested
  both directions and REVERSED by the data — keypoints-on produced the only
  back-body geometry. Recorded because the reversal is the finding.

**Interim practical answer** (Tobias's own realization mid-campaign): real back
views already exist in concept sheets — Avery's God/Speed sheets have them —
and `crop_reference` → `register_character` ingests them today. Artists draw
one back view per character; it becomes canon. Generation is not the only door.

**The 3D posable mannequin (Tobias's proposal) — ✅ SHIPPED / VALIDATED
2026-07-19:** re-applies the ecosystem's proven mesh-to-ControlNet pattern
(citygen.py cities → sketches; props.py parametric bicycle → Canny) to a
low-poly posable humanoid, `character-panel-mcp/mannequin.py`. Key technical
insight, confirmed correct: the failure lived partly in *extracting* skeletons
from 2D art (the OpenposePreprocessor guesses left/right limb assignment and
facing from appearance, with no way to encode "facing away from camera"). The
mannequin *synthesizes* the control map from 3D joints instead — a
hand-authored COCO-18 skeleton with pose presets, rotated about the y-axis to
any yaw, projected to 2D with correct left/right limb-color assignment (which
flips naturally at yaw=180°) and occlusion-based face-keypoint dropping
(rotated toward-viewer z-component below a threshold). Own module, no code
dependency on the background server (per §2), pure numpy+PIL rasterization
like citygen — no GPU needed to generate the map itself. Feeds the existing
ControlNet branch via `workflow.py`'s new `pose_preprocess=False` bypass
(skips `OpenposePreprocessor`, since running human-detection on an
already-synthesized stick figure fails).

**Live verification (2026-07-19, real Trevor reference, SDXL):** at
`pose_strength=1.0` the pose direction still relaxed back toward front-facing
in some trials; escalating to `pose_strength=1.4-1.5` produced the project's
first genuine clean single-figure back view — back of head, jacket back-seam
and vent, no face, correct anatomy. **Honest finding: stochastic, not
deterministic** — identical settings with a different seed produced a
front-facing result instead (2-seed sample). This is a curate-a-few-seeds
tool, matching the propose-then-curate discipline the rest of this server
already uses, not a one-shot deterministic fix. Identity retention
(IP-Adapter) at this strength/angle wasn't tested beyond `identity_mode="off"`
— a natural next question if back-view + strong identity locking is needed
together. Exposed as `generate_pose_map` (preset, yaw) on the MCP tool
surface; does NOT solve identity/costume attachment (that remains
IP-Adapter/description/Tier-3) — it solves pose+angle, which was exactly the
unsolved piece. The anime-specialist-SDXL-checkpoint alternative was not
needed and remains unexplored.

### 8b.8 Avery-template sheet, sequential generation, and the real hand-anatomy fix — ✅ SHIPPED 2026-07-20

Direct feedback on v1.0.0's first designed sheet: use Avery's actual template more
literally (front/back/expressions layout, kept), reduce the text to three fields
(Profile/Abilities/Appearance — Appearance being `description` itself, not a new
field, so nothing is typed twice), and generate views as a disciplined front→back→
expressions *sequence* rather than N independent rolls. All three shipped
(`tools/compose_sheet.py`'s `compose_concept_sheet`, `characters.py`'s `profile`
field, `server.py`'s sequential loop in `generate_reference_sheet`) — but the
sequencing's scope was corrected mid-flight by live testing: the first cut chained
EVERY later view's identity conditioning off the freshly-generated front view, and a
real end-to-end test against Trevor caught it immediately — the "smiling close-up"
view came back as a repeat of the front view's full-body action pose, because
IP-Adapter conditions on the whole reference image, not just "this person's face."
Narrowed to: only the back view chains off the front view (both full-body, so the
framing match is appropriate); expressions reverted to the bible's own primary
reference. Also reworded the close-up prompts ("close-up portrait, head and
shoulders only, head turned three-quarters, ...") after "face close-up, 3/4 view"
alone got interpreted as a 3/4-angle body shot.

**The same live test also caught the back view showing a fully front-facing
figure — not a new bug, exactly the pre-existing back-view limitation this
project already spent ~12 configurations on (§8b.7), just not yet wired into this
tool.** Tried fixing it properly: auto-generate a mannequin ControlNet pose map for
the back view and force `identity_mode="off"` (confirmed live that
`identity_mode="plus"`, this tool's default, wins the fight against ControlNet and
keeps renders front-facing even at `pose_strength=1.45`). With identity forced off,
genuine back-facing content DID start appearing in frame — real progress — but
**scrutinizing hands and feet specifically, not just checking facing direction,
found it came with a fused fingerless hand and hoof-like feet**, and retrying
reproduced the same failure rather than converging on a clean result. Reverted
entirely: shipping a mechanism that trades wrong-direction for deformed anatomy on
an unattended bulk call is worse than the honest status quo. Back view stays a
known, open, undismissed limitation of `generate_reference_sheet` — the validated
path (§8b.7's recipe, `generate_pose_map` + `generate_character_pose`, curated by
hand across a few seeds) remains the right tool for when a back view is actually
needed, not something safe to fire unattended in a 5-view bulk call. Worth
recording precisely because the failure mode here is instructive: automating a
tool that's only validated as a manually-curated, one-at-a-time flow doesn't
just inherit that flow's known unreliability — removing the human review step
that used to catch bad results let a materially worse failure mode (deformed
anatomy, not just wrong direction) ship silently until direct user scrutiny
caught it.

Also requested: install whatever's needed (ComfyUI Impact Pack, "human 3D models")
to cut down on hallucination/body horror. Assessed and reported honestly before
building: the field/sequencing work addresses sheet UX and cross-view *identity*
drift, not anatomy — the actual fix for hallucinated hands/faces is a
detect-and-inpaint-at-higher-resolution pass, since a hand is a small fraction of a
full-body frame (too few pixels), not a prompt-wording problem. Installed
`ComfyUI-Impact-Pack` + `ComfyUI-Impact-Subpack` (YOLOv8 face/hand detectors from
`Bingsu/adetailer`) and wired an opt-in `detail_fix` pass into `workflow.py`'s graph.
**Live-verified with an actual before/after crop comparison** (the discipline this
whole project has tried to hold to): the first attempt (`denoise=0.45`) detected the
hand correctly but was too conservative to fix it — visually identical to no fix at
all. `denoise=0.6` produced a real, visible improvement (distinct finger separation
vs. a featureless fist blob) on the same seed; shipped as the default.

**The "human 3D models" request (depth/volumetric body conditioning, beyond
`generate_pose_map`'s line-skeleton):** scoped honestly before building anything —
procedural capsule limbs (no download, lower fidelity) vs. a real posable mesh (real
download/licensing check, higher fidelity, better anime-proportion match) presented
as an explicit choice; Tobias chose the real mesh. Sourced
`assets/Base_Male.vrm` — VRoid's own alpha-era CC0-licensed base model, re-hosted on
OpenGameArt.org (verified genuinely CC0 via its FAQ page, in contrast to VRoid Hub's
`AvatarSample_A`-class samples, which are explicitly NOT CC0 — checked and rejected
first). 67-joint standard-VRM-bone-named skeleton, structurally verified via
`pygltflib` (`.load_binary()`, not `.load()` — the latter mis-sniffs VRM's binary
glTF container as text JSON and throws `UnicodeDecodeError`). **Not yet wired into
the pipeline** — loading the mesh, mapping VRM bone names onto `mannequin.py`'s
existing joint/pose-preset convention, posing via bone rotations, rendering a
depth/normal map, and feeding it into `workflow.py`'s ControlNet branch is queued as
its own follow-up build, not crammed into the same session as everything above.

### 8b.9 FLUX exploration + Stage 5 live-tool integration — ✅ WIRED IN, RELIABILITY CAVEATS OPEN (2026-07-21/22/23)

**Why FLUX at all:** §8b.7/8b.8 pushed the SD1.5/SDXL stack hard on hand anatomy —
CharTurn + RPGTurn + ClearHandsXL LoRA stacking, `detail_fix` denoise tuning — and
hit a real ceiling: hands kept coming back as "blobs of flesh with fingers sticking
out" even with every correction LoRA stacked at once. Direct call from Tobias after
watching this stall out: stop stacking fixes on a base model that's the actual
bottleneck, and prototype FLUX.1-dev instead — same reasoning as §8b.7's original
SD1.5→SDXL jump, one level up.

**Hardware, honestly:** same 6 GB VRAM laptop as every prior stage. FLUX.1-dev's
full checkpoint is far too large to load directly, so this used GGUF quantization
(`ComfyUI-GGUF` custom node, city96) — `flux1-dev-Q3_K_S.gguf` (~5.0 GB), the
conservative pick over the "recommended" Q4_K_S (~6.9 GB, already exceeds the VRAM
budget alone before anything else loads). Confirmed no OOM at Q3_K_S with everything
else (T5 + CLIP-L text encoders, VAE, LoRAs, ControlNet) loaded alongside it.

**Staged validation, each stage a real go/no-go gate before spending time on the
next** (all work so far lives in standalone scratch scripts, not yet ported into
`workflow.py` — see "Not yet done" below):

- **Stage 1 — base txt2img** (GGUF unet + a manhwa/webtoon style LoRA,
  `manwha_style.safetensors` @ strength 1.0–1.5): validated. ~185–320s per image
  depending on what else is chained on. Genuinely good manhwa-style output, a clear
  step up from SDXL on first look.
- **Stage 2 — hand `detail_fix`** (same Impact Pack mechanism as §8b.8, ported
  unchanged): FLUX needed a higher denoise than SDXL to actually fix anatomy —
  `denoise=0.55` was insufficient (still 6 fingers on live inspection), `denoise=0.7`
  fixed it (confirmed 5 fingers, only a minor cosmetic pinky-length issue remaining).
  Shipped as the FLUX-specific default, `SDXL_DETAIL_HAND_DENOISE=0.6` unchanged.
- **Stage 3 — back view via ControlNet + the existing mannequin pose map**
  (`mannequin.render_pose_map(yaw=180)`, reused completely unchanged from §8b.7,
  fed through `flux_controlnet_union_alpha.safetensors` — InstantX's community
  "Union" ControlNet, `SetUnionControlNetType(type="openpose")` in front of
  `ControlNetApplyAdvanced`): **partially reliable, not solved.** Across two full
  3-seed rounds (`pose_strength=0.8`, LoRA strength 1.0 then 1.5), 2 of 3 seeds
  produced genuine, unambiguous back-facing views — a first for this project across
  both SDXL and FLUX — but the third seed (1234) missed the direction lock
  identically both times, landing as a full front view instead. **This is seed-
  dependent, not noise**: the same seed failed twice under the same settings, while
  the other two succeeded twice. Diagnosis: `flux_controlnet_union_alpha` is an
  explicitly alpha-quality community adapter (FLUX's ControlNet ecosystem is much
  less mature than SDXL's), and ControlNet strength is a soft pull competing against
  the text prompt, the style LoRA, and FLUX's own base-model bias toward front-facing
  training data — not a hard constraint, so some seeds' starting noise just tips the
  balance the wrong way. Costume/style also drifted noticeably from the character's
  written description at this ControlNet strength — flagged, then explicitly
  deprioritized by Tobias ("costume is fine... I'm more concerned about anatomy than
  costume") — anatomy and direction correctness rank above costume fidelity for this
  pipeline's evaluation going forward.
- **Stage 4 — FLUX Kontext dev** (`flux1-kontext-dev-Q3_K_S.gguf`, ~5.23 GB,
  reuses the same T5/CLIP-L/VAE as Stage 1–3): a genuinely different mechanism from
  ControlNet — an image *editor*, not a pure text-to-image model, taking an existing
  render plus a natural-language instruction (`ReferenceLatent` +
  `FluxKontextImageScale` nodes, verified live against the running ComfyUI instance
  before building anything). Two distinct uses tested, with two different results:
  - **Local edit on an already-correctly-posed image**: took a genuine back view
    with hands hidden in sleeve cuffs (Stage 3's seed 777) and instructed it to
    "show both hands visible at his sides... keep everything else the same." **Worked
    cleanly** — hands appeared, anatomically correct (clear thumb + finger
    separation, natural curl), and the back-facing direction, costume, and pose were
    untouched. This is now the validated tool for surgical hand-anatomy fixes.
  - **Full front→back rotation as a single edit**: took a front-view miss (Stage
    3's seed 1234) and instructed Kontext to both turn the character around and
    expose his hands in one edit. **Failed** — produced a chimera: the head, hair,
    jacket, and hands turned to face away as instructed, but the tank-top's neckline
    (a clear front-facing scoop/collarbone silhouette) and both shoes (toe box facing
    the viewer, not heels) stayed rendered as if still facing front. Root cause:
    "turn around" and "keep everything else the same" are self-contradicting
    instructions for a full viewpoint change — a genuine back view requires the
    *whole* body's silhouette to change, and Kontext resolved the contradiction by
    only partially rotating the figure rather than committing to one direction.
    **Caught by Tobias, not by the first-pass review** — the review had only zoomed
    into the hands (the region the edit instruction named) and missed scanning the
    rest of the body; recorded as a standing review-discipline fix (scan the whole
    figure — head, neckline, hands, legs, shoes — for any direction verdict, not
    just the region an edit targeted).
  - **The dedicated turnaround-sheet LoRA** (`kontext-turnaround-sheet-v1.safetensors`,
    Civitai model 1753109, "trained using Ostris AI Toolkit" per the creator, not
    kohya-ss): tested once, at a guessed 1536×768 landscape canvas / 20 steps /
    LoRA strength 1.0. **First attempt failed** — produced 7 panels instead of the
    requested 5, and none of the seven showed an actual back view (every panel
    showed the face, front-on or in profile); costume also drifted in most panels.
    Not treated as a dead end, though — this was the LoRA's first-ever test, with
    mostly guessed settings, and a genuine, concrete lead surfaced afterward: the
    prompt used matched the creator's "recommended prompt" verbatim ("...of this
    **exact** character...", per the page), but the creator's separate
    trigger-phrase note requires the literal substring "create turnaround sheet of
    this character" (no "exact" spliced in) if the prompt is modified — the page
    itself is inconsistent between its "Required Trigger Phrase" callout ("create
    **a** turnaround sheet...") and that note.
    **Retested same-session with only that one word dropped, everything else
    identical (same source image, same seed, same 1536×768 canvas, same 20 steps):
    fixed it.** Panel 4 of 7 came back a genuine, clean back view — verified against
    the full whole-figure checklist below, not just a glance: correct back-of-collar
    shape (no front scoop), a visible center-back shirt seam, rear pants pockets, no
    belt buckle, both hands showing natural back-of-hand curl with no fusion. Real
    confirmation that the inserted word was diluting the learned trigger
    association, not a coincidence — dropping one word turned a 0-in-7 result into
    a working back view. Still 7 panels instead of 5 and costume still drifts on
    most panels, but the core capability (a genuine back view out of this LoRA) is
    now demonstrated, not just theorized.

**Current honest verdict:** the mechanisms themselves are wired into the live
tool (Stage 5, below), but their reliability figures haven't changed just
because the code moved out of scratch scripts. The mannequin+ControlNet path
remains the only mechanism validated across multiple seeds (~2/3-reliable); the
turnaround-sheet LoRA has now produced one genuine, fully-scrutinized back view
with the corrected trigger phrase, but that's a single successful seed, not yet a
reliability figure — worth a proper multi-seed re-run before treating it as
comparable to or better than ControlNet's reroll rate. Kontext-as-editor remains
validated only for surgical anatomy fixes on a pose that's already facing the
right way, not as a direction-control mechanism itself.

**Stage 5 — wired into the live tool (2026-07-23):** the validated recipe above
is now real code, not just scratch scripts. New `flux_workflow.py` (a separate
module from `workflow.py` — FLUX's ComfyUI graph shares almost no node types
with SD1.5/SDXL, so threading it through `build_graph()` as a third convention
would have made an already-dense function much harder to read, not simpler).
`model="flux_manwha"` now works anywhere a model name is accepted; three new
tools implement the staged workflow the validated stages actually call for —
`generate_turnaround_sheet` (Kontext + turnaround-sheet LoRA, reads a
character's registered reference), `edit_character_image` (Kontext as a
general-purpose plain-English editor, the validated local-fix mechanism), and
`compose_reference_sheet` (assembles the Avery poster from already-existing
images, e.g. panels `crop_reference` sliced from a turnaround sheet, rather
than generating fresh views). `identity_mode`/IP-Adapter raises a clear error
if requested with FLUX — that combination was never tested, and silently
ignoring it would be worse than refusing outright. Verified: the module
imports cleanly, `server.py` imports cleanly with all three new tools
registered, and a hand-built graph-construction smoke test produced the
expected node count — not yet exercised through an actual live ComfyUI call at
the time of this write-up (see the smoke-test step immediately following).

**Explicitly not yet done:**
- SDXL's checkpoint/LoRA/IP-Adapter/ControlNet files (~12.5 GB) are untouched —
  deliberately kept until the FLUX path gets real end-to-end use through the
  live tool, not deleted preemptively.
- `webcomic-background-mcp` (still SD1.5) has not been touched or evaluated for a
  FLUX/SDXL upgrade — no demonstrated quality problem exists there, unlike the
  character pipeline's concrete anatomy crisis that motivated this whole detour.
- Personal-LoRA training (kohya-ss `train_network.py`, already built for §8b's
  Tier-3 baking) does not support FLUX out of the box — FLUX needs either kohya's
  separate `flux_train_network.py` path or a different trainer (Ostris ai-toolkit,
  the tool that trained the turnaround-sheet LoRA above). Tobias floated training a
  custom anatomy LoRA from a personal manhwa collection as a much-later idea, no
  details yet — not scoped or started.

### 8b.10 VRM depth-map ControlNet — a more reliable direction fix, wired in (2026-07-22/23)

Stage 5 (§8b.9) shipped the mannequin skeleton's ControlNet path as the working
direction-control mechanism, but it stayed capped at ~2/3-seed reliability — an
open problem, not something Stage 5 solved. Motivated by that gap, plus
Tobias's specific question ("do we need to upgrade mannequin python to Blender
python?"): the current line-skeleton mannequin doesn't need Blender (pure
numpy+PIL, confirmed by re-reading its own docstring) — but the *other*
pending task, rendering a depth/normal map from the actual `Base_Male.vrm`
mesh (§8b.8's asset, never wired up), is a genuine 3D-rendering problem where
Blender is the right tool. Built and validated same-session, then wired in.

**Blender setup, decided live:** `pip install bpy` was ruled out — the
pip-installable Blender-as-Python-module package skips this project's Python
3.12 entirely (jumps 3.11 → 3.13, confirmed by checking PyPI's actual wheel
listings, not assumed). Installed the real portable Blender 5.2 LTS instead
(no installer, just unzip) — it bundles its own Python (3.13), sidestepping
the version-matching problem entirely, and having the actual application
was genuinely useful for interactively debugging the VRM import/pose/render
during development. The community VRM Add-on for Blender (saturday06,
"Extension" package) installs headless via `bpy.ops.extensions.package_install_files`
+ `bpy.ops.wm.save_userpref()` — the save step is required, or the addon
doesn't persist to the next headless launch (confirmed live: it silently
reverted to disabled in a fresh process without it).

**The Blender 5.2 API churn, worth recording since it cost real debugging
time and none of it was documented anywhere findable:** `Scene.node_tree`/
`use_nodes` were replaced by `Scene.compositing_node_group` (a real
`CompositorNodeTree` you create and assign yourself);
`CompositorNodeMapRange`/`CompositorNodeMath` no longer exist as
compositor-specific types — use the unified `ShaderNodeMapRange`/`ShaderNodeMath`
(works in any node-tree type now); `CompositorNodeOutputFile`'s `base_path`/
`file_slots` were replaced by `directory`/`file_output_items` (a collection
needing `.new(socket_type=...)`, with per-item format overrides silently
ignored unless `item.override_node_format = True` is set explicitly — this one
produced a real "why is it still writing EXR after I set format.file_format
='PNG' three different ways" debugging detour). Also: Blender's headless
image-loading (`bpy.data.images.load()`) doesn't decode pixel data at all in
`--background` mode on this version (`has_data` stays `False`, no amount of
`.reload()` fixes it) — worked around by having Blender write raw EXR passes
only, then converting to PNG entirely outside Blender, in this project's own
Python, via the `OpenEXR` package (added to requirements.txt).

**A real calibration bug, found by questioning a "looks fine" result rather
than trusting it:** the first depth-map render used a generous `dist±1.2`
near/far window (2.4 units) for the ControlNet remap, producing what looked
like a clean silhouette. Fed into FLUX, seeds came back with a hallucinated
second, disembodied head near the hip, a hard left/right color-split down
the body's midline, and other artifacts no line-skeleton test had ever
produced. Tobias pushed back on the assumption directly: "how can we fix
the costume geometry... the basic Blender maps worked... how did they not
translate into good seeds? Is that puzzling." Backing out the actual
camera-space Z values from the rendered output showed why: the body's real
front-to-back depth is only ~0.25 units (2.89–3.14 at `dist=3.0`) — the 2.4-unit
window was ~8x too wide, so the body's foreground pixels only ever spanned
roughly 0.44–0.55 of the 0–1 output range. It *looked* like a clean silhouette
at a glance but carried almost none of the actual relief/structure a depth
ControlNet needs — the model was starved of real geometric information and
had to guess, which is exactly the kind of gap hallucination fills. Recalibrating
to a tight `dist±0.25` window (measured, not guessed) fixed it outright:
**3/3 seeds landed genuine back views** on the very next test, matched again
on a second 3-seed batch — a real, repeated result, not a fluke, and a clear
improvement over the mannequin skeleton's ~2/3.

**Depth vs. normal, same recalibrated setup, head-to-head:** `type="normal"`
also nailed direction 3/3, but costume coherence was markedly worse across
the board — one seed's torso became an incoherent paint-smear, another's
entire garment derailed into an unrelated long robe (nothing like the
described shirt/tie/blazer/pants), a third had wrong pant color. `type="depth"`
won cleanly; `type="normal"` was dropped.

**The costume-geometry conflict — a second real bug, correctly separated from
the first:** even with the depth window fixed, one seed produced a ragged,
incoherent texture patch on the back of the shirt. Diagnosis, confirmed by a
pose-only regeneration test: the VRM mesh wears a plain t-shirt (no blazer
modeled), so describing Trevor's actual "rust-brown blazer with yellow-gold
trim" in the text prompt fights the depth geometry, which has no room for a
jacket — the model tries to paint a garment the silhouette doesn't support.
Dropping all costume text from the prompt (pose/anatomy identity only) and
regenerating: **2 of 3 seeds came back completely clean**, no texture-clash
artifact at all — confirming the conflict was the cause, not an unrelated
seed-quality issue (the one seed that still had an artifact showed a
*different*, independent quirk — an abstract graphic bled onto the shirt with
no costume text present at all to blame, i.e. some seeds are just rougher for
this mesh regardless of prompt).

**Costume then applied as a separate `edit_character_image` pass, validated
end-to-end including a real bug and its fix:** dressed a clean structural
result in Trevor's actual costume via one Kontext edit — direction, hands,
and proportions all held, and the colors landed correctly (white shirt, red
tie, rust-brown/gold trim), though the model applied the rust-brown/gold to
the *pants* rather than rendering a distinct blazer layer (a different kind
of costume-fidelity gap than the texture-clash, not confused with it). Tobias
caught a real logical error the first read-through missed: the necktie
appeared running down the *back* of the figure — a tie is a front-only
garment and has no reason to be visible in a back view at all, the same
"jacket and tie backward" failure category flagged much earlier in this
project. Fixed with a second, precise `edit_character_image` call ("remove
the necktie completely... a tie is only visible from the front and this is a
back view") — worked exactly as asked, nothing else in the image changed.
Validates the "generate structurally sound, dress and correct it afterward"
philosophy this whole FLUX effort has converged on: base generation only
needs to nail direction and anatomy reliably; costume/texture issues, even
logical ones like a backward tie, are cheap, precise `edit_character_image`
fixes, not something worth chasing at the generation stage.

**Wired in as a real, callable option, not left as scratch scripts** (same
discipline as Stage 5): `vrm_depth.py` (new) drives the Blender subprocess
and the EXR→PNG conversion (calibrated `dist±0.25` window baked in), exposed
as the `generate_pose_depth_map` MCP tool; `blender_scripts/vrm_pose_depth.py`
holds the actual Blender-side script (VRM import via the addon, "standing"
pose only — other mannequin.py presets not yet ported). `flux_workflow.py`
gained a `pose_control_type` parameter ("openpose" default, or "depth"),
threaded through `generate_character_pose`'s `_render_pose` helper, with two
safety behaviors: `pose_preprocess` is force-corrected to `False` whenever
`pose_control_type != "openpose"` (`OpenposePreprocessor` doesn't apply to
depth maps), and the character bible's `description` is automatically
excluded from the auto-built prompt in depth mode (so a caller can't
accidentally reintroduce the costume-geometry conflict by using the normal,
description-including call pattern). `generate_reference_sheet` deliberately
does NOT get this parameter — it has no `pose_ref_path` to pair it with, and
the validated recipe is a manual, curated flow
(`generate_character_pose` + `generate_pose_depth_map` + `edit_character_image`),
not the bulk/automated sheet tool.

**Explicitly not done:** only the "standing" VRM pose is implemented (no
t_pose/hands_behind_back/arms_crossed/walking equivalents yet); the VRM
mesh's own plain-shirt geometry means this path is inherently a two-step
(structure, then costume) workflow, not a one-shot generation the way the
mannequin+text-prompt path can sometimes be; Blender is a genuinely heavy
extra install (a separate ~400MB application, not a pip package) that a user
following README.md's setup would need to do once, on top of everything else.

---

### 8b.11 Real Stage-6 run on Trevor — the full concept→sheet workflow, validated end to end (2026-07-23/24)

Task #64: the first real (not synthetic-test) run of the whole pipeline on an
actual character, from a plain-English description all the way to a finished,
Avery-style reference sheet with action poses. Everything below is the
**replicable recipe for the next character** (Lumiere) — steps, the bugs that
actually bit, and their fixes, in the order they happened.

**Step 1 — concept image.** `generate_character_concept(description=...,
style_prompt="manwha, manwha_style, cartoon", model="flux_manwha")`. Existing
canon art in `Pictures/Illustrations/...` was checked first and explicitly
rejected as a direct reference (wrong outfit, heavy VFX obscuring the figure,
or a two-character composite) — generated fresh from the bible's plain-English
`description` instead. User-approved on the first real attempt this time.

**Step 2 — register as the character bible's sole reference**, via the
`characters.forget_character(delete_images=False)` + fresh `register_character(...)`
reset pattern (documented in §8b.6/§8b.9) — necessary because
`characters.primary_ref_path()` always returns `ref_paths[0]`, so simply
appending a new approved image would NOT make it primary if a wrong image was
already `ref_01`.

**Step 3 — turnaround sheet, then three real bugs, found and fixed in
sequence — this is the part worth reading closely before repeating it:**

1. *Legs looked "stumpy," reference image itself needed fixing first.*
   `edit_character_image` with a vague "roughly half his height" leg-length
   instruction barely moved the needle (measured leg-to-torso ratio barely
   changed). The instruction that actually worked: state the ratio as a
   **strict comparison, not a fraction** — "legs (hip to floor) must be
   LONGER than head+torso combined, ~52-55% of total height" — combined with
   raising Kontext's `guidance` from the default 2.5 to **4.0**. Also needed:
   an explicit "zoom out / shrink the whole figure so feet and shoes stay
   fully in frame" line, or Kontext extends the requested body part off the
   canvas edge instead of rescaling the composition (this exact failure
   happened on the first attempt — legs got longer but both feet vanished
   off-frame).
2. *Same short-legs bug reappeared in the turnaround sheet even after the
   reference was fixed* — regenerating from the corrected reference still
   came back stumpy, 2 tries in a row, tried at both LoRA strength 1.0 and
   0.75. Root cause, on Tobias's own suggestion: **the turnaround-sheet
   canvas was short (1536×768) — Kontext appears to infer body proportions
   partly from absolute canvas height, not just the reference image**, and a
   short/wide canvas biases toward a squat figure regardless of what the
   reference shows. Fix: raise the canvas to **1536×1280** (taller, not just
   the same aspect scaled up) AND add "maintain scale and proportion — do
   not compress/squash/shorten the figure" directly into the turnaround
   prompt itself. Both changes together fixed it outright, at full LoRA
   strength 1.0 — worth noting a first attempt at this fix added the phrase
   but *also* over-anchored the pose itself, producing a duplicate front view
   instead of a genuine 3/4 angle; a plain **reroll with a new seed** (same
   settings) fixed that side-effect for free — don't assume every generation
   needs a fresh fight, sometimes the fix already works and the seed was
   just unlucky.
3. *Glasses vanished or went faint in 2 of 5 panels* (present in front view,
   missing entirely in the profile panel, present-but-illegibly-thin in the
   3/4 panel). Patching this **after the fact on the merged 5-panel sheet**
   was a dead end tried three different ways (whole-sheet edit, per-panel
   crop-edit-and-paste-back, even an isolated head-crop edit) — every attempt
   either left the glasses missing/wrong or introduced a NEW regression in a
   panel that was told explicitly not to change (once even altering panel
   1's glasses thickness despite an explicit "do not change" instruction).
   The fix that actually worked: **bake the requirement into the main
   turnaround prompt from the start** ("bold, clearly visible black
   rectangular glasses in EVERY panel including profile views") and reroll
   the whole sheet fresh, rather than trying to patch a bad result — the
   same "reroll before you patch" lesson as the pose issue above.

**Step 4 — crop_reference, twice, because the first pass under-cropped.**
Panel boundaries in the sheet are NOT exactly `width/5` apart in practice —
a naive even split clips an outstretched hand/arm on one side, or bleeds a
sliver of the NEXT panel's figure on the other, and the two failure modes
require opposite fixes (widen the box vs. narrow it), so check both edges of
each crop independently rather than assuming one universal margin. A second,
separate bug: the expressions row's "square, top-anchored" thumbnail crop
(reused from `compose_concept_sheet`'s original design, which assumed
roughly-square source crops) silently **cut off the chin/mouth** whenever the
source crop was taller than it was wide — because a top-anchored square crop
using the *smaller* dimension as its side length has no way to include both
the hairline and the chin if the vertical span between them exceeds that
side length. Fixed in `compose_full_reference_sheet`'s `row_box()` by adding
a `square=False` mode: scale every image in the row to one shared **height**
(not width), preserving full aspect, and size-solve for that height so the
row still fits the box's total width — full faces, and even cell heights,
with no cropping at all.

**Step 5 — the full-template poster,** built as a new
`compose_full_reference_sheet()` function in `tools/compose_sheet.py`
(alongside the existing, simpler `compose_concept_sheet`) once Tobias shared
a real hand-composed Avery sheet as a reference and asked for the closest
practical match: bordered boxes throughout (not the old plain stacked-text
column), boxes scattered across left/center/right columns, front+back shown
**side by side in one box** rather than separate panels (with the box's
crop widened until both hands were fully in frame on each), a small
decorative crest, an "IN ACTION" row of new poses, one boxed prop
illustration, and a small PIL-drawn (boxes+arrows) diagram explaining the
character's ability mechanism. Deliberately NOT modeled: a stat block
(age/height/likes/dislikes), a personal quote, and a mission-statement box —
none of this project's data has real values for those fields, and guessing
was explicitly rejected once already this session (the placeholder-bio
incident, §8b.6-era) — add real params for these only when a caller actually
has real text to put in them, never invent filler.

**Step 6 — two new action poses**, via `edit_character_image` off the
approved single reference (not a fresh ControlNet generation) — a book-
reading pose and an ice-magic-casting pose, both keeping the same standing
base pose/identity/proportions and only changing the raised arm + adding a
prop/effect. This is a deliberately narrower ask than a full pose change
(validated unreliable elsewhere in this project, §8b.9) and it held up
cleanly both times, on the first try for the book pose; the ice pose needed
one retry with the same explicit leg-ratio + higher-guidance fix from Step 3
(the short-legs regression can recur on ANY fresh edit off the base
reference, not just the turnaround sheet — always re-check proportions on
new poses, don't assume a fix "sticks" to the character).

**Step 7 — background compositing, attempted, then explicitly abandoned for
this use case — decided, not just paused.** Approach tried: **flat cutout +
separately generated background**, pasted together in plain PIL (weighed
against a Kontext "re-render him in the scene" alternative and preferred for
speed and avoiding identity-drift risk on an already-approved image). Two
background scenes generated (`flux_workflow.generate()`, no character in the
prompt) — a library interior and a snow-covered courtyard garden; the
library needed a prompt rewrite (dropping dramatic "gazing into the
light"-type phrasing) plus a negative-prompt addition to stop a person from
appearing in the scene despite an in-prompt "no people" instruction (FLUX's
negative conditioning is weak at `cfg=1.0`, so the positive rewrite mattered
more). Cutout extraction (`extract_alpha()`, scratch-only, never moved into
the repo) used connected-component background detection rather than a plain
color threshold, solving two real sub-bugs along the way: seeding the
flood-fill from the whole image border rather than just the four corners
(a gap between his shoes reached the bottom edge off-center, not at a
corner), and telling a plain white shirt apart from a genuine topological
hole in the pose (gap between crossed legs) by checking whether the pixels
ringing it are dark (a real gap, ringed by black trousers) or bright (a
shirt, ringed by red blazer/skin) — measured on real pixel values, not
guessed.

**Where it broke down, and why it wasn't worth chasing further:** even after
those fixes, action poses with a glowing VFX element (the ice-magic burst,
the glowing book) kept showing a visible pale halo around the whole
silhouette on any non-white background. Root cause, confirmed by sampling
raw pixel values directly: the glow effects themselves render as a genuine
~15px gradient fading from saturated color to pure white in the source art —
not anti-aliasing noise, an actual soft-glow edge with nothing to "cut"
along cleanly. A hard alpha mask always leaves a visible remnant of that
fade. Tried, in order: blurring the alpha edge (made it worse — this art has
no real semi-transparent anti-aliasing to decontaminate, so blurring just
let pure-white pixels bleed through at partial opacity); a large uniform
dilation of the background mask (helped some regions, left others); an
additive/"screen"-style re-composite (`added_light = 255 - original`,
applied over the whole background region, reasoning that white-backed VFX
is invertible into light-plus-backdrop) — this actually made it WORSE,
producing a visible glow outline around the character's *entire* silhouette,
not just near the effect, once tested. At that point the honest call was to
stop: **this had already burned a disproportionate amount of session time on
a decorative detail for a reference sheet**, where backgrounds were never a
functional requirement to begin with (see below).

**The actual right answer, on reflection: reference sheets don't need
backgrounds at all.** Plain white/neutral backgrounds are the real industry
convention for character model sheets — the point of the sheet is reading
the design clearly, not scene-setting; even the real Avery sheet used as a
reference only put a background behind the single hero pose, as a flourish,
not a load-bearing part of the format. **Decision: reference sheets stay on
plain white going forward — do not attempt background compositing for them
again.** The glow-halo problem is real and would need solving properly if it
ever matters for actual comic PANEL production (where a character may need
to be composited into a scene with a glowing effect) — but that's a
different, correctly-scoped problem for whenever panel generation is
actually built (likely solved by generating the effect directly within the
conditioned scene generation, rather than cutting it out of a white-
background render after the fact), not something to re-attempt as an add-on
to a reference sheet. Non-glow poses (front, back, plain standing) were
already clean with the simpler fixes — the halo problem is specific to
glowing VFX content, not a general blocker.

Tobias separately provided a real anime-library reference image, unused now
that illustrated backgrounds are out of scope for reference sheets — kept in
mind for whenever panel-background generation is actually built.

**Follow-up, next session: plain color gradients (not illustrated scenes)
turned out to work fine, including for the glow poses** — the same
`extract_alpha()` cutout composited onto a simple two-color vertical
gradient (`make_gradient()`, new) instead of generated scene art. Confirmed
live: front/back/expression composites were clean immediately (no glow
content, same as the earlier finding). More usefully, pairing a glow-effect
pose with a light-toned gradient (pale icy blue for the ice-magic pose, pale
peach/rose for the glowing-book pose) makes the leftover soft-white fade
essentially invisible, since the gradient itself is already close to white
at the point where the fade would otherwise show — confirming the halo was
never really about "background vs. no background," only about *contrast*
between the glow's inherent white fade and whatever's behind it. A dark
gradient (navy "night") would still show it; a light one doesn't. This is a
genuinely useful rule for later panel work too: a glow/light VFX element
composited via cutout is only safe against a light-toned backdrop, not a
general fix, but a real, usable one for the specific case of reference-sheet
gradients. `compose_full_reference_sheet` was rebuilt with front=dusk
gradient, back=night gradient, expressions=dusk/night/winter, action
poses=sunset/winter (both light-toned, matching their pale-blue glow VFX).

**Net result:** a complete, finished reference sheet for Trevor exists
(`servers/character-panel-mcp/output/rxr/trevor/_concepts/sheet/full_sheet.png`,
gradient backgrounds, final) and the whole pipeline above — concept →
register → turnaround (tall canvas + proportion/glasses baked into the
prompt + reroll-before-patch discipline) → crop (check both edges
independently) → full reference sheet (bordered boxes, front+back combined,
action row, prop, diagram) → action poses (edit off the approved reference,
re-check proportions) → gradient backgrounds (light-toned for any glow-VFX
pose) — is the complete, validated, repeatable recipe for Lumiere.
Illustrated/generated-scene backgrounds remain OUT of scope for reference
sheets; plain color gradients are back IN scope, proven to work.

---

## 8c. Background server FLUX port — 📋 SCOPED, NOT STARTED (task #52)

`webcomic-background-mcp` is still entirely SD1.5 — three checkpoints
(`solstice_manhwa_v10`, `Counterfeit_V3`, `DreamShaper_8`), the scribble
ControlNet, `ManhwaUltimate` and `NijiV5Style`. It has no FLUX code and no FLUX
mention anywhere in its README or CHANGELOG. This section exists so the port
starts from what's already known rather than from the task title.

**Why it hasn't been done:** the server works, ships, and isn't exhibiting the
failures that drove the character server to FLUX (§8b.9). Same reasoning as the
SDXL prototype's scope note — don't migrate a working server to fix a problem it
doesn't have. The forcing function would be *quality*, not breakage.

**What's already been learned, from §8b.9 Step 7.** Background plates have
already been generated with `flux_workflow.generate()` (no character in the
prompt) during the character server's work — a library interior and a
snow-covered courtyard garden. So feasibility is not the open question. Two
findings transfer directly:

- **FLUX's negative conditioning is weak at `cfg=1.0`.** A prompt saying "no
  people" still put a person in the library scene; the fix was rewriting the
  POSITIVE prompt (dropping dramatic "gazing into the light"-type phrasing that
  implies a subject), with the negative addition mattering less. Any port must
  re-tune prompts positively rather than porting SD1.5's negative prompts across.
- **Plate quality was usable.** The abandonment in §8b.9 Step 7 was of *character
  compositing into generated scenes* for that specific panel, not of FLUX
  background generation as such.

**What the port would actually cost.** FLUX's ComfyUI graph shares almost no node
types with SD1.5 (GGUF unet loading, dual CLIP encoders, flux-specific sampling,
`cfg=1.0`), which is why the character server put it in a separate
`flux_workflow.py` rather than branching `build_graph()`. Expect the same shape
here: an additive `flux_workflow.py` alongside the existing SD1.5 path, with
`model="flux_manwha"` as a new option, not a replacement.

**Open questions to settle before starting:**

1. Does World Builder's location consistency survive the model change? Its
   consistency mechanism is prompt/recipe-based, not reference-conditioned, so it
   may transfer cleanly — unverified.
2. Does the scribble ControlNet path have a FLUX equivalent worth using? The
   character server's `flux_controlnet_union_*` covers canny/lineart; scribble is
   not a listed union type (see `CONTROL_TYPES` in `flux_workflow.py`).
3. Is ~8 min/plate acceptable versus SD1.5's ~20-40 s? For backgrounds — generated
   once per location and reused — probably yes, but that's a real change in feel.

**Downstream consequence worth noting:** if this port lands and SD1.5 is retired
from the background server, roughly 11 GB of SD1.5 checkpoints/LoRAs/ControlNets
become genuinely dead weight and can be deleted. Until then they cannot — the
background server is the only remaining consumer.

---

## 9. Build phases (STRICT order — do not start the interface early)

- **Phase 0 — prerequisites (separate projects, separate chats):**
  1. ✅ **Novel Translation MCP** (§8a) — **shipped 2026-07-17**, live in
     `webcomic-toolkit/servers/novel-translation-mcp/`, portfolio page live.
  2. Speech-bubble + translation MCP server, comic path (Tier 1: creator-with-source-files
     only; flattened-image OCR localization is explicitly out of scope for v1). Shares the
     translation *design principles* above with §8a; whether it shares a code *library* or
     stays fully separate is a decision for whoever builds it, now that a real second
     translation server exists to compare against.
  3. Publication MCP server (§7) — covers EPUB assembly for BOTH the novel path (reflow mode)
     and the comic path (fixed-layout mode); this is where §8a's deferred v2 work lands.
  4. Orchestration skill (§8).
  - **(unordered) Character & Panel server (§8b)** — all three tiers plus Concept
    Genesis (§8b.6) ✅ **shipped**, live in `webcomic-toolkit/servers/character-panel-mcp/`.
    Was not a Studio prerequisite and remains not one now that it's built — this
    was pulled forward out of the unordered slot rather than waiting on the
    speech-bubble/publication servers, which is exactly what this bullet always
    said was fine to do. It gets its own Studio panel (character bible browser +
    panel gallery) on the same generic-panel-first rule as everything else (§2.4),
    once the Studio itself is underway.
  *The interface without these is a shell of stub panels — not worth building yet. Still
  2 of 3 prerequisite servers away, plus the orchestration skill.*
- **Phase 1 — Studio MVP:** server + projects browser + Backgrounds studio + World bible + command bar (Claude Code adapter). This alone must beat "just use the terminal" for daily background work, or stop and reassess.
- **Phase 2:** Lettering panel + Video studio.
- **Phase 3:** Publish studio + polish (job history, error surfaces, onboarding checks: ComfyUI reachable? harness authed? servers installed?).
- **Phase 4:** Package as Tauri app; `npx` one-command launch; README + website page.

---

## 10. Risks & honest caveats (carry these into build decisions)

1. **Harness CLI drift** — non-interactive flags/stream formats change between versions. Mitigate: adapter isolates ALL harness-specific code; version-check on startup; fail with a clear message, never a hang.
2. **Auth/ToS** — driving the user's own installed, logged-in CLI on their machine for their own work is the intended use of these tools' non-interactive modes. Do NOT proxy/authenticate for third parties, do not ship shared credentials, and re-verify each harness's current ToS at build time (this doc is not legal review).
3. **GPU contention** — ComfyUI can't run two generations at once; the job queue's single-GPU-job rule is mandatory, and agent jobs may ALSO trigger GPU work (the queue must treat an agent job as potentially-GPU).
4. **Scope creep** — this is a product, and Tobias's time is the scarcest resource. The chapter-one rule applies: the comic ships first; the Studio is built in the gaps, panel by panel, each independently useful.
5. **Security** — localhost only; sanitized file routes; no secrets in the repo; `.gitignore` from day one (node_modules incident of June 2026 must never recur).
6. **Windows-first reality** — Tobias develops on Windows; paths, spawn behavior, and ComfyUI locations must be tested there first, POSIX second.

---

## 11. Instructions to the builder (Sonnet 5, read carefully)

1. **Do not build the interface first.** Confirm Phase 0 status with Tobias; if the speech-bubble or publication server is unbuilt, offer to build THOSE first (each in its own repo).
2. **Confirm before adding anything not in this plan** — no extra backends, cloud services, databases, or third-party accounts without explicit sign-off. (Standing rule: Tobias prefers Vercel over Cloudflare and Anthropic over OpenAI if a hosted/AI service is ever genuinely needed — but this plan needs neither.)
3. **Never commit `node_modules` or build artifacts.** Write the `.gitignore` before the first `npm install`.
4. **Repo strategy is decided — see §2.5.** Do NOT create separate repos for the new pieces
   and do NOT touch the two existing repos (`webcomic-background-mcp`, `anime-production-skill`
   stay exactly as they are). Instead: one new monorepo (name TBD, §12) containing
   `servers/novel-translation-mcp/` (build first), and later `servers/comic-translation-mcp/`,
   `servers/publication-mcp/`, `packages/translation-core/`, `skills/orchestration/`. Each
   server folder is independently installable/runnable with its own manifest + README. Use
   scoped git tags (`<server>@vX.Y.Z`) once the repo holds more than one server. Do not put
   any of this inside `tobiasfong-site`.
5. **Verify current CLI invocation shapes** (`claude --help`) before writing the adapter; do not trust the exact flags in §2.2.
6. At each phase boundary, stop and demo to Tobias before continuing.
7. Keep every server independently installable and documented with the same README quality as `webcomic-background-mcp` (GPU/CPU requirements table, step-by-step, troubleshooting).

---

## 12. Open questions for Tobias (decide before Phase 1)

1. Name: "Webcomic Studio"? Something with his branding?
2. **Name for the new monorepo** (§2.5) holding the translation/publication servers + orchestration skill (e.g. `webcomic-toolkit`, `tobiasfong-mcp-servers`).
3. Speech-bubble server name & whether novel translation ships inside it at v1 (current plan: yes, shared translation core).
4. Which fonts he owns/licenses for lettering (affects defaults in `project.json`).
5. Monorepo public from day one, or private until the first server (Novel Translation MVP) is solid?
6. Does the Studio page join the portfolio site at Phase 1 or Phase 4? Does the new monorepo get its own portfolio page once the Novel Translation MVP ships, same as the other tools?
7. Name for the Character & Panel server (§8b): `character-panel-mcp`? `webcomic-character-mcp`? And when to build it — is a writer friend committed enough to be its first real user (the best forcing function for scope)?
