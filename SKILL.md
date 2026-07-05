---
name: anime-production
description: アニメ動画・アニメMV・漫画/マンファ ティーザー動画の制作スキル。Anime/manhwa video production - turns finished illustrations or comic pages into vertical (9:16) YouTube Shorts-style videos with Ken Burns motion, crossfades, particle effects, credits text, and BGM, via a self-contained Remotion pipeline. Use when: (1) user says「アニメを作って」「アニメ動画」「アニメMV」or "make an anime video / teaser / manhwa short", (2) user wants a slideshow MV of their own artwork with music, (3) user mentions「キャラクターアニメーション」「アニメ制作」or animating comic panels. Do NOT use for: 実写動画、静止画像のみの生成 (this skill animates EXISTING art; it does not generate images).
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

Target state: a Remotion project with this skill's three source files installed.
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
   - `assets/Manhwa.tsx`       → `<project>/src/Manhwa.tsx`
   - `assets/Effects.tsx`      → `<project>/src/effects/Effects.tsx`

4. **Register the composition** in `<project>/src/Root.tsx`:
   ```tsx
   import { Manhwa, MANHWA_DURATION } from "./Manhwa";
   import { FPS as MANHWA_FPS, WIDTH as MANHWA_WIDTH, HEIGHT as MANHWA_HEIGHT } from "./data/manhwa-panels";
   // inside <>...</>:
   <Composition id="Manhwa" component={Manhwa} durationInFrames={MANHWA_DURATION}
     fps={MANHWA_FPS} width={MANHWA_WIDTH} height={MANHWA_HEIGHT} />
   ```

5. **Verify**: `npx remotion compositions src/index.ts` should list `Manhwa`.

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
  (Ken Burns is ignored). `artPosition`: `top|left|right|center`.
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
