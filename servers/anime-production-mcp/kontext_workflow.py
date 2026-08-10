"""
kontext_workflow.py — build the ComfyUI API graph for FLUX.1 Kontext editing.

Why this path exists at all: LTX cannot animate eye- or mouth-scale features.
A blink is roughly 0.2% of frame pixels and about four latent pixels wide after
the VAE's 8x compression — there is nothing there for it to move, and no seed or
prompt wording changes that. Blinks and mouth flaps therefore come from
generated KEYFRAMES (this graph), played back by a frame player.

⚠ NEVER SHIP THE OUTPUT WHOLESALE. Kontext regenerates the WHOLE frame, so it
can quietly restyle linework, shift colour, or alter parts nobody asked about.
The intended use is to composite ONLY the changed region
(the eye or mouth patch) back over the original art. `composite_patch` in
tools/framing.py is the other half of that.

Also: Kontext is BINARY. It cannot draw a half-lid. Blend an open and a closed
composite for mid positions.

⚠ HANDS: IT REPAIRS THEM AT Q6, AND DID NOT AT Q3. This file previously said
"do not promise this repairs hands", which was correct for the model it was
measured on and wrong about the tool.

Same six damaged frames, three seeds each, identical prompt and box:

    Q3_K_S   0 of 18 takes usable outright, 0 of 6 frames rescued
    Q6_K     every frame produced at least one usable take
             (of 9 takes: 1 good, 4 needing one line drawn, 1 heavy, 3 discard)

Run THREE SEEDS and expect to discard some — a third of Q6 takes are still bad,
fused fingers included. That is fine; only one has to land. The grade that
matters is not pass/fail but COST: "one line drawn" and "full manual redraw" are
different jobs, and Q6 moved most outcomes into the first.

Prior finding that did NOT survive: "repairs a GRIP, not an open hand", built on
n=2 and later contradicted at Q3. Whether an open hand blurred to nothing is
recoverable at Q6 is UNTESTED — 0-for-7 at Q3 says nothing about Q6 now.

⚠ AND MASKED INPAINTING HAS NEVER BEEN TRIED. Every attempt above used this
graph — INSTRUCTION-EDIT mode, hand it the whole frame and hope. For "this
region is destroyed", inpainting is the right technique: mask the hand, generate
into the hole with the surrounding arm and object as context, leave every other
pixel untouched by construction rather than by compositing afterwards.
SetLatentNoiseMask, VAEEncodeForInpaint, DifferentialDiffusion and
InpaintModelConditioning all ship with ComfyUI. Before concluding that Kontext
cannot repair hands, try the mode built for it.

Nothing in this module talks to ComfyUI — it returns a dict. comfy.py submits.
"""

from __future__ import annotations

# ⚠ QUANTISATION IS A QUALITY DIAL, NOT ONLY A SIZE ONE, and this line was set
# wrong for months. Q3_K_S is 5.2 GB for a 12B model — about 3.3 bits per weight
# — and fine structure under hard constraints (hands, faces, text) is what
# degrades first when you quantise that far. FLUX's reputation for hands is
# earned at fp8/fp16. Fused fingers and extra digits out of a FLUX-based model
# are a BIT-DEPTH symptom, not an architecture one.
#
# It was chosen to fit a 6 GB card, which was never the real constraint: the
# same card runs a 14.2 GB LTX model daily, because ComfyUI offloads to system
# RAM and streams weights. Q6_K (9.85 GB) and even Q8_0 (12.7 GB) sit inside
# what is already demonstrated to work. Same mistake as defaulting LTX to
# 832x576 — a limit assumed rather than measured.
#
# MEASURED 2026-08-10, and decisively: on six damaged frames at three seeds
# each, Q3_K_S produced ZERO usable repairs in 18 attempts while Q6_K produced a
# usable take for EVERY frame it was given. Same time per edit (~233 s), 5127
# MiB of 6144 peak. Q3_K_S has since been deleted; re-download from
# QuantStack/FLUX.1-Kontext-dev-GGUF if you ever need it.
UNET = "flux1-kontext-dev-Q6_K.gguf"        # was flux1-kontext-dev-Q3_K_S.gguf
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
