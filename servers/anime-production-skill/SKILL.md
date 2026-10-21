---
name: anime-production
description: アニメ動画・アニメ広告・アニメMV・漫画/マンファ ティーザー動画の制作スキル。Anime/manhwa video production & marketing - turns finished illustrations or comic pages into either vertical (9:16) YouTube Shorts with Ken Burns motion, crossfades, particle effects and a depth camera, OR landscape (16:9) music videos cut to a beat grid with real generated motion, drawn effects, a hand-drawn frame and burned-in bilingual subtitles. Use when: (1) user says「アニメを作って」「アニメ動画」「アニメ広告」「アニメMV」or "make an anime video / teaser / ad / marketing video / manhwa short", (2) user wants a slideshow MV or a music video of their own artwork, (3) user mentions「キャラクターアニメーション」「アニメ制作」or animating/promoting comic panels. Do NOT use for: 実写動画、静止画像のみの生成 (this skill animates EXISTING art; it does not generate images).
user-invocable: true
---

# アニメ制作スキル / Anime Production Skill

Turns a folder of finished illustrations (and/or short video clips) into an
anime-style teaser or music video.

**This skill is self-contained.** Everything needed ships in `assets/`.
Do NOT hunt for `taiyou-taiyo/...` reference content (a private path from this
skill's original author — it does not exist publicly). Do NOT assume
NanoBanana Pro / VOICEVOX are required (see "Scope of tools" below).

## ⚑ PICK THE ENGINE FIRST — they are different products

Both are supported and both work. Deciding late means building the piece twice.

| | **Remotion** (§ Usage) | **Python / MCP** (§ Landscape MV) |
|---|---|---|
| shape | vertical 1080×1920 Short | landscape 1920×1080 YouTube video |
| motion | Ken Burns, depth camera, crossfades | real generated motion per shot (LTX), drawn effects |
| structure | panel durations, optional beat sync | cut to a beat grid; each shot declares a motion KIND |
| text | overlays in the letterbox bands | burned-in bilingual captions + `.srt` |
| stack | Node + Remotion (~800 MB `node_modules`) | Python + Pillow + ffmpeg |
| grade | bloom / grain / vignette / audio-reactive | none |

**Choose Remotion** for a Short, when the artwork should be carried by camera
movement, when you want the depth camera or the grade stack, or when nothing
needs to genuinely animate.

**Choose the Python path** for a landscape video cut to a full song, when
individual shots must really move, when a hand-drawn frame should hold portrait
art inside a 16:9 canvas, or when captions must be burned in.

They share the LTX section below — generated clips drop into either.

## One-time setup (agent-executable)

Target state: a Remotion project with this skill's engine files installed.
Skip any step that's already satisfied. Windows-tested; adapt paths elsewhere.

1. **Node.js 18+** — check `node --version`. If missing (Windows):
   `winget install OpenJS.NodeJS.LTS --source winget --accept-source-agreements --accept-package-agreements --silent`
   (If winget offers multiple sources, always pass `--source winget`.)

2. **Project** — if the user has no Remotion project, clone the tested baseline:
   `git clone https://github.com/nyanko3141592/remotion-voicevox-template.git <dir>`
   (MIT; also brings an optional Japanese talking-head/VOICEVOX pipeline.)
   Then `npm install` inside it. A bare `npx create-video` project also works —
   the only hard deps are `remotion`, `@remotion/cli`, `@remotion/google-fonts`, `react`.

3. **Install this skill's engine** — copy from this skill's `assets/`:
   - `assets/manhwa-panels.ts` → `<project>/src/data/manhwa-panels.ts`
   - `assets/beats.ts`         → `<project>/src/data/beats.ts` (placeholder; regenerated in step 6)
   - `assets/Manhwa.tsx`       → `<project>/src/Manhwa.tsx`
   - `assets/Effects.tsx`      → `<project>/src/effects/Effects.tsx`
   - `assets/Grade.tsx`        → `<project>/src/effects/Grade.tsx`
   - `assets/DepthScene.tsx`   → `<project>/src/effects/DepthScene.tsx`
   - `assets/Impact.tsx`       → `<project>/src/effects/Impact.tsx`
   - `assets/anim/frames.ts`   → `<project>/src/anim/frames.ts`
   - `assets/tools/extract-beats.mjs` → `<project>/tools/extract-beats.mjs`

   The depth camera needs three extra packages (everything else is stock
   Remotion). Pin `@react-three/fiber` to v8 — v9 requires React 19 and a
   React 18 project will fail `ERESOLVE`:
   `npm i @remotion/three@<your remotion version> "@react-three/fiber@^8.17.10" three @types/three`
   Skip this only if you will never use `depth` panels.

4. **Register the composition** in `<project>/src/Root.tsx`:
   ```tsx
   import { Manhwa, MANHWA_DURATION } from "./Manhwa";
   import { FPS as MANHWA_FPS, WIDTH as MANHWA_WIDTH, HEIGHT as MANHWA_HEIGHT } from "./data/manhwa-panels";
   // inside <>...</>:
   <Composition id="Manhwa" component={Manhwa} durationInFrames={MANHWA_DURATION}
     fps={MANHWA_FPS} width={MANHWA_WIDTH} height={MANHWA_HEIGHT} />
   ```

5. **Verify**: `npx remotion compositions src/index.ts` should list `Manhwa`.

6. **Beat map** (only once the user has supplied music) — from `<project>`:
   `node tools/extract-beats.mjs public/bgm/<song>.mp3`
   This overwrites `src/data/beats.ts` with the real tempo/beat grid. Then set
   `beatSync.enabled = true` in `manhwa-panels.ts` and give panels `bars`.
   Until this is run, the shipped placeholder keeps everything compiling with
   audio-reactive effects inert.

### Known gotchas (each of these cost real debugging time — check here first)

- **"No browser found for rendering frames"** even after Remotion downloads
  Chrome Headless Shell: the auto-extract can silently produce only
  ABOUT/LICENSE with no exe. Fix: manually extract
  `node_modules/.remotion/chrome-headless-shell/chrome-headless-shell-win64.zip`
  into `node_modules/.remotion/chrome-headless-shell/win64/` (expect ~125 files
  incl. `chrome-headless-shell.exe`). It is NOT antivirus quarantine.
- **`@remotion/google-fonts` NotoSansJP**: do NOT pass `subsets: ["japanese"]`
  to `loadFont` — it throws "subset not available". Weights only
  (already correct in the bundled `Manhwa.tsx`). Japanese text renders fine.
- **Windows PowerShell 5.1**: no `&&` chaining; wildcard `Remove-Item` on some
  paths is blocked (delete by explicit file path); native stderr lines appear
  as fake `NativeCommandError` noise — not real failures, check exit state.
- **Long/Japanese file paths**: copy media into the project with short ASCII
  names (e.g. `01-intro.mp4`, `bgm/theme.mp3`); use `-LiteralPath` in PowerShell.
- **`extract-beats.mjs` can't spawn npx** on Node 20+/24 (`spawnSync npx.cmd
  EINVAL`). It resolves Remotion's bundled ffmpeg binary directly out of
  `node_modules/@remotion/compositor-*/`; if you port it, keep that, don't
  shell out to `npx remotion ffmpeg`.
- **Bloom must threshold the highlights.** `backdrop-filter: brightness(...)`
  alone lifts the blacks and the whole frame goes milky. Crush the darks first
  (`contrast(2.6)`) so only highlights survive the `screen` blend — measured,
  this is the difference between "graded" and "hazy".
- **Beat detection can pick an octave.** Sanity-check the reported BPM against
  the median inter-onset interval before trusting cut timings; alignment
  percentages must be normalised for grid density (a denser grid catches more
  onsets by chance) or you'll pick double-tempo.

## Usage

All editing happens in one file: `src/data/manhwa-panels.ts`.

1. Put media in `<project>/public/panels/` (stills `.jpg/.png` and/or clips
   `.mp4/.webm/.mov` — clips are auto-detected and played as-is, muted).
2. Put music in `<project>/public/bgm/` and set
   `bgm = { src: "bgm/theme.mp3", volume: 1, fadeOutSeconds: 3 }`.
3. List panels in display order:

```ts
{
  src: "panels/01.jpg",        // or .mp4 (video: motion is ignored, clip plays)
  durationInSeconds: 4,        // for video, match the clip length
  motion: "zoomIn",            // zoomIn|zoomOut|panUp|panDown|panLeft|panRight
  effects: ["twinkle", "shootingStars"],  // optional, see below
  overlays: [                  // optional text in the margin band (not over art)
    { text: "Story: ...\nArt: ...", position: "bottom-center", fontSize: 22 },
  ],
}
```

- **Effects** (deterministic, layered over the art): `twinkle` (starfield),
  `shootingStars`, `sparkles`, `embers` (rise), `petals` (fall).
- **Overlays** sit in the letterbox band with a dark backing box; same-edge
  overlays stack instead of colliding. Positions: `top|bottom` × `left|center|right`.
  Japanese text supported (NotoSansJP loaded). Add `plain: true` for box-less
  dark text (use on light showcase backgrounds).
- **Showcase panels** (cover shots, Kadokawa-LN-ad style): add
  `showcase: { background: "#ffffff", artPosition: "top", artSize: 0.78 }` —
  solid background, drop-shadowed art, credits in the empty space, static
  (Ken Burns is ignored). `artPosition`: `top|left|right|center`. The grade
  auto-damps on these panels so the vignette can't dirty a clean white.
- **Beat sync** — with a beat map present and `beatSync.enabled = true`, give a
  panel `bars: 2` instead of relying on `durationInSeconds`. Cuts then land
  exactly on downbeats (verified to 0.0ms). 2 bars is the teaser default; give
  money shots 3–4. Also set `clipSeconds` on video panels (the clip's true
  length) so the engine retimes playback to fit the bar count instead of
  truncating the camera move.
- **Depth camera — ENVIRONMENT AND WIDE SHOTS ONLY. Never a character
  close-up.** Measured 2026-08-02 on a two-character night scene: displacing a
  mesh by a depth map destroys a face in profile. The profile silhouette *is* a
  depth cliff and the nose/lips/chin sit directly on it, so the mesh spans the
  cliff and drags those features out into the background — they dissolve into a
  smear. Lowering `strength` to 0.18 did not fix it; neither did repairing the
  depth map (morphological closing dilates near-depth across the silhouette and
  makes it worse). This is the same reason a 3D mannequin failed for character
  reference in this ecosystem: **anime faces are cheated 2D**, drawn to read
  from one angle, and giving them relief breaks them. For character shots keep
  the flat Ken Burns path or a gentle pre-baked 2D parallax clip, which smears
  rather than tearing. Use the depth camera on landscapes, architecture,
  interiors, crowds-at-distance — anywhere depth is continuous and no face is
  near a silhouette edge.
- **Depth camera** (`depth` on a still panel) — the 2.5D upgrade. Give it a
  depth map (`tools/make_depth.py` in webcomic-background-mcp; white = near)
  and the still becomes a subdivided mesh displaced along Z with a real
  PerspectiveCamera moving through it: `{ src, move, strength, amount }`,
  `move` = `push|pull|pan|crane|orbit|drift`. Unlike a pre-baked parallax mp4,
  the move is a function of the panel's own progress — **retime the shot to a
  different `bars` count and the camera retimes for free.** Camera distance is
  computed to fit the plane (`objectFit: contain` equivalent), so any aspect
  ratio works. Keep `strength` ≈ 0.2–0.3: it is a relief map, not a model, so
  large values stretch silhouette edges (same caveat as `parallax.py`). Costs
  a WebGL pass per frame — a 35s 1080×1920 render with one depth shot took
  ~6 min.
- **Hand-drawn frames** (`animation` on a panel) — the artist draws a few key
  drawings; the engine handles timing. `{ frames[], mode, holds, startAt, smear }`.
  `mode`: `once` (punch/action, holds the last drawing) · `loop` · `pingpong`
  (sway) · `blink` (mostly frame 0, irregular flicks, occasional double) ·
  `mouth` (speech-rhythm flapping). **`holds` is per-drawing** so one cut can run
  wind-up on threes → contact on ones → recovery on twos, which is what sells
  impact. `smear` adds a directional blur on the frames right after a change —
  it fakes the missing in-between and makes a 3-drawing turn read as fast rather
  than as missing frames.
  ⚠ **Set `FPS = 24` for anything with hand-drawn animation.** At 24, `holds: 2`
  is exactly "on twos" = 12 drawings/sec. At 30fps no integer hold gives 12, so
  you get uneven 3,3,2,2 holds and visible judder.
- **Impact FX** (`impact` on a panel) — sells a hit without any extra drawing,
  which is what anime actually does (it doesn't animate the punch traveling):
  `{ at, speedlines, flash, shake, debris, originX, originY }` plus `*Decay`
  and color options. `at` is seconds from when the panel is **fully visible**.
  Peaks land exactly on `at` (attack = 0) — a one-frame-late flash reads as
  broken. Shake is applied to the foreground only; shaking the backdrop too
  looks cheap.
- **Backdrop** (`backdrop` per panel, or `defaultBackdrop` globally) — replaces
  the blurred self-fill with a designed background: `{ src, color, drift, blur,
  darken, shadow }`. Use for vertical frames where portrait art leaves bands —
  a generated backdrop plus `shadow: true` reads as designed rather than
  letterboxed. `drift` slowly moves it for depth. This is NOT outpainting: the
  art is not extended or blended, so there is no seam or style mismatch.
- **Grade** (`grade` in the config, `null` to disable): `bloom`, `grain`,
  `vignette`, `flash` (white hit on downbeats), `punch` (zoom hit),
  `audioReactive` (bloom rides the loudness envelope), `saturation`, `contrast`.
  Bloom is applied via `backdrop-filter` — the panels are never rendered twice,
  so it costs one pass no matter how many video layers are underneath.
- **Aspect handling**: every panel is shown complete (`contain`) over a blurred
  cover-fill of itself — landscape art gets soft bands above/below
  (YouTube-Shorts style), nothing is cropped.
- **Tall webtoon pages**: use `motion: "panDown"` for the scroll-the-page effect.

### Commands (run in the project directory)

- Preview: `npm start` → open the `Manhwa` composition
- Render: `npx remotion render src/index.ts Manhwa out/video.mp4`
- Spot-check a frame: `npx remotion still src/index.ts Manhwa out/f.png --frame=N`

## Optional: local image-to-video (LTX-2.5)

This skill assembles video from art you already have; it does not generate
motion. If a shot needs to actually move, **`ltx-setup.md`** covers running
LTX-2.5 locally in ComfyUI (no subscription), and **`assets/tools/ltx_run.py`**
is a working driver: it sizes the shot from the artwork, builds the graph,
submits it, and writes the 24 fps take plus a 12 fps preview to judge.

```
python assets/tools/ltx_run.py --image panel.png --out takes --len 49 --seed 1 \
    --prompt "The camera holds locked off. ... (motion only) ... X and Y stay still."
```

**Verified on a 6 GB RTX 3060 Laptop with 32 GB RAM** — ~3.5 min a 49-frame
take, ~7 min a 97 — on an eight-scene teaser of hand-drawn panels. LTX-2.3 was
used here until 2026-10-22; 2.5 was judged much better on the same panels.

**Match the ARTWORK'S OWN ASPECT, and size from the art, not from a default.**
The model silently resizes the input to whatever you ask for — there is no
letterboxing — so one fixed "good default" stretches every panel of a different
shape. `ltx_run.py` picks ~2 MP at the art's own aspect, both sides divisible by
64. Do NOT pad the input with bars; letterbox at ASSEMBLY, on a finished clip.

⚠ **24 fps and 49 or 97 frames — never 17.** At 17 frames 2.5 has only three
latent frames: every take sat still to frame 8, lurched at frame 9, and tore
faces on full-body action. (17 was the right length for 2.3, which smeared and
grew extra limbs on longer clips. The two models want opposite things.)

⚠ **Resolution is the lever for hands.** At 832x576 a hand is ~40 px, which
after the VAE's 8x compression is **~5 latent pixels** — not enough to draw
fingers, so any hand that MOVES becomes mush. On one 15-panel scene that cost
**65 hand-redrawn frames** (on 2.3).

### Two curves cross: resolution vs. prompt

Measured on 2.3, one hand-raise panel, same seed, three prompt styles:

| | 1 sentence | 5-8 sentences |
|---|---|---|
| **1.0 MP** | fingers fused | a defect in every style tried |
| **2.2 MP** | perfect anatomy, but **wandered off the prompt** — a spell-cast became the character styling his hair | **clean** |

Spare resolution is spare freedom, and a one-sentence prompt does not constrain
it. So the two move TOGETHER: aim high on resolution and write 4-8 sentences.

**For image-to-video the prompt is MOTION ONLY** — do not redescribe wardrobe,
setting or style, the drawing already fixes them. Name the camera first, lead
with the largest motion (it gets the motion budget), and end by saying WHAT
STAYS STILL. Positive phrasing throughout — negatives are ignored.

### What 2.5 still gets wrong, and the wording that fixed it

- **Blinks.** "Blinks", "blinks twice quickly", "blinks once" — eyes closed and
  stayed closed, three seeds each. **"Her eyes close, then open wide, then close
  again"**, no word "blink", gave a real blink on one seed in three. A figure
  lying down at night reads to the model as falling asleep.
- **Unasked head turns.** A head drawn in profile turned to the camera, and a
  scroll's string beside the face merged into a second pair of glasses stuck to
  it. **"He keeps his head turned to the side in profile"** stopped both.
- **Camera moves** despite "locked off" on one seed; **"the framing stays
  exactly the same from start to end"** held it.
- **New geometry.** Asked to grow ice, it raised the hand ~3% and grew almost
  nothing. ⚠ **An unusually LOW motion score means it DECLINED**, not that the
  motion is subtle.
- **A clip that runs too far** (a head lowering until he seems to fall) is a
  trim: cut the last 0.5-1 s rather than re-rolling.

Run ~3 seeds per shot and judge the 12 fps preview by eye — seeds differ a lot.
For an action no seed will do, the MCP server's `animate_shot_cloud` (Seedance
2.0, paid per take) is the fallback.

### Is LTX worth it for this shot?

The same 15-panel scene, run twice. **v1** at 832x576 with one-sentence prompts:
**65 frames redrawn by hand**, against ~45-75 drawings for the whole scene
traditionally — so it cost MORE than drawing it, and each repair was harder than
a fresh drawing. **v2**, per-panel sizing and 5-sentence motion-only prompts,
nothing else changed: **6 frames redrawn, 6 trimmed, no panel truncated.**

So it is worth it — but only with both levers set, and only for shots LTX can
actually do (see the table below). Two caveats that survive v2: the seed hunt is
load-bearing (3 seeds a panel, several rejected for tail smears — the count is
for SELECTED takes), and **a contact sheet will not catch a bad hand that is
small in frame.** v2's only redraws were a sword grip that read fine as stills
and was obviously broken on playback at full size. Review motion, not just
frames.

### The rule that decides whether a shot will work at all

> **LTX RELOCATES what exists. It cannot RE-IMAGINE it.**

Everything below follows from that one line:

| works | fails |
|---|---|
| Arm swings, head turns, a fist moving down | **Blinks** — the eyelid was never drawn |
| Hair, cloth, drifting snow, rotating runes | **Mouth shapes** — teeth/tongue don't exist |
| **Fire** — existing pixels churning | **Growing crystals** — new geometry |
| Camera drift | **Foreshortening** — a punch toward the viewer needs knuckles redrawn at a new angle |

(Measured on 2.3. 2.5 moved the line: it threw a punch toward the viewer, made
two people talk, and blinked on one seed in three. Growing ice still failed.)

- **Ask for the LARGEST motion that reads, and put it FIRST in the prompt.** The
  leading request gets the motion budget. "Blinks slowly" froze on 4 seeds;
  the same shot with "turns her head gently" moved — and the eyes closed *along
  with it*. Feature-scale motion only ever arrives as a passenger.
- **Then run ~3 seeds and keep the best — roughly 1 in 3 lands.** Seed variance
  is real, but ONLY when the request is achievable; an impossible ask freezes on
  every seed, so re-rolling it is wasted time. Change the WORDING first: on 2.5
  a blink failed on every seed as "blink" and landed once the prompt described
  the eyes closing and opening instead.
- **Seeds do NOT transfer across configs.** Changing `--len` or the prompt
  reshuffles everything. Re-hunt after any parameter change.
- **Two seeds can be MERGED.** All takes share frame 0, so they start aligned:
  composite region B from seed Y over seed X through a feathered mask. One take
  moved the scrolls, another the quill — the final shot used both.
- **Never render below 540p** — fine linework mushes before any upscale can
  recover it.
- Style survives well: cel shading, linework and color hold, with no drift
  toward photoreal.

### Judging the result — the part that goes wrong

- **Judge the 12 fps preview.** `ltx_run.py` writes it beside the 24 fps take:
  every other frame, so motion plays at true speed on twos.
- **`measure_motion.py --box` and then LOOK.** The number measures *change*, not
  quality — a clip whose faces dissolve scores very high. Crop the moving part
  at native resolution and check it.
- **Compare the SAME region across runs, never different regions.** Mean-abs-diff
  scales with local contrast, so a dark background and high-contrast linework
  give different numbers under identical drift.
- **Use an unmoved region as a control.** If the arm scores 17 and the face
  scores 2, that's real localized motion. If both move, it's global drift.
- **On art with frame-wide animated FX** (glowing text, sparkles) the metric is
  meaningless — those inflate every box they touch. Judge by watching.
- ⚠ **WHEN THE NUMBERS DISAGREE WITH THE ARTIST'S EYE, THE EYE WINS.** Not a
  platitude — the measured record. The motion score ranked the only acceptable
  take LAST in a config comparison, because that take had the most motion.
  Edge-energy artifact scanning separately missed a face melting inside hair
  (hair edges mask the change), a sword vanishing (outside the face box), eyes
  disappearing (0.2% of the frame), and reported failure at frame 3 on a take
  whose real damage was frames 12-17. Treat every score as a **sort order for
  what to look at**, never a verdict. The one exception is above: an unusually
  LOW score really does mean the model refused.
- **Color drift is invisible to edge-energy scanning.** A character's eyes
  changed from blue to gray over the last five frames of a take and no scan saw
  it — edge energy barely moves when an iris desaturates. Only the artist caught
  it. Look at color separately from structure.

### What LTX can't do, and what does it instead

- **Blinks / mouth shapes** → `klein_edit.py` (FLUX 3 Klein) generates the
  keyframe, then composite ONLY the eye or mouth patch back over the original.
  Klein redraws the WHOLE frame even for a boxed edit — 18.5 of mean change
  outside the box, measured — so never ship its full frame. With `--box` the
  script pastes back only the box; for a blink, run it without one and take
  just the eye interiors with `pipeline.framing.composite_patch(ellipses=...)`.
  Whether Klein can draw a half-lid is untested; blending the open and closed
  composites always gives the mid positions.
- ⚠ **NO MACHINE REPAIR OF AN LTX HAND HAS EVER SHIPPED. Plan to draw them.**
  Every repaired hand in the test scene's final cut was finished by the
  artist's hand: one over a Kontext base, the rest drawn outright.
  - **Klein**, 2026-10-17, on a sword hand LTX had blurred to a smudge
    (1920x1088, `--box` around the hand, three seeds): **0 usable** by the
    artist's eye. The closest had a bad thumb; one splayed its fingers; two
    redesigned the hilt. Klein's crisp inking also **stands out against soft
    LTX frames**, which flickers across a 12 fps sequence. (Confound: that
    instruction asked for "crisp black outlines". Leave line words out.)
    ~97 s a seed on the 6 GB card, and exactly zero change outside the box.
  - **FLUX.1 Kontext**, retired 2026-10-17, did no better. At Q6_K its best
    takes were "usable as a base" — the artist still drew on every one. At
    Q3_K_S, one take in 18 was good enough to draw over.
  - So a repair pass is worth running only as a BASE for the artist, and only
    while there are other frames to work on in the meantime. Never count a
    take that still needs drawing as a repair.
  - ⚠ **A box sets SIZE as well as place** — a hand asked to fill a 220x166
    box came back 220x166 and swollen. Fit the box to the hand.
- ⚠ **Klein lives on its OWN ComfyUI (v0.41, port 8189), LTX on the main one
  (port 8188). NEVER RUN BOTH AT ONCE.** With two ComfyUIs neither queue sees
  the other's job, so nothing stops both models landing on a small card
  together. One edit submitted during an LTX batch once thrashed until it hung
  and cost five hours. `klein_edit.py` and the server both refuse to start
  while the other side is busy.
- **Before concluding a model "can't do" something, check its bit depth.**
  The lesson FLUX.1 left behind: the same Q3_K_S → Q6_K swap changed Kontext's
  raw repairs visibly and ordinary generation not at all. Quantization error
  shows where the task is hard. And **VRAM was never the reason to quantize
  low** — ComfyUI streams weights from system RAM, and this 6 GB card runs a
  14.2 GB LTX model routinely.
- ⚠ **MASKED INPAINTING HAS STILL NEVER BEEN TRIED** — every edit so far,
  Kontext and Klein alike, handed the model the whole frame. For "this region
  is destroyed", inpainting is the textbook technique: mask the hand and
  generate into the hole with the surrounding arm as context.
- **Anything that must APPEAR** (growing ice, shooting stars, speed lines) →
  draw it. Deterministic, retimeable onto musical beats, and it can't smear a
  face. `impact_preview.py` previews the speed-line/flash/shake kit.
- **Negative instructions are ignored by BOTH models.** "Do not close her eyes"
  closed them; "without turning" turned. Phrase every request positively.

Setup gotchas: LTX-2.5 needs **ComfyUI v0.32+**; its text encoder must be
Lightricks' own Gemma 4 file (a stock Gemma 4 is refused); and ComfyUI caches
model listings at startup, so restart it after adding files. See `ltx-setup.md`.

## Landscape MV — the Python path

Assembles a 16:9 video in Pillow and pipes frames to ffmpeg. No Node, no
Remotion. This is the path that produced the reference 1:47 teaser.

Available two ways, same code either way:

- **`anime-production-mcp`** — a sibling server in this repo. 20 tools, a shot
  library with per-name approval and `FINAL_` publishing, and the seed hunt as
  one call. Use this unless there is a reason not to.
- **`assets/tools/pipeline/`** — the same modules as an importable package
  (`motion`, `effects`, `framing`, `assemble`, `subs`), for driving it directly
  without the server. They use relative imports, so keep the folder intact and
  import it as a package. The GPU-driving half (LTX, Klein) is not duplicated
  here — use `assets/tools/ltx_run.py` and `klein_edit.py`, or the server.

### Shape of a run

1. **Animate each shot** — `animate_shot` runs ~3 seeds, retimes each to 12 fps,
   scores the motion, records them. Judge, then `approve_shot`.
   Anything LTX can't do goes to `edit_frame`+`composite_patch` (eyes, mouths)
   or a drawn effect (things that must APPEAR).
2. **Frame portrait shots** — `frame_clip` drops each clip into a hand-drawn
   frame's transparent slot, centered in 1920×1080. Portrait art is only ~720px
   wide at full height in 16:9; the frame fills the rest with the artist's own
   work rather than blur or black. Landscape shots skip this — `extract_bars`
   keys the frame's rules out and flanks the wide image with them, so every
   panel shares one visual language.
   ⚠ **The alpha bounding box is NOT the slot.** Decoration drawn on
   transparency makes the gaps between leaves count, so the bbox comes out far
   too wide (1180px against a true 802px on the reference frame) and leaves a
   colored line along one edge of every panel. `measure_frame_slot` measures
   the columns clear for the FULL height.
3. **Assemble** — `assemble_video` with a beat grid from `music-generation-mcp`.

### Scene kinds — this is most of the edit

The problem: a 1.4 s clip inside a 9.6 s panel leaves 8 s of dead air, and
putting the motion first means every panel DECAYS into stillness. So each shot
declares what kind of motion it has, and the kind decides the timing.

| kind | timing | for |
|---|---|---|
| `loop` | whole panel | ambient with no natural end — drifting cloth, an argument, falling snow |
| `pong` | whole panel, forward-then-back | oscillatory motion; no jump at the turnaround |
| `once` | **exactly its clip** | an event that can't repeat |
| `hold` | clip, then freezes on the last frame | play the motion, then rest |

**`once` gets no static hold, deliberately.** Holding a still frame *before* an
event reads, to a viewer who doesn't know one is coming, as the video having
frozen — genuinely, as "has it buffered?". Cut the stationary time and hand it
to the end card. **`hold` works for the opposite reason**: the stillness comes
*after* the motion, so the viewer has just watched something happen and
lingering there reads as a beat, not a bug.

Ping-pong a one-way event and you literally un-grow the ice. Loop a shot where a
character lowers her head and she does it on a cycle, which looks broken.

### The end card

A card that holds for a minute is most of the video, and a still image that long
reads as the file having ended. `build_card` animates the frame's own decoration
(each leaf on its own phase), pushes each image slightly, and pulses warm
lettering. Text staggers in ~1.1 s apart — at 6.8 s spacing the last credit line
did not appear until 41 s in.

### Subtitles

One cue list drives both the burned-in captions and the `.srt`, so they cannot
drift apart. Timings must be called against the vocal BY EAR — beat detection
cannot supply them, because a downbeat says where the bar is, not where a sung
line starts.

Captions get a blurred glow, a dark stroke and near-white fill, because panels
are full-bleed and background brightness changes shot to shot: dark text
disappears on a night sky, light text on a white mat.

⚠ **Burned in OR sidecar, rarely both** — players that default captions on will
draw a second copy over the first.

⚠ Keep the block ~68px off the bottom. YouTube's control bar covers roughly the
last 60px whenever the viewer moves the mouse.

## Production guidance

- **Panel curation**: teaser = ~8–15 strongest beats, ~4s each, end on
  cover/CTA with credits. A 60s Short cannot hold a full chapter.
- **Motion clips**: prefer the **local LTX path above** — no subscription, no
  watermark, ~65 s a take. Paid services (Kling/Hailuo) remain an option via the
  user's own account, but are no longer necessary; their free tiers watermark
  output, while this pipeline adds none. Animate only 1–3 hero panels and let
  Ken Burns carry the rest — that is a pacing choice as much as a cost one.
- **A punch does not need the arm to travel.** Anime sells the moment of
  contact, not the trajectory: speed lines, flash, camera shake and a held
  drawing read as an impact. `Impact.tsx` does this, and it is why a paid
  image-to-video service is not required for action beats.
- **Music**: this pipeline plays an mp3; it does not generate music. AI music
  (e.g. Suno) is generated by the user in their own account — the usage license
  attaches at generation time (free tier = non-commercial).
- **Scope of tools named by the original skill**: NanoBanana Pro (image gen) is
  NOT required — this skill animates existing art. VOICEVOX (Japanese TTS) is
  only relevant for a Japanese voiced dub via the baseline template's own
  pipeline; it cannot speak English and cannot sing.

## Provenance

- Slideshow engine (`Manhwa.tsx`, `Effects.tsx`, `manhwa-panels.ts`):
  built by Claude Code for Tanaka Tomoyuki's webcomic/anime production
  ecosystem (https://tobiasfong.github.io/) — companion to the
  webcomic-background-generator MCP (whose depth-parallax mp4s drop straight
  in as video panels).
- Baseline project: nyanko3141592/remotion-voicevox-template (MIT).
- Original skill listing: https://mcpmarket.com/tools/skills/anime-production
  (metadata only; this package replaces its missing reference content).
