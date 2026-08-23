# webcomic-toolkit — working rules

Read this before generating or editing any character art. These rules exist
because each one was broken in practice and cost real time.

## Model quantisation — settled 2026-08-10

**Everything runs Q6_K. Both FLUX models are on disk and both are configured.**

| | model | why |
|---|---|---|
| Kontext | `flux1-kontext-dev-Q6_K.gguf` | decisive quality win, see below |
| generation | `flux1-dev-Q6_K.gguf` | no quality change, but faster and lighter |

⚠ **WHERE BIT DEPTH ACTUALLY MATTERS, measured on both:**

| task | Q3_K_S -> Q6_K |
|---|---|
| Kontext REPAIR of a damaged hand | 0 of 6 frames usable -> **3 of 3 usable** |
| Panel GENERATION, same seed and prompt | **identical — no visible difference, no character drift** |

The rule that explains both: **quantisation error surfaces when the task is
HARD.** Kontext repair reconstructs destroyed structure from corrupted pixels,
right at the edge of the model's capability, and 3.3 bits per weight is not
enough — hands came back as fused blobs. Generation from a good prompt with a
LoRA and ControlNet is a much easier ask, the model has headroom, and the extra
precision buys nothing you can see.

So: **do not expect Q6 to improve generated panels. It will not.** Existing
Q3-era panels and character sheets are NOT compromised and do not need
regenerating. If sheets get regenerated for a new series, that is a story
decision, not a technical migration.

The Q3_K_S files have been DELETED (2026-08-10) — 10.5 GB reclaimed, and there
is no measured case where they are preferable. Reverting means re-downloading:
`flux1-dev-Q3_K_S.gguf` from city96/FLUX.1-dev-gguf, `flux1-kontext-dev-Q3_K_S`
from QuantStack/FLUX.1-Kontext-dev-GGUF. Do not "fall back to Q3" casually;
nothing here suggests you would want to.

Q6 was adopted for generation anyway because it costs nothing: **225 s against
Q3's 339 s, and 5482 MiB peak VRAM against 5892** — faster and lighter, with
LoRA and ControlNet both active at 832x1216. Low K-quants are more expensive to
unpack per operation, which is the likely reason the bigger file is quicker.

⚠ **VRAM IS NOT THE CONSTRAINT ON THIS CARD, and assuming it is has cost real
work three times now.** ComfyUI offloads to system RAM and streams weights: this
6 GB card runs a **14.2 GB** LTX model daily. Online guidance that Q6 "needs
12 GB VRAM" describes holding weights resident, which is not what happens here.
The three occasions, for pattern recognition:

- LTX defaulted to `832x576` "for the 6 GB card" — cost 65 hand-redrawn frames
  on one scene. A later ceiling sweep found no out-of-memory point at ANY
  resolution tested.
- Kontext at `Q3_K_S` — produced nothing usable across 18 repair attempts.
- Generation at `Q3_K_S` — harmless as it turned out, but chosen for the same
  bad reason.

**Before concluding a model "can't do" something, check its bit depth and check
whether the limit you are respecting was ever measured.**

### LTX-2.3 stays at Q4_K_M — a decision, not an oversight

Deliberately deferred 2026-08-10. Do not "upgrade" it without working through
the order below first.

Sizes, for reference: in use `Q4_K_M` 14.2 GB (~4.85 bits) · `Q5_K_M` 15.9 GB ·
`Q6_K` 17.8 GB · `Q8_0` 22.8 GB. Add the Gemma-3-12B encoder (6.0 GB) that
loads alongside, and Q6 means **~23.8 GB of weights against 31.9 GB of system
RAM** — it should run, since ComfyUI streams from RAM, but expect paging and
slower takes. That is a different risk profile from the FLUX upgrade, which was
~15 GB total and comfortable.

Three reasons to leave it alone unless something forces the issue:

1. **The evidence points away from a benefit.** Bit depth mattered for Kontext
   REPAIR (reconstruction from corrupted pixels) and did NOTHING for FLUX
   generation. LTX animating a clean 1216x832 source is generation-shaped — it
   has good input and headroom.
2. **LTX's remaining failures are drift-shaped, not precision-shaped.** Tail
   degradation and the occasional bad hand at length 17. Drift is not something
   more bits fix.
3. **Cheaper techniques are untried.** `LTXVAddGuide` pins a final frame and
   attacks drift directly — that comes first.

ORDER OF ESCALATION, agreed with the author: run the series at Q4_K_M · if
quality is a problem, try LTXVAddGuide and prompt/resolution work · only if
those fail, test Q6_K — and test it on p07 of the murim scene, where Q4's
sword-hand deformation across f11-f16 is a known, reproducible failure to
compare against.

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

If a ref predates that rule and the source render is genuinely not on disk, look
for it first, then record `"irrecoverable: <what you searched, when>"` instead of
a path. The check reports that as a NOTE and stays green. Do not write a
plausible-looking path to silence it — a wrong provenance is worse than a missing
one, because the next person believes it.

`ref_sources` accepts exactly three shapes, and inventing a fourth breaks the
checker rather than the data:

| shape | when |
|---|---|
| `path/to/file.png` | the normal case |
| `irrecoverable: <what you searched, when>` | the source is genuinely gone |
| `path/to/file.png (<how the provenance was established>)` | the path resolves, but somebody re-verified it and the reasoning is worth keeping |

The parenthetical is validated by splitting on the first `" ("` — the path in
front of it is still checked on disk, and a missing file still FAILS, narrative
or not. Use the third form when a source was reconstructed rather than found:
record what you compared (dimensions, saturation, hashes) so the next person can
tell verification from assumption.

⚠ Added 2026-08-22 after a session appended prose to a bare path and broke
`check_bible`, which resolved the whole string as a filename. The prose was
right and the format was wrong; the fix was to teach the checker the shape, not
to delete the evidence.

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

### A full SCENE with the character's likeness — `edit_image()` UNMASKED

Settled 2026-08-23, building a landscape throne CG for the visual novel.

`generate()` has no identity input, and a Kontext EDIT cannot restructure — so
"a big pose change with the likeness held" looks impossible from those two
rules. It is not. **`edit_image()` without a `mask_box` is not an edit**: it
starts from `EmptySD3LatentImage` at `denoise 1.0` and injects the reference
through `ReferenceLatent`, so every pixel is generated with an identity bias and
there is nothing underneath to preserve. That is the same mechanism as the back
views. Pass `canvas_width`/`canvas_height` for a landscape frame from a portrait
reference; the reference is still encoded at its own scale for conditioning.

STANDING -> SEATED WORKED first time, with the throne hall, the lighting and the
low camera all generated around him, and the likeness held across six renders.
Do not assume a big silhouette change needs a redesign of the approach.

⚠ **What did NOT work, after 4 seeds x 2 wordings x 2 references: a
SELF-CONTACT pose.** "Head resting on his hand, elbow on the armrest" came back
with the hand on the armrest every single time. What the failures teach:

| change | result |
|---|---|
| more per-limb detail ("knuckles pressed into his cheek", "the classic bored king pose") | a SEASHELL appeared against the cheek, hand still down — it placed an OBJECT rather than routing the arm, the same family as the three-legged figure |
| reference cropped to head-and-shoulders, to strip the arms-down pose bias | pose and likeness came back IDENTICAL; only the robe changed (lost the jacket) |
| three fresh seeds | thrones and robes varied a lot — one came back a European throne — but not one hand reached the cheek |

So the ordering is: **a reference modulates SURFACE detail (robe, costume); the
seed decides COMPOSITION (throne, framing, drape); and a limb that must touch
the body is reachable by neither.** Wording is the weakest lever of the three,
and adding limb detail actively backfires.

This is the same shape as the rule that a mouth cannot be animated: a small,
high-frequency articulation against the body's own surface. If a CG needs
self-contact, budget for the author to paint the arm, and reach that conclusion
by MEASURING — one sample is not evidence, and he should never be handed a
manual job the tool was not fairly asked to do first.

### An EFFECT the scene needs — draw it, do not prompt it

Settled 2026-08-23 on a spellcasting CG. WHERE an element sits is not
steerable: "a magic circle directly in front of him, between him and the
viewer" put the seal off to one side twice, exactly like a shoulder emblem
refusing to change shoulders. And fine repeated detail — a band of runes —
comes back as texture, because that is what diffusion does to small repeated
marks.

So a geometric effect gets CONSTRUCTED: `tools/magic_circle.py` draws concentric
rings, an evenly spaced rune band and a {points/skip} star polygon to RGBA at
any size, with a proper bloom. Exact placement, exact scale, legible runes,
re-usable for every spell in the series, and `--color` separates one magic
system from another for free. This is the same principle as lettering a plaque
deterministically rather than asking Kontext for hanzi.

**Generating the plate that RECEIVES an effect — three rules:**

1. Do NOT negate the effect. "no magic circle" summons one, like every other
   negation here.
2. DROP THE PHRASE THAT CARRIES IT. "casting a spell" is what puts a seal in
   frame; describe the BODY instead ("both arms raised, palms turned forward").
   Removing the noun is not enough if the verb implies it.
3. MOTIVATE ITS LIGHTING ANYWAY, or the composite reads as pasted. State a
   light source in front of the figure, below eye level and outside the frame,
   throwing light UP onto the face and the front of the costume. That is what
   the effect would do, and it is stated without drawing one — so the author's
   layer lands in light that already agrees with it.

Bloom, for anything that must read as LIGHT rather than as a blurred copy: a
white-hot CORE with the hue surviving only in the halo, SEVERAL blur radii
summed rather than one, and ADDITIVE accumulation. All three, or it looks
painted. `add_glow` in the anime-production server is the moving-picture
equivalent and pulses a sigil over a clip; it does nothing for a still.

### A CHILDISH face is a RESOLUTION problem, and CROPPING THE OUTPUT is a fix

Seven renders on one sword CG, 2026-08-23.

**A full figure in a 896-tall frame gives the head ~90 px, and at that size the
model falls back to a rounded generic face that reads CHILDISH with an oversized
head.** It is not the style LoRA — the same LoRA at the same 1.5 produces mature
faces in 832x1216 portrait concepts, where the head is large. Give the face
pixels and it matures. Asking in words ("mature adult face", "eight heads tall")
does nothing; this is the same ordering as always, with wording weakest.

**Framing comes from the REFERENCE's crop, but it is a BIAS, not a dictate, and
cropping too tight costs costume.** Measured on the same character:

| reference | aspect | result |
|---|---|---|
| full body | 0.50 | "MEDIUM SHOT" in the prompt ignored entirely; full body returned |
| head-to-mid-thigh | 0.86 | worked — face large and mature |
| head-to-hip | 1.11 | composition went WIDER again, and with the skirt no longer visible in the reference the model invented TROUSERS for legs it still had to draw |

So crop the reference to the framing you want, keep it PORTRAIT, and make sure
every garment that must appear is still visible in it. A near-square reference
stops tightening the shot.

**When anatomy fails at the edge of frame, CROP THE OUTPUT.** One thigh came out
thicker than the other — relative limb thickness is not promptable, and per-limb
detail backfires (see the seashell and the three-legged figure). A deterministic
16:9 crop across the mid-thigh removed the problem in seconds, cost nothing, and
risked none of the face that six renders had bought. Check what the crop must
KEEP before promising it: a blade sweeping to the far edge and a hip-level cut
could not both fit, and that trade is worth naming rather than discovering.

⚠ Pose wording did not take either: "legs close together and straight" returned
a wide braced stance. Do not credit a prompt clause for an improvement without a
controlled comparison — what actually helped between two of these runs is still
unidentified.

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
- **Crop the reference TIGHT before a turnaround sheet, and state the
  drift-prone details in `extra_prompt`.** Measured 2026-08-10 on the same
  character, three runs:

  | reference | seed | identity | back view | costume |
  |---|---|---|---|---|
  | raw concept, 0.68 aspect | 6001 | held, but TWO strangers inserted | none in 8 panels | drifted |
  | tight crop, 0.44 aspect | 6101 | face changed | yes | drifted badly |
  | **tight crop + `extra_prompt`** | **6001** | **holds throughout** | **two** | **correct** |

  A panel in a five-figure row on a 2048x1024 sheet is about 410x1024 — aspect
  **0.40**. A raw txt2img concept is 832x1216, aspect 0.68, with the figure
  filling only ~61% of the width. Crop to the figure's bbox and the aspect lands
  near 0.44, and the sheet stops inventing extra people and starts producing
  genuine back views. Same rule as the framing bullet above, applied one level
  up: the reference's SHAPE is inherited, not just its zoom.

  Note the middle row: at a different seed the tight crop lost the face
  entirely. That was seed variance, not the crop — the same crop at the original
  seed held identity fine. **One sample cannot separate a setting from a seed**,
  which is the same trap the LTX section documents. Change one thing at a time
  and keep the seed fixed.

  `extra_prompt` is the documented fix for anything the reference cannot show or
  keeps losing — glasses, a full-length hem, an emblem on the BACK that a
  front-view reference has no way to display. Patching a bad sheet afterwards
  reliably fails; stating the requirement upfront works.

  ⚠ **A "lean" extra_prompt naming only the losses DOES NOT WORK. Tested and
  falsified 2026-08-21, same day it was proposed.** The reasoning was: hair,
  eyes, silhouette and sash held across two sheets while the boots and back view
  failed, so restate only the failures. That inference was WRONG — those details
  held *because the full description was present*. There was never a run without
  it to justify calling them self-sustaining.

  Run with a lean prompt (boots geometry plus a back-view push, nothing else),
  the character came back in a **white t-shirt, denim shorts and slouchy
  boots, with short bobbed hair** — every trace of the design gone. That is the
  same collapse this file already records for running with NO extra_prompt at
  all. Naming only the losses is functionally the same as naming nothing: the
  prior fills every clause you leave out.

  So `extra_prompt` carries the WHOLE costume and identity description, every
  time, and the drift-prone details get stated *in addition* — not instead.
  The cost of a redundant clause is far smaller than the cost of an absent one.

- **⭐ WHEN A SHEET KEEPS LOSING ONE DETAIL: regenerate it with that detail
  corrected in `extra_prompt`, and consider conditioning on a render THIS STACK
  made itself.** Settled 2026-08-21 after six failed sheets.

  One character's knee-high smooth boots came back as LACED COMBAT BOOTS in
  every sheet conditioned on `ref_tight` (cropped from her FLUX-dev concept) —
  through four seeds, geometry wording, a stacked style LoRA and a full
  description. Her concept SHOWS the correct boots, so a correct reference was
  never sufficient on its own.

  The sheet that fixed it changed TWO things together, and they cannot be
  separated from one run:
    1. the boots were restated in `extra_prompt` as "exactly as shown: ...
       completely smooth unbroken uppers, flat soles with no heel" — the same
       shape of fix that corrected another character's costume; and
    2. the reference became `profile_6303`, a single view produced by the
       sheet's OWN stack (Kontext + turnaround LoRA + `manwha_style`) rather
       than by FLUX-dev.

  Result: correct boots in every panel, plus two genuine opposite-facing side
  profiles — an angle three single views had refused outright.

  The author's reading is that (1) is the operative fix, and it matches the
  earlier precedent. (2) has a plausible mechanism — a reference the sheet
  generator itself drew is in-distribution, so ReferenceLatent conditions more
  strongly — but it is UNTESTED ALONE. Try the corrected `extra_prompt` first;
  reach for the self-produced reference only if that is not enough, and if you
  do run them separately, record which one carried it.

  Either way the useful pattern is: **fix a stubborn detail once in a single
  view, then regenerate the sheet.** Single views render faithfully; sheets
  rotate.

- **Single views rotate to 180° but NOT to 90°.** Back views come out reliably.
  A side profile does not: three attempts on the same character collapsed to a
  near-front view with a slight turn — asking for "side profile view", then for
  geometry ("one shoulder directly behind the other, one eye and one ear
  visible, nose and chin in silhouette"), then in image space ("the toes
  pointing toward the left of the image"). None moved it. Profiles come from
  SHEETS; back views come from single views.

- **The turnaround LoRA cannot rotate an OBJECT.** Given a cropped pair of boots
  as its reference it invented an entire middle-aged man in a shirt and tie and
  put work boots on him, across nine panels. Its prior demands a character; hand
  it an object and it manufactures a person to wear it. Do not try to turn
  props, weapons or costume pieces this way.

- **Never write "soft" — or any negation — into a prompt you want sharp.**
  A standalone boot render came back blurred three times. The cause was in the
  prompt the whole time: it said "soft matte fabric" (asking for softness
  outright) and "no blur, no depth of field" (naming blur, which summons it, per
  the negation rule above). Replacing both with positives — "crisp black
  outlines and hard-edged flat color, every edge in sharp focus" — fixed it in
  one run. Two wrong diagnoses were chased first, the matting stage and the
  style LoRA's strength; neither was at fault.

- **⚠ NEVER answer "the model will not turn this character" with "draw it
  yourself."** This server is for everyone, not just artists — anyone who can
  draw a back view on demand does not need a character generator. That answer is
  a failure of the tool, not a fallback for it. A prior session recorded the
  opposite, wrongly attributed to the author; see ARCHITECTURE.md's retraction.
  Related and equally binding: a character sheet WITHOUT a genuine back view is
  incomplete — do not propose dropping it.

- **When cropping a panel out of a wide sheet, a top-band-only gap search
  under-crops the bottom of the figure.** Splitting panels by column gaps in
  just the head/shoulder band (needed because trailing hems and pooled robes
  merge across the WHOLE canvas at floor level, defeating a full-height gap
  search) finds boundaries that are correct up top but too narrow lower down,
  where sleeves flare, hems drape forward, and hanging hands extend past the
  shoulder-width column. Cut into one floor-length figure three times in one sitting:
  a forward-draping hem, a dangling hand, and a full second figure accidentally
  merged in. Two floor-length figures can genuinely touch at the hem with no
  clean vertical gap between them at all — check a specific row band for an
  all-white column before assuming one exists.

  Verify a crop by looking at the actual saved file at real resolution before
  calling it done, not by trusting the code that produced it.

- **A crop-aspect theory of back-view success was tested in-session on
  2026-08-21 and FALSIFIED before it was ever written down here.** Five
  characters' first sheets seemed to fit a pattern: 0.47, 0.49 and 0.58 aspect
  all produced a back view, while 0.68 and 0.31 did not. Rerolling the two
  failures disproved it. One reroll used the IDENTICAL 0.68
  crop — the trim logic found the same bounding box — and only the seed
  changed; it then produced a clean back view. Same aspect, opposite outcome.
  The other reroll changed both the aspect (0.31 -> 0.48) and the
  seed together, so it cannot rescue the theory either — it is confounded.

  Conclusion: **whether a sheet produces a genuine back view is seed-dependent,
  not aspect-dependent.** If a sheet lacks one, reroll with a new seed (same
  stack: manwha_style stacked, full description in extra_prompt) rather than
  reshaping the reference crop first.

- **When a sheet's panels disagree with EACH OTHER, generate one view at a time
  instead.** A turnaround is a single generation across one canvas, and nothing
  ties panel 2's costume to panel 1's — consistency is emergent, and it only
  emerges when the reference is winning against the LoRA's own priors. When it
  is not, each panel resolves independently onto a different nearby archetype,
  and you get five variations rather than one character five times.

  Every character shows some of this; the normal workflow is to keep the three
  to five panels that agree and bin the rest. The question is the HIT RATE. One
  character in eleven dropped to roughly two usable panels per sheet and stayed
  there across **sixteen sheets** — every LoRA strength, both guidance values,
  four resolutions, and a dozen prompt rewrites.

  What finally worked: `create a [back|side profile|three-quarter] view of this
  exact character, one single full-body figure ...` at **832x1216, one figure
  per canvas**, keeping the turnaround LoRA (it is what supplies the rotation —
  plain Kontext will not rotate a viewpoint) and stacking `manwha_style`
  alongside it. One figure cannot be internally inconsistent, and each view is
  independently rerollable. Her back view — the panel sixteen sheets had failed
  to produce — came out clean on the first single-view attempt.

  Costs: the views will not match each other perfectly, and **facing direction
  still ignores instruction**, so opposite profiles cannot be requested — mirror
  one at composite time. Reach for this when a character's hit rate collapses,
  not as the default; sheets are cheaper when they work.

- **Beware the design that sits inside the LoRA's prior.** The character who
  failed wore a two-piece outfit (fitted top, long skirt) — the only one in the
  cast not in a full-length wrapped robe. Run with no `extra_prompt` at all she
  came back in a crop top, jeans and trainers; other rolls produced a school
  sailor uniform, laced combat boots and a mini skirt. A robed silhouette has no
  modern analogue for the prior to pull toward, which is why every robed
  character worked first or second time. If a design maps onto common anime
  character-sheet wardrobe, expect to fight for it.

- **The reference carries POSE bias too.** Check what it actually shows before
  blaming the prompt — a "back turnaround" whose head is turned to
  three-quarter will keep producing a visible face.
- **Expression must be set at generation time.** It is not a safe edit: two
  masked passes at 780px of face failed to turn a grin into alarm. Avoid
  "mouth open, eyes wide" — that describes laughing as well as shock. Say
  what the features DO ("corners pulled down, brows raised and pinched").
  ⚠ CORRECTED 2026-08-23: this rule used to end "and negate the wrong read
  explicitly", which contradicts the no-negation rule above it and lost. A
  threatening face prompted with "not amused, not pleased and not smiling"
  came back SMILING. Name muscle actions only the wanted expression can
  make — a sneer needs a raised upper lip, fury needs flared nostrils and a
  clenched jaw — and the wrong read becomes unsatisfiable without ever
  being mentioned. That worked first try on the same shot.
- **Facing direction and body angle never respond to instruction.** Every solo
  came out facing the sheet's direction, and a requested 35° turn produced a
  square-on figure twice. Mirror at composite time instead — and remember a
  mirror flips asymmetric costume detail, which must be repainted.
- **WHICH SIDE an asymmetric costume detail lands on is not steerable either —
  MIRROR THE IMAGE.** Settled 2026-08-22 on a character's back view, whose
  shoulder embroidery came out on the wrong side.

  Two attempts failed. Stating the side in the prompt did nothing, in image
  space ("the shoulder at the LEFT side of the image") as well as
  anatomically — the reroll put the embroidery back on the same shoulder and
  moved an unrelated dangling sash to the other hand instead. Then Kontext was
  asked to move it, which looked safe because an emblem RECOLOR had worked on
  another character. It did not move: measured over the upper body, the blue
  pixel count fell 33840 -> 24812 and the mean x slid from 453 to 412 against a
  figure centre of 408, i.e. the marking diffused toward the spine and partly
  dissolved rather than relocating. A recolor changes a surface in place; a MOVE
  has to reconstruct plain fabric where the emblem was, which is the
  invent-what-lies-underneath problem that always fails.

  A horizontal flip fixes it exactly, instantly and for free. The usual
  objection — a mirror flips asymmetric costume detail — is not a cost here,
  it is the entire mechanism. On a back view the crossed collar barely reads,
  so there is nothing else to repaint.

  Check the side numerically rather than by eye: mask the emblem colour, take
  its mean x over the upper body, compare against the figure's bbox centre.

  ⚠ Note which way the author is reading "left". On a figure seen from behind,
  the character's own left shoulder appears on the VIEWER'S RIGHT. Measure where
  the emblem actually is before acting — on this render it was already on his
  anatomical left, which established that the author meant image space. Either
  way "move it to the other shoulder" is unambiguous, so prefer that wording.
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

  ### ✅ The two levers that actually work

  **`strength` on `LTXVImgToVideo` is THE lever, and its default is the trap.**
  At `1.0` the first frames are pulled hard onto your image and the clip
  freezes — that *is* the notorious LTX I2V "slow zoom, no motion" failure, and
  it is what made `dev` look broken here for six experiments. Set it to **0.8**.

  **`frame_rate` on `LTXVConditioning`: use 48, not 24.** A known anti-static
  trick, and here it improved motion *and* fidelity simultaneously — the only
  change all day that did not just trade one for the other.

  Measured, dev, same prompt/seed, comparing frame 12 at native resolution:

  | config | motion | frame 12 faces |
  |---|---|---|
  | strength 1.0, fps 24 | 2.6 | perfect, but a still |
  | strength 0.8, fps 24 | 37.3 | glasses smeared, hand a blob |
  | **strength 0.8, fps 48** | **44.5** | **glasses readable, faces clean, fingers intact** |

  **Render near the source's native resolution.** At 576x832 a portrait
  illustration came back with scratchy noise through the fine hairline and
  eyebrows; at **768x1088** (same seed, same everything else) that vanished —
  clean eyes, clean strands. Fine linework needs pixels to survive, and this
  bites well above the 540p floor. Raising strength does NOT fix it: 0.90, 0.92
  and 0.95 all showed identical scratching. It is a resolution problem.

  Degradation is **progressive over the clip** — frame 8 is cleaner than 12,
  which is cleaner than 24. Generate 25 frames and use the first ~18; trimming
  is free.

  ### Working recipe for small character motion

      --variant dev --strength 0.9 --fps 48 --steps 25 --cfg 3.0
      --w 768 --h 1088 --len 25          # near-native aspect, both /32

  ~400 s per shot on a 6 GB card. Verified on a hand-drawn portrait asked to
  "close her eyes and lower her head": eyes shut cleanly by frame 16, head down
  by 24, face intact throughout.

  **Ask for small motion.** Big actions (a kick) still wreck faces and hands at
  any setting. Small ones — a blink, a head tilt, cloth drift — come out clean.

  **Never ask for ROTATION.** Turning a head or body needs an angle the drawing
  does not contain, so the model invents it and the face smears. Measured: a
  head *lowering* (Silvia) stayed clean; a head *turning from profile toward the
  viewer* (Matsuyama) degraded the eye and hair. Word prompts to forbid it —
  "tilts her head down, still facing the same way" — because a loose phrase like
  "lowers and tilts his head" is enough for the model to rotate him.

  **Animate the ENVIRONMENT, not the character.** Cloth, hanging scrolls, hair,
  fire, water, foliage, particles and glow have no identity to preserve, so
  there is nothing to degrade — and they are what this model is best at. Give
  the character one small safe action (head lowering, eyes closing) and let the
  scene carry the life. This also lifts the total ask above the frozen
  threshold, so the character's small motion is less likely to be ignored.
  It is the same trick limited-animation anime uses to hide a held cel.

  > ⚠ **UNVERIFIED — the rules in this block need re-testing.** They were each
  > drawn from a single run, and the seed was changed between runs. The same
  > shot (Matsuyama) moved at 35.6 with a diminutive-heavy prompt on seed 201
  > and FROZE at 2.29 with a plain prompt on seed 401 — the opposite of what
  > "diminutives freeze it" predicts. Seed variance is the uncontrolled
  > variable. Before trusting any of this, run the same prompt across 3+ seeds
  > and compare distributions, not single samples.

  **Do not stack diminutives, and never use negation.** Writing "slightly /
  slowly / gently / tiny" into a prompt — especially alongside a style suffix
  like "subtle gentle motion" — pushes the ask under the threshold and the clip
  comes back static. Measured: two shots froze at 1.87 and 1.27 for exactly this
  reason, while a plain "closes her eyes and lowers her head" worked at 20.8.
  State the action plainly. And phrase what you *want*, never what you don't —
  "without turning" tends to summon the turn.

  **There is a motion WINDOW — asks can be too small as well as too big.**
  Measured: "blinks slowly, hair drifts gently, tiny head movement" produced
  motion 1.87, i.e. a frozen clip with three identical frames. "Closes her eyes
  and lowers her head" produced 20-40 and worked. A kick produced 30+ and
  destroyed the faces. So aim for a middle-sized ask: a head lowering, a sway,
  ice growing. If a clip comes back static, the fix is a BIGGER ask, not a
  smaller one.

  **LTX will NOT animate a mouth.** Prompting "their mouths open and close as
  they talk" produced a mouth held open for all 25 frames — measured by cropping
  the mouth region and diffing every frame. Open/close is a small, high-frequency
  articulation and the model treats the mouth as fixed facial geometry. Do mouths
  (and blinks) with the engine's frame player instead: one drawn closed-mouth
  frame plus `animation: { mode: "mouth" }`. Instant, deterministic, no VRAM.

  Safe asks: eyes closing, head lowering/nodding, hair and
  cloth drift, fire/water/particles, glow pulsing.
  Unsafe asks: head or body turning, limbs travelling far, anything revealing a
  surface not visible in the source.

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

## Music: ACE-Step text-to-music (local, 6 GB card)

Verified working 2026-08-06 — a 120 s vocal track at 48 kHz stereo in **87-105 s**
on the RTX 3060 Laptop, ACE-Step 1.5 turbo, 12 steps. Driver:
`servers/music-generation-mcp/` (MCP) or `tools/ace_run.py` (CLI).

- **No custom nodes.** ACE-Step 1.0 and 1.5 are both in ComfyUI core as of 0.25
  (`comfy_extras/nodes_ace.py`). Nothing to install but the weights — unlike LTX,
  which needed city96's GGUF loaders.
- **6 GB is enough, and no quantisation exists or is needed.** Peak ~5.9-6.0 GB
  for a 120 s track. It runs FASTER THAN REAL TIME, which inverts the assumption
  that auditioning would be expensive: `generate_variations` at n=5 is ~9 minutes.
  Audition properly instead of settling for the first usable take.
- **`--lowvram` makes no measurable difference here — use the plain
  `run_nvidia_gpu.bat`.** Measured on the same 120 s graph and seed:
  with the flag 87 s / 5972 MiB peak, without it 91 s / 5904 MiB. Neither OOMs;
  the gap is run-to-run noise. Do not inherit the flag from a running process and
  assume it was a considered choice.
- **1.5 needs `DualCLIPLoader(type="ace")` with TWO text encoders.**
  `comfy/text_encoders/ace15.py` always builds a qwen3_06b for the base/lyrics
  embedding, and the larger Qwen is a *separate* autoregressive audio-code LLM.
  A single-file `CLIPLoader` does not error — it silently lands on ACE 1.0's T5
  path instead (`comfy/sd.py:1527` vs `:1692`). Same class of silent-garbage trap
  as mixing LTX connectors across variants.
- **`duration` and `seconds` are two inputs that must agree.**
  `TextEncodeAceStepAudio1.5` conditions on `duration`; `EmptyAceStep1.5LatentAudio`
  sets the real latent length from `seconds`. Nothing checks them, and a mismatch
  conditions for one length while sampling another. Derive both from one value.
- **Never let the negative conditioning run the audio-code LLM.**
  `generate_audio_codes` defaults to True; leaving it on for the negative pays for
  a second autoregressive pass that is discarded — and at cfg 1.0 the negative is
  not used at all.
- **1.5 is the LARGER download** (10.0 GB vs 1.0's 7.7 GB), not the smaller one,
  because of the second text encoder. Chosen anyway: it has an explicit
  `language` input including `ja`, plus `bpm`/key/time-signature. 1.0 has no way
  to declare a language and infers it from the lyric script.
- `memory_usage_factor` 4.7 (1.5) vs 0.5 (1.0) is **not** an OOM signal — the
  factors multiply different latent shapes. For 120 s the attention working sets
  come out comparable (~282 MB vs ~207 MB).
- **Judge by ear.** Compression ratio catches silence (<6% of raw) and noise
  (>92%), and real music sits between — 27% for a sparse lo-fi bed, ~60% for a
  full band with vocals. That is a *sanity* check, not a quality one. No
  statistic tells you whether the vocal is any good, which is the entire reason
  this server exists.

  ### Writing a song that actually sings (learned on a 120 s Japanese vocal track)

  ### ⚠ Getting the model to sing the words you actually wrote

  Learned the hard way on a 31 s haiku/tanka/chōka that took ~40 takes. Every
  one of these beat the parameters — no seed, temperature, cfg, duration or
  section marker fixed what these fix.

  **FEED IT SONG-LENGTH LINES. This is the big one.** ACE-Step was trained on
  sung lines of sentence length and loses its place in short poetic fragments —
  it drops them, merges them, or invents replacements.

  | lyric | avg morae/line | result |
  |---|---|---|
  | the working song | 15.8 | correct |
  | haiku 5-7-5 | 5.7 | badly wrong |
  | tanka 5-7-5-7-7 | 6.2 | badly wrong |
  | chōka (9 lines) | 6.1 | badly wrong |
  | **chōka, 5-7 pairs JOINED** | **11.0** | **correct** |

  The fix costs nothing: join each 5-7 pair into one line. Identical text,
  identical order, identical meter when read — only the line breaks move. Treat
  line breaks in the model input as PHRASING marks, not meter marks.

  **Keep two versions of every lyric.** The written one for humans (kanji,
  poetic line breaks) and a model-input one (singing-phrase line breaks,
  ambiguous words spelled out). They are different artefacts; nobody but the
  model sees the second.

  **Some words are simply misread, and kana fixes them — but NOT plain
  hiragana.** Confirmed failures: 転移 (read wrong; its dominant sense is
  medical *metastasis*, not isekai transfer), 異世界, 心, ありふれた.
  - Rewriting the WHOLE lyric in hiragana makes things WORSE. Japanese has no
    spaces; the kanji/kana alternation IS the word-boundary cue, and
    いせかいにてんいしたんだ is a wall the encoder has to guess through. Lines
    went missing when this was tried.
  - Spell out ONLY the offending word, and prefer **katakana** — it fixes the
    reading while keeping the script contrast that marks boundaries.
  - ありふれた-class cases are already kana, so there is no reading to fix; it
    just fails. Untested whether katakana perturbs it usefully.
  - **Rōmaji is expected to be worse** and was not tried: it is
    out-of-distribution for `language="ja"`, and it destroys mora timing (きゃ
    is one mora, `kya` is three letters; っ is a mora with no letter).

  **Short total durations sing badly.** 30-31 s requests mangled lyrics
  consistently while 62 s and 107 s did not — the model's own default is 120 s
  and it was trained on songs, not fragments. For short video music, **generate
  at song length and extract the window you need** (`tools/trim_audio.py
  --start`). Cut on a downbeat and fade both edges.
  ⚠ Do NOT over-read this: 62 s vs 93 s was one sample each and both had
  errors. What is solid is that 31 s is bad; the rest is draw variance.

  ### Lyric density

  **Density is arithmetic, but count MORAE, not lines.** One bar =
  `4 * 60 / bpm` seconds. The bars-per-line rule below was derived from one song
  and INVERTED on short-line poetry — it rated a working 16-line lyric
  "fragments" (4.18) and a failing tanka "good" (3.10). Morae per bar is the
  metric that transfers: **~3.5-4.0 morae/bar** is the working range
  (the working song measured 3.77; a failing tanka measured 2.00).

  Bars-per-line is still a useful secondary check when line lengths are
  song-like and roughly even:

  | bars/line | what you hear |
  |---|---|
  | ~4.7 | each line stretched across 2-3 fragments with gaps — sounds broken |
  | **~2.3** | **correct — lines sung as lines** |
  | <2 | lines run together with no breath, and trailing lines get DROPPED |

  Measured: 16 lines over 120 s at 150 BPM = 75 bars = 4.7 bars/line, and every
  line came back fragmented. The same lyric at 60 s = 2.34 bars/line sang
  cleanly. **If a clip sounds broken, do the division before touching anything
  else.**

  **Instrumental sections are NOT free duration — they compete with the lyric
  for the same bars.** Adding `[intro]`, three `[instrumental]` blocks and an
  `[outro]` to an 85 s track silently truncated the lyric: it sang lines 1-10 of
  16 and stopped. Budget **~6 bars per instrumental block**, not the ~4 that
  seems reasonable. The full-song budget that worked:
  `16 lines * 2.3 bars + 5 blocks * 6 bars = 67 bars = ~107 s at 150 BPM`.

  **A blank line between EVERY lyric line produces per-line pauses.** Bare
  newlines are weak punctuation to the Qwen encoder and lines get sung
  back-to-back with no breath. Putting a blank line between each one fixed it;
  phrasing instructions in the `tags` did not (tested separately).

  **Requesting a relative minor does nothing — it is the same seven notes.**
  Asking for `B minor` returns audio that measures as **D major** (its relative
  major); `E minor` measures as **G major**. This is not the analyser failing,
  it is what a relative pair *is*. Picking B minor to "keep the tonal centre
  related to the D major they liked" was exactly backwards: sharing a pitch
  collection is what made it unable to change the mood. To actually shift mood,
  count how many notes differ from the current key — D→B minor differs by 0,
  D→E minor or F# minor by 1, D→D minor by 3 (which overshot into "wrong").

  **`tools/analyze_reference.py` measures bpm and key** from any mp3/flac/wav —
  no ffmpeg needed. Use it on a reference track the author already likes instead
  of guessing at parameters, and on your own output to check what the model
  actually did. Validated against known inputs: 152.0 measured vs 150 requested.
  It cannot separate relative major/minor pairs (nothing chroma-based can) and
  it flags them when it sees one.

  **A measured tempo that is a HARMONIC of the requested one is a detection
  error, not a rendering.** Autocorrelation peaks at every harmonic of the true
  period, so half-time, double-time and the 3-against-4 subdivisions are all
  real peaks and choosing between them is a guess. Measured on the 31 s isekai
  chōka: the detector returned **161.50 BPM** for a track asked for 120, while
  envelope autocorrelation put the strongest peak at exactly **120.00** —
  161.5 is 120 x 4/3, a weaker peak it latched onto. That grid would have been
  simply wrong, not slightly off.

  So neither source is authoritative:

  | case | measured | requested | truth |
  |---|---|---|---|
  | model ignored the request | 117.45 | 120 | **measured** — a 120 grid drifts 0.78 s by 30 s |
  | detector picked a harmonic | 161.50 | 120 | **requested** — ratio is 4/3 |

  The discriminator is the RATIO. Close to 1 → agreement. Close to a simple
  harmonic (2, 3, 1/2, 1/3, 3/2, 2/3, 4/3, 3/4) → the detector is wrong, trust
  the request. Anything else → the model is wrong, trust the measurement.
  `extract_beats` does this automatically and reports `bpm_basis`; do the same by
  hand when using `analyze_reference.py`, which does not.

  ⚠ Both simpler rules were committed to this file at some point and both were
  wrong. Do not replace the above with either one.

  **Two things are NOT controllable, so sample and pick rather than tune:**
  - *Vocal gender/register.* Identical `deep male vocal, baritone, low register,
    male singer` tags produced a male vocal at 85 s and a female-sounding one at
    95 s. Confirmed at scale: of 5 same-config variations, **one came back
    female and one noticeably high-pitched**. Budget for roughly 1 in 5 takes
    being unusable on register alone, and generate accordingly — no wording
    tested fixed it.
  - *Half-time feel.* Measured across **6 seeds at an identical config**
    (`bpm=150`, 107 s, B minor): four came back at a measured 73.8-76 BPM
    (half-time), two at 152.0. So half-time is the majority outcome, not a coin
    flip — but not reliable either.
    ⚠⚠ **This whole observation is now in doubt, and probably wrong.** 73.8-76 is
    almost exactly HALF of 152 — precisely the harmonic-confusion pattern
    documented above. Those four takes may never have been in half-time at all;
    the detector may simply have picked the 1/2 peak. The reconciliation rule
    resolves 73.8-against-150 to 150. Nothing was re-verified because those
    tracks have since been deleted, so this stands as unresolved rather than
    corrected — do not cite the 4-of-6 figure as evidence of anything.
    ⚠ I briefly credited half-time for making the winning take "finally sound
    like regret". **That was wrong**: the author then preferred a 152.0 take as
    well. Tempo feel varies by seed and does NOT predict which take is liked.
    Do not build on it. (The key change was ALSO wrongly credited at the time —
    the audio measured as D major throughout, so it cannot have been the cause
    either. What actually fixed the mood is still unidentified; the honest
    account is that the winning takes were found by sampling, not by a lever.)

  This is the same lesson as LTX's seed variance: single samples produce
  confident conclusions that do not replicate. Note that the 6-seed sweep above
  is the ONLY claim in this section backed by a distribution — everything else
  came from one run per configuration, and should be treated accordingly. Once
  the config is musically right, use `generate_variations` and choose a
  performance rather than tuning further.

## ⚠ Token economy: DO NOT READ THE RENDERS

The whole point of ComfyUI on the GPU is that images are cheap. They stop being
cheap the moment Claude looks at them.

**Measured 2026-08-22.** One session read 768 distinct images; two earlier
sessions that produced a comparable amount of art read **zero** and **one**.
Transcript sizes: **827 MB** against 3 MB and 1 MB. 91.7% of the big one was
image payload. It burned a 5-hour Max-plan limit in under 2 hours; the earlier
sessions did a full day of concepts and turnaround sheets with limit to spare.

Why it compounds: image tokens are roughly `width x height / 750`, so a
2560x1024 sheet is ~3,500 tokens — but the first read is the cheap part.
**Images persist in context and are re-sent on every subsequent turn.** In that
session a single image appeared **112 times** across 1,583 total occurrences,
so late turns were carrying an enormous payload before any work happened.

### The rules

1. **Default to NOT looking. The author reviews the renders; act on his verdict.**
   He is faster at it and it costs nothing. In the session above he caught the
   wrong boots, the short arms, the missing topknots and a wrongly deleted file
   — Claude's own review mostly duplicated his at great expense.
2. **If you must look, DOWNSCALE FIRST.** "Is there a back view?" is answerable
   at 800x320 for ~340 tokens instead of ~3,500. Only go full resolution when
   the question genuinely needs pixels (a hand's digit count, a lineart edge).
3. **One composite, never N crops.** A single numbered contact strip beats eight
   panel reads. Do not read the strip AND the individual panels.
4. **Never re-read an image already in context.**
5. **Prefer numeric checks, which are free** — alpha coverage, bbox, aspect,
   image size, mean saturation, pixel diffs. ⚠ But they mislead on their own:
   an arm-proportion check "passed" numerically while the author could see the
   arms were stubby, because the canvas had been truncated and the
   normalization was wrong. Use numbers to filter, his eye to judge.
6. **When a session has read many images, COMPACT OR START FRESH.** The cost is
   already sunk into context and every further turn pays it again.

## Practical

- **Pin `mcp<2` in every Python server.** mcp 2.0.0 REMOVED `mcp.server.fastmcp`,
  which all four servers import. An unbounded `mcp>=1.2.0` resolves to 2.0 on a
  fresh install and dies at import. Verified 2026-08-06: bounded → 1.29.0,
  unbounded → 2.0.0. Existing venvs are unaffected; this bites new installs only.
- ComfyUI runs prompts **serially**. Submit one job at a time; stacked jobs burn
  their timeouts waiting in queue.

  ⚠ This bit hard on 2026-08-11 and the failure looks like something else
  entirely. `_submit_and_wait` measures wall-clock **from submission**, so its
  timeout counts QUEUE WAITING as well as rendering. Two scripts were in flight,
  each submitting sequentially; every job in the second script sat behind the
  first script's work, blew its 600 s, and raised `Timed out after 600s`.

  ComfyUI rendered all of them perfectly. The *clients* gave up. So the symptom
  is "my renders vanished" — finished images that never reach the destination
  folder, while the job log shows nothing wrong until it exits.

  **Nothing is ever actually lost:** ComfyUI writes its own copy of every render
  to `ComfyUI/output/` under the graph's `filename_prefix`, whatever the client
  does. Recover by timestamp. Three renders were rescued this way in one night.

  Two habits that turn a 30-second check into a 20-minute stall, both self-
  inflicted the same night:
  - **Never pipe a background job through `tail` or `grep`.** Both buffer until
    the process exits, so the log stays empty while the job runs — and a `grep`
    filter silently discarded an error return that would have flagged a broken
    edit immediately. Write the full log; filter when reading it.
  - **Poll `ComfyUI/output/` directly, not the job log.** The output directory is
    ground truth and updates the moment a render finishes.

- **Chaining jobs on a log marker breaks silently if the upstream job is
  killed.** A downstream script that waits for `"=== upstream done ==="` will
  wait forever when that marker never prints, giving no error and no output —
  one sat idle for twenty minutes before anyone noticed. Prefer launching
  directly and letting ComfyUI's own serial queue order the work.
- Use the repo venv: `servers/character-panel-mcp/.venv/Scripts/python.exe`.
- ~15 min per ControlNet generation, ~8 min per Kontext edit on a 6 GB card.
