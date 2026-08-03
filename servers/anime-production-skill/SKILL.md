---
name: anime-production
description: アニメ動画・アニメ広告・アニメMV・漫画/マンファ ティーザー動画の制作スキル。Anime/manhwa video production & marketing - turns finished illustrations or comic pages into vertical (9:16) YouTube Shorts-style teaser/ad/MV videos with Ken Burns motion, crossfades, particle effects, credits text, and BGM, via a self-contained Remotion pipeline. Use when: (1) user says「アニメを作って」「アニメ動画」「アニメ広告」「アニメMV」or "make an anime video / teaser / ad / marketing video / manhwa short", (2) user wants a slideshow MV of their own artwork with music, (3) user mentions「キャラクターアニメーション」「アニメ制作」or animating/promoting comic panels. Do NOT use for: 実写動画、静止画像のみの生成 (this skill animates EXISTING art; it does not generate images).
user-invocable: true
---

# アニメ制作スキル / Anime Production Skill

Turns a folder of finished illustrations (and/or short video clips) into a
vertical 1080×1920 anime-style teaser/MV: per-panel camera motion, crossfades,
blurred-fit framing for any aspect ratio, ambient particle effects, credits
text in the margin bands, and a music track with fade-out.

**This skill is self-contained.** Everything needed ships in `assets/`.
Do NOT hunt for `taiyou-taiyo/...` reference content (a private path from this
skill's original author — it does not exist publicly). Do NOT assume
NanoBanana Pro / VOICEVOX are required (see "Scope of tools" below).

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

## Production guidance

- **Panel curation**: teaser = ~8–15 strongest beats, ~4s each, end on
  cover/CTA with credits. A 60s Short cannot hold a full chapter.
- **Motion clips**: for "living illustration" panels, generate image-to-video
  clips externally (Kling/Hailuo etc. — user's own account) and drop them in as
  video panels. Free tiers watermark their output; the Remotion pipeline itself
  adds no watermark. Animate only 1–3 hero panels; Ken Burns covers the rest.
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
