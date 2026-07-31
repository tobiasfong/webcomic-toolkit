# webcomic-toolkit — working rules

Read this before generating or editing any character art. These rules exist
because each one was broken in practice and cost real time.

## The one rule

**Character appearance is data, not something you write.** It lives in
`servers/character-panel-mcp/characters/<project>/characters.json` and in the
approved sheets under `output/<project>/<character>/_concepts/`. Never type a
character's hair, eyes, costume or footwear into a prompt from memory or from
looking at a panel.

What happened when this was broken: a hand-written prompt gave a character the
wrong hair colour and dropped his eye colour entirely. His bible had carried
both correctly the whole time. The wrong values propagated into a finished panel
and were only caught sessions later.

Resolve descriptions in code:

```python
import characters as ch
desc = ch.get_character("<character_id>", project="<project>")["description"]
```

A crossover scene puts its characters in **different projects**, so no single
lookup covers them all. That is exactly when retyping from memory feels
reasonable. Don't.

## Before generating, validate

```bash
python servers/character-panel-mcp/tools/check_bible.py --all
```

Non-zero exit means the bible cannot be trusted yet. Fix it first. This checks
that every registered ref exists, that no unlisted image is lurking in a
character folder, and that the primary reference traces back to an approved
sheet.

## Registering references

The primary ref (`refs[0]`) is what every generation conditions on. It must be a
crop from that character's approved `*_sheet_FINAL.png`, and its origin must be
recorded in `ref_sources`. Never register a one-off render or a story panel as
the primary.

What happened when this was broken: a character's primary ref was a stray render
with the hair styled differently and the frame cropped above the ankles, so her
footwear did not appear in it at all. Her approved sheet had a full turnaround
showing it front and back. Every "why is this costume detail wrong" question
traced to that one bad path.

## Finished panels are canon

`FINAL_*.png` in `output/<project>/_scene1/` are approved and locked. Consult
them for how something has already been drawn, and check `canon_panels` in each
bible entry for which panel establishes which detail. **Never delete or
overwrite a `FINAL_*` file or an approved sheet.** Intermediate `edit_*.png`
renders under `output/` are disposable.

## Identity conditioning — know which path you are on

- `flux_workflow.generate()` — **no identity input.** Only `pose_ref_path` for
  ControlNet. Identity comes from prompt text alone, so it *will* drift.
- `flux_workflow.edit_image()` — real identity conditioning via `ReferenceLatent`
  from **one** source image. This is what the locked panels used.
- `workflow.generate()` (SD1.5) — has `ref_path`/`identity_mode`, but SD1.5 has
  the anatomy ceiling.

Every mechanism binds **one reference to one generation**. There is no way to
lock two different characters' identities in a single image. Attempting it gives
attribute bleed — in a live test, her glasses landed on him and his long hair on
her. For multi-character panels: generate each figure solo from its own sheet,
then composite with `tools/cutout.py` + `tools/place_cutout.py`.

## Prompting rules that came from failures

- **Kontext restyles, it does not restructure.** Ask yourself: does this edit
  change the SILHOUETTE against skin or background? If yes, Kontext will fail
  however you word it — decide the shape deterministically instead.
- **State limb totals once.** "Exactly two legs and two boots altogether."
  Enumerating limbs individually reads as a request for more of them; a
  per-limb pose description produced a three-legged figure.
- **Two surfaces at the same depth fuse.** Stage limbs against background, never
  across the character's own torso.
- Keep light direction identical across figures meant to be composited
  ("lit from the upper left") — mismatched lighting is the one thing manual
  compositing cannot fix cheaply.

## Practical

- ComfyUI runs prompts **serially**. Submit one job at a time; stacked jobs burn
  their timeouts waiting in queue.
- Use the repo venv: `servers/character-panel-mcp/.venv/Scripts/python.exe`.
- ~15 min per ControlNet generation, ~8 min per Kontext edit on a 6 GB card.
