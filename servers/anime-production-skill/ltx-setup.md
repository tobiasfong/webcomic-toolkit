# LTX-Video 2.3 — local I2V setup for a 6GB card

Prep notes for adding the one missing stage of the pipeline: **image-to-video**,
running locally so the ecosystem stays subscription-free.

> Status: **not yet installed or tested.** Written 2026-08-03 from current
> community sources. Verify version details at install time — this space moves
> fast and some specifics below may already have shifted.

## Why this stage at all

Everything else already exists:

| Stage | Tool | Status |
|---|---|---|
| Generate keyframes | `character-panel-mcp` + `webcomic-background-mcp` | ✅ built |
| **Animate keyframes** | **LTX-Video (this doc)** | ❌ the gap |
| Assemble / time / grade | the Remotion engine | ✅ built |
| Music | Suno → ACE-Step later | ✅ |

## Target workflow: FFLF (first-and-last frame)

**This is the goal, not open-ended image-to-video.** You supply the first *and*
last frame — both your own drawings — and the model generates only the
in-betweens. Because it must land on your drawing at the end, it cannot drift
off into its own style, which is the main risk when animating hand-drawn art.

It also matches the drawings already planned: "2 frames per scene" was going to
be *held* as limited animation; with FFLF the same two drawings become smoothly
in-betweened motion instead. Same exports, better result.

**Use FFLF for:** arm raise, head lower/tilt, the dance turn, ice growth.
**Do NOT use it for:** blinks and mouth flaps — those must *snap*. A smoothly
interpolated blink looks like the character's eyes are melting shut. Those stay
on the engine's frame player (`animation: { mode: "blink" | "mouth" }`), which
is instant, deterministic and costs no VRAM.

## Files — run `tools/fetch-ltx.sh` (downloads everything, resumable)

**Repo: `unsloth/LTX-2.3-GGUF`** — a self-consistent set. Each variant ships a
matching embeddings connector and VAE.

⚠ **Do not mix generations.** `Kijai/LTXV2_comfy` is the *older* LTX-2 **19B**;
its connector and VAE are not interchangeable with 2.3's. (Downloaded that by
mistake first — the 22B 2.3 set is the current one.)

| File | Purpose | Size |
|---|---|---|
| `distilled-1.1/…-Q4_K_M.gguf` | fast variant, 4–8 steps | ~13 GB |
| `text_encoders/…distilled_embeddings_connectors.safetensors` | must match variant | — |
| `vae/…distilled_video_vae.safetensors` | must match variant | — |
| `gemma-3-12b-it-Q3_K_M.gguf` | text encoder (Gemma, **not** T5) | ~6 GB |
| `ltx-2.3-22b-dev-Q4_K_M.gguf` + its connector/VAE | quality variant, 20–30 steps | ~13 GB |

**ComfyUI-GGUF nodes (city96) are already installed** in this ComfyUI.

### dev vs distilled — why both

- **distilled-1.1** — 4–8 steps. Use it for the *first* session: while hunting
  OOM settings you want fast iterations, not 30-step renders. Weakness is
  blurring on fine detail (character eyes), which matters for this art.
- **dev** — 20–30 steps, better prompt adherence and cleanest fine detail.
  Switch to it once distilled is proven to run.

A common trick is dev + a distilled LoRA, to get dev quality at distilled step
counts from a single base model. That saves *disk*, which isn't the constraint
here (508 GB free), and adds LoRA-compatibility risk — so downloading both
checkpoints is simpler. Worth revisiting if a 2.3 distilled LoRA turns up.

## Placement gotcha

**GGUF models go in `models/checkpoints/`, not `models/diffusion_models/`.**
This trips people up and produces a "model not found" that looks like a bad
download.

## 6GB settings

Reported working levers (one user ran LTX-2 at 720p/10s on 6GB VRAM, though
with 44GB system RAM — you have 32GB, so expect it to be tighter):

- Use the **fp8** checkpoint variant, or GGUF
- **Offload the VAE to CPU**
- **Last-stage batch = 1**
- Keep the text encoder quantised low (it can be offloaded after encoding —
  it only runs once per generation)

## Resolution floor — important for this art style

**Do not go below 540p on the first pass.** Dropping resolution is the obvious
way to fit a video model on a small card, but fine linework and cel shading —
exactly what this project's art is made of — turn to mush below 540p, before
any upscale can recover it. So a VRAM test at 360p proves nothing useful: it
has to fit *at 540p+* to count.

## LoRAs — what we actually need

### IC-LoRA — NOT style-locking, but WANTED for the dance shot

A secondhand tip claimed IC-LoRA "locks anime linework and shading". **Wrong.**
It is *motion/structure control from a reference video* — Canny / Depth / Pose /
Motion-Track modes — whose stated purpose is to **separate motion from style**.

It is therefore useless for plain still→video FFLF (nothing to condition on),
**but exactly right for the dance shot**, where the plan is to drive motion from
an anime dance reference clip.

✅ Downloaded: `models/loras/ltx-2.3-22b-ic-lora-motion-track-control-ref0.5.safetensors` (313 MB)

Open questions to settle by testing:
- **Composition mismatch** — the dance illustration is a tight waist-up embrace
  seen from behind Lumiere; a full-body dance reference frames very differently.
  Motion transfer wants similar framing.
- **Two overlapping figures** are the hard case for pose/motion extraction.
- **Does the artwork's identity survive?** IC-LoRA conditions *motion*; identity
  must come from image conditioning. Whether they hold together is the test.
- IP: motion reference is defensible (motion isn't the protected element, output
  is the artist's own characters) — just don't let source imagery show through
  and don't publish the reference clip.

### Style LoRAs — test the baseline first, don't add preemptively

The rule is **not** "hand-drawn vs generic" (that only covers his own art). It is:
**style should come from the source image, whatever its origin.** For the test
the panels are already generated anime — but a style LoRA whose look differs
from the panel's look still causes drift, just between two generated styles.

A style LoRA only helps if **the model itself** drifts — e.g. LTX pulling anime
input toward photoreal. So:

1. Animate one panel with **no LoRA** and look at it.
2. If it stays 2D → no LoRA needed.
3. If it drifts realistic → add an anime LoRA as a corrective, and you'll know
   it's helping because you saw the baseline.

⚠ **LoRAs are architecture-specific.** Existing Flux/SD anime LoRAs will NOT
load on LTX-2.3; it needs LTX-2.3-trained ones, which are scarce (new model).

What actually preserves the look:
1. **FFLF** — both endpoints are the artist's own drawings, so the model can
   only interpolate between them
2. **Short clips** — less generated time, less drift
3. **540p+** — below that the linework mushes regardless

Only LoRA worth considering *later*: one trained on the artist's own style. With
FFLF that's likely unnecessary.

(IC-LoRA does have a possible future use — driving character motion from
reference footage — but that's a different workflow and would fight character
consistency.)

## Test plan (do in this order)

1. **Generated test panel first** — generated art, so no hand-drawn canon for drift
   to violate. Lowest-risk proof that it runs at all.
2. **Then one of his own illustrations** — the real question. Compare against the
   original at 100% zoom: does the linework survive?
3. **Then FFLF** with two real drawings once they exist.

Keep clips short. Less generated time = less drift.

## Output → the pipeline

Clips drop straight into the existing engine as video panels:

```ts
{ src: "panels/shot_03.mp4", durationInSeconds: 5, clipSeconds: 5 }
```

They inherit crossfades, the grade, beat-synced cuts, effects and overlays.
Continuity between clips is a non-issue here: each shot is a different
illustration, so drift between them is invisible — it only matters when
extending a single shot past the model's clip limit.

## Fallbacks if it won't fit at 540p+

- **Wan 2.2 5B** (TI2V hybrid — does image-to-video, GGUF exists)
- **AnimateDiff** on SD1.5 — definitely runs, but shorter and weaker; the floor
- Decide in advance whether the answer is "accept lower quality", "wait for
  better open models", or "break the no-subscription principle for one project"
