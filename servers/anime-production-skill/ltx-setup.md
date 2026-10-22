# LTX-2.5 — local image-to-video on a 6 GB card

The one stage of the pipeline that makes art MOVE, run locally so the ecosystem
stays subscription-free. Verified on a 6 GB RTX 3060 Laptop with 32 GB of RAM:
an eight-scene teaser of hand-drawn panels was animated with it end to end.

LTX-2.3 (GGUF, via city96's ComfyUI-GGUF) was used here until 2026-10-22. On
the same panels 2.5 was judged much better — a real punch toward the viewer, a
waltz turn, a prayer pose, two people talking — and 2.3 was removed.

## Which ComfyUI

2.5 needs **ComfyUI v0.32 or later** and runs Lightricks' official files with
**no custom nodes**. This project keeps it on a separate v0.41 portable install
(port 8189) that it shares with FLUX 3 Klein, so an older main install with
add-ons you rely on is never touched. If you have one current ComfyUI, use it.

## Files — `assets/tools/fetch-ltx.sh` (resumable)

From **`Lightricks/LTX-2.5`**, which is gated: accept its license on Hugging
Face, create a read token, then `HF_TOKEN=hf_... bash fetch-ltx.sh`.

| file | folder | size |
|---|---|---|
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `models/diffusion_models/` | 21.5 GB |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `models/text_encoders/` | 15.4 GB |
| `ltx-2.5-video-vae-bf16.safetensors` | `models/vae/` | 1.5 GB |
| `ltx-2.5-audio-vae-bf16.safetensors` | `models/vae/` | 0.4 GB |
| `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | `models/latent_upscale_models/` | 1.0 GB |

**INT8 ("int8-convrot") is the build for RTX 30/40-series cards** — they have
INT8 tensor cores; NVFP4 needs Blackwell. The text encoder must be Lightricks'
own Gemma 4 file: a stock Gemma 4 is checked against the checkpoint and refused.
The optional prompt enhancer (`gemma4_e2b_it_int8_convrot`) is not needed — it
rewrites the prompt, and every prompting rule here assumes the prompt the model
sees is the one you wrote.

## Memory on a small card

The weights total ~37 GB against 32 GB of RAM. It runs: ComfyUI drops the text
encoder after reading the prompt, so sampling needs ~23 GB. Measured: **~3.5
min for a 49-frame take, ~7 min for a 97-frame take**, at about 2 MP. The first
take of a session loads everything and is slower.

⚠ **Nothing else may sit in RAM.** An idle ComfyUI still holds its model in
system RAM. One take started with another model resident and only 3.7 GB free
took 694 s; with that one unloaded, 176 s. `ltx_run.py` and the MCP server both
unload the other install before rendering.

## Settings that matter

- **24 fps, 49 (2 s) or 97 (4 s) frames. Never 17.** At 17 frames the model has
  only three latent frames: every take sat still to frame 8, lurched at frame 9
  and tore faces on full-body action. At 49-97 the same panels came back clean.
- **Size from the artwork's own shape, ~2 MP, both sides divisible by 64** (the
  first stage renders at half size). The model stretches its input to whatever
  size it is given — no letterboxing — so a fixed default ruins every panel of
  a different shape. `ltx_run.py` picks this for you.
- **Prompt for motion only**: name the camera first, then the motion, then what
  stays still; 4-8 sentences; positive phrasing (negatives are ignored). The
  first motion named gets the motion budget.

## What it still gets wrong

- **Blinks.** Asked to "blink", eyes closed and stayed closed on three seeds.
  "Her eyes close, then open wide, then close again" — no word "blink" —
  produced a blink on one seed in three.
- **Unasked head turns.** A head drawn in profile turned toward the camera, and
  a string hanging beside the face merged into a second pair of glasses. Saying
  the head stays in profile stopped both.
- **Growing new geometry.** Asked to grow ice, it raised the hand ~3% and grew
  almost nothing. An unusually LOW motion score means "it declined", not "it is
  subtle".
- **Camera moves despite "locked off"** on one seed of three; "the framing stays
  exactly the same from start to end" held it.

Run ~3 seeds per shot and judge the 12 fps preview by eye. Seeds change a lot.

## LoRAs

Not needed to animate existing art: in image-to-video the look comes from the
panel, and a style LoRA would pull it away from the drawing. LoRAs are tied to a
model version — 2.3 LoRAs do not reliably work on 2.5. Consider one only for a
specific, repeated failure (a combat-motion LoRA if fights keep failing).

## First and last frame

2.5 can animate from one picture to another (ComfyUI's `video_ltx2_5_flf2v`
template) — the fix for an action image-to-video refuses: supply the END pose and
it only fills in the motion. `ltx_run.py --last end.png`, or the server's
`animate_shot(last_frame_path=...)`. It renders in one stage at full size, so it
is slower than image-to-video. A last resort, with the end pose made by Klein:
for generated art an edit of the whole panel; for hand-drawn art a BOXED edit
that redraws just the moving part first, and the whole panel only if that fails
(it re-inks the whole drawing). See SKILL.md, "The workflow".

## Output → the pipeline

`ltx_run.py` writes the 24 fps take and a 12 fps preview (every other frame —
anime on twos). The pipeline modules and the MCP server read 12 fps webp; drop
the preview straight in.

## When LTX is not enough

The MCP server's `animate_shot_cloud` sends a shot to Seedance 2.0 on BytePlus —
paid per take, the panel leaves the machine — for actions a local model will
not do.
