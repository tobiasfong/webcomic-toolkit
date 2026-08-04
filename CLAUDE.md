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

## The multi-character panel workflow

Run this in order for any panel with two or more characters. Every step exists
because skipping it cost a re-render.

1. **Validate the bible**, resolve descriptions in code (see above).
2. **Try both characters in ONE generation first.** `edit_image()` conditioned
   on an approved panel that already contains both of them carries both
   identities with no attribute bleed. One job settles it; solos cost a manual
   composite every time, so this is the cheaper thing to rule out first.
   - It **will** change the camera ANGLE on the same beat.
   - It will **not** change the camera DISTANCE, and will **not** change where
     the figures are relative to each other. If either must change, stop and go
     to step 3 rather than spending more seeds.
   - Where bodies touch, expect them to fuse. That is the signal to go solo.
3. **Generate each figure solo** from its own sheet with `edit_image()`.
   - Flat white backdrop, no ground line, no cast shadow — a generated shadow
     fights the one added at placement.
   - Same light direction in every figure ("lit from the upper left").
   - Match the canvas to the figure's axis: portrait for a standing figure,
     landscape for a lying one.
   - Name the terminal feature to avoid cropping: "clear empty space below his
     black shoes", not "full body in frame".
   - Specify EXPRESSION here. It cannot be reliably edited in afterwards.
4. **Key and trim** with `tools/cutout.py`, then crop to the alpha bbox.
   Tolerance is per-image and must be MEASURED, not guessed — a pale costume
   sits ~20 RGB from a white backdrop while a cast shadow sits ~100.
5. **The author composites the figures by hand.** Overlap, interleaving and
   contact are trivial manually and unsolved automatically.
6. **Build the background plate** and match its projection to the figures
   (see below). Measure its saturation against the locked panels; the
   correction factor is per-plate and never transfers.
7. **Generate shadows as a drop-in layer** — build them around the composite's
   own alpha on transparency, pad the canvas, and report the offset. Never try
   to re-derive the author's placement inside a finished file; doing so once
   pasted the figures twice.
8. **The author paints the final shadows**, then locks the panel as
   `FINAL_p<NN>_<slug>.png`.

### Projection: the background must match the figures

The single most expensive mistake in this pipeline. If the figures are drawn
flat and the plate is a corridor converging on a vanishing point, the panel
reads as pasted no matter how well the colour and placement are matched — the
error is geometric, not tonal. A supine figure on a converging ground even reads
as lying on his *side*.

- Figures drawn flat need a ground plane PARALLEL to the picture plane: camera
  perpendicular, floor as a horizontal band or a full top-down surface.
- The ground's DIRECTION matters too, not just its projection. Measure the
  figures' principal axis (PCA over the composite's alpha) and rotate the plate
  to match. A top-down plate has no correct "up", so rotating it is free.
- Rotating needs headroom: upscale ~2.3x first, or the crop reaches past the
  rotated corners and leaves black wedges.

### Shadows depend on the camera

- **Eye-level** — a soft sheared pool running away from the light, plus a tight
  contact core. `lift` (the fraction of the shadow above the ground line) must
  be SMALL (~0.15) for standing figures; the larger values that suit a lying
  figure float the pool up to shin height and read as fog. Build the core from
  the FEET band only, not the whole silhouette.
- **Overhead** — no shear at all. The shadow sits almost under the body with a
  small offset toward the light's opposite corner. A sheared pool would read as
  a side view.
- Either way the offset must EXCEED any erosion of the silhouette, or the
  shadow never emerges from behind the figure.
- A shadow is only visible where the ground is PALE. Position figures for the
  shadow, not just the composition.

## Prompting rules that came from failures

- **Kontext restyles, it does not restructure.** Ask yourself: does this edit
  change the SILHOUETTE against skin or background? If yes, Kontext will fail
  however you word it — decide the shape deterministically instead. The sharper
  test is whether the model must invent what lies UNDERNEATH: raising a
  character's arms into open air worked, while spreading her knees beneath a
  skirt did not.
- **`edit_image()` inherits its FRAMING from the reference**, and no wording
  overrides it. Asking for a close-up off a full-length reference returns
  full-length. The fix is to crop the reference to the framing you want,
  enlarge it, and condition on that.
- **The reference carries POSE bias too.** Check what it actually shows before
  blaming the prompt — a "back turnaround" whose head is turned to
  three-quarter will keep producing a visible face.
- **Expression must be set at generation time.** It is not a safe edit: two
  masked passes at 780px of face failed to turn a grin into alarm. Avoid
  "mouth open, eyes wide" — that describes laughing as well as shock. Say
  what the features DO ("corners pulled down, brows raised and pinched") and
  negate the wrong read explicitly.
- **Facing direction and body angle never respond to instruction.** Every solo
  came out facing the sheet's direction, and a requested 35° turn produced a
  square-on figure twice. Mirror at composite time instead — and remember a
  mirror flips asymmetric costume detail, which must be repainted.
- A "failed" render often contains USABLE ART. An object rendered correctly but
  detached from the body can be harvested and composited; a duplicated limb on
  an otherwise good frame is a cleanup, not a dead end.
- **State limb totals once.** "Exactly two legs and two boots altogether."
  Enumerating limbs individually reads as a request for more of them; a
  per-limb pose description produced a three-legged figure.
- **Two surfaces at the same depth fuse.** Stage limbs against background, never
  across the character's own torso.
- Keep light direction identical across figures meant to be composited
  ("lit from the upper left") — mismatched lighting is the one thing manual
  compositing cannot fix cheaply.

## Video: LTX-2.3 image-to-video (local, 6 GB card)

Verified working 2026-08-04 — 25 frames @ 832x576 in **161 s** on the RTX 3060
Laptop (6.4 GB VRAM), distilled-1.1, 8 steps. No OOM, no special flags. Driver:
`anime-production/tools/ltx_run.py`.

- **A GGUF text encoder will NOT load through the core node.**
  `LTXAVTextEncoderLoader` reads `models/checkpoints/`, and ComfyUI's
  `supported_pt_extensions` has no `.gguf` — so it can never list a GGUF Gemma,
  no matter where you move the file. That node is for *safetensors* encoders.
  Use city96's loader instead, with Gemma in `models/text_encoders/`:
  `DualCLIPLoaderGGUF(clip_name1=gemma-*.gguf,
  clip_name2=<variant>_embeddings_connectors.safetensors, type="ltxv")`.
- **Connector and VAE must match the checkpoint's variant** (distilled↔distilled,
  dev↔dev) *and* generation. Mixing them does not error — it silently produces
  garbage, which is a miserable thing to debug.
- **ComfyUI caches folder listings at startup.** After adding models, restart it;
  re-querying `/object_info` will keep returning the stale list.
- Hard constraints: width and height divisible by **32**; frame count must be
  **8n+1** (25, 49, 73, 97).
- **Never render below 540p** for this art. Dropping resolution is the obvious
  way to fit a small card, but fine linework and cel shading turn to mush below
  it — before any upscale can recover them. A VRAM test at 360p proves nothing.
- **Motion and fidelity trade off directly.** This is the constraint to design
  around, measured across three runs on the same hardware:

  | Prompt | Motion produced | Face fidelity |
  |---|---|---|
  | generic "subtle motion" | mild | mild drift |
  | ambient, portrait framing | minimal | **excellent** — glasses, linework intact |
  | directed "she kicks him" | **real, dynamic** | **badly degraded** — glasses dissolved, features mush |

  Prompting *does* direct the action — the kick happened. It costs identity to
  get it. So ask for the least motion that reads, and let the impact FX
  (speedlines, flash, shake) carry the rest. That is also what anime does: it
  sells a hit with the hit, not with the travel.
- **Style survives regardless** — cel shading, linework, colour and background
  hold in every run; no drift toward photoreal. Verified on generated panels
  *and* hand-drawn illustrations. It is specifically **faces** that degrade.
- Favour mid/long shots for animation; keep close-ups static or nearly so. Keep
  clips short — drift compounds with generated time.
- **Use `distilled` for motion. `dev` barely moves.** Measured as mean absolute
  pixel difference between first and last frame (0-255 scale), same seed and
  prompt:

  | run | motion | peak |
  |---|---|---|
  | distilled, generic prompt | 13.8 | 3.3 |
  | distilled, ambient (portrait) | 6.9 | 2.9 |
  | **distilled, directed "she kicks him"** | **30.6** | **17.3** |
  | dev@25 steps, same prompt, cfg 3.0 | 2.6 | 1.9 |
  | dev@25 steps, same prompt, cfg 1.0 | 1.5 | 1.2 |
  | dev@25 steps, "ice grows rapidly" | 1.5 | 1.2 |

  This **inverts** the common "dev = production quality, distilled = fast draft"
  advice. That may hold for still-image fidelity; for *motion* dev is close to
  static (~1.5 is barely above noise) and no prompt moves it.

  **Everything below was tested and FAILED. Do not retry them:**

  | attempted fix | result |
  |---|---|
  | steps 8 vs 25 | no motion (2.6) |
  | cfg 1.0 vs 3.0 | no motion; lower cfg was *worse* (1.5) |
  | `max_shift`/`base_shift` 4.0/1.5, 7.0/2.5 | no motion (1.5, 1.9) |
  | swap `LTXVScheduler` → `BasicScheduler` | no motion (2.66) |
  | low resolution (640x384) | image **destroyed** — characters dissolve |
  | hybrid split-sigma: distilled early → dev late | **broken** — frame 0 never denoises, quality worse than distilled alone |

  The hybrid is worth explaining since it sounds plausible: the idea is that
  early high-noise steps decide motion and late steps decide detail, so
  distilled commits the motion and dev cleans up. It does not work here — most
  likely the two variants' latents are not interchangeable mid-sample, having
  separate VAEs and connectors. (A version of this circulating online puts dev
  *first*; that ordering is worse still, since it locks in stillness during the
  steps where motion is decided.)

  **Conclusion: use `distilled`. The motion/fidelity trade-off survived six
  attempts to break it and looks like a property of the model, not a setting.**

  ⚠ **Judge output by eye, not by the motion metric.** Mean pixel difference
  measures *change*, so a frame dissolving into mush scores higher than a clean
  action: the destroyed 640x384 run scored 40.9 and the broken hybrid 105.2,
  against 30.6 for the good distilled take. Always look at the frames.
- **Directed prompting works, but only on distilled**: generic 13.8 -> directed
  30.6 (2.2x). Prompt wording is a real lever there and inert on dev.
- **cfg is not the motion knob.** Lowering it 3.0 -> 1.0 *reduced* motion
  (2.6 -> 1.5), the opposite of the obvious guess.
- ComfyUI does not auto-start for this work:
  `Start-Process C:\AI\ComfyUI_windows_portable
un_nvidia_gpu.bat`.

## Practical

- ComfyUI runs prompts **serially**. Submit one job at a time; stacked jobs burn
  their timeouts waiting in queue.
- Use the repo venv: `servers/character-panel-mcp/.venv/Scripts/python.exe`.
- ~15 min per ControlNet generation, ~8 min per Kontext edit on a 6 GB card.
