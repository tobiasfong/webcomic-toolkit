"""
flux_workflow.py — FLUX.1-dev / FLUX.1-Kontext-dev generation, wired in as Stage 5
of the FLUX exploration recorded in ARCHITECTURE.md §8b.9 and this project's
CHANGELOG. Additive alongside workflow.py's SD1.5/SDXL pipeline — nothing there
is touched or removed; `model="flux_manwha"` is just a new option wherever a
model name is accepted.

FLUX's ComfyUI graph shares almost no node types with SD1.5/SDXL (GGUF unet
loading, dual CLIP text encoders, flux-specific model sampling/guidance nodes,
cfg=1.0 samplers), so this is a separate module rather than more branches
threaded through workflow.py's build_graph() — that function is already dense
with SD1.5/SDXL/Tier-2 branches, and FLUX's shape is different enough that
sharing it would trade a working, well-tested function for a much harder to
read one. Shares ComfyUI plumbing (COMFY_URL, ensure_comfy_running,
_upload_image, ComfyUIError, the clean-backdrop prompt suffix) from workflow.py
by import — no duplicated connection/backdrop logic.

Three capabilities, each validated live before being wired in here (see
CHANGELOG's "FLUX exploration" entry for the full record, including what did
NOT work):

1. `generate()` / `generate_concepts()` — base FLUX txt2img, optionally with
   the mannequin's ControlNet pose map for back views (~2/3-seed reliable —
   an alpha-quality community ControlNet adapter, not a tuning problem) and/or
   a hand-only Impact Pack detail_fix pass (denoise=0.7, needed — 0.55 was
   insufficient). No IP-Adapter/identity_mode support — that combination with
   FLUX has never been tested; identity here comes from the prompt/description
   text alone (same as SD1.5/SDXL's plain-text-only path).

2. `edit_image()` — FLUX Kontext dev used as a pure image *editor* (no LoRA):
   takes an existing image + a plain-English instruction. Validated for local
   anatomy fixes on a pose that's already facing the right direction (e.g.
   exposing hidden hands). NOT validated, and one test actively disproved,
   using this for a full viewpoint rotation in one edit — "turn him around"
   plus "keep everything else the same" are self-contradicting for a full
   pose change, and produced a chimera (back-facing head/hands, front-facing
   torso/shoes) rather than a clean back view. Use generate_turnaround_sheet
   for direction changes instead.

3. `generate_turnaround_sheet()` — FLUX Kontext dev + a dedicated turnaround-
   sheet LoRA (Civitai 1753109, trained with Ostris AI Toolkit): takes one
   reference image, produces a multi-pose sheet (typically 7 panels: some
   repeats of front/3-4/profile alongside a back view). First test (matching
   the creator's "recommended prompt" verbatim) produced zero genuine back
   views out of 7 — traced to that recommended prompt inserting the word
   "exact" into the LoRA's literal required trigger substring ("create
   turnaround sheet of this character"), diluting it. Dropping that one word
   (FLUX_TURNAROUND_PROMPT below) fixed it on retest — one confirmed clean
   back view, whole-figure-verified (correct back collar, back seam, rear
   pockets, no belt buckle, clean hands). One successful seed so far, not yet
   a measured reliability rate the way ControlNet's ~2/3 is.
"""

import os
import uuid
import time
import requests

from workflow import (
    COMFY_URL, ComfyUIError, ensure_comfy_running, _upload_image,
    CLEAN_BACKDROP_SUFFIX, DEFAULT_NEGATIVE,
)

# --- Base FLUX model (Stage 1-3, validated 2026-07-21/22) -------------------
FLUX_MODELS = {
    "flux_manwha": {
        "unet": "flux1-dev-Q3_K_S.gguf",
        "clip1": "t5xxl_fp8_e4m3fn.safetensors",
        "clip2": "clip_l.safetensors",
        "vae": "ae.safetensors",
    },
}
DEFAULT_FLUX_MODEL = "flux_manwha"

# manwha_style @ 1.5 is the validated setting — 1.0 was the initial pick, but
# needed bumping once ControlNet entered the graph (it was losing the fight
# for style/costume against the pose conditioning at 1.0). See CHANGELOG.
FLUX_LORA = os.environ.get("WEBCOMIC_CHAR_FLUX_LORA", "manwha_style.safetensors")
FLUX_LORA_STRENGTH = float(os.environ.get("WEBCOMIC_CHAR_FLUX_LORA_STRENGTH", "1.5"))
FLUX_GUIDANCE = float(os.environ.get("WEBCOMIC_CHAR_FLUX_GUIDANCE", "3.5"))

# InstantX's community "Union" ControlNet — one model, multiple control types
# selected via SetUnionControlNetType's `type` field ("openpose" or "depth",
# both verified live against the running ComfyUI instance's /object_info
# enum, not guessed from docs). Explicitly alpha-quality, which is the likely
# cause of "openpose" mode's seed-dependent (~2/3) direction-lock reliability
# rather than a strength-tuning problem (see CHANGELOG) — "depth" mode
# reaches ~3/3 once the depth map itself is properly calibrated (vrm_depth.py).
FLUX_CONTROLNET_UNION = os.environ.get(
    "WEBCOMIC_CHAR_FLUX_CONTROLNET", "flux_controlnet_union_alpha.safetensors")
FLUX_DEFAULT_POSE_STRENGTH = float(os.environ.get("WEBCOMIC_CHAR_FLUX_POSE_STRENGTH", "0.8"))

# Impact Pack hand-only detail_fix. FLUX needed a higher denoise than SDXL's
# 0.6 — 0.55 detected the hand correctly but wasn't enough to redraw finger
# structure (still 6 fingers on live inspection); 0.7 fixed it. No face-pass
# equivalent was ever tested for FLUX (unlike SDXL's face+hand double pass) —
# only wiring what's actually validated.
FLUX_DETAIL_HAND_DENOISE = float(os.environ.get("WEBCOMIC_CHAR_FLUX_HAND_DENOISE", "0.7"))

# Every FLUX generate() call asks for visible hands explicitly — validated
# fix for this recipe's systematic tendency to stuff hands into pockets/
# sleeves when not told otherwise (see CHANGELOG). Harmless on close-ups where
# hands aren't in frame at all.
FLUX_HAND_VISIBLE_SUFFIX = ", both hands visible, relaxed open hands"

# --- FLUX Kontext dev (Stage 4, validated 2026-07-22) ------------------------
# Same T5/CLIP-L/VAE as the base model above — Kontext dev is a direct
# conversion of the same base architecture, confirmed by not needing separate
# text-encoder/VAE downloads.
FLUX_KONTEXT_MODEL = {
    "unet": "flux1-kontext-dev-Q3_K_S.gguf",
    "clip1": "t5xxl_fp8_e4m3fn.safetensors",
    "clip2": "clip_l.safetensors",
    "vae": "ae.safetensors",
}
FLUX_KONTEXT_GUIDANCE = float(os.environ.get("WEBCOMIC_CHAR_FLUX_KONTEXT_GUIDANCE", "2.5"))
FLUX_KONTEXT_STEPS = int(os.environ.get("WEBCOMIC_CHAR_FLUX_KONTEXT_STEPS", "20"))

FLUX_TURNAROUND_LORA = os.environ.get(
    "WEBCOMIC_CHAR_FLUX_TURNAROUND_LORA", "kontext-turnaround-sheet-v1.safetensors")
FLUX_TURNAROUND_LORA_STRENGTH = float(
    os.environ.get("WEBCOMIC_CHAR_FLUX_TURNAROUND_LORA_STRENGTH", "1.0"))
# The validated fix (2026-07-22): the creator's "recommended prompt" inserts
# "exact" into the LoRA's literal required trigger substring ("create
# turnaround sheet of this character"), which measurably weakened it — a first
# attempt with "exact" produced zero genuine back views out of 7 panels; the
# identical settings minus that one word produced a genuine, whole-figure-
# verified back view. Do not reintroduce "exact" here without retesting.
#
# Second validated fix (2026-07-23/24, real Trevor run, ARCHITECTURE.md
# §8b.11): a short/wide canvas (the old 1536x768 default) biases Kontext
# toward a squat figure regardless of what the reference image actually
# shows — Kontext appears to infer body proportions partly from absolute
# canvas HEIGHT, not just the reference. Fixed by both raising the default
# height (768 -> 1280, a taller canvas, not just the same aspect scaled up)
# AND stating the proportion requirement directly in the prompt itself — the
# canvas fix alone was not enough, and the prompt fix alone was not enough
# either; both together is what fixed it. Confirmed on a live reroll: this
# combination can still occasionally over-anchor a panel's POSE (e.g.
# produce a duplicate front view instead of a genuine 3/4 angle) — if that
# happens, a plain reroll with a new seed at the same settings resolved it
# for free, cheaper than fighting the prompt further.
FLUX_TURNAROUND_PROMPT = (
    "create a turnaround sheet of this character, 5 full-body poses on pure white "
    "background: front view, 3/4 left, left profile, back view, right profile, 3/4 right "
    "— evenly spaced in a clean horizontal row, consistent lighting and style, no "
    "background noise, no shadows, same proportions and detailing across all views. "
    "Maintain scale and proportion — do not compress, squash, or shorten the figure "
    "vertically to fit the frame. Preserve the character's exact body proportions from "
    "the reference image in every one of the five poses — do not draw the figure "
    "shorter, stumpier, or more squat in any panel than in the reference."
)
FLUX_TURNAROUND_WIDTH = int(os.environ.get("WEBCOMIC_CHAR_FLUX_TURNAROUND_WIDTH", "1536"))
FLUX_TURNAROUND_HEIGHT = int(os.environ.get("WEBCOMIC_CHAR_FLUX_TURNAROUND_HEIGHT", "1280"))


def _submit_and_wait(graph: dict, output_node: str = "12", timeout: int = 300) -> bytes:
    r = requests.post(f"{COMFY_URL}/prompt", json={"prompt": graph}, timeout=30)
    if r.status_code != 200:
        raise ComfyUIError(f"Prompt rejected ({r.status_code}): {r.text[:300]}")
    prompt_id = r.json()["prompt_id"]

    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2.0)
        h = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=30).json()
        if prompt_id in h:
            outs = h[prompt_id]["outputs"]
            if output_node not in outs:
                raise ComfyUIError("Generation produced no image (check ComfyUI log).")
            img = outs[output_node]["images"][0]
            params = {"filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]}
            return requests.get(f"{COMFY_URL}/view", params=params, timeout=60).content
    raise ComfyUIError(f"Timed out after {timeout}s")


def _save(data: bytes, out_dir: str, stem: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, stem)
    out_path = base + ".png"
    n = 1
    while os.path.exists(out_path):
        out_path = f"{base}_{n}.png"
        n += 1
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def _build_base_graph(
    prompt: str, negative: str, width: int, height: int, seed: int, steps: int,
    guidance: float, unet_name: str, clip1: str, clip2: str, vae_name: str,
    lora_name: str | None, lora_strength: float,
    pose_ref_name: str | None = None, pose_strength: float = FLUX_DEFAULT_POSE_STRENGTH,
    pose_preprocess: bool = True, detail_fix: bool = False,
    pose_control_type: str = "openpose",
) -> dict:
    g = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet_name}},
        "4": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": clip1, "clip_name2": clip2, "type": "flux"}},
        "10": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
    }
    base_model = ["1", 0]
    base_clip = ["4", 0]
    vae_ref = ["10", 0]

    if lora_name:
        g["2"] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": base_model, "lora_name": lora_name,
                             "strength_model": lora_strength}}
        base_model = ["2", 0]

    g["3"] = {"class_type": "ModelSamplingFlux",
              "inputs": {"model": base_model, "max_shift": 1.15, "base_shift": 0.5,
                         "width": width, "height": height}}
    base_model = ["3", 0]

    g["5"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": base_clip}}
    g["6"] = {"class_type": "FluxGuidance", "inputs": {"conditioning": ["5", 0], "guidance": guidance}}
    g["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": base_clip}}
    pos_ref, neg_ref = ["6", 0], ["7", 0]

    # ControlNet pose branch — two validated sources, selected by
    # pose_control_type:
    #   "openpose" — mannequin.py's synthesized line-skeleton (used since
    #     v1.0.0), run through OpenposePreprocessor unless pose_preprocess is
    #     False (the map is already OpenPose-format, e.g. from mannequin.py).
    #   "depth" — vrm_depth.py's rendered depth map from the real VRM mesh
    #     (ARCHITECTURE.md §8b.9) — validated 2026-07-22/23 as MORE reliable
    #     for back views (3/3 seeds vs. ~2/3 for the skeleton), but ONLY once
    #     the depth map's near/far window is properly calibrated (see
    #     vrm_depth.py) and ONLY with a costume-neutral prompt (the VRM mesh's
    #     plain-shirt geometry conflicts with text describing a different
    #     outfit — see flux_workflow.py's/vrm_depth.py's docstrings). Never
    #     run OpenposePreprocessor on a depth map — it isn't a pose skeleton.
    if pose_control_type not in ("openpose", "depth"):
        raise ComfyUIError(
            f"Unknown pose_control_type '{pose_control_type}'. Options: openpose, depth."
        )
    if pose_control_type != "openpose":
        pose_preprocess = False  # safety: OpenposePreprocessor never applies to depth maps

    if pose_ref_name:
        g["30"] = {"class_type": "LoadImage", "inputs": {"image": pose_ref_name}}
        if pose_preprocess:
            g["31"] = {"class_type": "OpenposePreprocessor",
                       "inputs": {"image": ["30", 0], "detect_hand": "enable",
                                  "detect_body": "enable", "detect_face": "enable",
                                  "resolution": 512}}
            pose_image_ref = ["31", 0]
        else:
            pose_image_ref = ["30", 0]
        # Same Union ControlNet model for both control types — SetUnionControlNetType's
        # `type` value below is what actually switches its behavior, not the file.
        g["32"] = {"class_type": "ControlNetLoader",
                   "inputs": {"control_net_name": FLUX_CONTROLNET_UNION}}
        g["33"] = {"class_type": "SetUnionControlNetType",
                   "inputs": {"control_net": ["32", 0], "type": pose_control_type}}
        g["34"] = {"class_type": "ControlNetApplyAdvanced",
                   "inputs": {"positive": pos_ref, "negative": neg_ref,
                              "control_net": ["33", 0], "image": pose_image_ref,
                              "vae": vae_ref, "strength": pose_strength,
                              "start_percent": 0.0, "end_percent": 1.0}}
        pos_ref, neg_ref = ["34", 0], ["34", 1]

    g["8"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}}
    g["9"] = {"class_type": "KSampler",
              "inputs": {"model": base_model, "seed": seed, "steps": steps, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple",
                         "positive": pos_ref, "negative": neg_ref,
                         "latent_image": ["8", 0], "denoise": 1.0}}
    g["11"] = {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": vae_ref}}
    final_ref = ["11", 0]

    if detail_fix:
        g["20"] = {"class_type": "UltralyticsDetectorProvider", "inputs": {"model_name": "bbox/hand_yolov8s.pt"}}
        g["21"] = {"class_type": "FaceDetailer",
                   "inputs": {
                       "image": final_ref, "model": base_model, "clip": base_clip, "vae": vae_ref,
                       "guide_size": 512, "guide_size_for": True, "max_size": 1024,
                       "seed": seed + 1, "steps": steps, "cfg": 1.0,
                       "sampler_name": "euler", "scheduler": "simple",
                       "positive": pos_ref, "negative": neg_ref, "denoise": FLUX_DETAIL_HAND_DENOISE,
                       "feather": 5, "noise_mask": True, "force_inpaint": True,
                       "bbox_threshold": 0.5, "bbox_dilation": 10, "bbox_crop_factor": 3.0,
                       "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
                       "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
                       "sam_mask_hint_use_negative": "False", "drop_size": 10,
                       "bbox_detector": ["20", 0], "wildcard": "", "cycle": 1,
                   }}
        final_ref = ["21", 0]

    g["12"] = {"class_type": "SaveImage", "inputs": {"images": final_ref, "filename_prefix": "flux_pose"}}
    return g


def generate(
    prompt: str,
    out_dir: str,
    negative: str = DEFAULT_NEGATIVE,
    width: int = 832,
    height: int = 1216,
    seed: int | None = None,
    steps: int = 25,
    guidance: float = FLUX_GUIDANCE,
    model: str = DEFAULT_FLUX_MODEL,
    lora: str | None = None,
    lora_strength: float | None = None,
    pose_ref_path: str | None = None,
    pose_strength: float = FLUX_DEFAULT_POSE_STRENGTH,
    pose_preprocess: bool = True,
    pose_control_type: str = "openpose",
    detail_fix: bool = False,
    timeout: int = 600,
) -> str:
    """Base FLUX generation. No img2img/identity-conditioning ref_path (unlike
    workflow.generate()) — untested combination; identity comes from the
    prompt/description text alone, same as this project's plain-text-only
    path. detail_fix runs the hand-only Impact Pack pass (denoise=0.7) — no
    face pass, that combination was never tested for FLUX.

    pose_ref_path + ControlNet is the validated mechanism for back views, in
    two flavors selected by pose_control_type:

    - "openpose" (default): mannequin.render_pose_map(yaw=180), pose_strength
      =0.8, pose_preprocess=False. ~2/3-seed direction-lock reliability.
    - "depth": vrm_depth.render_depth_map(yaw=180) — a real posable VRM
      mesh's depth map, ~3/3-seed reliability once calibrated (see
      vrm_depth.py). pose_preprocess is forced off automatically for this
      mode. IMPORTANT: `prompt` must NOT describe the character's actual
      costume in this mode — the VRM mesh wears a plain t-shirt, and
      describing a different outfit causes a text-vs-geometry conflict
      (ragged texture-clash artifacts). Use a costume-neutral prompt here,
      then apply the real costume afterward via edit_character_image as a
      separate pass (ARCHITECTURE.md §8b.9).

    Note: FLUX's negative conditioning has limited effect at cfg=1.0 (guidance
    comes from FluxGuidance instead) — `negative` is passed through for parity
    with workflow.generate()'s signature, but don't expect it to steer the
    result the way it does for SD1.5/SDXL."""
    ensure_comfy_running()
    if model not in FLUX_MODELS:
        raise ComfyUIError(f"Unknown FLUX model '{model}'. Options: {', '.join(FLUX_MODELS)}")
    m = FLUX_MODELS[model]
    if seed is None:
        seed = uuid.uuid4().int % (2**31)

    use_lora = FLUX_LORA if lora is None else lora
    use_lora_strength = FLUX_LORA_STRENGTH if lora_strength is None else lora_strength
    full_prompt = f"{prompt}{CLEAN_BACKDROP_SUFFIX}{FLUX_HAND_VISIBLE_SUFFIX}"

    pose_ref_name = _upload_image(pose_ref_path) if pose_ref_path else None

    graph = _build_base_graph(
        full_prompt, negative, width, height, seed, steps, guidance,
        m["unet"], m["clip1"], m["clip2"], m["vae"],
        use_lora, use_lora_strength,
        pose_ref_name, pose_strength, pose_preprocess, detail_fix,
        pose_control_type,
    )
    data = _submit_and_wait(graph, "12", timeout)
    return _save(data, out_dir, f"flux_{seed}")


def generate_concepts(
    prompt: str,
    out_dir: str,
    n: int = 4,
    negative: str = DEFAULT_NEGATIVE,
    width: int = 832,
    height: int = 1216,
    seed: int | None = None,
    model: str = DEFAULT_FLUX_MODEL,
    lora: str | None = None,
    lora_strength: float | None = None,
    timeout: int = 600,
) -> list[str]:
    """Batch FLUX txt2img candidates — mirrors workflow.generate_concepts()'s
    contract. n=1 is the recommended first step of the staged FLUX workflow: a
    single approved front view before spending the ~5min generate_turnaround_sheet
    call on it."""
    if n < 1:
        raise ComfyUIError("generate_concepts needs n >= 1.")
    paths = []
    for i in range(n):
        s = None if seed is None else seed + i
        paths.append(generate(prompt=prompt, out_dir=out_dir, negative=negative,
                              width=width, height=height, seed=s, model=model,
                              lora=lora, lora_strength=lora_strength, timeout=timeout))
    return paths


def edit_image(
    image_path: str,
    instruction: str,
    out_dir: str,
    seed: int | None = None,
    guidance: float = FLUX_KONTEXT_GUIDANCE,
    steps: int = FLUX_KONTEXT_STEPS,
    lora: str | None = None,
    lora_strength: float = 0.8,
    timeout: int = 300,
) -> str:
    """FLUX Kontext dev as a pure image editor — see module docstring for what
    this is and is not validated for (local fixes: yes; full viewpoint
    rotation in one edit: no, produces a chimera).

    lora: optional LoRA filename (e.g. FLUX_LORA, the manwha/webtoon style
    LoRA) loaded onto the base model before editing — for a restyle pass
    (redraw this exact pose/figure in a specific art style) rather than a
    structural edit. None (default) runs the base Kontext model with no
    LoRA, same as before this parameter existed."""
    ensure_comfy_running()
    if seed is None:
        seed = uuid.uuid4().int % (2**31)
    uploaded = _upload_image(image_path)
    m = FLUX_KONTEXT_MODEL

    g = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": m["unet"]}},
        "4": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": m["clip1"], "clip_name2": m["clip2"], "type": "flux"}},
        "10": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "40": {"class_type": "LoadImage", "inputs": {"image": uploaded}},
        "41": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["40", 0]}},
        "42": {"class_type": "GetImageSize", "inputs": {"image": ["41", 0]}},
        "43": {"class_type": "VAEEncode", "inputs": {"pixels": ["41", 0], "vae": ["10", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": instruction, "clip": ["4", 0]}},
        "44": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["5", 0], "latent": ["43", 0]}},
        "6": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["44", 0], "guidance": guidance}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 0]}},
        "45": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["7", 0]}},
        "8": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": ["42", 0], "height": ["42", 1], "batch_size": 1}},
        "9": {"class_type": "KSampler",
              "inputs": {"model": ["3", 0], "seed": seed, "steps": steps, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple",
                         "positive": ["6", 0], "negative": ["45", 0],
                         "latent_image": ["8", 0], "denoise": 1.0}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["10", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "flux_edit"}},
    }
    if lora:
        g["2"] = {"class_type": "LoraLoaderModelOnly",
                   "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": lora_strength}}
        model_ref = ["2", 0]
    else:
        model_ref = ["1", 0]
    g["3"] = {"class_type": "ModelSamplingFlux",
              "inputs": {"model": model_ref, "max_shift": 1.15, "base_shift": 0.5,
                         "width": ["42", 0], "height": ["42", 1]}}
    data = _submit_and_wait(g, "12", timeout)
    return _save(data, out_dir, f"edit_{seed}")


def generate_turnaround_sheet(
    image_path: str,
    out_dir: str,
    seed: int | None = None,
    width: int = FLUX_TURNAROUND_WIDTH,
    height: int = FLUX_TURNAROUND_HEIGHT,
    steps: int = FLUX_KONTEXT_STEPS,
    guidance: float = FLUX_KONTEXT_GUIDANCE,
    lora_strength: float = FLUX_TURNAROUND_LORA_STRENGTH,
    extra_prompt: str = "",
    timeout: int = 900,
) -> str:
    """FLUX Kontext dev + the turnaround-sheet LoRA — see module docstring for
    the trigger-phrase fix this depends on (FLUX_TURNAROUND_PROMPT). One
    confirmed clean back view so far; not yet a measured reliability rate —
    treat like the mannequin ControlNet path early on: generate, inspect the
    whole figure (not just direction), reroll with a different seed if the
    back-view panel isn't genuinely clean.

    extra_prompt: appended to FLUX_TURNAROUND_PROMPT — use this for a
    character-specific accessory that needs reinforcing across all 5 panels
    (found live on Trevor: glasses were missing/faint in 2 of 5 panels until
    "bold, clearly visible black rectangular glasses in EVERY panel" was
    baked into the prompt directly — patching a bad sheet after the fact
    reliably failed, rerolling with the requirement stated upfront worked).
    Leave blank for characters with no single accessory that needs that kind
    of reinforcement."""
    ensure_comfy_running()
    if seed is None:
        seed = uuid.uuid4().int % (2**31)
    uploaded = _upload_image(image_path)
    m = FLUX_KONTEXT_MODEL
    prompt = f"{FLUX_TURNAROUND_PROMPT} {extra_prompt}" if extra_prompt else FLUX_TURNAROUND_PROMPT

    g = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": m["unet"]}},
        "2": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["1", 0], "lora_name": FLUX_TURNAROUND_LORA,
                         "strength_model": lora_strength}},
        "4": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": m["clip1"], "clip_name2": m["clip2"], "type": "flux"}},
        "10": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "40": {"class_type": "LoadImage", "inputs": {"image": uploaded}},
        "41": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["40", 0]}},
        "43": {"class_type": "VAEEncode", "inputs": {"pixels": ["41", 0], "vae": ["10", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 0]}},
        "44": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["5", 0], "latent": ["43", 0]}},
        "6": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["44", 0], "guidance": guidance}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 0]}},
        "45": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["7", 0]}},
        "3": {"class_type": "ModelSamplingFlux",
              "inputs": {"model": ["2", 0], "max_shift": 1.15, "base_shift": 0.5,
                         "width": width, "height": height}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "9": {"class_type": "KSampler",
              "inputs": {"model": ["3", 0], "seed": seed, "steps": steps, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple",
                         "positive": ["6", 0], "negative": ["45", 0],
                         "latent_image": ["8", 0], "denoise": 1.0}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["10", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "flux_turnaround"}},
    }
    data = _submit_and_wait(g, "12", timeout)
    return _save(data, out_dir, f"turnaround_{seed}")
