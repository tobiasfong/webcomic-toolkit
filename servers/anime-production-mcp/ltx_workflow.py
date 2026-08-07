"""
ltx_workflow.py — build the ComfyUI API graph for LTX-2.3 image-to-video.

Lifted from the driver script that produced the reference teaser, so the
defaults here are the SETTLED RECIPE, not a starting guess:

    variant=distilled, length=17, strength=0.9, fps=48   # ~65 s per take

`distilled` at length 17 is ~5x faster than `dev` at 25 **with no motion
penalty** — measured, distilled out-moved dev on the same shot. That speed is
what makes a three-seed hunt affordable at all.

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

# Negative prompts steer only weakly here, but hands and faces are where a bad
# take goes visibly wrong, so they are worth naming.
NEG = "blurry, distorted, deformed hands, extra limbs, warped face, watermark, text"

DEFAULT_PROMPT = ("anime illustration, the character moves slightly, hair and "
                  "clothes sway, subtle natural motion, cel shaded, clean linework")

# Output resolution floor. Below 540 the linework mushes and no upscale recovers
# it — this is a hard floor, not a preference.
MIN_DIM = 540


class RecipeError(ValueError):
    """A parameter combination ComfyUI would reject, caught before submitting."""


def validate(width: int, height: int, length: int, variant: str) -> None:
    if variant not in VARIANTS:
        raise RecipeError(f"variant must be one of {list(VARIANTS)}, got {variant!r}")
    if (length - 1) % 8:
        raise RecipeError(
            f"length must be 8n+1 (got {length}); try 17, 25, 33, 49, 73, 97. "
            f"17 is the settled default — about 1.4 s of motion at 12 fps."
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
          width: int = 832, height: int = 576, length: int = 17,
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
           width: int = 832, height: int = 576, length: int = 17,
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
