# character-panel-mcp — agent notes

Generates characters and panels from a Character Bible with local FLUX
models through ComfyUI, turns single views into turnaround sheets, and mattes
figures onto transparency for compositing.

- **The repo's root `AGENTS.md` governs everything here**, and most of its
  rules were paid for in this server: character appearance is DATA in the
  bible and is never typed into a prompt from memory; validate with
  `python tools/check_bible.py --all` before generating; the prompting rules
  that came from failures each cost a re-render; the token rule says do not
  read renders into context by default, the author reviews them.
- `tools/` holds the reusable steps: cutout and placement, hand repair and
  figure completion, sheet composition, reference cropping. Project output
  lives under `output/<project>/`; `FINAL_*` files and approved sheets are
  never deleted or overwritten, intermediate renders are disposable.
- Matting uses permissively licensed models only (BiRefNet-general by
  default, BEN2 where it keeps a detached part the other drops); the choice
  is a license decision and is recorded in `flux_workflow.py`. A sprite is
  re-cut only from the exact render it came from.
- After editing anything under this folder: `python -m pyflakes` over what
  you edited, and read its output after editing, not before.
