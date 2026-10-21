"""
ltx_workflow.py — build the ComfyUI API graph for LTX-2.5 image-to-video.

LTX-2.3 WAS REMOVED 2026-10-22. On an eight-scene teaser of hand-drawn panels
the artist judged 2.5 "much better" — a real punch toward the viewer, a waltz
turn, a prayer pose, two people talking — and had 2.3 uninstalled. Its graph
(GGUF loaders, Gemma 3, the `distilled`/`dev` variants) is gone from this file;
git history has it. The lessons below were measured on 2.3 unless marked, and
are kept because they are about pictures, not about that model.

RESOLUTION IS THE LEVER. This module defaulted to 832x576 for two days because
it was fast; that cost an artist 65 hand-repaired frames on a single 15-panel
scene, and the seven panels that came back clean were the ones that barely moved.

    DO NOT PICK A SIZE BY HAND — call pick_size(src_w, src_h). It matches the
    ARTWORK'S OWN ASPECT and then maximizes pixels inside a budget. The model
    silently resizes its input to whatever it is given, so a fixed "good
    default" stretches every panel of a different shape. 1216x832 art at a
    1920x1088 default ships 20% too wide, with no warning.

Why: at 832x576 a hand is ~40px, which after the VAE's 8x compression is ~5
latent pixels. There is not enough there to draw fingers, so any hand that MOVES
becomes mush. That is a resolution problem and no seed fixes it.

⚠ FRAME COUNT FLIPPED BETWEEN VERSIONS. 2.3 was clean only at 17 frames (25
smeared, 33 lost a finger, 49 grew a third arm). 2.5 is the opposite: at 17
frames it has three latent frames, so every take sat still to frame 8, lurched
at frame 9 and tore faces; at 49 or 97 frames and 24 fps it came back clean.
Use 2.5's own settings — 24 fps, 49 (2 s) or 97 (4 s) frames.

⚠ LTX DECLINES AN ASK IT CANNOT MEET RATHER THAN SMEARING. 2.3 asked for a
kick scored 3.6/5.8/8.2 against a scene typical of 11-48 and barely moved the
leg; 2.5 asked to grow ice raised the hand ~3% and grew almost nothing. An
unusually LOW motion score means "it refused", not "it is subtle".

PROMPTS (both versions): camera first, then the motion, then what stays still,
4-8 sentences, phrased positively — negatives are ignored. The first motion
named gets the motion budget, so lead with the one that matters. 2.5 notes:
"blinks" became eyes closed for good on three seeds; "her eyes close, then open
wide, then close again" produced a blink on one seed in three. A head drawn in
profile turned toward the camera unasked until the prompt said it stays in
profile.

⚠ WHERE DAMAGE LANDS MOVES WITH RESOLUTION. At 0.5 MP defects sat MID-CLIP and
needed drawing; at ~2 MP every rejected take had its damage in the final few
frames, where a cut costs nothing. Find the bad window; don't blind-truncate.
A mid-clip drop of 2-3 frames is fine — 0.17-0.25 s at 12 fps reads as a faster
action, not a hole.

Nothing in this module talks to ComfyUI — it returns a dict. klein.py submits.
"""

from __future__ import annotations

# ⚠ DO NOT HARDCODE A DEFAULT SIZE. Use pick_size(). A fixed default is the
# wrong SHAPE of answer, and getting this wrong is silent: the model resizes the
# input to whatever width/height it is given, with no letterboxing and no
# complaint. These two are kept only as reference points:
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


# --------------------------------------------------------------------------- #
# LTX-2.5 — on the Klein ComfyUI (v0.41, port 8189), not the main one
# --------------------------------------------------------------------------- #
#
# Added 2026-10-20, judged "much better" than 2.3 on 2026-10-21, and the only
# LTX since 2026-10-22, when 2.3 was removed. 2.5 needs ComfyUI >= 0.32, which the main
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
#   * Output is frames only, saved as animated webp. The model
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
