# webcomic-background-mcp — agent notes

Generates background plates for panels and scenes in any referenced
aesthetic through a local ComfyUI + FLUX pipeline, keeps a world bible of
registered locations, and builds city scenes from districts.

- **The repo's root `AGENTS.md` governs everything here.** Its plate rules
  were each learned on this server: a plate that receives figures must match
  their projection, and its architecture must be cropped by the frame or the
  figure reads as a giant; a ControlNet guide says WHERE and never WHAT, so it
  is drawn irregular and held loosely; plate size is 1536x864, exactly 16:9;
  an overhead floor comes back with a spotlight and is tiled from a clean
  patch rather than flattened.
- The world bible under `world/<project>/` holds the canonical plate for
  each location. Passing a location to a generation reproduces that plate's
  composition, so a figure-scale shot of a known place is generated fresh
  from the location's vocabulary and graded afterwards.
- Project output lives under `output/<project>/`; keep the source render of
  anything tiled or cropped even when it looks like a reject, since it is
  the only thing that can rebuild the result at another scale.
- After editing anything under this folder: `python -m pyflakes` over what
  you edited, and read its output after editing, not before.
