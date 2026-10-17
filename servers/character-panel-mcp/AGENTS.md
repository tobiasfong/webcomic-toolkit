# character-panel-mcp — agent notes

Generates characters and panels from a Character Bible with FLUX 3 Klein,
turns single views into turnaround sheets, and mattes figures onto
transparency for compositing.

- **FLUX 3 Klein only since v2.0.0 (2026-10-17)**, in `klein_workflow.py`,
  on its OWN ComfyUI (v0.41, port 8189, `C:/AI/ComfyUI_flux3`) that starts on
  first use. FLUX.1 is gone: no `model=`, `lora=`, `negative=` or
  `pose_ref_path=` parameters remain. Matting runs on the main ComfyUI (port
  8188), in `comfy.py`. What Klein changes, measured, is in the root `AGENTS.md`.
- `generate_scene` puts several characters in one render (a CG with its room
  and light); `generate_expression` renders an expression as a WHOLE new body
  from scratch, on a different seed from its base. Never paste a face.
- **The repo's root `AGENTS.md` governs everything here**, and most of its
  rules were paid for in this server: character appearance is DATA in the
  bible and is never typed into a prompt from memory; validate with
  `python tools/check_bible.py --all` before generating; the token rule says
  do not read renders into context by default, the author reviews them.
- `tools/` holds the reusable steps: cutout and placement, hand repair and
  figure completion, sheet composition, reference cropping. Project output
  lives under `output/<project>/`; `FINAL_*` files and approved sheets are
  never deleted or overwritten, intermediate renders are disposable.
- **Matting uses permissively licensed models only** — BiRefNet-general by
  default (`comfy.MATTE_MODEL`), BEN2 where it keeps a detached part the other
  drops. RMBG-2.0 is non-commercial and must never be the default again: it
  was, in `comfy.matte()`, until 2026-10-17, after the replacement was believed
  done. A sprite is re-cut only from the exact render it came from.
- After editing anything under this folder: `python -m pyflakes` over what
  you edited, and read its output after editing, not before. Restart the MCP
  server for an edit to take effect.
