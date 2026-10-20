"""
ltx_workflow.py — build the ComfyUI API graph for LTX-2.3 image-to-video.

RESOLUTION IS THE LEVER. Everything else is a detail. This module defaulted to
832x576 for two days because it was fast; that cost an artist 65 hand-repaired
frames on a single 15-panel scene, and the seven panels that came back clean
were the ones that barely moved.

    DO NOT PICK A SIZE BY HAND — call pick_size(src_w, src_h). It matches the
    ARTWORK'S OWN ASPECT and then maximizes pixels inside a budget. A constant
    cannot do this: LTXVImgToVideo silently resizes the input to whatever it is
    given, so a fixed "good default" stretches every panel of a different shape.
    1216x832 art at a 1920x1088 default ships 20% too wide, with no warning.

Why: at 832x576 a hand is ~40px, which after the VAE's 8x compression is ~5
latent pixels. There is not enough there to draw fingers, so any hand that MOVES
becomes mush. That is a resolution problem and no seed fixes it.

And it is nearly free. A ceiling sweep on a 6 GB RTX 3060 Laptop found NO
out-of-memory point at all, and steady-state cost was ~90-140 s a take across
the entire range once the model is resident. (The first take of a session pays
the model load and reads far slower — never benchmark on it.) The low default
bought speed that was immediately spent on repairs.

WHAT LIGHTRICKS RECOMMEND, on the knobs still left wrong:
  * PROMPT LENGTH: 4-8 descriptive sentences; longer consistently beats shorter.
    One-sentence prompts (what this project used throughout) are far too short.
    ComfyUI ships `TextGenerateLTX2Prompt` as an expander for exactly this.
  * FRAME COUNT: upstream uses 121 and 257; 17 is the floor of the 8n+1 rule.
    TESTED AND REJECTED HERE ANYWAY. Re-run at 1920x1088 changing only length:
    17 clean, 25 smears at frames 18-19, 33 loses a finger at 11-13, and 49
    grows a third arm in EVERY frame (a broken composition, not drift). At
    1216x832 the length-33 damage was frames 12-17; at 1920x1088 it was 11-13 —
    same place, more pixels, so length is its own failure mode. Cutting the bad
    window out does not rescue them: dropping 3 of 33 frames left a seam 5.2x
    the clip's own median motion, a visible pop. Stay at 17.
  * MOTION DENSITY: do not stack simultaneous motions into a short clip. A
    spin-and-slash inside 1.4 s is over-packed by the model's own guidance.
    CONFIRMED IN PRODUCTION: asked to "snap her leg forward in a fast kick",
    LTX scored 3.6/5.8/8.2 against a scene typical of 11-48 and the artist
    said the leg "rises very slightly, almost like never". The same panel,
    same seed, same 2.18 MP, asked to "raise her extended leg a little higher"
    worked first try. ⚠ LTX DECLINES AN ASK IT CANNOT MEET RATHER THAN
    SMEARING — an unusually low motion score means "it refused", not "it is
    subtle". That is the one situation where the score predicts a real problem.
  * STEPS: distilled at 8 is correct — this one choice held up.

⚠ THE NEGATIVE PROMPT IS INERT ON `distilled`. It runs at cfg 1.0, and
classifier-free guidance discards the negative branch entirely at cfg 1.0.
Measured: generating with the full negative and with an empty string produced
PIXEL-IDENTICAL output (mean abs difference 0.000, against ~67 between two
seeds). Every word of NEG below is thrown away before sampling. It is kept only
because `dev` runs at cfg 3.0, where it does apply.

⚠ WHERE DAMAGE LANDS MOVES WITH RESOLUTION, and this is the most useful thing
in this file. At 0.5 MP defects sat MID-CLIP — a melted hand at f10 with good
frames either side, fixable only by drawing. At ~2 MP, across a whole 14-panel
scene, every single rejected take had its damage in the FINAL few frames, where
a cut costs nothing (no join, no seam). Resolution does not just reduce defects,
it relocates them somewhere cheap.

Still not a law, though: at length 33 the bad window was frames 12-17 and the
clip RECOVERED afterwards, tail included. Find the bad window; don't
blind-truncate. And a mid-clip drop of 2-3 frames is fine anyway — 0.17-0.25 s
at 12 fps reads as a faster action, not a hole.

⚠ HEIGHT MAY NEED TO BE DIVISIBLE BY 64, NOT 32 (UNCONFIRMED). validate()
enforces 32. In the ceiling sweep, 1408x800 was the only size whose height fails
64 (800/64 = 12.5) and the only one that produced extra fingers, plus a deformed
hand in its last two frames. The VAE compresses 8x and the transformer
patchifies 2x2 above that, so 64 is a plausible real alignment unit. One take at
1408x832 would settle it. Until then prefer 704, 832, 896, 1088.

⚠ THE GGUF TEXT ENCODER GOTCHA, which costs the most time of anything here:
core's `LTXAVTextEncoderLoader` reads `models/checkpoints/`, and `.gguf` is not
in ComfyUI's `supported_pt_extensions`, so it can never list one. The encoder
must go through city96's `DualCLIPLoaderGGUF(type="ltxv")` with the file in
`models/text_encoders/`. Connector and VAE must also match the checkpoint's
variant *and* generation, or you get silent garbage rather than an error.

Nothing in this module talks to ComfyUI — it returns a dict. comfy.py submits.
"""

from __future__ import annotations

VARIANTS = {
    "distilled": {
        "unet": "ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf",
        "connector": "ltx-2.3-22b-distilled_embeddings_connectors.safetensors",
        "vae": "ltx-2.3-22b-distilled_video_vae.safetensors",
        "steps": 8, "cfg": 1.0,
    },
    "dev": {
        "unet": "ltx-2.3-22b-dev-Q4_K_M.gguf",
        "connector": "ltx-2.3-22b-dev_embeddings_connectors.safetensors",
        "vae": "ltx-2.3-22b-dev_video_vae.safetensors",
        "steps": 25, "cfg": 3.0,
    },
}
GEMMA = "gemma-3-12b-it-Q3_K_M.gguf"

# INERT on `distilled` (cfg 1.0 discards the negative branch — proven by
# pixel-identical output with and without it). Applies only to `dev` at cfg 3.0.
NEG = "blurry, distorted, deformed hands, extra limbs, warped face, watermark, text"

DEFAULT_PROMPT = ("anime illustration, the character moves slightly, hair and "
                  "clothes sway, subtle natural motion, cel shaded, clean linework")

# ⚠ DO NOT HARDCODE A DEFAULT SIZE. Use pick_size(). A fixed default is the
# wrong SHAPE of answer, and getting this wrong is silent: LTXVImgToVideo
# resizes the input to whatever width/height it is given, with no letterboxing
# and no complaint. Point 1216x832 artwork at a 1920x1088 "default" and every
# panel ships stretched 20% wider. These two are kept only as reference points:
PRIMARY = (1920, 1088)   # artist-approved, 16:9-ish art
FALLBACK = (1216, 832)   # artist-approved; also a common panel native size

# ⚠ TARGET, NOT CEILING. Resolution is not monotonically better on its own —
# it only pays off once the prompt is long enough to spend it.
#
# THREE PROMPT STYLES x TWO SIZES on one panel (p08, a hand-raise), same seed,
# artist-reviewed frame by frame. The prompt is not a tiebreaker here — it moves
# the answer:
#
#                     1 sentence        8 sentences        5 sentences
#                     (terse)           (descriptive)      (motion-only, i2v)
#   1.01 MP           fingers fused     f16-17 missing     GHOST HAND floating
#   (1216x832)        f7-8              a finger           below him
#   2.18 MP           perfect anatomy,  CLEAN              CLEAN
#   (1792x1216)       wandered into
#                     hair-styling
#
# 0.50 MP (864x576), for reference, was worst of all: f10-12 fingers fused, hand
# deformed, face warped.
#
# 2.18 MP is clean under BOTH long prompts; 1.01 MP produced a defect under all
# three. So the target is high — but only because the prompt got long.
#
# THEN A WHOLE 14-PANEL SCENE WAS RUN AT THESE SETTINGS, and the target turned
# out to be softer than that one panel implied. Panels landed between 1.12 and
# 2.18 MP (aspect and the 2x upscale cap decide, not preference) and EVERY ONE
# was usable. Notably p02 at 1.12 MP was clean where p08 at 1.01 MP was not —
# because p02 is a calm shot of a hand GRIPPING a hilt and p08 is an OPEN hand
# raising. What the shot asks for matters as much as the pixel count:
#     grips, small motions, no hands in shot   -> ~1 MP is fine
#     open hands, fast motion, faces up close  -> want 2 MP+
# Result of that scene: 65 hand-redrawn frames in v1 became ZERO, with a single
# frame trimmed in the entire cut.
#
# TWO CURVES CROSS, which is why "higher is better" fails as a standalone rule:
#   * ANATOMY improves with resolution. Too few latent pixels and the model
#     cannot render what it is moving, so hands mush.
#   * PROMPT FIDELITY degrades with it. Spare capacity is spare freedom, and a
#     one-sentence prompt does not constrain it, so the model invents motion.
# A 4-8 sentence prompt naming the camera, the motion, and WHAT STAYS STILL
# removes that freedom — and then the extra resolution is pure gain.
#
# ⚠ SO THIS TARGET AND THE PROMPT ARE A PAIR. Aim here with a one-sentence
# prompt and the shot will wander. If you cannot write 4-8 sentences, drop to
# ~1_000_000 instead and accept the occasional finger.
TARGET_PX = 2_200_000

# Hard ceiling. A full ceiling sweep on the 6 GB RTX 3060 Laptop found no OOM
# anywhere below this, including 1920x1088 at length 49. It bounds what a caller
# may ask for; it is NOT what the picker aims at.
BUDGET_PX = 2_200_000

# Latent alignment. The VAE compresses 8x and the transformer patchifies 2x2 on
# top, making 64 the plausible true unit — 1408x800 (800/64 = 12.5) was the only
# size in the sweep to grow an extra finger. validate() still only enforces 32,
# so this is a preference the picker honours rather than a hard rule.
ALIGN = 64

# Absolute floor below which linework mushes and no upscale recovers it. This is
# a FLOOR, not a target — 832x576 clears it and still cannot hold a moving hand.
MIN_DIM = 540


def pick_size(src_w: int, src_h: int, target_px: int = TARGET_PX,
              budget_px: int = BUDGET_PX, align: int = ALIGN,
              max_dim: int = 1920, max_scale: float | None = 2.0) -> dict:
    """Largest render size that MATCHES THE SOURCE ASPECT, within a pixel budget.

    Replaces picking a fixed default. Three things have to be true at once and
    a constant can only ever satisfy one of them:

      1. ASPECT MUST MATCH THE ARTWORK. There is no letterboxing in
         LTXVImgToVideo — a mismatch is a silent stretch. And padding the input
         yourself is worse than useless: bars eat the pixel budget, and LTX has
         no concept of a border, so it drifts and bleeds into them. Letterbox at
         ASSEMBLY, on a finished clip, never at generation.
      2. AIM FOR ~2.2 MP, PAIRED WITH A 4-8 SENTENCE PROMPT. A hand ~40px wide
         in an 864px frame is ~5 latent pixels after the VAE's 8x compression —
         too few to draw fingers, so moving hands mush. Resolution fixes that.
         The catch is that spare capacity plus a SHORT prompt gets filled with
         invention, so the two must move together. With a one-sentence prompt,
         pass target_px=1_000_000 instead.
      3. BOTH DIMENSIONS SHOULD DIVIDE BY 64 (see ALIGN).

    Returns the chosen size plus `scale` (vs the source) and `aspect_error`, so
    a caller can see what it is getting instead of trusting a magic number.
    """
    if src_w <= 0 or src_h <= 0:
        raise RecipeError(f"bad source size {src_w}x{src_h}")
    aspect = src_w / src_h

    # Aim at the target, or at the artwork's own size when it already clears it.
    # Never downscale good art toward the target, and never upscale past it.
    native_px = src_w * src_h
    aim_px = min(max(native_px, target_px), budget_px)

    # Beyond ~2x the source, added pixels are pure interpolation and buy latent
    # capacity at a steep compute price. Overridden below if the cap would push
    # the frame under the linework floor.
    cap = int(max_dim if max_scale is None else min(max_dim, src_w * max_scale))

    def candidates(unit: int, w_cap: int):
        for h in range(unit, max_dim + 1, unit):
            w = int(round(h * aspect / unit)) * unit
            if w < unit or w > w_cap or w * h > budget_px:
                continue
            if max(w, h) < MIN_DIM:
                continue
            yield w, h, abs(w / h - aspect) / aspect

    # ⚠ DO NOT RANK BY ASPECT ERROR ALONE, then by size. That looks right and is
    # badly wrong: an EXACT-ratio size always beats a near-exact larger one, so
    # 1216x832 art returns 1216x832 (never upscaling) and 1920x1080 art returns
    # 1024x576 — a 0.53x downscale on a 2.2 MP budget. Both measured.
    #
    # Aspect error is a THRESHOLD, not a score. Under ~1% nothing is visible, so
    # inside that band the only thing that matters is size. Widen the band only
    # if nothing qualifies.
    best = None
    for w_cap in (cap, max_dim):                      # relax the scale cap last
        for tol in (0.01, 0.02, 0.04):
            for unit in (align, 32):                  # prefer 64-alignment
                pool = [c for c in candidates(unit, w_cap) if c[2] <= tol]
                if pool:
                    # Closest to the AIM. Ties (equidistant above and below)
                    # break upward — a hand is likelier to survive with slightly
                    # more room than slightly less.
                    w, h, err = min(pool, key=lambda c: (abs(c[0] * c[1] - aim_px),
                                                         -(c[0] * c[1])))
                    best = (w, h, err, unit, w_cap != cap)
                    break
            if best:
                break
        if best:
            break

    if best is None:
        raise RecipeError(
            f"no size fits {src_w}x{src_h} within {budget_px:,} px above the "
            f"{MIN_DIM}px floor — raise budget_px or supply larger art.")

    w, h, err, unit, capped_out = best
    scale = w / src_w
    notes = []
    if capped_out:
        notes.append(f"ignored the {max_scale}x upscale cap — obeying it fell under "
                     f"the {MIN_DIM}px floor")
    if unit != align:
        notes.append(f"fell back to {unit}px alignment; {align} could not hold the aspect")
    if err > 0.01:
        notes.append(f"aspect off by {err*100:.1f}% — the drawing will stretch slightly")
    if scale < 1.0:
        notes.append(f"DOWNSCALING to {scale:.2f}x — raise budget_px if the card allows")
    if w * h < target_px * 0.8:
        notes.append(f"{w*h/1e6:.2f} MP is below the ~{target_px/1e6:.1f} MP target — "
                     f"a moving hand may not survive; see the README")
    if w * h > target_px * 1.6:
        notes.append(f"{w*h/1e6:.2f} MP is well above the ~{target_px/1e6:.1f} MP target — "
                     f"expect clean anatomy but drift off the prompt unless the "
                     f"prompt is long and specific")

    return {"width": w, "height": h, "align": unit, "aim_megapixels": round(aim_px / 1e6, 2),
            "aspect": round(aspect, 4), "aspect_error": round(err, 4),
            "scale": round(scale, 3), "megapixels": round(w * h / 1e6, 2),
            "source": [src_w, src_h], "notes": notes}


class RecipeError(ValueError):
    """A parameter combination ComfyUI would reject, caught before submitting."""


def validate(width: int, height: int, length: int, variant: str) -> None:
    if variant not in VARIANTS:
        raise RecipeError(f"variant must be one of {list(VARIANTS)}, got {variant!r}")
    if (length - 1) % 8:
        raise RecipeError(
            f"length must be 8n+1 (got {length}); try 17, 25, 33, 49, 73, 97. "
            f"17 is this project's VRAM-constrained default, not a good one — "
            f"Lightricks' own guidance uses 121 and 257."
        )
    for name, d in (("width", width), ("height", height)):
        if d % 32:
            raise RecipeError(f"{name} must be divisible by 32 (got {d})")
    if max(width, height) < MIN_DIM:
        raise RecipeError(
            f"{width}x{height} is below the {MIN_DIM}px floor — fine linework "
            f"mushes at that size and no upscale brings it back."
        )


def build(image: str, prompt: str = DEFAULT_PROMPT, *, seed: int = 12345,
          width: int = PRIMARY[0], height: int = PRIMARY[1], length: int = 17,
          variant: str = "distilled", strength: float = 0.9, fps: float = 48.0,
          steps: int | None = None, cfg: float | None = None,
          max_shift: float = 2.05, base_shift: float = 0.95,
          scheduler: str = "ltxv", prefix: str = "ltx",
          negative: str = NEG) -> dict:
    """ComfyUI API-format graph. Node ids are strings; links are [id, out_index]."""
    validate(width, height, length, variant)
    v = VARIANTS[variant]
    steps = steps or v["steps"]
    cfg = v["cfg"] if cfg is None else cfg

    return {
        # --- loaders ---
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": v["unet"]}},
        "2": {"class_type": "DualCLIPLoaderGGUF",
              "inputs": {"clip_name1": GEMMA, "clip_name2": v["connector"], "type": "ltxv"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": v["vae"]}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image}},

        # --- conditioning ---
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},

        # image -> video latent (also rewrites the conditioning).
        # `strength` is THE lever: 1.0 is perfectly faithful to the input and the
        # clip FREEZES — the notorious LTX i2v failure. 0.9 gives motion room
        # without losing the drawing.
        "7": {"class_type": "LTXVImgToVideo",
              "inputs": {"positive": ["5", 0], "negative": ["6", 0], "vae": ["3", 0],
                         "image": ["4", 0], "width": width, "height": height,
                         "length": length, "batch_size": 1, "strength": strength}},
        # frame_rate is conditioning, not output fps. Telling it 48 is a known
        # anti-static trick: the model reads the shot as high-framerate footage,
        # where more inter-frame change is normal.
        "8": {"class_type": "LTXVConditioning",
              "inputs": {"positive": ["7", 0], "negative": ["7", 1], "frame_rate": fps}},

        # --- sampling ---
        "9": {"class_type": "ModelSamplingLTXV",
              "inputs": {"model": ["1", 0], "max_shift": max_shift,
                         "base_shift": base_shift, "latent": ["7", 2]}},
        "10": ({"class_type": "LTXVScheduler",
                "inputs": {"steps": steps, "max_shift": max_shift,
                           "base_shift": base_shift, "stretch": True,
                           "terminal": 0.1, "latent": ["7", 2]}}
               if scheduler == "ltxv" else
               {"class_type": "BasicScheduler",
                "inputs": {"model": ["9", 0], "scheduler": scheduler,
                           "steps": steps, "denoise": 1.0}}),
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "12": {"class_type": "SamplerCustom",
               "inputs": {"model": ["9", 0], "add_noise": True, "noise_seed": seed,
                          "cfg": cfg, "positive": ["8", 0], "negative": ["8", 1],
                          "sampler": ["11", 0], "sigmas": ["10", 0],
                          "latent_image": ["7", 2]}},

        # --- out ---
        # Written at 24 fps regardless of the conditioning fps above, so a
        # 17-frame take plays in 0.7 s. ALWAYS retime before judging it.
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "SaveAnimatedWEBP",
               "inputs": {"images": ["13", 0], "filename_prefix": prefix,
                          "fps": 24.0, "lossless": False, "quality": 90,
                          "method": "default"}},
    }


def recipe(image: str, prompt: str = DEFAULT_PROMPT, *, seed: int = 12345,
           width: int = PRIMARY[0], height: int = PRIMARY[1], length: int = 17,
           variant: str = "distilled", strength: float = 0.9, fps: float = 48.0,
           steps: int | None = None, cfg: float | None = None,
           max_shift: float = 2.05, base_shift: float = 0.95,
           scheduler: str = "ltxv", **_ignored) -> dict:
    """Everything needed to reproduce a take. Stored on the shot record.

    Seeds do NOT transfer across configs — change `length` or `variant` and the
    whole seed space reshuffles — so the recipe must carry every parameter, not
    just the seed.
    """
    v = VARIANTS[variant]
    return {
        "image": image, "prompt": prompt, "seed": seed,
        "width": width, "height": height, "length": length,
        "variant": variant, "strength": strength, "fps": fps,
        "steps": steps or v["steps"], "cfg": v["cfg"] if cfg is None else cfg,
        "max_shift": max_shift, "base_shift": base_shift, "scheduler": scheduler,
    }


# --------------------------------------------------------------------------- #
# LTX-2.5 — on the Klein ComfyUI (v0.41, port 8189), not the main one
# --------------------------------------------------------------------------- #
#
# Added 2026-10-20 and judged 2026-10-21: on an eight-scene teaser of hand-drawn
# panels the artist found 2.5 "much better" than 2.3, at 24 fps and 49-97
# frames (NOT 2.3's 17 frames, which tore faces). 2.3 is still the default
# variant until he decides otherwise. 2.5 needs ComfyUI >= 0.32, which the main
# install (0.25.1, kept old for the matting add-on) is not — but the separate
# Klein install is, and runs these official files natively with no custom
# nodes. Lightricks' own files from the gated Lightricks/LTX-2.5 repo; INT8 is
# the build for this Ampere card.
#
# ⚠ RAM: transformer 21.5 GB + text encoder 15.4 GB = 36.9 GB against the 32 GB
# machine. ComfyUI can drop the encoder after reading the prompt, so sampling
# should need ~23 GB — expect a slow first take either way.
#
# The graph follows ComfyUI's own video_ltx2_5_i2v template (Image to Video
# subgraph), with three changes:
#   * The prompt enhancer (a second Gemma that REWRITES the prompt) is off, as
#     Klein's is: every prompting rule here assumes the model sees the prompt
#     that was written.
#   * The template's ResizeImageMaskNode (longest side to 1536, Lanczos) is
#     done in Python before upload — same resize, no dependence on how that
#     node's newer input format serializes.
#   * Output is frames only, saved as animated webp like 2.3's. The model
#     generates audio jointly and its latent must be present, but it is never
#     decoded: the soundtrack comes from the music server.
LTX25 = {
    "unet": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
    "text_encoder": "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
    "vae": "ltx-2.5-video-vae-bf16.safetensors",
    "audio_vae": "ltx-2.5-audio-vae-bf16.safetensors",
    "upscaler": "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
}
# Folder each file sits in, inside the Klein install's models/ (check_status).
LTX25_FOLDERS = {"unet": "diffusion_models", "text_encoder": "text_encoders",
                 "vae": "vae", "audio_vae": "vae", "upscaler": "latent_upscale_models"}
LTX25_REF_LONG_SIDE = 1536   # the template's reference-image resize
# The template's two noise schedules: 8 steps at half size, then 3 refining
# steps after the 2x latent upscale.
LTX25_SIGMAS_1 = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
LTX25_SIGMAS_2 = "0.85, 0.7250, 0.4219, 0.0"
# The template opens every image-to-video prompt with this sentence.
LTX25_LEAD = "Use the provided start image as the first frame. "


def validate25(width: int, height: int, length: int) -> None:
    if (length - 1) % 8:
        raise RecipeError(f"length must be 8n+1 (got {length}); try 17, 25, 33, 49, 97, 121.")
    # Stage 1 renders at HALF size and its latent steps by 32, so the final
    # size must divide by 64. 1920x1088 and 1216x832 both do.
    for name, d in (("width", width), ("height", height)):
        if d % 64:
            raise RecipeError(f"{name} must be divisible by 64 for LTX-2.5 (got {d})")
    if max(width, height) < MIN_DIM:
        raise RecipeError(f"{width}x{height} is below the {MIN_DIM}px floor.")


def build25(image: str, prompt: str, *, seed: int = 12345, width: int = PRIMARY[0],
            height: int = PRIMARY[1], length: int = 17, fps: float = 48.0,
            strength: float = 0.7, refine_strength: float = 1.0,
            prefix: str = "ltx25") -> dict:
    """ComfyUI API graph for one LTX-2.5 image-to-video take.

    `image` must already be uploaded, and resized so its longest side is
    LTX25_REF_LONG_SIDE. `strength` is the template's stage-1 image strength
    (0.7) — lower than 2.3's 0.9, because stage 2 re-applies the image at 1.0.
    `fps` is conditioning, as in 2.3; 48 keeps the comparison with the
    approved 2.3 takes like-for-like (the template itself uses 24).
    """
    validate25(width, height, length)
    m = LTX25
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["text_encoder"], "type": "ltxv", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": m["audio_vae"]}},
        "5": {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": m["upscaler"]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": image}},
        "7": {"class_type": "LTXVPreprocess", "inputs": {"image": ["6", 0], "img_compression": 18}},

        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": LTX25_LEAD + prompt, "clip": ["2", 0]}},
        # Inert: both guider cfgs are 1, which discards the negative branch.
        "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "10": {"class_type": "LTXVConditioning",
               "inputs": {"positive": ["8", 0], "negative": ["9", 0], "frame_rate": fps}},
        "11": {"class_type": "LTXVDualCFGGuider",
               "inputs": {"model": ["1", 0], "positive": ["10", 0], "negative": ["10", 1],
                          "video_cfg": 1.0, "audio_cfg": 1.0}},
        "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},

        # --- stage 1: half size ---
        "20": {"class_type": "EmptyLTXVLatentVideo",
               "inputs": {"width": width // 2, "height": height // 2, "length": length, "batch_size": 1}},
        "21": {"class_type": "LTXVImgToVideoInplace",
               "inputs": {"vae": ["3", 0], "image": ["7", 0], "latent": ["20", 0],
                          "strength": strength, "bypass": False}},
        "22": {"class_type": "LTXVEmptyLatentAudio",
               "inputs": {"frames_number": length, "frame_rate": fps, "batch_size": 1,
                          "audio_vae": ["4", 0]}},
        "23": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["21", 0], "audio_latent": ["22", 0]}},
        "24": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "25": {"class_type": "ManualSigmas", "inputs": {"sigmas": LTX25_SIGMAS_1}},
        "26": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["24", 0], "guider": ["11", 0], "sampler": ["12", 0],
                          "sigmas": ["25", 0], "latent_image": ["23", 0]}},
        "27": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["26", 0]}},

        # --- stage 2: 2x latent upscale, then refine ---
        "30": {"class_type": "LTXVLatentUpsampler",
               "inputs": {"samples": ["27", 0], "upscale_model": ["5", 0], "vae": ["3", 0]}},
        "31": {"class_type": "LTXVImgToVideoInplace",
               "inputs": {"vae": ["3", 0], "image": ["7", 0], "latent": ["30", 0],
                          "strength": refine_strength, "bypass": False}},
        "32": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["31", 0], "audio_latent": ["27", 1]}},
        # The template fixes stage 2's noise at 42; only stage 1 takes the seed.
        "33": {"class_type": "RandomNoise", "inputs": {"noise_seed": 42}},
        "34": {"class_type": "ManualSigmas", "inputs": {"sigmas": LTX25_SIGMAS_2}},
        "35": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["33", 0], "guider": ["11", 0], "sampler": ["12", 0],
                          "sigmas": ["34", 0], "latent_image": ["32", 0]}},
        "36": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["35", 0]}},

        # --- out: frames only ---
        "40": {"class_type": "VAEDecodeTiled",
               "inputs": {"samples": ["36", 0], "vae": ["3", 0], "tile_size": 512,
                          "overlap": 64, "temporal_size": 64, "temporal_overlap": 16}},
        "41": {"class_type": "SaveAnimatedWEBP",
               "inputs": {"images": ["40", 0], "filename_prefix": prefix, "fps": 24.0,
                          "lossless": False, "quality": 90, "method": "default"}},
    }


def recipe25(image: str, prompt: str, *, seed: int = 12345, width: int = PRIMARY[0],
             height: int = PRIMARY[1], length: int = 17, fps: float = 48.0,
             strength: float = 0.7, refine_strength: float = 1.0, **_ignored) -> dict:
    return {"image": image, "prompt": prompt, "seed": seed, "width": width,
            "height": height, "length": length, "variant": "2.5", "fps": fps,
            "strength": strength, "refine_strength": refine_strength,
            "model": LTX25["unet"], "lead": LTX25_LEAD.strip()}
