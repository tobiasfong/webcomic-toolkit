"""
kontext_workflow.py — build the ComfyUI API graph for FLUX.1 Kontext editing.

Why this path exists at all: LTX cannot animate eye- or mouth-scale features.
A blink is roughly 0.2% of frame pixels and about four latent pixels wide after
the VAE's 8x compression — there is nothing there for it to move, and no seed or
prompt wording changes that. Blinks and mouth flaps therefore come from
generated KEYFRAMES (this graph), played back by a frame player.

⚠ NEVER SHIP THE OUTPUT WHOLESALE. Kontext regenerates the WHOLE frame, so it
can quietly restyle linework, shift colour, or alter parts nobody asked about —
and Q3_K_S is aggressive quantisation, so that risk is higher here than with a
full-precision model. The intended use is to composite ONLY the changed region
(the eye or mouth patch) back over the original art. `composite_patch` in
tools/framing.py is the other half of that.

Also: Kontext is BINARY. It cannot draw a half-lid. Blend an open and a closed
composite for mid positions.

Nothing in this module talks to ComfyUI — it returns a dict. comfy.py submits.
"""

from __future__ import annotations

UNET = "flux1-kontext-dev-Q3_K_S.gguf"
T5 = "t5xxl_fp8_e4m3fn.safetensors"
CLIP_L = "clip_l.safetensors"
VAE = "ae.safetensors"


def build(image: str, edit: str, *, seed: int = 1, steps: int = 20,
          guidance: float = 2.5, prefix: str = "kontext") -> dict:
    """ComfyUI API-format graph for one instruction-driven edit.

    `guidance` is the preservation/obedience dial: lower keeps more of the
    original, higher follows the instruction harder and drifts further. 2.5 is
    the working default.
    """
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": CLIP_L, "clip_name2": T5, "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image}},

        # Kontext expects one of its supported resolutions; this snaps to the
        # nearest without changing the aspect ratio.
        "5": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["4", 0]}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},

        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": edit, "clip": ["2", 0]}},
        # ReferenceLatent is what makes this an EDIT rather than a fresh
        # generation — it pins the conditioning to the source image's latent.
        "8": {"class_type": "ReferenceLatent",
              "inputs": {"conditioning": ["7", 0], "latent": ["6", 0]}},
        "9": {"class_type": "FluxGuidance",
              "inputs": {"conditioning": ["8", 0], "guidance": guidance}},
        # Flux is distilled-guidance: cfg stays 1.0 and the negative is a
        # zeroed-out copy of the positive rather than a real negative prompt.
        "10": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["7", 0]}},

        "11": {"class_type": "KSampler",
               "inputs": {"model": ["1", 0], "seed": seed, "steps": steps, "cfg": 1.0,
                          "sampler_name": "euler", "scheduler": "simple",
                          "positive": ["9", 0], "negative": ["10", 0],
                          "latent_image": ["6", 0], "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["12", 0], "filename_prefix": f"{prefix}_{seed}"}},
    }


def recipe(image: str, edit: str, *, seed: int = 1, steps: int = 20,
           guidance: float = 2.5, **_ignored) -> dict:
    return {"image": image, "edit": edit, "seed": seed,
            "steps": steps, "guidance": guidance, "model": UNET}
