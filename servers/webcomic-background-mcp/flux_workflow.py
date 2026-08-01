"""
flux_workflow.py — FLUX.1-dev generation for the background server.

ADDITIVE. `workflow.py`'s SD1.5 pipeline is untouched and remains the default;
`model="flux_manwha"` is simply a new option wherever a model name is accepted.
FLUX's ComfyUI graph shares almost no node types with SD1.5 (GGUF unet loading,
dual CLIP text encoders, flux-specific model-sampling/guidance nodes, cfg=1.0
samplers), so this is a separate module rather than more branches threaded
through `workflow.build_graph()` — the same call the sibling character-panel
server made, for the same reason. ComfyUI plumbing (COMFY_URL, ensure_comfy_
running, _upload_image, ComfyUIError) is imported from workflow.py, not
duplicated.

Rationale for the port: ARCHITECTURE.md §8c. Short version — two different
failures hid under "bad geometry" in the v1.8.0 bicycle session. "Is this a
coherent bicycle?" is base-model quality, and FLUX is markedly better at it.
"Four bikes, 2.2 units apart, one occluded, identical in panel 40" is count/
placement/occlusion/reproducibility, which no base model solves — that stays
props.py's job. So this is FLUX *painting* props.py, not replacing it.

------------------------------------------------------------------------------
ControlNet strength is a fidelity-vs-correction dial, and the right setting
depends on WHERE THE SKETCH CAME FROM. This is the key operational insight:

  • HIGH (0.85-1.0, end_percent ~0.9) — obeys the sketch exactly, errors and
    all. The model is a pure colorist.
    -> Correct for SYNTHETIC geometry (props.py, citygen.py). Those sketches
       are right by construction; "correcting" them would destroy the exact
       placement/occlusion that is the entire reason they exist.

  • MID (0.55-0.7, end_percent ~0.6-0.8) — holds composition, camera and
    gesture, but lets the model resolve proportions and joints itself.
    -> Correct for HAND-DRAWN sketches, where the lines carry intent but the
       proportions may not survive scrutiny. Note the real cost: the model
       corrects toward *generic* anatomy, so deliberate stylization gets
       normalized along with the mistakes. It cannot tell intent from error.

  • LOW (<0.5) — the sketch becomes a loose suggestion; composition is lost.

(Bands established by the character-panel server's live testing; its
tools/sketch_to_lineart.py validated 0.65 / end_percent 0.80 for hand-drawn
line art specifically.)

Also inherited from that server's testing, and the reason this module never
runs a preprocessor by default: feeding a *pencil sketch* through
CannyEdgePreprocessor detects both sides of every stroke, so one drawn line
becomes two parallel control edges and the model paints the doubled hairlines
literally. Every sketch this server produces is ALREADY a white-on-black edge
map (props.prop_sketch, citygen.city_sketch, tools/make_sketch.py), so it is
fed straight through with no preprocessing. For raw hand-drawn input, run
tools/make_sketch.py first — its `drawing` mode binarizes instead of Canny-ing.

FLUX caveat worth knowing before tuning prompts: at cfg=1.0 negative
conditioning is WEAK. A prompt saying "no people" still put a person in a test
library scene; the fix was rewriting the POSITIVE prompt to stop implying a
subject. Do not expect SD1.5's negative prompts to carry over — re-tune
positively.
"""

import os
import uuid

import cv2

from workflow import (
    COMFY_URL, ComfyUIError, ensure_comfy_running, _upload_image,
    _submit_and_wait,
)

# FLUX's SaveImage lives at node "12" (SD1.5's is "9") — the graphs share no
# numbering, so every _submit_and_wait call here passes it explicitly.
_SAVE_NODE = "12"


def _unique_out_path(out_dir: str, stem: str) -> str:
    """`out_dir/stem.png`, with a numeric suffix if that name is taken —
    same no-clobber rule workflow.generate() applies to SD1.5 renders (a
    fixed-seed sweep would otherwise overwrite itself)."""
    base = os.path.join(out_dir, stem)
    out_path = base + ".png"
    n = 1
    while os.path.exists(out_path):
        out_path = f"{base}_{n}.png"
        n += 1
    return out_path

# --- models -----------------------------------------------------------------
FLUX_MODELS = {
    "flux_manwha": {
        "unet": "flux1-dev-Q3_K_S.gguf",      # Q3_K_S, not the "recommended"
        "clip1": "t5xxl_fp8_e4m3fn.safetensors",  # Q4_K_S — 6 GB VRAM budget
        "clip2": "clip_l.safetensors",            # (RTX 3060 *Laptop*)
        "vae": "ae.safetensors",
    },
}
DEFAULT_FLUX_MODEL = "flux_manwha"

# NOT ManhwaUltimate.safetensors — that is an SD1.5 LoRA and cannot load on
# FLUX at all (same architecture mismatch that got the SDXL Midjourney Manga
# LoRA rejected in v1.7.0). manwha_style is the FLUX-native equivalent, shared
# with the character-panel server. Expect a different palette from the SD1.5
# recipe as a result; that is the LoRA, not a bug.
FLUX_LORA = os.environ.get("WEBCOMIC_BG_FLUX_LORA", "manwha_style.safetensors")
# 1.5 is the best setting FOR MANHWA STYLING specifically. 1.0 renders washed
# out (style loses the fight against ControlNet conditioning — character
# server's finding, reproduced here). 2.0 goes muddy/grainy under ControlNet,
# so don't raise it for sketch-conditioned work.
#
# But 2.0 in plain txt2img is not simply "worse" — it drifts toward
# photorealistic/cinematic, which is LESS webtoon yet produced the single
# best-lit frame of the whole sweep (strong raking light, cool-vs-warm colour
# separation, real depth). For a grimdark 40K panel that painterly-realistic
# register may be more on-genre than webtoon flatness. Treat 2.0 as a
# different aesthetic worth reaching for deliberately, not a failed setting.
FLUX_LORA_STRENGTH = float(os.environ.get("WEBCOMIC_BG_FLUX_LORA_STRENGTH", "1.5"))

# --- Which model should you actually use? (measured 2026-07-28) --------------
# CORRECTED: an earlier version of this note claimed FLUX simply can't do
# manhwa and that SD1.5 was required for styling. That was wrong. The
# character-panel server ships a genuinely manhwa-looking plate
# (plates/topdown/flux_3141.png) from straight FLUX txt2img at manwha_style
# @ 1.5 — nothing hand-painted. Our own best-looking renders were likewise
# txt2img. FLUX's styling is fine.
#
# The real boundary is narrower and it is CONTROLNET, not the model:
#
#   FLUX txt2img            luminance std ~0.26-0.29 — rich tonal range, reads
#                           manhwa. This is FLUX working properly.
#   FLUX + edge-map sketch  luminance std ~0.03-0.08 — 3-4x flatter than our own
#                           APPROVED SD1.5 plate (0.123). Reads semi-realistic
#                           and murky.
#
# Cause: the control map's own luminance bleeds into the render. Our edge maps
# are ~99% black (mean luminance 0.008), which drags the whole frame dark and
# flat. Confirmed by inverting the sketch to ~99% white: std jumped 0.041 ->
# 0.156. But inversion is NOT a fix — it flips which side gets painted
# literally, and the objects render as glowing white ghosts. Both polarities
# leak; only the artifact changes.
#
# Also ruled out: a no-ControlNet hires repaint does not recover the tone
# (0.041 -> 0.044 at denoise 0.35, -> 0.049 at 0.55). The flatness is baked in
# at generation time.
#
#   Need exact staging AND rich tone        -> SD 1.5 (solstice + ManhwaUltimate).
#                                              Still the default; its ControlNet
#                                              does not flatten the render.
#   Need correct object geometry            -> FLUX + sketch. Bicycles/props come
#     (props, vehicles, machinery)             out right where SD1.5 deformed them
#                                              — at the cost of flatter tone.
#   Need the best-looking FLUX plate        -> FLUX txt2img, no sketch. Composition
#                                              is whatever the seed gives you.
#   Need cross-panel location consistency   -> SD 1.5 + World Builder, or FLUX
#                                              + props/citygen geometry.
#
# STILL OPEN: making ControlNet hold composition without flattening tone. Not
# yet tried — Kontext editing an already-approved plate (the mechanism that
# solved consistency on the character side), and re-aiming/reusing one good
# txt2img plate across panels rather than regenerating per panel.
#
# Measure, don't eyeball (character server's trick, and it works):
#   L = (np.asarray(img,float)/255 * [0.299,0.587,0.114]).sum(2)
#   L.mean(), L.std()
# Our approved SD1.5 bike plate sits at mean 0.138 / std 0.123. But check the
# IMAGE too — an inverted control map scored 0.156 while looking terrible.
FLUX_GUIDANCE = float(os.environ.get("WEBCOMIC_BG_FLUX_GUIDANCE", "3.5"))
FLUX_STEPS = int(os.environ.get("WEBCOMIC_BG_FLUX_STEPS", "20"))

# Union Pro 2.0, not the alpha. Pro 2.0 is trained as one unified conditioner
# and DROPPED the alpha's per-type embedding, so the union type is "auto" —
# naming a specific type misroutes it. This also dissolves the old worry that
# "scribble" has no FLUX equivalent: there are no per-type slots to match.
FLUX_CONTROLNET = os.environ.get(
    "WEBCOMIC_BG_FLUX_CONTROLNET", "flux_controlnet_union_pro2.safetensors")
FLUX_CONTROLNET_UNION_TYPE = "auto"

# --- ControlNet window, MEASURED on this server 2026-07-28 -------------------
# An 8-render sweep against a props.py bike-row sketch (seed fixed at 4242).
# The dominant variable turned out to be END_PERCENT, not strength — FLUX keeps
# injecting the edge map's luminance through the detail/colour phase, so
# releasing it early is what produces solid painted objects instead of glowing
# outlines:
#
#   strength/end   result
#   0.85 / 0.90    composition perfect, but bikes are glowing white outlines
#                  on near-black — the control map painted literally. Unusable.
#   0.65 / 0.80    composition held; still washed out and ghostly.
#   0.80 / 0.55    still ghostly.
#   0.90 / 0.40    solid, correctly-drawn bikes. First usable result.
#   0.95 / 0.30    BEST — solid bikes, gothic arches, real materials/lantern.
#   0.90 / 0.20    beautiful, but composition starts drifting off the sketch.
#   0.50 / 0.70    lovely art, composition LOST (floating detached wheels).
#
# So: hold the sketch HARD but RELEASE IT EARLY. Structure is decided in the
# first ~30% of denoising; after that the ControlNet only does damage.
#
# Shipping 0.40 rather than the 0.30 that rendered prettiest, deliberately:
# 0.30 produced the single best-looking frame but composition drifted (a live
# end-to-end run of generate_prop_scene with n_bikes=4 painted ONE bicycle),
# while 0.40 held the row solidly. For SYNTHETIC geometry, exact count and
# placement IS the reason the sketch exists — trading it for a slightly richer
# render defeats the purpose. Drop to 0.30 for hero plates where you care more
# about the painting than the staging.
#
# ⚠️ Composition hold on FLUX is APPROXIMATE, not the near-exact reproduction
# SD1.5 gives at 0.95. Expect to reroll for exact counts; this is the same
# alpha-quality-ControlNet-ecosystem limitation the character server hit
# (~2/3 seed reliability on direction lock).
CN_SYNTHETIC_STRENGTH = float(os.environ.get("WEBCOMIC_BG_FLUX_CN_SYNTHETIC", "0.95"))
CN_SYNTHETIC_END = 0.40
# Hand-drawn input wants a little more freedom (the model should resolve
# proportions the drawing got wrong) but the same early release. NOTE: unlike
# the synthetic numbers above, this pair is interpolated, not swept — the
# character server validated 0.65/0.80 for sparse character lineart, but this
# server's sketches are far denser and bled badly at end_percent 0.80.
CN_DRAWN_STRENGTH = float(os.environ.get("WEBCOMIC_BG_FLUX_CN_DRAWN", "0.70"))
CN_DRAWN_END = 0.45

# FLUX's own webtoon-ish styling. Deliberately NOT a copy of workflow.py's
# SD1.5 RECIPE_* strings — those were tuned against a different base model.
FLUX_PROMPT_SUFFIX = ("painterly soft lighting, atmospheric perspective, "
                      "korean webtoon background art, soft gradients, cinematic, "
                      "highly detailed background illustration")
# Kept short on purpose: at cfg=1.0 this does little. Steer positively instead.
FLUX_NEGATIVE = "people, person, figure, text, watermark, blurry, low quality"


def sketch_defaults(synthetic: bool) -> tuple[float, float]:
    """(strength, end_percent) for a sketch of the given provenance."""
    return ((CN_SYNTHETIC_STRENGTH, CN_SYNTHETIC_END) if synthetic
            else (CN_DRAWN_STRENGTH, CN_DRAWN_END))


def build_graph(
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int = FLUX_STEPS,
    guidance: float = FLUX_GUIDANCE,
    model: str = DEFAULT_FLUX_MODEL,
    lora_name: str | None = None,
    lora_strength: float | None = None,
    sketch_name: str | None = None,
    controlnet_strength: float = CN_SYNTHETIC_STRENGTH,
    controlnet_end_percent: float = CN_SYNTHETIC_END,
    init_image_name: str | None = None,
    denoise: float = 1.0,
    filename_prefix: str = "flux_bg",
) -> dict:
    """Assemble the FLUX ComfyUI API graph.

    sketch_name: an ALREADY-EDGE-MAPPED image (white lines on black). No
        preprocessor is applied — see the module docstring.
    init_image_name / denoise: img2img, used by World Builder's `location`
        mode and by the hires re-detail pass.
    """
    if model not in FLUX_MODELS:
        raise ComfyUIError(
            f"Unknown FLUX model '{model}'. Options: {', '.join(FLUX_MODELS)}.")
    m = FLUX_MODELS[model]

    g = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": m["unet"]}},
        "4": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": m["clip1"], "clip_name2": m["clip2"],
                         "type": "flux"}},
        "10": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
    }
    base_model, base_clip, vae_ref = ["1", 0], ["4", 0], ["10", 0]

    use_lora = FLUX_LORA if lora_name is None else lora_name   # "" forces off
    use_strength = FLUX_LORA_STRENGTH if lora_strength is None else lora_strength
    if use_lora:
        g["2"] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": base_model, "lora_name": use_lora,
                             "strength_model": use_strength}}
        base_model = ["2", 0]

    g["3"] = {"class_type": "ModelSamplingFlux",
              "inputs": {"model": base_model, "max_shift": 1.15,
                         "base_shift": 0.5, "width": width, "height": height}}
    base_model = ["3", 0]

    g["5"] = {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": base_clip}}
    g["6"] = {"class_type": "FluxGuidance",
              "inputs": {"conditioning": ["5", 0], "guidance": guidance}}
    g["7"] = {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": base_clip}}
    pos_ref, neg_ref = ["6", 0], ["7", 0]

    # --- ControlNet (composition) — fed a finished edge map, never preprocessed
    if sketch_name:
        g["30"] = {"class_type": "LoadImage", "inputs": {"image": sketch_name}}
        g["32"] = {"class_type": "ControlNetLoader",
                   "inputs": {"control_net_name": FLUX_CONTROLNET}}
        g["33"] = {"class_type": "SetUnionControlNetType",
                   "inputs": {"control_net": ["32", 0],
                              "type": FLUX_CONTROLNET_UNION_TYPE}}
        g["34"] = {"class_type": "ControlNetApplyAdvanced",
                   "inputs": {"positive": pos_ref, "negative": neg_ref,
                              "control_net": ["33", 0], "image": ["30", 0],
                              "vae": vae_ref, "strength": controlnet_strength,
                              "start_percent": 0.0,
                              "end_percent": controlnet_end_percent}}
        pos_ref, neg_ref = ["34", 0], ["34", 1]

    # --- latent: empty (txt2img) or encoded init image (img2img)
    if init_image_name:
        g["40"] = {"class_type": "LoadImage", "inputs": {"image": init_image_name}}
        g["41"] = {"class_type": "VAEEncode",
                   "inputs": {"pixels": ["40", 0], "vae": vae_ref}}
        latent_ref = ["41", 0]
    else:
        g["8"] = {"class_type": "EmptySD3LatentImage",
                  "inputs": {"width": width, "height": height, "batch_size": 1}}
        latent_ref = ["8", 0]
        denoise = 1.0

    g["9"] = {"class_type": "KSampler",
              "inputs": {"model": base_model, "seed": seed, "steps": steps,
                         "cfg": 1.0, "sampler_name": "euler",
                         "scheduler": "simple", "positive": pos_ref,
                         "negative": neg_ref, "latent_image": latent_ref,
                         "denoise": denoise}}
    g["11"] = {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": vae_ref}}
    g["12"] = {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": filename_prefix}}
    return g


def generate(
    prompt: str,
    out_dir: str,
    negative: str | None = None,
    width: int = 896,
    height: int = 672,
    seed: int | None = None,
    steps: int = FLUX_STEPS,
    guidance: float = FLUX_GUIDANCE,
    model: str = DEFAULT_FLUX_MODEL,
    sketch_path: str | None = None,
    sketch_is_synthetic: bool = True,
    controlnet_strength: float | None = None,
    controlnet_end_percent: float | None = None,
    location_ref_path: str | None = None,
    location_denoise: float = 0.65,
    lora: str | None = None,
    lora_strength: float | None = None,
    hires: bool = False,
    append_recipe: bool = True,
    timeout: int = 900,
) -> str:
    """Render a background plate with FLUX; return the saved PNG path.

    sketch_is_synthetic: True when the sketch came from props.py/citygen.py
        (correct by construction -> high ControlNet strength, pure colorist).
        False for hand-drawn input (-> mid strength, model resolves
        proportions). Ignored if controlnet_strength is given explicitly.
    """
    ensure_comfy_running()
    if seed is None:
        seed = uuid.uuid4().int % (2**31)
    if negative is None:
        negative = FLUX_NEGATIVE
    if append_recipe:
        prompt = f"{prompt}, {FLUX_PROMPT_SUFFIX}"

    d_strength, d_end = sketch_defaults(sketch_is_synthetic)
    if controlnet_strength is None:
        controlnet_strength = d_strength
    if controlnet_end_percent is None:
        controlnet_end_percent = d_end

    sketch_name = _upload_image(sketch_path) if sketch_path else None
    init_name = _upload_image(location_ref_path) if location_ref_path else None

    graph = build_graph(
        prompt=prompt, negative=negative, width=width, height=height,
        seed=seed, steps=steps, guidance=guidance, model=model,
        lora_name=lora, lora_strength=lora_strength,
        sketch_name=sketch_name, controlnet_strength=controlnet_strength,
        controlnet_end_percent=controlnet_end_percent,
        init_image_name=init_name,
        denoise=location_denoise if init_name else 1.0,
    )
    data = _submit_and_wait(graph, timeout, _SAVE_NODE)
    os.makedirs(out_dir, exist_ok=True)
    out_path = _unique_out_path(out_dir, f"flux_{seed}")
    with open(out_path, "wb") as f:
        f.write(data)

    if hires:
        return hires_pass(out_path, prompt, negative, model=model, seed=seed,
                          lora=lora, lora_strength=lora_strength,
                          guidance=guidance, timeout=timeout)
    return out_path


def hires_pass(image_path: str, prompt: str, negative: str,
               model: str = DEFAULT_FLUX_MODEL, scale: float = 1.5,
               denoise: float = 0.35, seed: int | None = None,
               lora: str | None = None, lora_strength: float | None = None,
               guidance: float = FLUX_GUIDANCE, steps: int = FLUX_STEPS,
               timeout: int = 900) -> str:
    """Upscale a finished FLUX render and re-detail it at low denoise.

    Mirrors workflow.hires_pass. Keep denoise low — a high value here
    re-generates rather than sharpens, which throws away the composition the
    ControlNet pass just enforced."""
    ensure_comfy_running()
    if seed is None:
        seed = uuid.uuid4().int % (2**31)

    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ComfyUIError(f"could not read image for hires pass: {image_path}")
    h, w = img.shape[:2]
    nw, nh = int(w * scale) // 8 * 8, int(h * scale) // 8 * 8
    up_path = os.path.splitext(image_path)[0] + "_upscaled.png"
    cv2.imwrite(up_path, cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LANCZOS4))

    graph = build_graph(
        prompt=prompt, negative=negative, width=nw, height=nh, seed=seed,
        steps=steps, guidance=guidance, model=model,
        lora_name=lora, lora_strength=lora_strength,
        init_image_name=_upload_image(up_path), denoise=denoise,
        filename_prefix="flux_bg_hires",
    )
    data = _submit_and_wait(graph, timeout, _SAVE_NODE)
    out_path = os.path.splitext(image_path)[0] + "_hires.png"
    with open(out_path, "wb") as f:
        f.write(data)
    try:
        os.remove(up_path)
    except OSError:
        pass
    return out_path
