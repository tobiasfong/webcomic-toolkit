# Changelog

All notable changes to the Character & Panel Generator MCP server are documented
here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This server lives in the [`webcomic-toolkit`](https://github.com/tobiasfong/webcomic-toolkit)
monorepo (`servers/character-panel-mcp`) alongside its sibling servers from day one;
releases are tagged `character-panel-mcp@vX.Y.Z`.

## [Unreleased] — FLUX-only: the SD1.5/SDXL path is retired

**Breaking.** This server now runs on FLUX exclusively. The SD path had been
carried along unused — every finished panel of the first real scene went through
FLUX Kontext — and maintaining two stacks meant two model registries, two sets
of defaults, and ~1400 lines of graph code nobody executed.

### Removed

- **`workflow.py`** — SD1.5/SDXL graph building, `generate`, `generate_concepts`.
  Its model-agnostic plumbing moved to the new **`comfy.py`** (connection,
  auto-launch, image upload, clean-backdrop suffix, rembg matting).
- **Tier 3 — `training.py`, `bake_character_lora`, `check_lora_training`,
  `cancel_lora_training`.** kohya trains SD1.5 LoRAs; FLUX LoRA training is a
  different pipeline and isn't built here. No character was ever baked.
- **Tier 2 — `identity_mode`, `ip_adapter_weight`** on `generate_character_pose`,
  and the guard that rejected them on FLUX. FLUX has never supported IP-Adapter.
- **Tier 1 — `ref_denoise`** (img2img seeding from the primary reference).
- `setup_models.py` (downloaded only the SD Tier-2 models) and
  `setup_models_sdxl.py`. FLUX models are documented in README Step 9; the Union
  Pro 2.0 ControlNet keeps `setup_models_controlnet_pro.py`.

### Changed

- `generate_character_concept` now defaults to `model="flux_manwha"`.
- Tool count 22 → 17 (three Tier-3 tools, two pose-map tools).

- **The 3D pose-map generators — `generate_pose_map`, `generate_pose_depth_map`,
  `mannequin.py`, `vrm_depth.py`, `vrm_scene.py`, `blender_scripts/` and the VRM
  base meshes (~930 lines + 33 MB).** They forced direction structurally through
  ControlNet and worked (~2/3 and ~3/3 seeds), but they fed
  `generate_character_pose`, which has no image identity input. A
  structurally-correct back view of nobody in particular cannot become a
  reference for a specific character, and Kontext cannot rotate a viewpoint to
  fix it afterward. `generate_turnaround_sheet` produces a genuine back view
  **with the likeness intact** — which is what the real reference sheets used.
  Removing IP-Adapter is what turned this machinery from redundant into unusable.

  **ControlNet is NOT retired.** `generate_character_pose` still accepts any
  control map via `pose_ref_path`, which is how `tools/sketch_to_lineart.py`
  corrects hand-drawn anatomy (`pose_control_type="canny_auto"`).

### Fixed

- **FLUX txt2img was returning photorealistic people.** `CLEAN_BACKDROP_SUFFIX`
  said "studio backdrop", "simple even lighting" and "clean sharp edges" — all
  photography words, fighting `manwha_style` on every generation — and this
  server had no style suffix at all. Added `FLUX_STYLE_SUFFIX` naming only the
  medium (no lighting, mood or camera words). Verified live on a fixed seed:
  distinct colours 857 → 382, luminance 0.577 → 0.786, photoreal → cel-shaded
  manhwa. Applies to txt2img only; `edit_image()` and the turnaround sheet
  inherit style from their reference. **This predated the migration** — it was
  invisible because every finished panel went through Kontext.



### What this costs, stated plainly

- **`generate_character_pose` has no image identity input at all.** Identity is
  prompt text from the bible description, so it drifts. Use it when the camera
  angle outranks the likeness; use `edit_character_image` (Kontext, conditions on
  a real image) when the likeness outranks the angle. This is a real trade, not a
  strict upgrade — the two mechanisms are mutually exclusive in one pass.
- **Generation is minutes, not 20-40 seconds.** Compositing stays instant and
  GPU-free; that separation matters more than before.
- IP-Adapter identity conditioning is gone with no replacement. It defaulted to
  off and the finished panels never used it, but it was a shipped capability.

> This is the first tagged release. Everything below was built and live-tested across
> one continuous development arc before anything was ever released or announced —
> the numbered stages are development history, kept for the honest record of what was
> tried, what broke, and what the fix actually was, not a chain of prior public releases.

## [Unreleased] — The character bible was never being used (2026-07-30/31)

### Fixed — both characters were registered to the wrong reference images
One character's primary reference was a stray render: hair styled differently,
cropped above the ankles so a whole costume element was **not visible at all**,
while the approved sheet had a full turnaround showing it front and back. The
other character's entry listed one ref while two sat in the folder, so the
registry and the disk disagreed about what was canon.

Both now point at crops from their approved `*_sheet_FINAL.png`, with the back
view, an expression crop and an action pose registered alongside.

This is the root of a whole session's worth of "why is this detail wrong".

### Fixed — descriptions were missing canon that thirteen panels already showed
One character's description omitted her eye colour, an accessory and her
footwear, despite all three being consistent across every locked panel. Added,
with full specs.

### Added — `get_character` MCP tool
There was **no way through the MCP interface to obtain a character's reference
image path**. `list_characters` returns prose. So hand-writing appearance into
prompts was not laziness, it was the only available route — and it is how a
panel shipped with the wrong hair and eye colour for a character whose bible
had carried both correctly the whole time.

Returns the description marked *use verbatim*, the primary ref flagged as the
one to condition on, each ref's recorded origin, and the approved panels that
establish each detail.

### Added — provenance, canon panels, and `tools/check_bible.py`
Each ref now records which approved sheet it came from (`ref_sources`), and each
character lists which finished panels establish which detail (`canon_panels`).
The validator checks that refs resolve, that no unlisted image lurks in a
character folder, that the primary ref traces to an approved sheet, and that
descriptions are non-empty. Non-zero exit, so it can gate a run. It immediately
found a third case nobody was looking at -- another character's primary ref has
no provenance either.

### Added — repo-root `CLAUDE.md`
Nothing loaded project rules into context automatically, so every session
rediscovered the conventions and compaction erased them. The rules now live
where they are always read, each stated with the failure that produced it.

### Finding — plain FLUX has NO identity conditioning, and it shows
`flux_workflow.generate()` takes `pose_ref_path` for ControlNet but no identity
reference; identity comes from prompt text alone. Four text-only attempts at a two-character
contact panel failed with **attribute bleed** — one character's accessories
landed on the other, and their hairstyles swapped — because nothing binds an
attribute to a body. Every identity
mechanism in the codebase binds ONE reference to ONE generation, so two
characters cannot be locked in a single image. Hence solo-generate + composite.

Reference-conditioned solo passes held identity on every single attempt.

### Changed — panel 4 was REBUILT through the solo-generate route, and shipped
This started as a control test: regenerate a known-good panel through the new
route to see whether it held up. It held up well enough that the composite
replaced the depth-map version as final p04.

So there are now two different panel 4s in this project's history, made two
different ways, and it matters which one the notes describe:

- **The depth-map p04 (superseded).** Both figures generated in ONE image off a
  VRM depth map. Real contact between the figures, and ground shadows drawn
  natively by FLUX. Reached final only after heavy hand repair: six-finger and
  missing-thumb fixes, a costume pass, a hair recolour, and footwear that had to
  be composited in from a separate render.
- **The composite p04 (shipped).** Each figure generated solo from its own sheet,
  keyed with `tools/cutout.py`, placed on a FLUX background plate
  (`_scene1/plates/flux_3312.png`) sharing one ground line and an upper-left key
  light. Identity was correct from the first pass on both figures, down to the
  small costume details, with no repair pass at all.

### Finding — solo-generate solves identity, not interaction
The rebuild produced two on-model figures on one ground line with matched
lighting and no fusion — and **no contact between them**. The composite route
cannot make characters touch. It shipped because the beat survives the change:
the near miss reads as intentional rather than as a failed contact.
That was a story call, not a technical fix, and it will not be available for
panels whose beat REQUIRES contact.

Two costs come with it. Composited figures have no shadows, so they must be
given them (squashed silhouette, sheared away from the key light) — the depth-map
route never needed this because FLUX drew them. And mirroring a figure flips
asymmetric costume detail: a lapel pin had to be erased from the mirrored side
and repainted on the correct one, at coordinates measured off the mirrored figure
rather than assumed.

For p13/p15, where two bodies must interleave, expect depth staging or hand work.

### Finding — a finished panel works as a TWO-character identity reference
Two-character identity locking was written off as impossible because every
mechanism binds one reference to one generation. That constraint is about the
number of reference SLOTS, not the number of characters inside the reference.
Conditioning on the one approved panel containing both characters carried both
identities correctly in a single generation across both seeds, with zero
attribute bleed, where four text-only attempts had swapped their accessories and
hairstyles between them.

Boundary: it holds identity, it does not restructure. Both seeds kept the
source panel's standing-over-prone relationship instead of adopting the
requested one. So this is the cheap route for a panel whose staging is
CLOSE to an existing locked panel — a reaction shot, a new camera on the same
beat — and no help at all when the pose must change fundamentally.

### Finding — the model will not put a character's back on the ground
Six seeds across three prompts, all conditioned on a standing sheet, all
refused "lying flat on his back": two reclining on one hip, two prone and
propped on their hands, one lounging pin-up. Identity was flawless every time,
so this is purely pose.

What every failure shares is the chest facing camera — the model rotates the
figure around that rather than turning his back to the ground, which is exactly
what a true supine side view requires. Camera-led wording ("the camera is down
at ground level beside him") did not beat it, and explicit negations did not
either: the seed that followed "not propped, not on his side" landed on prone,
the one position not excluded.

**The workaround is to sidestep it.** Generate him STANDING in rigid side
profile — a near-zero change from a standing sheet, which Kontext does happily —
then rotate the image 90°. Facing viewer's-right maps to face-up, and top of
frame maps to left, giving supine with the head at the left.

Two things this needs. Light rotates with the image, so generate with the key
light on the side that lands correctly after the turn (upper-RIGHT becomes
upper-LEFT under a counter-clockwise rotation). And ask for no ground line and
no cast shadow, or the shadow rotates into a vertical smear beside him.

### Finding — "whole body in frame" does not prevent cropping
It failed three times (braced stance, then twice on the upright profile, always
cutting at the knees). What worked was naming the terminal feature and demanding
space past it: "clear empty space below his BLACK SHOES, which are fully visible
at the bottom of his legs." Both seeds framed correctly on the first try after
that. Canvas aspect has to suit the figure's axis too — a lying figure needs
landscape, a standing one portrait.

Facing direction, by contrast, never responded to instruction at all: every solo
render faced the same way regardless, holding its reference sheet's orientation. Do not
spend seeds on it — mirror at composite time, and if the figure is also being
rotated, flip the rotation direction so the mirror and the turn cancel out on
lighting.

### Rewrote — `tools/cutout.py` for whole characters
The original hue rules were built for a brown boot on a forest wash and failed
completely on a character: "blue leads red" ate black hair and navy trousers,
a neutral-grey rule ate the white shirt, a distance rule ate the skin. It now
keys what is **connected to the image border**, so black, white and skin survive
inside the figure at any value.

Thresholds measured, not guessed: backdrop white (255,255,255); its cast shadow
(190,196,203) — distance ~101, COOL, blue leading red by 13; skin (253,236,218)
— distance ~42 but WARM, red leading blue by 35. So tolerance must exceed 100 to
take the shadow, and what protects skin at that distance is the SIGN of
red-minus-blue. Tolerance is per-image: a figure with a hard cast shadow needs
~120, while a figure in pale cool clothing may need ~14, because that costume can
sit only 20 from the backdrop.

### Added — `tools/place_cutout.py`
Two landmark pairs solve scale, rotation and position as one affine. Mirroring
is a separate flag because two points cannot distinguish a flipped figure from
a rotated one. Note that mirroring also flips asymmetric costume detail — a
lapel pin changes sides — which must be corrected against canon afterwards.

### Finding — extra limbs are stochastic, not caused by the pose
A third arm appeared on one seed and not on another **from the identical
prompt**. An earlier theory that describing a limb repeatedly invites another
one did not survive that test. Removing a spare limb by hand took six PIL passes
and never came clean; re-rolling the seed cost eight minutes and worked. The
CHANGELOG already said why the surgery fails: painting flat colour cannot
replace deleted linework, because it has no texture to stand in for what the
lines were drawn on.

## [Unreleased] — Panel 4 complete: what Kontext will and won't do (2026-07-29/30)

Panel 4 (a two-figure contact beat) is done —
`output/<project>/_scene1/depth/p04_FINAL.png`. It took far more repair rounds
than it should have, and the rounds sort cleanly into two kinds: the ones that
found a genuine limit of the model, and the ones that were compositing bugs of
my own making. Both are worth keeping straight for the next contact panel.

### Finding — Kontext restyles, it does not restructure
Across two hands and roughly ten attempts, direct instructions to add a thumb,
fix handedness, or remove a digit never once succeeded — the topology stayed
locked to the source silhouette no matter how the prompt was worded or how many
seeds were tried. The one thing that worked was asking for a different
GESTURE: "make this an open hand" (rather than "add a thumb" to the existing
fist) succeeded first try, because a gesture change is local rendering, not a
structural edit. The same distinction explains why "remove the rear skirt
panel" failed twice — deleting an occluding layer means inventing what was
behind it, which is structural reasoning — while finishing a shape already
blocked in crudely in PIL succeeded immediately. Practical rule: if an edit
requires the model to decide *what exists*, do that part deterministically
(prefill in PIL, or force the layer order via compositing) and only ask
Kontext to render the result.

### Finding — small regions don't have enough latent cells to fix anatomy
A masked in-place hand repair at ~125x105px returned the source essentially
unchanged across two different seeds (mean abs diff 3.0 — VAE round-trip
noise, not a redraw). Cropping with context, upscaling 4x, editing, and
shrinking back gave the model real resolution to work with and produced clean
results on the first attempt. Bigger crops (~300x280) worked better still.
Small-region repairs need both the mask (to protect the composition) and the
enlargement (to give the model something to reason about).

### Bugs — all mine, all in the compositing, not the model
Restoring her bare skin from an earlier base render — needed so her raised leg
could occlude the new skirt rather than the reverse — went through four bad
iterations before it was right:
- a brightness threshold that silently excluded the brightest highlight skin,
  leaving lavender-tinted streaks behind on her thigh;
- a hand-drawn polygon that covered only her STANDING leg, so the KICKING leg
  got no protection at all and picked up stray fabric and discoloration;
- the sunlit dirt path passing the same skin colour test and becoming the
  single largest "skin" region in the frame, punching holes in the skirt hem;
- the mask including her face, so an earlier version of her head got pasted
  back a few pixels offset from the current one (Kontext rescales its own
  output), double-exposing her eye, ear and jaw.

None of these were the model failing — they were an under-specified region
mask being asked to do a job only careful measurement can do. The fix each
time was to measure the actual pixel values in play (`sample points, don't
guess`) rather than tune a threshold blind.

Also: stacking a new fix onto a file whose hem a PREVIOUS bug had already
broken kept the hole alive through two more rounds — rebuilding from the last
known-good file instead of the most recent one fixed it instantly. And "looks
clean" needs checking end-to-end, not at one corner: a hem gap on the far side
of the skirt survived a review that only checked the near side.

Two straight pixel-paint attempts to clean up a stray shading strip both
failed for the same reason: painting can move existing pixels around but
cannot invent texture (grass, embroidery) that was never behind the removed
object. Handing that same edit to Kontext as a local re-render — not a
structural change, just "clean up this outline and continue the background
texture" — succeeded on the first attempt. Compositing and generation solve
different problems; this session mixed them up in both directions before
sorting out which one belongs where.

### Final assembly
The very last mile — hand pose readability and fine proportions — was finished
by hand in image-editing software rather than through further Kontext rounds,
once the pipeline had produced a version where every remaining issue was that
small. That is exactly the fallback this server was always meant to support:
AI generation gets a panel most of the way there, a human finishes it, nobody
is stuck re-drawing from scratch.

## [Unreleased] — Masked Kontext editing: repairs that cannot wreck the pose (2026-07-29)

### Added — `mask_box` on `flux_workflow.edit_image()`
`edit_image` ran Kontext at `denoise=1.0` over the entire canvas. There was no
mask, so nothing in the frame was ever protected and "keep her pose exactly as
it is" was a suggestion the sampler was free to ignore. It usually held, which
is why this went unnoticed — until an edit asked for something that competed
with the composition.

Panel 4 was that case. Three separate costume passes, each asking for the canon
hanfu robe, each destroying the kick: the wide sleeve was painted over the
pixels the raised leg occupied and the leg fused into it, leaving a boot growing
out of a cuff, then a detached boot lying on the path, then both feet back on
the ground. Naming the leg in the prompt and fencing it off in words changed
nothing, because words were never the mechanism.

`mask_box=(x0, y0, x1, y1)` gates denoising through `SetLatentNoiseMask`, so
pixels outside the box are carried through from the source instead of being
re-decided. The mask is pushed through the same `FluxKontextImageScale` as the
image — Kontext rescales its input to a supported bucket, and a mask that
skipped that rescale would be offset from the latent it is meant to gate.
Mutually exclusive with `canvas_width`/`canvas_height`.

Every pass after this change preserved the pose exactly. The same skirt edit
that had failed three times unmasked landed first try.

### Added — `tools/region_composite.py`
Feathered rectangular composite between two renders of the same base, for
keeping the good part of one pass and the good part of another. Also the
building block of the crop-enlarge repair below, and of the solo-generate +
manual-composite route.

### Finding — masking protects composition, enlargement fixes anatomy
Masked in-place repair stalled on a hand: at 125x105 px it is ~15x13 latent
cells, and two different seeds both returned the source essentially unchanged
(mean abs diff 3.0 inside the box — VAE round-trip noise). The mask was working;
there were not enough latent cells to redraw an anatomy from.

Cropping the hand with context, upscaling 4x, editing at full Kontext
resolution and compositing back produced a clean five-digit hand on both seeds,
after every in-place attempt had failed. Small-region repairs need both: the
mask to protect the composition, the enlargement to give the model something to
reason about.

### Finding — the fusion rule applies to Kontext, not just control maps
Two surfaces meeting at near-identical depth fuse. Already recorded for depth
and lineart conditioning; it governs edits too. Adding fabric next to a limb is
enough to trigger it, which makes costume passes on action panels inherently
risky and is the reason `mask_box` exists.

Corollary that is a staging decision, not a repair: panel 4's sleeves stayed
short-capped because her raised leg crosses directly under both arms, so a
wrist-length hanfu sleeve has nowhere to hang that the leg is not already using.
No prompt or mask fixes that — the leg has to be posed clear of the arm line
back at the depth render.

### Fixed — mask edges leave the old colour behind
A recolour masked to the skirt left maroon fringes along the top and left edges,
where the feather faded out before reaching them. Feathered masks need to extend
past the region being changed, not stop at its boundary.

## [Unreleased] — Two-figure posed depth maps: multi-character contact panels (2026-07-28/29)

### Added — `vrm_scene.py` + `blender_scripts/vrm_scene_depth.py`
Any number of posed VRM figures from a JSON scene spec, rendered to one depth
map. The multi-figure sibling of `vrm_depth.py` (one figure, one hardcoded
standing pose, yaw only). Per figure: `vrm`, `location`, `yaw` or full
`rotation: [x,y,z]`, and per-bone euler offsets. Plus `assets/Base_Female.vrm`
from the same OpenGameArt CC0 pack as the male mesh.

This is what finally placed a two-character action beat. Everything else had
failed on the same panel: text-only prompting, FLUX Redux, FLUX IP-Adapter,
Impact-Pack regional conditioning, lineart ControlNet at every strength from
0.40 to 0.80, Kontext pose editing (0 for 7), and generating each character
separately.

### The finding — limb fusion is a DEPTH problem, not a model weakness
Two surfaces meeting at near-identical depth get merged. This one fact explains
every artifact chased across two sessions: a boot fusing into a shirt, a
forearm into a chest, a forearm into its own upper arm, a kicking leg rendering
as a sleeve ending in a boot. It also explains why flat lineart cannot work —
a line map says "edge here", never "this outline is a leg and that one is a
sleeve" — and that failure reproduces with a SINGLE figure in frame, which
rules out limb overlap as the cause.

Staging rules that follow, all verified live:

- Pose limbs against background, never across the character's own torso.
- Keep folded arms in an open V, so forearm and upper arm sit at different
  depths rather than stacking.
- Leave a gap at contact points and close it afterwards.

### Fixed — perspective camera for scene renders
`vrm_pose_depth.py` uses an orthographic camera, correct for turnaround sheets
where front and back must scale-match. Inherited into scene rendering it was
wrong: ortho has no foreshortening at all, so a limb thrust at the viewer
renders the same size as one held back. With no perspective cue FLUX improvises
limb scale — mismatched arms, and an enlarged, deformed foreshortened hand.
Perspective at 65mm fixed both. 40mm was wide enough to distort on its own.

### Fixed — `detail_fix` hand pass conditioning
The hand detailer inherited the ControlNet-applied conditioning, so it redrew
whatever the control map said the hand was — against a low-poly VRM mitten,
the same claw it was meant to repair. Decoupled from ControlNet but still fed
the SCENE prompt it was worse: at denoise 0.7 a hand crop is close to a fresh
generation, so "two people sparring" rendered a tiny complete person inside a
hand's bounding box. It now gets its own short hand-only prompt
(`FLUX_HAND_DETAIL_PROMPT`).

Important correction: `detail_fix` is NOT useless, which two separate tests
suggested. It only works once the arm is staged clear of the torso — tested in
isolation against a fused arm it looks like a no-op. The combination is what
produces a correct hand.

### Known — masking hands out of the control map does not work
Three attempts, three artifacts, one cause. Fading the hand disc to background
produced a bright-rim/dark-centre gradient, which is the depth signature of a
sphere: the model drew a translucent bubble over every hand. Flattening to
wrist depth produced haloed discs. Blurring glowed. Hands sit on the silhouette
edge, so any local edit there is visible against the background. The code
remains in `vrm_scene.py` behind `mask_hands`, DEFAULT OFF, with the failure
modes documented. The working answer is the hand-only detailer prompt above,
which leaves the map alone.

### Known — silhouette cannot be prompted against a strong control map
The base meshes are effectively bald, so asking for long hair at
`pose_strength=0.75` does nothing — the head silhouette wins. Same applies to
loose clothing or anything else that changes outline. Either add the geometry,
lower `end_percent`, or handle it in a later edit pass.

## [Unreleased] — Sketch-driven ControlNet: found the real cause of the line bleed (2026-07-27)

### Fixed — the "white scratch lines" were Canny's doubled edges, not the ControlNet model
Storyboard-sketch ControlNet runs had been compositing visible white hairlines
over the finished art and desaturating the whole frame, at every strength strong
enough to hold a composition. Six tests against `flux_controlnet_union_alpha`
(strengths 0.45/0.60/0.70/0.75, preprocessor on and off, noisy and cleaned
sketch) pinned it on the model, since the control map itself verified clean.

That was the wrong conclusion. Swapping in Shakker-Labs Union Pro 2.0
(`setup_models_controlnet_pro.py`) improved anatomy markedly — two-body frames
stopped dropping limbs and rendering hands as feet — but reproduced the same
bleed. The actual cause is `CannyEdgePreprocessor` run over a *pencil sketch*:
Canny detects both sides of every drawn stroke, so each line becomes two
parallel control edges, and the model renders the doubled hairlines literally.

Fix: binarize the sketch to a single-stroke white-on-black map and feed it
directly with `pose_preprocess=False`. New `tools/sketch_to_lineart.py` does
this (deliberately high default threshold of 215 — hand sketches are faint, and
a conventional 128 drops most of the drawing).

### Added — `canny_auto` control type
Union Pro 2.0 dropped the per-type embedding the alpha model had; it is trained
as one unified conditioner, so naming a specific type misroutes it. `canny_auto`
sets the union type to `auto`. Measured effect on Pro 2.0 was near-nil, which is
itself the confirmation.

### Known — strength trades composition against art quality, and ControlNet only draws what you drew
On lineart input at seed 7777, 1216x1088: **0.65 / end_percent 0.80** is the
working setting. 0.80 reproduces the drawn composition exactly but smears and
desaturates; 0.40-0.50 render cleanly but ignore the pose.

Separately: limbs left undrawn in the sketch come out missing or as empty
sleeves. This is a property of the input, not a model defect — a sketch is a
specification, and an incomplete one is followed faithfully.

### Known — Kontext cannot relocate a limb between figures in a two-character frame
Attempted to drive pose from a clean 0.65 render instead of raising ControlNet
strength: 0 for 7 across two rounds. Asked to raise the *woman's* leg into a
kick, Kontext raised the *man's* leg in 6 of 7 runs — placing it exactly where
hers belonged, so the geometry was right and the subject attribution wrong. The
7th gave her a raised arm instead. Positional anchoring ("the figure on the
right in the lavender robe"), an explicit "do not lift the boy's leg", and a
framing lock did not help, and tightening constraints degraded held details
(boots became dress shoes, framing zoomed out). Composition must come from the
control map, not from a post-hoc edit.

## [Unreleased] — Fixed: front/back hero images overflowing their box (2026-07-26)

### Fixed — `compose_full_reference_sheet()` scaled hero images by height only
`fb_scale` was computed purely as `HERO_MAX_H / max(front.height, back.height)`,
never checking the resulting combined width against `CENTER_W`. For tall source
images the pair overflowed the center box, and because the paste offset is
`cx0 + (CENTER_W - fb_w) // 2`, an oversized `fb_w` made that offset **negative**
— silently pasting the figures on top of the left-hand PROFILE/APPEARANCE text
column, truncating the last characters of every wrapped line. Found on a real
A sheet rebuild (591x1248 front + 532x1248 back overflowed to 756px against
a 580px inner width). Now constrained by both height and inner width, whichever
binds first; figures coming out shorter than `HERO_MAX_H` is the correct outcome
when width binds. An earlier sheet happened to fit under the old code, so
this was latent rather than previously visible.

## [Unreleased] — Investigated and reverted — FLUX Redux for multi-character panels (2026-07-26)

### The problem this was chasing
A real two-character crossover test (two characters across two projects,
projects) surfaced that `edit_image()` only accepts one reference image —
in a contact/action panel with both characters, the unanchored one drifts
(observed: eye-color drift on the anchored character, costume drift on the
unanchored one, and the requested contact choreography was ignored outright
on two separate attempts).

### Tried: FLUX Redux (`StyleModelLoader`/`CLIPVisionEncode`/`StyleModelApply`,
native ComfyUI-core, no custom node needed) — chain one `StyleModelApply` per
reference image onto the text conditioning, hypothesis being it'd hold both
characters' identity in one txt2img generation. Four staged tests (single
reference, strength 0.5/0.2/0.08, then a face-only crop at 0.4) all showed
the same failure: Redux reproduces the *entire composition* of whatever
reference image it's given — pose, framing, background — regardless of what
the text prompt asks for, and regardless of whether the reference is a
full-body shot or a tight face crop. Lower strength let the background start
following the prompt but never freed the pose. Higher strength also visibly
degraded output sharpness. **Not a tuning problem — StyleModelApply's global,
whole-image conditioning is structurally the wrong tool for "new pose/
composition, held identity."** `generate_with_redux()` and its model
constants have been removed from `flux_workflow.py`; the two downloaded
model files (`flux1-redux-dev.safetensors`,
`sigclip_vision_patch14_384.safetensors`, ~940MB combined) were deleted from
the ComfyUI install, and `setup_models_flux_redux.py` was deleted.

### Also researched, not yet tried: FLUX IP-Adapter
Checked both real options before writing any code. **Neither supports the
regional/spatial masking this problem actually needs** (confining each
character's identity to its own part of the frame) — confirmed by reading
source, not just docs:
- XLabs-AI/x-flux-comfyui: attention-mask support was requested in
  [issue #120](https://github.com/XLabs-AI/x-flux-comfyui/issues/120)
  (Sept 2024), a maintainer said "we are going to do this," never shipped;
  repo has had no commits since Oct 2024 — abandoned.
- Shakker-Labs/ComfyUI-IPAdapter-Flux (InstantX's model, more recently
  active): `ApplyIPAdapterFlux`'s actual `INPUT_TYPES` only exposes `weight`
  and temporal (`start_percent`/`end_percent`) controls — no mask input.

Without spatial masking, two IP-Adapter references would condition the whole
image at once, same failure class as Redux just via a different mechanism.

### Leading candidate for next attempt: per-character LoRA + regional
conditioning ("Latent Couple"-style canvas-region splitting during sampling),
not reference-image conditioning at all. This is how the commercial AI-comic
platforms that have actually solved this (Dashtoon, ComicsMaker.ai) do it,
and it's this project's own already-documented Tier 3 — the strongest
consistency tier — just never applied to a *multi*-character scene before.
Architecturally the right shape for this problem either way: identity (LoRA)
and spatial placement (regional conditioning) are independently controllable,
unlike Redux/IP-Adapter's single global reference-image conditioning.

## [Unreleased] — Token-budget optimization pass (2026-07-26)

### Changed — trimmed `@mcp.tool()` docstrings in `server.py`
Every tool docstring is sent as that tool's `description` in the MCP schema on
every request where this server is connected — a recurring per-request cost,
not a one-time read (the same lesson `novel-translation-mcp` already
documented for its own schema trim, ARCHITECTURE.md §8a). Light-trimmed 10 of
21 tools (biggest cuts: `generate_character_pose` ~84→~58 lines,
`generate_reference_sheet` ~104→~62 lines), cutting restated/redundant
phrasing while preserving every distinct number, date, failure mode, and
rationale. 1546→1452 lines. Left untouched: the module-level top docstring,
inline code comments, and non-`@mcp.tool()` private helpers (e.g.
`_render_pose`) — none of these are part of the schema sent per-request, so
trimming them wouldn't have saved anything. `webcomic-background-mcp` and
`novel-translation-mcp` were not touched in this pass.

## [Unreleased] — Real Stage-6 run + full-template reference sheet (2026-07-23/24)

### Added — `compose_full_reference_sheet()` (`tools/compose_sheet.py`)
A denser, bordered-box poster layout modeled on a real hand-composed Avery
reference sheet, alongside the existing simpler `compose_concept_sheet`:
scattered left/center/right columns instead of one stacked text column,
front+back shown side by side in one box, an "IN ACTION" pose row, one boxed
prop illustration, and a small ability-mechanism diagram box. Not yet wired
into `server.py` as an MCP tool — called directly from a script so far.
Deliberately does not model a stat block, personal quote, or mission
statement — no real data for those fields; don't invent filler (see
ARCHITECTURE.md §8b.11).

### Fixed — three real bugs found live during the first full real-character run
- **Turnaround-sheet proportions**: a short/wide canvas (1536×768) biases
  Kontext toward a squat figure regardless of the reference image's own
  proportions. Fixed by using a taller canvas (1536×1280) plus explicit
  "maintain scale and proportion" language in the prompt itself, not just the
  reference image.
- **Glasses missing/faint in some panels**: patching a bad turnaround sheet
  after the fact (whole-sheet edit, per-panel crop-and-paste) reliably failed
  or introduced new regressions in untouched panels. Fix was to bake the
  requirement into the main generation prompt and reroll fresh, not patch.
- **Expression thumbnails cropped off the chin**: `row_box()`'s square,
  top-anchored crop assumed roughly-square source images; a taller-than-wide
  source lost the bottom of the face. Added a `square=False` mode that scales
  to one shared height instead, preserving full aspect with no cropping.

### Added — `tools/bg_composite.py`, `compose_full_reference_sheet`, `apply_gradient_background` MCP tools
Tried a flat-cutout-plus-separate-illustrated-background approach first:
connected-component background detection correctly told a shirt apart from
a same-colored pose-gap (e.g. between crossed legs), but any pose with a
glowing VFX element (ice-magic burst, glowing book) kept showing a visible
halo — the glow renders as a genuine soft fade to white in the source art
with no hard edge to cut along. Decided illustrated backgrounds weren't
worth the time: plain white/gradient is the actual convention for model
sheets, not a compromise. **Plain two-color gradients work cleanly**,
including for glow poses, as long as the gradient is light-toned at the
point the glow fades into — pairing the ice-magic/glowing-book poses with
pale (winter/sunset-toned) gradients made the halo invisible, since it was
never about background vs. no background, only contrast between the glow's
white fade and whatever's behind it. Shipped as `tools/bg_composite.py`
(`extract_alpha`, `make_gradient`, `composite_on_gradient` — the illustrated-
background path was deliberately NOT carried over, see its module
docstring) plus two new MCP tools: `compose_full_reference_sheet` (wraps
`compose_sheet.py`'s new bordered-box poster layout, §8b.11) and
`apply_gradient_background`. The sheet ships with gradient backgrounds
(front=dusk, back=night, expressions=dusk/night/winter, action
poses=sunset/winter). The illustrated-scene-compositing problem is
real and left for whenever panel generation (character composited into an
actual scene) is built properly, where it can be solved by generating the
effect within the conditioned scene directly rather than cutting it from a
white-background render. See ARCHITECTURE.md §8b.11 for the full
step-by-step recipe, meant to be repeated for the next character.

## [Unreleased] — VRM depth-map ControlNet: a more reliable direction fix (2026-07-22/23)

### Added — `generate_pose_depth_map`, `pose_control_type="depth"`
A second, more reliable direction-control mechanism alongside Stage 5's
mannequin-skeleton ControlNet path, built from a real posable VRM mesh
(`assets/Base_Male.vrm`) rendered in Blender rather than a line skeleton.
New `vrm_depth.py` drives a separate Blender install (portable Blender 5.2
LTS + the community VRM Add-on — NOT pip-installable for this project's
Python 3.12, since the `bpy` pip package skips 3.12 entirely) via subprocess,
producing a depth map that `generate_character_pose`/`flux_workflow.py` can
use via the new `pose_control_type="depth"` parameter (default remains
`"openpose"`, the mannequin skeleton — nothing existing changes). New
`generate_pose_depth_map` MCP tool wraps it, mirroring `generate_pose_map`'s
shape.

**Result: ~3/3-seed direction-lock reliability, up from ~2/3** — but only
after fixing a real calibration bug (the depth remap's near/far window was
~8x too wide, producing a near-flat, low-relief map that looked clean but
gave the ControlNet almost no real structural information — the actual cause
of a hallucinated second head and other artifacts in initial testing, not a
ControlNet-strength problem). `type="normal"` was tested head-to-head and
dropped — same direction reliability, markedly worse costume coherence (one
seed's entire garment derailed into an unrelated robe).

**A second, distinct bug found and fixed**: the VRM mesh wears a plain
t-shirt, not any character's actual costume — describing a different outfit
in the prompt while conditioning on this mesh's depth silhouette causes a
text-vs-geometry conflict (ragged texture-clash artifacts). Fix: this mode's
prompt automatically excludes the character bible's `description` (costume
text) — use it for pose/anatomy only, then apply the real costume afterward
via `edit_character_image` as a separate pass. Validated end-to-end,
including catching and fixing a real logical error along the way (a necktie
rendered on the back of a back-view figure — a tie is front-only and
shouldn't be visible from behind at all) with a second, precise
`edit_character_image` call. See ARCHITECTURE.md §8b.10 for the full,
occasionally painful story (a lot of undocumented Blender 5.2 API churn
along the way — `Scene.node_tree`, `CompositorNodeMapRange`/`Math`, and
`CompositorNodeOutputFile`'s format-override handling all changed shape
since most available documentation was written).

`generate_reference_sheet` deliberately does NOT get `pose_control_type` —
it has no `pose_ref_path` parameter to pair it with; this is a manual,
curated flow (`generate_character_pose` + `generate_pose_depth_map` +
`edit_character_image`), not the bulk sheet tool.

## [Unreleased] — FLUX exploration + Stage 5: wired into the live tool (2026-07-21/22/23)

Motivation: 1.1.0's SDXL hand-anatomy fixes (CharTurn + RPGTurn + ClearHandsXL
LoRA stacking) plateaued — hands kept coming back deformed even fully stacked.
Prototyped FLUX.1-dev instead, GGUF-quantized (`flux1-dev-Q3_K_S.gguf`, ~5.0 GB,
via `ComfyUI-GGUF`) to fit the same 6 GB VRAM budget.

### Added — Stage 5: `model="flux_manwha"` + a staged concept-to-sheet workflow
The validated scratch-script recipe below is now real, callable code, not just
standalone test scripts. New `flux_workflow.py` (mirrors `workflow.py`'s shape
for FLUX's distinct ComfyUI graph — GGUF unet loading, dual CLIP encoders,
flux-specific sampling/guidance nodes — kept as a separate module rather than
threading a third graph convention through `build_graph()`, which is already
dense with SD1.5/SDXL/Tier-2 branches). `model="flux_manwha"` works anywhere a
model name is accepted (`generate_character_concept`, `generate_character_pose`,
`generate_reference_sheet`), routed via `_render_pose`'s new FLUX branch;
`identity_mode`/IP-Adapter raises a clear error if requested with FLUX (that
combination has never been tested). Three new tools complete the staged
workflow the validated stages actually call for: `generate_turnaround_sheet`
(FLUX Kontext dev + the turnaround-sheet LoRA, reading a character's registered
reference), `edit_character_image` (FLUX Kontext dev as a general-purpose
plain-English editor — the validated local-anatomy-fix mechanism), and
`compose_reference_sheet` (assembles the Avery-style poster from
already-existing images — e.g. panels `crop_reference` sliced out of a
turnaround sheet — rather than generating fresh views the way
`generate_reference_sheet` does). SDXL/SD1.5 are completely untouched; this is
purely additive, same non-migration philosophy as the SDXL prototype.

Validated in standalone scratch scripts before being ported into the above:
- Base FLUX txt2img + a manhwa-style LoRA (`manwha_style.safetensors`), no OOM,
  clearly better anatomy on first look than SDXL.
- Impact Pack `detail_fix` hand pass ported to FLUX — needs `denoise=0.7` (0.55 was
  insufficient), confirmed 5-finger hands vs. SDXL's persistent deformity.
- Mannequin-generated ControlNet back view (`flux_controlnet_union_alpha`, InstantX
  Union, same `mannequin.render_pose_map` used since 1.0.0): genuine back-facing
  views on 2 of 3 seeds across two separate rounds — real progress, but not reliable
  enough to ship unattended (the same seed missed the direction lock both times it
  was tried, so this is seed-dependent, not noise).
- FLUX Kontext dev installed (`flux1-kontext-dev-Q3_K_S.gguf`) as an image *editor*
  (not text-to-image): validated for **local anatomy fixes on an already-correctly-
  posed image** (took a genuine back view with hands hidden in sleeve cuffs,
  instructed a hand-exposure edit, got clean 5-finger hands with everything else
  unchanged). **Not validated** for full front→back rotation as a single edit — one
  test produced a chimera (back-facing head/hair/hands, but front-facing tank-top
  neckline and shoe orientation), because "turn around" and "keep everything else
  the same" are self-contradicting instructions for a full viewpoint change.
- Kontext turnaround-sheet LoRA (Civitai 1753109): first test (recommended prompt
  verbatim) produced 7 panels, none an actual back view. Traced to the recommended
  prompt inserting "exact" into the creator's required trigger substring ("create
  turnaround sheet of this character"), breaking it. **Retested same-session with
  only that word dropped — fixed it.** Panel 4 of 7 came back a genuine back view,
  verified whole-figure (correct back collar, back seam, rear pockets, no belt
  buckle, clean hands) not just glanced at. Single successful seed so far, not yet
  a reliability figure — needs a multi-seed re-run before comparing to
  ControlNet's ~2/3 rate.

Explicitly still deferred: deleting the ~12.5 GB of SDXL-era files (checkpoint,
LoRAs, IP-Adapter, ControlNet) — held until the live tool above gets real
end-to-end use, not just an import-time smoke test; tuning the turnaround-sheet
LoRA's reliability further (one confirmed clean seed, not yet a measured rate);
any FLUX/SDXL upgrade decision for the sibling `webcomic-background-mcp` server
(still SD1.5, no demonstrated problem there — a separate investigation).

## [1.1.0] — 2026-07-20

### Added — Avery-style poster sheet, restructured fields
`generate_reference_sheet`'s combined output is now a real designed sheet (title,
large front-view hero pose, back-view panel, labeled expression row, text blocks) —
`tools/compose_sheet.py`'s new `compose_concept_sheet()`, modeled directly on Tobias's
friend Avery's hand-composed character sheets, with deliberately far less text (no
bio, no quotes, no lore boxes). Uses Noto Sans JP so mixed English/Japanese text
renders correctly (needed for the personality field's speech-pattern notes). Character
Bible fields reworked per direct feedback on the first cut: `role`/`status`/
`personality` (three separate fields) consolidated into one `profile` field;
`abilities` unchanged; the sheet's third block, "Appearance," is NOT a new field — it's
`description` itself, shown on the sheet as well as fed to generation, so hair/eye/
costume notes (including ones pulled from an artist's own markdown notes when
ingesting their art) are only ever typed once, never duplicated between a
generation-facing field and a sheet-facing one.

### Added — disciplined sequential generation (scope corrected after live testing)
`generate_reference_sheet` generates in a fixed order regardless of how `views` is
passed: front view first, then back, then expressions. Once the front view succeeds,
it becomes the **back view's** identity anchor (img2img seed + IP-Adapter reference)
instead of the raw bible photo — chaining an already-in-style render should hold
costume/color continuity better than re-deriving it from a raw source photo.
**Expression/face close-ups deliberately do NOT chain off the front view** — the
first cut of this feature chained everything, and live testing caught it immediately:
a "face close-up, smiling" request came back as a repeat of the front view's full-body
action pose, because IP-Adapter conditions on the whole reference image, not just "this
person's face." Reverted that part; close-ups use the bible's own primary reference,
same as before this feature existed. Also reworded the close-up view prompts
("close-up portrait, head and shoulders only, head turned three-quarters, ...")
after live testing showed "face close-up, 3/4 view" alone was ambiguous enough to
render as a 3/4-angle body shot instead of a tight face crop.

### Investigated and reverted — automatic back-view ControlNet in generate_reference_sheet
Tried wiring the (already-shipped, already-validated as its own manual tool)
mannequin ControlNet pose map automatically into the back view here, forcing
`identity_mode="off"` to stop IP-Adapter from fighting the pose signal (confirmed
live that `identity_mode="plus"`, this tool's default, wins that fight and keeps the
render front-facing even at `pose_strength=1.45`). With identity_mode forced off,
genuine back-facing content DID start appearing — but **full-resolution scrutiny of
hands and feet, not just checking facing direction, found it came with a fused,
fingerless hand and hoof-like feet**, and retrying the same call reproduced the same
failure rather than a clean result. Reverted entirely rather than ship a mechanism
that trades one failure mode (wrong direction) for a worse one (deformed anatomy) on
an unattended, un-curated bulk call. **Back view remains an honest, open limitation
of this tool** — text + IP-Adapter alone still doesn't produce one reliably (matches
every prior finding in this project's history). The validated path when a real back
view is needed stays `generate_pose_map` + `generate_character_pose`, run and curated
by hand across a few seeds — a deliberately reviewed one-at-a-time flow, not
something safe to fire unattended inside a 5-view bulk sheet call.

### Added — `detail_fix`: the actual fix for hallucinated hands/faces
New opt-in pass on `generate_character_pose`/`generate_reference_sheet`
(`workflow.py`'s `build_graph`/`generate`), needing two new custom nodes
(`ComfyUI-Impact-Pack`, `ComfyUI-Impact-Subpack`) and two YOLOv8 detector models
(`face_yolov8m.pt`, `hand_yolov8s.pt` from `Bingsu/adetailer`). Detects the face and
hands, re-samples each region at a much higher effective resolution, composites back —
the standard fix for a resolution problem (a hand is a small fraction of a full-body
frame) that no amount of prompt/negative tuning was ever going to solve, which is what
every earlier hand-anatomy complaint in this project's history actually was. **Found
via live before/after comparison, not assumed:** the first tuning pass
(`denoise=0.45`) detected hands correctly but didn't give the sampler enough freedom
to redraw them — visually indistinguishable from doing nothing. `denoise=0.6` produced
a real, visible fix (individual finger separation instead of a featureless fist) on
the same seed; shipped as the default. Face pass stayed at `denoise=0.4`. Off by
default — extra install, roughly doubles generation time.

### Fixed
- Downloading the two YOLOv8 detector models hit the same SSL revocation-check
  failure documented in 1.0.0's OpenPose-annotator fix (`curl`/Python's own SSL stack
  both failed; `CRYPT_E_NO_REVOCATION_CHECK` / `unable to get local issuer
  certificate`) — worked around with PowerShell's `Invoke-WebRequest` (Windows
  certificate store, different validation path), not by disabling verification.
- Impact-Subpack's model whitelist (a PyTorch 2.6+ `weights_only` safety feature)
  blocks loading `.pt` files by default; documented adding the two detector filenames
  to `ComfyUI/user/default/ComfyUI-Impact-Subpack/model-whitelist.txt` in README.md's
  setup steps.

## [1.0.0] — 2026-07-19

### Added — the three consistency tiers
- **Character Bible** (`register_character`, `list_characters`, `forget_character`,
  `list_projects`) — the character-domain sibling of `webcomic-background-mcp`'s
  World Builder. Unlike a location's single canonical image, a character has a
  *set* of reference images (turnarounds, expression sheets); re-registering an
  existing character appends to the set instead of replacing it.
- **Tier 1 — `generate_character_pose`**: img2img seeded from the character's
  primary reference image onto a clean backdrop, auto-matted to RGBA via `rembg`.
  Always on; the baseline every other tier layers onto.
- **Tier 2 — IP-Adapter identity + ControlNet OpenPose**, opt-in params on
  `generate_character_pose` (`identity_mode="plus"`/`"plus_face"`, `pose_ref_path`)
  rather than a separate tool — additive on top of Tier 1's img2img, off by
  default. Uses `cubiq/ComfyUI_IPAdapter_plus` and the `OpenposePreprocessor`
  node from `comfyui_controlnet_aux`. Ships `"plus_face"` instead of true
  FaceID — avoids an InsightFace/`antelopev2` install, a known-fiddly Windows
  dependency; a deliberate, documented substitution, not a silent gap.
- **Tier 3 — per-character LoRA baking**, via `bake_character_lora`,
  `check_lora_training`, `cancel_lora_training` (kohya-ss/sd-scripts,
  `accelerate launch train_network.py`). Training takes 30-90 min, so this is
  **async by construction**: `bake_character_lora` preps a dataset and launches
  a detached background process, returning immediately; the other two poll/
  cancel it. A finished LoRA auto-installs into ComfyUI's `models/loras/` and
  is recorded on the character's bible entry — `generate_character_pose` uses
  it automatically from then on. **Bakes the Niji V5 Style LoRA into every
  character LoRA by default** (sd-scripts' `--base_weights`, merged into the
  checkpoint before training starts — distinct from `generate_character_pose`'s
  `lora=`, which applies a style LoRA at generation time); pass `style_lora=""`
  to bake against a plain checkpoint.
- **`compose_panel`** — deterministic CPU compositing of a matted character onto
  a background plate, feet-anchored (`feet_x`/`feet_y`/`height_px`) to match the
  exact shape `webcomic-background-mcp`'s `generate_city_scene` anchor tool
  already reports, so the two servers' outputs chain directly. Multi-character
  panels chain calls (`base=<previous output>`).
- **`check_status`** — ComfyUI reachability check, same as the background server.

### Added — Concept Genesis (ARCHITECTURE.md §8b.6)
Three on-ramps into the Character Bible for users who don't already have a full
reference set:
- **`generate_character_concept`** — batch txt2img candidates (n distinct seeds)
  for a character that doesn't exist in the bible yet, for writers with a story
  but no art. Nothing auto-registers; the human picks a winner and calls
  `register_character`.
- **`crop_reference`** — deterministic PIL slicer (`tools/crop_reference.py`)
  for composite concept sheets (ChatGPT/Midjourney sheet generators — hero pose
  + expressions + text overlay, all in one image). A composite sheet conditions
  img2img/IP-Adapter on its layout, not the person; it must be sliced into
  single-view crops first.
- **`generate_reference_sheet`** — grows a registered character toward a
  standard 7-view turnaround checklist (front/back/side/3-4 body views + 3
  expressions), one Tier-2 generation per view. Also the tool for on-ramp 3
  (an artist's own drawing) — that on-ramp needs zero new code, just
  `register_character` on the drawing directly, then this tool for the
  turnaround views. Defaults `combine=True`: all views are also laid out on
  one labeled grid image via `tools/compose_sheet.py` (deterministic PIL, no
  GPU) — real users expect one sheet like a traditional turnaround/concept
  sheet, not N separate files.

### Added — SDXL prototype: `model="mj_manga_sdxl"`
An additional, opt-in model family (SDXL 1.0 base +
[Midjourney Manga Art Style LoRA](https://civitai.com/models/185798)), **not**
a migration — all SD1.5 models remain untouched and are the default. Motivated
by live testing hitting the SD1.5 stack's ceiling: distorted full-body anatomy
and no genuine back views regardless of tuning. Verified live on the dev
machine (6 GB RTX 3060 Laptop): **anatomy fixed outright**, clean backdrops,
strong identity retention, ~30s warm / ~75s cold generations — far better than
the "multi-minute, maybe-won't-fit" expectation for a 6.94 GB checkpoint on
6 GB VRAM. `SDXL_MODELS` registry + `sdxl` branch in `build_graph()`
(`CLIPSetLastLayer` for the LoRA's clip-skip-2, SDXL OpenPose ControlNet
filename), automatic trigger-word injection, automatic 832×1216 resolution
when defaults are untouched. `setup_models_sdxl.py` downloads the stack, with
`--stage1-only` (~7.5 GB) vs full (~12 GB) staging.

### Added — the 3D mannequin: `generate_pose_map` (ARCHITECTURE.md §8b.7)
The back-view breakthrough. `mannequin.py` poses and rotates a low-poly 3D
COCO-18 skeleton to any yaw angle and projects it directly into an OpenPose
control map — the same mesh-to-ControlNet pattern as `webcomic-background-mcp`'s
`citygen.py`/`props.py`, applied to the character's body instead of a scene.
`generate_pose_map(preset, yaw)` synthesizes the map; feed it to
`generate_character_pose(pose_ref_path=..., pose_preprocess=False)` to pin the
pose without running `OpenposePreprocessor` (which would try, and fail, to
detect a human in a stick figure).

This exists because 2D-photo pose *extraction* fundamentally cannot produce an
unambiguous back view — see "the back-view campaign" below for why. The
mannequin sidesteps extraction entirely: at yaw=180 the left/right limb-color
assignment flips and the face keypoints vanish, exactly like a genuine
back-view annotation, because it's built from a real 3D angle instead of
guessed from a flat image. **Live-verified (2026-07-19)**: at `pose_strength=1.45`,
a synthesized yaw=180 map produced the project's first genuine clean
single-figure back view — back of head, jacket back-seam and vent, no face.
**Honest caveat: stochastic, not deterministic** — the identical settings with
a different seed produced a front-facing figure instead, in a two-seed sample.
Treat it like every other tier here: generate 2-3 seeds, curate the hit.
Identity retention (IP-Adapter) at this strength/angle combination is untested
beyond `identity_mode="off"`; Tier-3 LoRA baking remains the principled fix for
identity if `pose_strength` this high fights IP-Adapter.

### The back-view campaign (honest findings, folded into the mannequin's design)
~12 configurations tested across SD1.5 and SDXL before the mannequin —
prompt-only, img2img sweeps, IP-Adapter weights 0.25–0.8, pure text-to-image,
and OpenPose ControlNet (strengths 1.0–1.6, face/hand keypoints on and off,
direction-ambiguous and direction-distinctive pose references, identity on and
off) — established: **the checkpoints can paint back-view bodies, but never as
a clean single figure via 2D-extracted pose conditioning.** Back-body geometry
only ever appeared inside messy multi-figure compositions; every configuration
that forced a clean solo figure reverted to front/profile. A checkpoint-level
prior, not a tuning failure — the root cause being that `OpenposePreprocessor`
guesses left/right limb assignment from a 2D image's appearance and has no way
to encode "this person is facing away from camera." The mannequin above is the
fix that actually worked.

### Fixed (found via real-world testing, not synthetic tests)
- **`rembg` alone doesn't pull in a working inference backend.** `requirements.txt`
  now pins `onnxruntime` explicitly; without it, `matte()` fails at runtime with
  "No onnxruntime backend found" despite `rembg` itself installing cleanly.
- **`generate_reference_sheet`'s original tuning produced unusable output
  against a real, busy source illustration.** Every "view" came back as a
  near-identical re-roll of the source image's own pose and VFX (ice crystals,
  magic circles), ignoring both the requested angle and the clean-backdrop
  prompt — because `ref_denoise=0.7` still let the img2img branch anchor
  heavily on the source latent, and `ip_adapter_weight=0.8` conditioned on the
  reference's whole scene, not just the character. Fixed: `ref_denoise` now
  defaults to `1.0` (view text actually gets to steer composition) and
  `ip_adapter_weight` to `0.25` (identity without dragging the scene along —
  much more effective once `register_character`'s `description` field is
  actually populated with real visual detail). `workflow.py`'s
  `CLEAN_BACKDROP_NEGATIVE`/`CLEAN_BACKDROP_SUFFIX` gained explicit
  VFX-suppression terms and a `solo` tag (both apply globally, not just to
  sheets) — the `solo` tag also fixed SD1.5 occasionally rendering two figures
  side-by-side at full `ref_denoise`. Validated anti-duplicate/fusion negative
  terms (`2boys`, `fused body`, `conjoined`, etc.) were later promoted into
  `generate_reference_sheet`'s default negative during the SDXL/OpenPose
  campaign, eliminating fused-body/multi-figure artifacts entirely.
- **`IPAdapter`'s `weight_type` accepted `"linear"` in the code but ComfyUI
  rejects it.** Fixed to the actual valid enum value, `"standard"` — found via
  live `/prompt` HTTP validation, not guessed.
- **OpenPose annotator models documented + manual-install path** — the
  `OpenposePreprocessor` node's first-use download of its three `.pth`
  annotator models can fail in-process ("Cannot send a request, as the client
  has been closed"); README troubleshooting now documents placing them flat in
  `custom_nodes/comfyui_controlnet_aux/ckpts/lllyasviel/Annotators/`. (Found
  the hard way: the node's `subfolder="annotator/ckpts"` path only applies to
  the legacy `lllyasviel/ControlNet` repo id, not the default
  `lllyasviel/Annotators`.)

### Known limitations (documented, not silently dropped)
- **Hand/finger anatomy** is improved by SDXL vs SD1.5 but still imperfect —
  occasionally a thumb renders as a fifth "normal" finger. Out of scope for
  this release; no reliable fix found.
- **Back views need the mannequin + retries**, not a single deterministic
  call — see above. Front/side/3-4 views are reliable; back views specifically
  benefit from generating a couple of seeds and curating.
- **Multi-character interaction panels** (embraces, fights, physical contact)
  are the weakest spot of the layered compositing approach — layers don't
  interpenetrate.

### Verification note
Unit-tested: `build_graph`/dataset-prep/command-building/async-job-lifecycle
(Tier 1/2/3), `crop_reference`, `compose_sheet`, `generate_concepts`'
seed-stepping, `generate_reference_sheet`'s view-iteration/defaults/
unregistered-character guard, and the `_render_pose` refactor. **Live-tested
end-to-end** against real art (two characters from the author's own
Reincarnator x Regressor project, not synthetic images) — this is what
surfaced the `ref_denoise`/`ip_adapter_weight` bug, the `rembg` dependency
bug, and drove the entire back-view campaign through to the mannequin's live
verification. Tier-3 training's async job lifecycle is verified with a stub
trainer; a real kohya-ss training run hasn't been exercised live yet.
