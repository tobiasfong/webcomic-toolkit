"""
workflow.py — Tier-1/Tier-2 character pose generation against a running ComfyUI
instance.

Tier 1 (see ARCHITECTURE.md §8b.2): img2img from a character's reference image,
onto a deliberately plain/clean backdrop, so the result can be auto-matted to a
clean RGBA cutout afterward. Weakest tier, nearly free to build — good for "same
character, slightly different angle/pose," drifts on anything ambitious. Always
on (CLEAN_BACKDROP_SUFFIX is unconditional) — Tier 2 layers on top of it, it
doesn't replace it.

Tier 2 (`identity_mode` + `pose_ref_path`): IP-Adapter (cubiq/ComfyUI_IPAdapter_plus,
presets "PLUS (high strength)" / "PLUS FACE (portraits)") conditions the render on
the reference image's *identity*; an OpenPose ControlNet (via the already-required
comfyui_controlnet_aux node's OpenposePreprocessor) pins the *pose* from a supplied
photo. Both are optional, additive branches on the same graph — off by default so
existing callers/behavior are unaffected until a caller opts in (and so this
doesn't break for anyone who hasn't run setup_models.py's new downloads yet).

Tier 3 (per-character LoRA baking) lives in training.py, not here — see its
docstring. Once baked, a LoRA plugs back into this module's existing `lora=`
mechanism with zero new graph code.

Shares its ComfyUI connection (COMFY_URL) and checkpoint registry (MODELS) with
webcomic-background-mcp by convention — both point at the same local ComfyUI
install by default — but this module has no code dependency on that server.
"""

import time
import uuid
import os
import subprocess
import requests

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")

# Same checkpoint registry as webcomic-background-mcp/workflow.py — reuse whatever
# is already installed for that server (same models/ folder, same local ComfyUI).
MODELS = {
    "solstice":    {"ckpt": "solstice_manhwa_v10.safetensors",
                    "vae":  "vae-ft-mse-840000-ema-pruned.safetensors"},
    "counterfeit": {"ckpt": "Counterfeit_V3.safetensors", "vae": ""},
    "dreamshaper": {"ckpt": "DreamShaper_8.safetensors",  "vae": ""},
}
DEFAULT_MODEL = os.environ.get("WEBCOMIC_CHAR_MODEL", "solstice")

# Optional style LoRA — same idea as the background server's, including the Niji V5
# Style LoRA (added there in v1.7.0): character style and background style should be
# pickable from the same pool so a project's panels match its plates.
LORA = os.environ.get("WEBCOMIC_CHAR_LORA", "")
LORA_STRENGTH = float(os.environ.get("WEBCOMIC_CHAR_LORA_STRENGTH", "0.8"))

# Tier 2: OpenPose ControlNet (same repo as webcomic-background-mcp's scribble
# model, different file) and IP-Adapter presets (verified exact strings against
# cubiq/ComfyUI_IPAdapter_plus — the node validates these against its own enum).
CONTROLNET_OPENPOSE = "control_v11p_sd15_openpose_fp16.safetensors"
IDENTITY_PRESETS = {
    "plus": "PLUS (high strength)",        # body/identity — the Tier-2 default
    "plus_face": "PLUS FACE (portraits)",  # face-focused portraits; NOT true
                                            # FaceID (that needs InsightFace, a
                                            # notoriously fiddly Windows install —
                                            # deliberately not built here)
}

# --- SDXL prototype (2026-07-19) ---------------------------------------------
# Additional, opt-in model family alongside MODELS/SD1.5 above — NOT a
# replacement. Tried after real testing this session showed SD1.5 (specifically
# solstice_manhwa_v10) cannot produce genuine back views or clean full-body
# anatomy no matter how the Tier-1/2 prompt/weights are tuned; see CHANGELOG.
# Nothing SD1.5-related is removed by this — `model="mj_manga_sdxl"` is just a
# new option alongside "solstice"/"counterfeit"/"dreamshaper".
SDXL_MODELS = {
    "mj_manga_sdxl": {"ckpt": "sd_xl_base_1.0.safetensors",
                      "vae": "sdxl_vae_fp16fix.safetensors"},
}
# Midjourney Manga Art Style SDXL LoRA (civitai.com/models/185798) — trigger
# word "mj manga" (must be in the prompt for the LoRA to take effect),
# recommended clip skip 2 (see CLIP_SKIP_SDXL below) and strength 0.8.
SDXL_LORA = os.environ.get("WEBCOMIC_CHAR_SDXL_LORA", "MJMangaSDXL.safetensors")
SDXL_LORA_STRENGTH = float(os.environ.get("WEBCOMIC_CHAR_SDXL_LORA_STRENGTH", "0.8"))
SDXL_LORA_TRIGGER = "mj manga"
CLIP_SKIP_SDXL = int(os.environ.get("WEBCOMIC_CHAR_SDXL_CLIP_SKIP", "2"))

# Tier-2 SDXL equivalents. ControlNet uses the rank-256 LoRA-style variant
# (774 MB), not the full 5 GB OpenPoseXL2 model — the full model alone would
# exceed most consumer VRAM budgets alongside an already-6.94 GB checkpoint.
SDXL_IPADAPTER = "ip-adapter-plus_sdxl_vit-h.safetensors"
SDXL_CLIP_VISION = "CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors"
SDXL_CONTROLNET_OPENPOSE = "control-lora-openposeXL2-rank256.safetensors"

# --- Auto-launch config (mirrors webcomic-background-mcp) -------------------
COMFY_DIR = os.environ.get("WEBCOMIC_CHAR_COMFY_DIR", r"C:\AI\ComfyUI_windows_portable")
COMFY_LAUNCH = os.environ.get("WEBCOMIC_CHAR_COMFY_LAUNCH", "run_nvidia_gpu.bat")
AUTOLAUNCH = os.environ.get("WEBCOMIC_CHAR_AUTOLAUNCH", "1").lower() not in ("0", "false", "no", "")
LAUNCH_TIMEOUT = int(os.environ.get("WEBCOMIC_CHAR_LAUNCH_TIMEOUT", "180"))


class ComfyUIError(RuntimeError):
    pass


def comfy_is_up(timeout: float = 2.0) -> bool:
    try:
        return requests.get(f"{COMFY_URL}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


def _spawn_comfy() -> None:
    """Start ComfyUI as a detached background process (survives this server).
    If webcomic-background-mcp already has it running, this is a no-op path —
    ensure_comfy_running() only calls this when ComfyUI isn't already up."""
    launch_path = COMFY_LAUNCH
    if not os.path.isabs(launch_path):
        launch_path = os.path.join(COMFY_DIR, launch_path)
    if not os.path.isfile(launch_path):
        raise ComfyUIError(
            f"Cannot auto-launch ComfyUI: launcher not found at {launch_path}. "
            f"Set WEBCOMIC_CHAR_COMFY_DIR / WEBCOMIC_CHAR_COMFY_LAUNCH, or start "
            f"ComfyUI manually (or just start webcomic-background-mcp first)."
        )
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["cmd", "/c", launch_path], cwd=COMFY_DIR,
                         creationflags=flags, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    else:
        subprocess.Popen([launch_path], cwd=COMFY_DIR, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def ensure_comfy_running() -> None:
    if comfy_is_up():
        return
    if not AUTOLAUNCH:
        raise ComfyUIError(
            f"ComfyUI not reachable at {COMFY_URL} and auto-launch is disabled "
            f"(WEBCOMIC_CHAR_AUTOLAUNCH=0). Start it manually."
        )
    _spawn_comfy()
    t0 = time.time()
    while time.time() - t0 < LAUNCH_TIMEOUT:
        time.sleep(2.0)
        if comfy_is_up():
            return
    raise ComfyUIError(
        f"Auto-launched ComfyUI but it was not ready within {LAUNCH_TIMEOUT}s at "
        f"{COMFY_URL}. Check the ComfyUI window for errors."
    )


def _upload_image(path: str) -> str:
    if not os.path.isfile(path):
        raise ComfyUIError(f"Image not found: {path}")
    with open(path, "rb") as f:
        files = {"image": (os.path.basename(path), f, "application/octet-stream")}
        data = {"overwrite": "true"}
        r = requests.post(f"{COMFY_URL}/upload/image", files=files, data=data, timeout=30)
    if r.status_code != 200:
        raise ComfyUIError(f"Upload failed ({r.status_code}): {r.text[:200]}")
    return r.json()["name"]


# Tier-1's actual mechanism: a plain/clean backdrop so the render mattes cleanly
# afterward. Appended automatically — see generate()'s prompt/negative handling.
CLEAN_BACKDROP_SUFFIX = (
    ", solo, plain flat light-gray studio backdrop, solid color background, "
    "full body, standing pose, simple even lighting, clean sharp edges"
)
CLEAN_BACKDROP_NEGATIVE = (
    "background clutter, scenery, room, outdoors, patterned background, "
    "multiple people, crowd, extra limbs, extra fingers, fused fingers, "
    "mutated hands, poorly drawn face, blurry, low quality, watermark, text, signature, "
    # Added 2026-07-19 after live testing against busy source illustrations: a
    # reference image with its own VFX (magic circles, fire, ice) bleeds those
    # effects into every render regardless of the backdrop prompt, because
    # IP-Adapter's identity conditioning doesn't separate "this person" from
    # "this scene." Suppress the common categories explicitly.
    "magic effects, spell effects, glowing runes, glowing effects, particle effects, "
    "motion lines, speed lines, energy effects, sparkles, fire, flames, embers, "
    "ice, ice crystals"
)
DEFAULT_NEGATIVE = "blurry, low quality, watermark, text, signature, deformed"


def build_graph(
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    ckpt_name: str,
    vae_name: str = "",
    ref_image_name: str | None = None,
    ref_denoise: float = 0.55,
    lora_name: str | None = None,
    lora_strength: float | None = None,
    ip_adapter_image_name: str | None = None,
    ip_adapter_preset: str | None = None,
    ip_adapter_weight: float = 0.8,
    pose_ref_name: str | None = None,
    pose_strength: float = 1.0,
    sdxl: bool = False,
    pose_preprocess: bool = True,
) -> dict:
    """Assemble the ComfyUI API graph.

    Base shape (Tier 1, always available): plain txt2img (no reference — free
    concept exploration), or img2img seeded from a character's reference image
    (the same "seed the latent from a canonical image" trick as World Builder's
    location_denoise mode, applied to a character instead of a place).

    Tier 2 adds two optional, independent branches on top of that base shape:
    IP-Adapter (ip_adapter_image_name + ip_adapter_preset) conditions the model
    on the reference's *identity*, chained onto whatever the current model head
    is (post-LoRA, if a style LoRA is active) — identity and style stack rather
    than compete. OpenPose (pose_ref_name) extracts a pose skeleton from a
    supplied photo via the OpenposePreprocessor node and pins the *pose* via
    ControlNet, chained onto positive/negative the same way a composition
    ControlNet does in webcomic-background-mcp.

    sdxl (2026-07-19 prototype): when True, inserts a CLIPSetLastLayer node
    (clip skip, per the Midjourney Manga Art Style LoRA's recommended setting)
    and resolves the OpenPose ControlNet filename from the SDXL registry
    instead of the SD1.5 one. IPAdapterUnifiedLoader needs no special handling
    here — its preset resolution is expected to auto-detect SD1.5 vs SDXL from
    the loaded checkpoint architecture (verify this holds in practice)."""
    g = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt_name}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
    }

    base_model, base_clip = ["4", 0], ["4", 1]
    vae_ref = ["4", 2]
    if vae_name:
        g["41"] = {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}}
        vae_ref = ["41", 0]

    if sdxl:
        use_lora = SDXL_LORA if lora_name is None else lora_name
        use_lora_strength = SDXL_LORA_STRENGTH if lora_strength is None else lora_strength
    else:
        use_lora = LORA if lora_name is None else lora_name
        use_lora_strength = LORA_STRENGTH if lora_strength is None else lora_strength
    if use_lora:
        g["40"] = {"class_type": "LoraLoader",
                   "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": use_lora,
                              "strength_model": use_lora_strength, "strength_clip": use_lora_strength}}
        base_model, base_clip = ["40", 0], ["40", 1]

    if sdxl and CLIP_SKIP_SDXL:
        g["42"] = {"class_type": "CLIPSetLastLayer",
                   "inputs": {"clip": base_clip, "stop_at_clip_layer": -CLIP_SKIP_SDXL}}
        base_clip = ["42", 0]

    # --- Tier 2: IP-Adapter identity branch ---
    if ip_adapter_image_name and ip_adapter_preset:
        g["50"] = {"class_type": "IPAdapterUnifiedLoader",
                   "inputs": {"model": base_model, "preset": ip_adapter_preset}}
        g["51"] = {"class_type": "LoadImage", "inputs": {"image": ip_adapter_image_name}}
        g["52"] = {"class_type": "IPAdapter",
                   "inputs": {"model": ["50", 0], "ipadapter": ["50", 1], "image": ["51", 0],
                              "weight": ip_adapter_weight, "start_at": 0.0, "end_at": 1.0,
                              # Verified enum (ComfyUI_IPAdapter_plus): "standard" /
                              # "prompt is more important" / "style transfer". "standard"
                              # is correct for identity conditioning (not "style transfer",
                              # which is for the removed style-transfer use case webcomic-
                              # background-mcp used to have).
                              "weight_type": "standard"}}
        base_model = ["52", 0]

    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": base_clip}}
    g["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": base_clip}}

    pos_ref, neg_ref = ["6", 0], ["7", 0]

    # --- Tier 2: OpenPose ControlNet branch ---
    if pose_ref_name:
        g["60"] = {"class_type": "LoadImage", "inputs": {"image": pose_ref_name}}
        # pose_preprocess=True: the input is a photo/artwork — extract its
        # skeleton via OpenposePreprocessor. pose_preprocess=False: the input
        # IS already an OpenPose-format map (e.g. synthesized by mannequin.py)
        # — feed it to ControlNet directly; running the preprocessor over a
        # stick figure would try to detect a human in it and fail.
        if pose_preprocess:
            g["61"] = {"class_type": "OpenposePreprocessor",
                       "inputs": {"image": ["60", 0], "detect_hand": "enable",
                                  "detect_body": "enable", "detect_face": "enable",
                                  "resolution": 512}}
            pose_image_ref = ["61", 0]
        else:
            pose_image_ref = ["60", 0]
        # SDXL uses the rank-256 LoRA-style ControlNet (774 MB, not the full
        # 5 GB model) — loads fine via the standard ControlNetLoader node
        # (verified live 2026-07-19).
        g["62"] = {"class_type": "ControlNetLoader",
                   "inputs": {"control_net_name":
                              SDXL_CONTROLNET_OPENPOSE if sdxl else CONTROLNET_OPENPOSE}}
        g["63"] = {"class_type": "ControlNetApplyAdvanced",
                   "inputs": {"positive": pos_ref, "negative": neg_ref,
                              "control_net": ["62", 0], "image": pose_image_ref,
                              "strength": pose_strength,
                              "start_percent": 0.0, "end_percent": 1.0}}
        pos_ref, neg_ref = ["63", 0], ["63", 1]

    latent_ref, denoise = ["5", 0], 1.0
    if ref_image_name:
        g["20"] = {"class_type": "LoadImage", "inputs": {"image": ref_image_name}}
        g["21"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": vae_ref}}
        latent_ref, denoise = ["21", 0], ref_denoise

    g["3"] = {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": denoise,
                         "model": base_model, "positive": pos_ref, "negative": neg_ref,
                         "latent_image": latent_ref}}
    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": vae_ref}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "pose"}}
    return g


def _submit_and_wait(graph: dict, timeout: int = 300) -> bytes:
    r = requests.post(f"{COMFY_URL}/prompt", json={"prompt": graph}, timeout=30)
    if r.status_code != 200:
        raise ComfyUIError(f"Prompt rejected ({r.status_code}): {r.text[:300]}")
    prompt_id = r.json()["prompt_id"]

    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(1.5)
        h = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=30).json()
        if prompt_id in h:
            outs = h[prompt_id]["outputs"]
            if "9" not in outs:
                raise ComfyUIError("Generation produced no image (check ComfyUI log).")
            img = outs["9"]["images"][0]
            params = {"filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]}
            return requests.get(f"{COMFY_URL}/view", params=params, timeout=60).content
    raise ComfyUIError(f"Timed out after {timeout}s")


def generate(
    prompt: str,
    out_dir: str,
    negative: str = DEFAULT_NEGATIVE,
    width: int = 640,
    height: int = 896,
    seed: int | None = None,
    steps: int = 25,
    cfg: float = 7.0,
    ref_path: str | None = None,
    ref_denoise: float = 0.55,
    model: str = DEFAULT_MODEL,
    lora: str | None = None,
    lora_strength: float | None = None,
    identity_mode: str = "off",
    ip_adapter_weight: float = 0.8,
    pose_ref_path: str | None = None,
    pose_strength: float = 1.0,
    pose_preprocess: bool = True,
    timeout: int = 300,
) -> str:
    """Run the pipeline; return the path to the saved (un-matted) PNG.

    Always appends CLEAN_BACKDROP_SUFFIX/_NEGATIVE — the whole point of Tier 1 is
    a render clean enough to auto-matte afterward. ref_path (a character's primary
    reference image) is optional but is what makes this "the same character" rather
    than a fresh random render; ref_denoise controls how much of the reference
    survives (lower = closer to the reference, higher = more prompt-driven drift).

    Tier 2 (opt-in): identity_mode "plus" (body/identity) or "plus_face"
    (portraits) conditions the render on ref_path's identity via IP-Adapter,
    independent of ref_denoise/img2img — combine both, or set ref_denoise=1.0 for
    pure txt2img + IP-Adapter (more pose range, relies entirely on IP-Adapter for
    identity). pose_ref_path (a photo of someone in the target pose) pins the pose
    via OpenPose ControlNet. Both need the Tier-2 models from setup_models.py and
    the ComfyUI_IPAdapter_plus custom node — see README.md.

    model may also be an SDXL prototype entry (see SDXL_MODELS, 2026-07-19) —
    resolved automatically here, no separate flag needed from callers."""
    ensure_comfy_running()

    sdxl = model in SDXL_MODELS
    if sdxl:
        ckpt_name = SDXL_MODELS[model]["ckpt"]
        vae_name = SDXL_MODELS[model]["vae"]
    elif model in MODELS:
        ckpt_name = MODELS[model]["ckpt"]
        vae_name = MODELS[model]["vae"]
    else:
        raise ComfyUIError(f"Unknown model '{model}'. Options: "
                           f"{', '.join(list(MODELS) + list(SDXL_MODELS))}")

    if identity_mode != "off" and identity_mode not in IDENTITY_PRESETS:
        raise ComfyUIError(f"Unknown identity_mode '{identity_mode}'. "
                           f"Options: off, {', '.join(IDENTITY_PRESETS)}")
    if identity_mode != "off" and not ref_path:
        raise ComfyUIError("identity_mode needs ref_path (IP-Adapter conditions "
                           "on the reference image's identity).")

    if seed is None:
        seed = uuid.uuid4().int % (2**31)

    # SDXL is native at ~1024²-class resolutions; the SD1.5 defaults (640x896)
    # under-drive it. If the caller left the defaults untouched, bump to the
    # portrait resolution every live SDXL test this session validated. Explicit
    # width/height are always respected.
    if sdxl and (width, height) == (640, 896):
        width, height = 832, 1216

    full_prompt = f"{prompt}{CLEAN_BACKDROP_SUFFIX}"
    full_negative = f"{negative}, {CLEAN_BACKDROP_NEGATIVE}"
    # The SDXL LoRA only activates with its trigger word in the prompt — bake
    # it in automatically (this model entry IS the LoRA, unlike the optional
    # style-LoRA pool elsewhere, so there's no case where a caller would want
    # mj_manga_sdxl selected without the trigger).
    use_lora_name = SDXL_LORA if (sdxl and lora is None) else lora
    if sdxl and use_lora_name and SDXL_LORA_TRIGGER not in full_prompt:
        full_prompt = f"{SDXL_LORA_TRIGGER}, {full_prompt}"

    ref_image_name = _upload_image(ref_path) if ref_path else None
    ip_adapter_preset = IDENTITY_PRESETS.get(identity_mode)
    # IP-Adapter needs its own image reference — reuse the same character ref.
    ip_adapter_image_name = ref_image_name if ip_adapter_preset else None
    pose_ref_name = _upload_image(pose_ref_path) if pose_ref_path else None

    graph = build_graph(full_prompt, full_negative, width, height, seed, steps, cfg,
                        ckpt_name, vae_name, ref_image_name, ref_denoise,
                        use_lora_name, lora_strength,
                        ip_adapter_image_name, ip_adapter_preset, ip_adapter_weight,
                        pose_ref_name, pose_strength, sdxl, pose_preprocess)

    data = _submit_and_wait(graph, timeout)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"pose_{seed}")
    out_path = base + ".png"
    n = 1
    while os.path.exists(out_path):
        out_path = f"{base}_{n}.png"
        n += 1
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def generate_concepts(
    prompt: str,
    out_dir: str,
    n: int = 4,
    negative: str = DEFAULT_NEGATIVE,
    width: int = 640,
    height: int = 896,
    seed: int | None = None,
    model: str = DEFAULT_MODEL,
    lora: str | None = None,
    lora_strength: float | None = None,
    timeout: int = 300,
) -> list[str]:
    """Batch txt2img candidates for a character that does NOT exist in the
    bible yet — Concept Genesis on-ramp 1 (ARCHITECTURE.md §8b.6): a writer with
    a story but no reference art. Just loops generate() with ref_path=None (pure
    txt2img — generate() already supports this) over n distinct seeds; one graph
    submit per seed, GPU-local, no token cost. Returns the saved PNG paths —
    nothing is registered here, the caller picks a winner and calls
    register_character."""
    if n < 1:
        raise ComfyUIError("generate_concepts needs n >= 1.")
    paths = []
    for i in range(n):
        s = None if seed is None else seed + i
        path = generate(prompt=prompt, out_dir=out_dir, negative=negative,
                        width=width, height=height, seed=s, model=model,
                        lora=lora, lora_strength=lora_strength, timeout=timeout)
        paths.append(path)
    return paths


def matte(image_path: str, out_path: str | None = None) -> str:
    """Auto-remove the clean backdrop, producing an RGBA cutout. Uses `rembg`
    (u2net) — a pure-Python matting model, no ComfyUI custom node required.
    Downloads its model to the user's home dir on first use."""
    try:
        from rembg import remove
        from PIL import Image
    except ImportError as e:
        raise ComfyUIError(
            "Matting needs `rembg` and `pillow` in the server venv. "
            "Install: <venv>/python -m pip install rembg pillow"
        ) from e
    if out_path is None:
        root, _ = os.path.splitext(image_path)
        out_path = f"{root}_matted.png"
    im = Image.open(image_path).convert("RGBA")
    cut = remove(im)
    cut.save(out_path)
    return out_path
