# visual-novel-mcp — agent notes

Branching visual-novel production for Ren'Py projects: a scene database with
cross-session continuity, a branch-graph validator, the one-body-plus-face-patch
sprite manifest, emitters that generate every scene from a master document,
the verification sequence, and the web build.

- **`WORKFLOW.md` beside this file is the manual.** The one rule (the .rpy
  scripts are the single source of truth for the branch graph), the engine
  traps, generating scenes, the tool table, verifying, web builds, and the
  Phones chapter. The repo's root `AGENTS.md` carries the verification
  sequence and the emitter rules every session must run; read both before
  touching a project.
- **Run the whole sequence as one command** on every change:
  `python tools/verify_all.py <project-dir> "<master.docx>"`. It stops at the
  first failing step. A green run is the only green worth reporting; the
  steps run by hand get skipped, reordered or filtered wrong.
- `tools/` holds the emit, diff, lint, audit and build tools; `snippets/`
  holds drop-in Ren'Py files (touch input with two-tap commands, the
  three-state text size with its scaling rules). Every scene file is
  generated: never hand-edit one, change its emitter.
- **Privacy.** Game content -- character and project names, story, prose --
  never enters this public tree. The game lives under a gitignored path with
  its own private notes; describe mechanisms here, never the work they were
  found on.
- After editing anything under this folder: `python -m pyflakes` over what
  you edited and read its output, and restart the running server before
  calling its tools, since the process keeps the old module.
