# anime-production-mcp

Turn finished illustrations into an animated video cut to music — entirely
locally, no subscription, no watermark.

Companion to [`music-generation-mcp`](../music-generation-mcp): that server makes
the track and its beat grid, this one animates the artwork and cuts to it.

Verified on a 6 GB RTX 3060 Laptop.

---

## The rule that decides whether a shot will work at all

> **LTX relocates what EXISTS. It cannot RE-IMAGINE it.**

| works | fails |
|---|---|
| Arm swings, head turns, a fist moving down | **Blinks** — the eyelid was never drawn |
| Hair, cloth, drifting snow, rotating runes | **Mouth shapes** — teeth and tongue don't exist |
| **Fire** — existing pixels churning | **Growing crystals** — new geometry |
| Camera drift | **Foreshortening** — a punch toward the viewer needs knuckles redrawn at a new angle |

Everything about this server follows from that line, and choosing the wrong tool
is what wastes GPU-hours:

- Left column → `animate_shot`
- Eye- and mouth-scale features → `edit_frame` + `composite_patch`
- Anything that must **appear** → the drawn effects (`add_streaks`, `grow_layer`,
  `add_water`, `add_impact`)

Re-rolling seeds on an impossible ask never works. Seed variance is real *only*
when the request is achievable.

## The second rule: resolution, and the two curves that cross

**Do not pick a size by hand.** `animate_shot` derives it from the artwork via
`lw.pick_size`, which matches the source's own aspect and aims at ~2.2 MP.
`LTXVImgToVideo` silently resizes the input to whatever it is given — no
letterboxing, no warning — so a hardcoded default stretches every panel of a
different shape, and a vertical panel comes out crushed into landscape.

And do NOT pad the input to reach a target aspect. Bars eat the pixel budget,
and LTX has no concept of a border, so it drifts and bleeds into them. Letterbox
at ASSEMBLY, on a finished clip, where nothing can smear into it.

### The measurement that set the target

One panel (a hand-raise that needed 15 repaired frames in v1), same seed, same
one-sentence prompt, three sizes, reviewed frame by frame:

| size | anatomy | prompt fidelity |
|---|---|---|
| 0.50 MP `864x576` | f10-12 fingers **fused**, hand deformed, face warped | on prompt |
| 1.01 MP `1216x832` | f7-8 fingers slightly fused — "just need to draw a line" | on prompt |
| 2.18 MP `1792x1216` | **perfect, zero defects** | **wandered off** — a spell-cast became the character styling his hair |

Two curves cross, which is why "bigger is better" fails as a rule:

- **Anatomy improves monotonically with resolution.** Too few latent pixels and
  the model cannot render what it is moving. Settled.
- **Prompt fidelity degrades with it.** Spare capacity is spare freedom, and a
  one-sentence prompt doesn't constrain it, so the model invents motion.

~1 MP is where they cross **for a short prompt** — and that clause matters,
because upstream guidance is 4-8 descriptive sentences and the wandering at
2.18 MP is exactly what a longer prompt should suppress. If prompts get longer,
re-measure; the target may move up. Pinning the last frame with `LTXVAddGuide`
is the other candidate fix, and is untested.

### The old default, for the record

`832x576` was this server's default for two days because it was fast. That is
the single most expensive mistake in its history: on one 15-panel scene it cost
**65 hand-repaired frames**, and the seven panels that came back clean were the
ones that barely moved.

At 832x576 a hand occupies ~40 px, which after the VAE's 8x compression is ~5
latent pixels — not enough to draw fingers. Any hand that **moves** turns to
mush. That is a resolution problem, not a seed problem, and no amount of
re-rolling fixes it.

| knob | recommended | this project's default | verdict |
|---|---|---|---|
| resolution | 1280x720 minimum, 1080p+ better | now per-panel via `pick_size` | **fixed** |
| prompt | 4–8 descriptive sentences | now 5, motion-only | **fixed** |
| frames | 121, 257 | 17 (the 8n+1 floor) | tested and rejected — see below |
| steps | 8 on `distilled` | 8 | correct all along |
| motion density | fewer, readable beats | now one beat per panel | **fixed** |

**And resolution is nearly free.** A ceiling sweep on the 6 GB card found **no
out-of-memory point at all**, with steady-state cost of ~90-140 s a take across
the entire range once the model is resident. The first take of a session pays
the model load and reads much slower — never benchmark on it. The low default
bought speed that was immediately spent on repairs.

⚠ **The negative prompt does nothing on `distilled`.** It runs at cfg 1.0, and
classifier-free guidance discards the negative branch entirely at cfg 1.0.
Verified: full negative vs. empty string gave **pixel-identical** output (mean
absolute difference 0.000, against ~67 between two seeds). Do not tune it —
raise the resolution instead. It applies only on `dev`, at cfg 3.0.

### Verified by eye, not by metric (2026-08-09 ceiling sweep)

| config | artist's verdict |
|---|---|
| 1216x832 len17 | **usable** |
| 1408x800 len17 | six fingers throughout; hand deforms in the last 2 frames |
| 1920x1088 len17 | **good, no problems** |
| 1216x832 len25 | smears and *missing* fingers; mostly okay |
| 1216x832 len33 | frames 12-17 bad (smears, extra fingers, deformed hands) — **every other frame fine, including the tail** |

### Length is its own failure mode — resolution does not fix it

Re-run at 1920x1088, same seed and prompt, changing only length. The hypothesis
was that the length defects were really resolution defects. **They were not.**
At 1216x832 the len-33 bad window was frames 12-17; at 1920x1088 it was frames
11-13. Same place, more pixels.

| length | bad frames (artist's eye) | usable after a cut | duration | cost |
|---|---|---|---|---|
| 17 | none | 17 | 1.4 s | 141 s |
| 25 | 18-19 — smears | 23 | 1.9 s | 199 s |
| 33 | 11-13 — a finger vanishes | 30 | 2.5 s | 229 s |
| 49 | **all of them** — an extra arm, present from frame 0 | 0 | — | 446 s |

Two things to take from this:

**Defects scale with length: 0, 2, 3 bad frames at 17/25/33, then structural.**

Cutting the bad window back out does NOT rescue these takes, and it is worth
being precise about why, because "only 3 bad frames out of 33" sounds cheap:

| take | drop | kept | seam vs. the clip's own median motion |
|---|---|---|---|
| len 25 | 18-19 | 23 | **3.6x** — marginal |
| len 33 | 11-13 | 30 | **5.2x** — reads as a skip |

The len-33 shot is slow: its typical frame-to-frame change is 2.33, so removing
three frames leaves a jump five times larger than any real motion in it. A cut
is only invisible when the motion under it is slow relative to the cut — and a
slow clip is exactly where a cut shows most. **Longer takes were wanted for
CONTINUITY, and a cut is precisely what spends continuity.** Length 17 clean
beats length 33 with a pop in it.

⚠ THE SEAM RATIOS ABOVE OVERSTATE THE PROBLEM, and the threshold behind them
was invented rather than measured. The ratio divides by the clip's own median,
so it punishes slow clips: len-33's seam had a SMALLER absolute jump (12.0) than
len-25's (18.6) yet scored worse. In practice **dropping 2-3 frames mid-clip is
fine** — 0.17-0.25 s at 12 fps reads as a faster action, and limited animation
runs on twos and threes. `cut_frames` keys its verdict off the number of frames
dropped for that reason, and reports both `jump` and `ratio` so neither number
stands alone. What sinks long takes is not the cut; it is that a longer take was
wanted for CONTINUITY in the first place.

**Length 49 fails STRUCTURALLY, not by drift.** An extra limb present in frame 0
is a broken composition, not accumulated error, and no cut recovers it.

⚠ CAVEAT ON THE LENGTH NUMBERS: this sweep used `EmptyLTXVLatentVideo` — it is
**text-to-video**, with no source illustration. `animate_shot` is image-to-video,
where frame 0 is the artist's drawing. The len-49 extra arm in particular is a
t2v failure that i2v conditioning would likely prevent. The resolution findings
transfer (latent-pixels-per-hand is the same arithmetic); the long-length
findings need one i2v confirmation on real art before being trusted.

Two rules die here:

⚠ **"The tail degrades" is a length-17 observation, not a law.** At len 33 the
damage sat in the MIDDLE — frames 12-17 — and the clip RECOVERED after it. Do
not blind-truncate long takes; find the bad window and cut that.

⚠ **Height may need to be divisible by 64, not 32.** `validate()` enforces 32.
1408x800 is the only size tested whose height fails 64 (800/64 = 12.5) and the
only one with extra fingers. The VAE compresses 8x and the transformer
patchifies 2x2 on top, so 64 is a plausible true alignment unit and a
half-patch would smear precisely at fine detail. UNCONFIRMED — one take at
1408x832 settles it. Until then, prefer heights divisible by 64: 704, 832, 896,
1088.

### The v2 result — the same scene, both levers fixed

The 15-panel scene that cost 65 hand-redrawn frames was rerun with per-panel
sizing and 5-sentence i2v prompts, everything else held constant (distilled,
length 17, strength 0.9, 3 seeds a panel, same artwork, same artist reviewing
every frame):

| | v1 | v2 |
|---|---|---|
| frames redrawn by hand | **65** | **0** |
| frames trimmed | — | 1 |
| panels truncated for damage | 13 of 14 | 0 |
| resolution | 864x576 for everything | per-panel, 1.12–2.18 MP |
| prompt | 1 sentence | 5 sentences, i2v style |

v1 needed a `TRUNCATE` table with an entry for almost every panel because almost
every panel fell apart before its end. v2's is one frame.

Three things that only showed up at scene scale:

- **The pixel target is softer than one panel suggested.** Panels landed
  anywhere from 1.12 to 2.18 MP — aspect and the 2x upscale cap decide, not
  preference — and all were usable. p02 was clean at 1.12 MP where p08 failed at
  1.01 MP, because p02 is a calm shot of a hand GRIPPING a hilt and p08 is an
  OPEN hand raising. Grips and small motions survive ~1 MP; open hands, fast
  motion and close faces want 2 MP+.
- **LTX declines rather than smears.** Asked for a fast kick it scored
  3.6/5.8/8.2 against a scene typical of 11–48 and simply did not move the leg.
  The same panel asked to "raise her leg a little higher" worked first try. An
  unusually LOW score is the one signal that reliably means trouble.
- **More motion is not better motion.** On the last panel the artist chose the
  take scoring 7.9 over one scoring 14.8. Never pick by score.

### When LTX is worth it at all

The v1 accounting was damning: traditional limited animation would have been
45–75 drawings for that scene, each a cheap lasso-and-rotate, so 65 repairs on
top of generation was *more* work than drawing it — and each repair was harder
than a fresh drawing.

**v2 reverses that**, at 0 redrawn frames and one trim, for ~3 GPU-hours
unattended. What made the difference was not the model; it was giving it enough
pixels and a real prompt.

Two things still true. **Shot selection still decides everything** — the works
/fails table above has not moved, and asking for a motion LTX cannot do wastes
GPU no matter the resolution. And **the seed hunt is load-bearing**: v2 ran 3
seeds a panel and the artist rejected several for tail smears. The zero is the
count for *selected* takes, not for all takes.

## Working notes that cost real time to learn

- **Ask for the largest motion that reads, and put it FIRST.** The leading
  request gets the motion budget. "Blinks slowly" froze on four seeds; the same
  shot asked to "turn her head gently" moved — and the eyes closed along with it.
  Feature-scale motion only ever arrives as a passenger.
- **Negative instructions are ignored by both models.** "Do not close her eyes"
  closed them; "without turning" turned. Phrase everything positively.
- **Seeds do not transfer across configs.** Change `length` or `variant` and the
  space reshuffles. Re-hunt after any parameter change.
- **Retime before judging.** ComfyUI writes at 24 fps, so a 17-frame take plays
  in 0.7 s and reads as "nothing happened". `animate_shot` does this for you.
- **The motion score is not quality, and it is wrong more often than it looks.**
  It measures *change*. A take whose faces dissolve scores very high; a take that
  barely moves scores low even when it is the only clean one. In a config
  comparison it ranked the artist's only acceptable take **last**, because that
  take had the most motion. Edge-energy artifact scanning has its own blind
  spots — it missed a face melting inside hair (hair edges mask it), a sword
  vanishing (outside the face box), eyes disappearing (0.2% of the frame), and —
  on a 33-frame take — it reported failure at frame 3 when the real damage was
  frames 12-17 and frame 3 was fine. On the length sweep it went fully useless:
  it called failure at frame 1, frame 0 and frame 16 on three takes whose real
  defects were at 18-19, 11-13, and everywhere. Every time the numbers disagreed with the
  artist's eye, the eye was right.
  Treat all scores as a *sort order for what to look at*, never as a verdict.
- **Freezing is as useful as animating.** If the hands go wrong, a `hold` scene
  beats another twenty seeds.
- **ComfyUI runs prompts serially.** The seed hunt is a sequential loop by
  design; stacking jobs just burns timeouts in the queue.
- ⚠ **Never interleave LTX and Kontext on a small card.** One Kontext call
  submitted while an LTX batch was running made a 22B video model and FLUX fight
  over 6 GB; it thrashed until the job hung and cost **five hours** and two
  finished takes. All of one model, then all of the other. Check the queue is
  empty before switching.
- **Kontext repairs a GRIP, not an open hand.** Given a hand closed on a book
  edge or a sword hilt it fixed the fingers, 2 for 2. Given an open hand that had
  blurred away it failed 0 for 7 — three seeds, two phrasings, and a tight-crop
  pass. There is no contour left for it to follow, so it is being asked to
  invent, which is the same failure as the table above.

## Install

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe test_tools.py            # 13 GPU-free checks
```

Register it (paths must be absolute):

```bash
claude mcp add anime-production -- /abs/path/.venv/Scripts/python.exe /abs/path/server.py
```

## Models

Everything runs through ComfyUI. **LTX and Kontext both load GGUF weights, which
core ComfyUI cannot do** — install [city96's
ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) into `custom_nodes` first.
`check_status` reports whether it is present.

| file | folder |
|---|---|
| `ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf` | `models/unet/` |
| `ltx-2.3-22b-distilled_embeddings_connectors.safetensors` | `models/text_encoders/` |
| `ltx-2.3-22b-distilled_video_vae.safetensors` | `models/vae/` |
| `gemma-3-12b-it-Q3_K_M.gguf` | `models/text_encoders/` |
| `flux1-kontext-dev-Q6_K.gguf` | `models/unet/` |
| `t5xxl_fp8_e4m3fn.safetensors`, `clip_l.safetensors`, `ae.safetensors` | `models/text_encoders/`, `models/vae/` |

⚠ **The text encoder goes in `models/text_encoders/`, never
`models/checkpoints/`.** Core's `LTXAVTextEncoderLoader` reads `checkpoints/`,
and `.gguf` is not in ComfyUI's supported extensions, so it can never list one.
Connector and VAE must match the checkpoint's variant *and* generation, or you
get silent garbage instead of an error. ComfyUI caches folder listings at
startup — restart it after adding files.

## Environment

| variable | default |
|---|---|
| `COMFY_URL` | `http://127.0.0.1:8188` |
| `WEBCOMIC_ANIME_COMFY_DIR` | `C:\AI\ComfyUI_windows_portable` |
| `WEBCOMIC_ANIME_AUTOLAUNCH` | `1` |
| `WEBCOMIC_ANIME_TIMEOUT` | `1800` |
| `WEBCOMIC_ANIME_OUTPUT` | `./output` |
| `WEBCOMIC_ANIME_FFMPEG` | first on `PATH` — only `assemble_video` needs it |

## Tools

**Generate** — `animate_shot` (the seed hunt: N takes, retimed, scored, recorded)
· `edit_frame` (Kontext keyframe) · `composite_patch` (bring back the region
only)

**Judge** — `measure_motion` · `retime_clip` · `contact_sheet`

**Draw** — `add_impact` · `grow_layer` · `add_streaks` · `add_water`

**Frame** — `measure_frame_slot` · `frame_clip`

**Assemble** — `assemble_video` · `write_srt`

**Library** — `list_shots` · `get_shot` · `approve_shot` · `forget_shot` ·
`forget_rejected` · `check_status`

### Scene kinds — most of the edit is picking these

`assemble_video` takes `[{"clip": ..., "kind": ..., "name": ...}]`:

| kind | timing | for |
|---|---|---|
| `loop` | whole panel | ambient with no natural end — drifting cloth, an argument, falling snow |
| `pong` | whole panel, forward-then-back | oscillatory motion; no seam at the turnaround |
| `once` | **exactly its clip** | an event that can't repeat; ping-ponging would un-grow the ice |
| `hold` | clip, then freezes | play the motion, then rest — contemplation |

`once` gets no static hold on purpose. Holding a still frame *before* an event
reads, to a viewer who doesn't know one is coming, as the video having frozen.
The stationary time is cut and handed to the end card. `hold` works because the
stillness comes *after* the motion, so the viewer has just watched something
happen.

### Frames and slots

⚠ **The alpha bounding box is not the slot.** Decoration drawn on transparency
makes the gaps between leaves count as transparent, so the bbox comes out far
too wide — on the reference frame, 1180px against a true 802px, which left a
background-colored line along the bottom of every panel.
`measure_frame_slot` measures the columns clear for the *full height*, which is
the only region artwork can show through.

## Scope guard

Generation, framing, drawn effects and assembly. **Not** music (that's
`music-generation-mcp`), **not** image generation, **not** color grading or
compositing beyond what's here. If those appear, stop and split.

## Privacy

`output/` is gitignored, and deliberately: shot recipes embed prompts, and an
assembled video's config embeds credits and subtitle cues — i.e. unreleased
lyrics. Do not add an exception to "keep the manifest". The source artwork is
the author's own; the machinery is the open-source deliverable, the art is not.
