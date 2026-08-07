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
- **The motion score is not quality.** It measures *change*; a take whose faces
  dissolve scores very high. Look at the clip.
- **Freezing is as useful as animating.** If the hands go wrong, a `hold` scene
  beats another twenty seeds.
- **ComfyUI runs prompts serially.** The seed hunt is a sequential loop by
  design; stacking jobs just burns timeouts in the queue.

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
| `flux1-kontext-dev-Q3_K_S.gguf` | `models/unet/` |
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
background-coloured line along the bottom of every panel.
`measure_frame_slot` measures the columns clear for the *full height*, which is
the only region artwork can show through.

## Scope guard

Generation, framing, drawn effects and assembly. **Not** music (that's
`music-generation-mcp`), **not** image generation, **not** colour grading or
compositing beyond what's here. If those appear, stop and split.

## Privacy

`output/` is gitignored, and deliberately: shot recipes embed prompts, and an
assembled video's config embeds credits and subtitle cues — i.e. unreleased
lyrics. Do not add an exception to "keep the manifest". The source artwork is
the author's own; the machinery is the open-source deliverable, the art is not.
