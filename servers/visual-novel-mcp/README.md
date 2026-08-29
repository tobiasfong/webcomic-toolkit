# visual-novel-mcp

Branching visual-novel production server for Ren'Py projects built from
webcomic-toolkit assets: a scene database with cross-session continuity, a
branch-graph validator, and the one-body-plus-face-patch sprite manifest.

## Why a server (and why this shape)

A kinetic VN would not have needed one — matting, patch tooling, and script
writing are plain scripts and text files. A **branching** VN adds exactly the
things MCP is for: a scene database consulted across many sessions, graph
validation that must run against the whole story, and continuity state that
no single chat can hold. Same reasoning as novel-translation-mcp, which this
server's structure copies (projects.json registry, per-project state file,
WORKFLOW.md served as instructions, terse tool docstrings).

## The core design rule

**The .rpy scripts are the single source of truth for the branch graph.**

`rpy_parse.py` scans the scripts for labels, jumps/calls, menus, flag writes
(`$ x = …`, `default`), flag reads (conditions, choice conditions, `[x]`
interpolations), `show`/`scene` displayables, and audio refs. `graph.py`
builds the graph fresh on every check — nothing graph-shaped is ever stored,
so nothing graph-shaped can drift.

The state file (`vn_state.json`) holds only what a script cannot express:

- scene **synopses** and **status** (planned → drafted → reviewed → approved)
- **flag meanings** (`define_flag`) — check_story flags undocumented flags
- append-only **continuity notes** (`record_note`)
- an `approved_digest` per approved scene, so silent edits to approved
  scenes are detected

Approval is the author's alone. `save_scene` refuses to demote an approved
scene, and nothing here auto-approves.

## Conventions

- One scene = one file (`game/scenes/<scene_id>.rpy`) = one entry label
  named after the scene id. `plan_scene` before writing; `save_scene` to
  commit (it parses immediately and reports problems while context is warm).
- The scanner is deliberately not a full Ren'Py parser — Ren'Py's own
  `lint` stays the syntax authority once the SDK is installed. The scanner's
  simplifications are conservative: dynamic jumps are excluded from checks
  rather than guessed at.
- Fallthrough is real: a label whose body does not end in `return`/`jump`
  falls through to the next label in the file, and the graph models that.

## Sprites: one body + face patches

Decided 2026-08-16: expressions are hand-drawn deltas (eyes/brows/mouth)
over a single matted body render — never separate renders, which give
non-identical bodies and mid-conversation jitter. The manifest
(`sprites.json`) records body, patches, pixel offsets, `target_height`
(fraction of the 1080p screen, for deterministic scale normalization), and
`mirror_ok` (false for asymmetric costume details).

`emit_sprites` generates `sprites_generated.rpy`: one `layeredimage` per
character, zoom computed from `target_height`, each patch padded onto a
transparent body-sized canvas so every layer is the same size and offsets
are baked into pixels — the jitter-proof representation.
`preview_expression` composites body + patch over magenta for the alignment
eyeball check.

## Privacy

The repo is public. `projects.json` is gitignored here; game trees and
state dirs must live under gitignored paths (`vn/` at the repo root is
ignored). Scene scripts are full of character and world names — never let
them reach git.

## Setup

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

`mcp<2` is load-bearing (mcp 2.0 removed `mcp.server.fastmcp`). Register in
`~/.claude.json` `mcpServers` with this venv's python, like the other
servers.

### The engine

The server itself never runs Ren'Py — it parses scripts, so the game tree is
plain files. You need the engine to PLAY the game or build it for a browser,
and the harness installs that itself:

```
python tools/install_renpy.py
```

It fetches the pinned SDK and the separate web-build component, verifies both
against recorded SHA-256 hashes, and records where it put them. Nothing else
should ever contain an SDK path — resolve it through `tools/renpy_sdk.py`,
which reads an explicit argument, then `RENPY_SDK`, then that record.

Then build and play it in a browser:

```
python tools/build_web.py <project-dir> --serve --open
```

⚠ The version is pinned deliberately. The engine traps in WORKFLOW.md were
measured against 8.5.3 and `renpy lint` catches none of them, so `--version`
moves ground that this repository has notes about.
