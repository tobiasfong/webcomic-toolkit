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
  which is what anime actually does (it doesn't animate the punch travelling):
  `{ at, speedlines, flash, shake, debris, originX, originY }` plus `*Decay`
  and colour options. `at` is seconds from when the panel is **fully visible**.
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

## Optional: local image-to-video (LTX-2.3)

This skill assembles video from art you already have; it does not generate
motion. If a shot needs to actually move, **`ltx-setup.md`** covers running
LTX-2.3 locally in ComfyUI (no subscription), and **`assets/tools/ltx_run.py`**
is a working driver — it builds the ComfyUI API graph, submits it and polls.
Clips come back as ordinary video panels.

**Verified on a 6 GB RTX 3060 Laptop.** Settled recipe — start here, don't tune:

```
--variant distilled --len 17 --strength 0.9 --fps 48   # ~65 s per take
```

`distilled` at len 17 is ~5x faster than `dev` at len 25 **with no motion
penalty** (measured: distilled out-moved dev on the same shot). That speed is
what makes the workflow below affordable.

### The rule that decides whether a shot will work at all

> **LTX RELOCATES what exists. It cannot RE-IMAGINE it.**

Everything below follows from that one line:

| works | fails |
|---|---|
| Arm swings, head turns, a fist moving down | **Blinks** — the eyelid was never drawn |
| Hair, cloth, drifting snow, rotating runes | **Mouth shapes** — teeth/tongue don't exist |
| **Fire** — existing pixels churning | **Growing crystals** — new geometry |
| Camera drift | **Foreshortening** — a punch toward the viewer needs knuckles redrawn at a new angle |

- **Ask for the LARGEST motion that reads, and put it FIRST in the prompt.** The
  leading request gets the motion budget. "Blinks slowly" froze on 4 seeds;
  the same shot with "turns her head gently" moved — and the eyes closed *along
  with it*. Feature-scale motion only ever arrives as a passenger.
- **Then run ~3 seeds and keep the best — roughly 1 in 3 lands.** Seed variance
  is real, but ONLY when the request is achievable; an impossible ask freezes on
  every seed, so re-rolling a blink is wasted time.
- **Seeds do NOT transfer across configs.** Changing `--len` or `--variant`
  reshuffles everything — a seed that moved at len 25 can freeze at len 17.
  Re-hunt after any parameter change.
- **Two seeds can be MERGED.** All takes share frame 0, so they start aligned:
  composite region B from seed Y over seed X through a feathered mask. One take
  moved the scrolls, another the quill — the final shot used both.
- **Never render below 540p** — fine linework mushes before any upscale can
  recover it.
- Style survives well: cel shading, linework and colour hold, with no drift
  toward photoreal.

### Judging the result — the part that goes wrong

- **`retime.py` FIRST.** `ltx_run.py` writes at 24 fps, so a 17-frame clip plays
  in **0.7 s** and reads as "nothing happened" even when the motion is fine.
  Always retime to 12 fps before looking.
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

### What LTX can't do, and what does it instead

- **Blinks / mouth shapes** → `kontext_edit.py` generates the keyframe, then
  composite ONLY the eye or mouth patch back over the original. Kontext
  regenerates the whole frame and will quietly restyle hair or colour, so never
  ship its output wholesale. It is also **binary** — it cannot do a half-lid, so
  blend the open and closed composites for mid positions.
- **Anything that must APPEAR** (growing ice, shooting stars, speed lines) →
  draw it. Deterministic, retimeable onto musical beats, and it can't smear a
  face. `impact_preview.py` previews the speed-line/flash/shake kit.
- **Negative instructions are ignored by BOTH models.** "Do not close her eyes"
  closed them; "without turning" turned. Phrase every request positively.

The gotcha that wastes the most time: **a GGUF text encoder will not load via
ComfyUI's core `LTXAVTextEncoderLoader`** (it reads `models/checkpoints/`, and
`.gguf` is not in ComfyUI's supported extensions). Use city96's
`DualCLIPLoaderGGUF(..., type="ltxv")` with the encoder in `models/text_encoders/`.
Also: connector and VAE must match the checkpoint's variant *and* generation, or
you get silent garbage; and ComfyUI caches model listings at startup, so restart
after adding files.

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
  import it as a package. The GPU-driving half (LTX, Kontext) is not duplicated
  here — use `assets/tools/ltx_run.py` and `kontext_edit.py`, or the server.

### Shape of a run

1. **Animate each shot** — `animate_shot` runs ~3 seeds, retimes each to 12 fps,
   scores the motion, records them. Judge, then `approve_shot`.
   Anything LTX can't do goes to `edit_frame`+`composite_patch` (eyes, mouths)
   or a drawn effect (things that must APPEAR).
2. **Frame portrait shots** — `frame_clip` drops each clip into a hand-drawn
   frame's transparent slot, centred in 1920×1080. Portrait art is only ~720px
   wide at full height in 16:9; the frame fills the rest with the artist's own
   work rather than blur or black. Landscape shots skip this — `extract_bars`
   keys the frame's rules out and flanks the wide image with them, so every
   panel shares one visual language.
   ⚠ **The alpha bounding box is NOT the slot.** Decoration drawn on
   transparency makes the gaps between leaves count, so the bbox comes out far
   too wide (1180px against a true 802px on the reference frame) and leaves a
   coloured line along one edge of every panel. `measure_frame_slot` measures
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
