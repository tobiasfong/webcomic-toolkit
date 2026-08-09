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

  ### Writing a song that actually sings (learned on RxR's セカンドチャンス)

  ### ⚠ Getting the model to sing the words you actually wrote

  Learned the hard way on a 31 s haiku/tanka/chōka that took ~40 takes. Every
  one of these beat the parameters — no seed, temperature, cfg, duration or
  section marker fixed what these fix.

  **FEED IT SONG-LENGTH LINES. This is the big one.** ACE-Step was trained on
  sung lines of sentence length and loses its place in short poetic fragments —
  it drops them, merges them, or invents replacements.

  | lyric | avg morae/line | result |
  |---|---|---|
  | セカンドチャンス | 15.8 | correct |
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
  (セカンドチャンス measured 3.77; a failing tanka measured 2.00).

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

## Practical

- **Pin `mcp<2` in every Python server.** mcp 2.0.0 REMOVED `mcp.server.fastmcp`,
  which all four servers import. An unbounded `mcp>=1.2.0` resolves to 2.0 on a
  fresh install and dies at import. Verified 2026-08-06: bounded → 1.29.0,
  unbounded → 2.0.0. Existing venvs are unaffected; this bites new installs only.
- ComfyUI runs prompts **serially**. Submit one job at a time; stacked jobs burn
  their timeouts waiting in queue.
- Use the repo venv: `servers/character-panel-mcp/.venv/Scripts/python.exe`.
- ~15 min per ControlNet generation, ~8 min per Kontext edit on a 6 GB card.
