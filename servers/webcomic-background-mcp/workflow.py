"""
workflow.py — builds and runs the Webcomic Background generation pipeline
against a running ComfyUI instance via its HTTP API.

The pipeline is the one validated interactively:
  checkpoint -> [IP-Adapter style] -> KSampler <- [ControlNet angle] <- prompt
Both the ControlNet (composition) and IP-Adapter (style) branches are optional;
the graph is assembled conditionally based on what the caller provides.
"""

import json
import time
import uuid
import os
import subprocess
import tempfile
import requests

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")

CONTROLNET_SCRIBBLE = "control_v11p_sd15_scribble_fp16.safetensors"

# Selectable models (files under ComfyUI/models/*). Each pairs a checkpoint with the
# VAE it needs — Solstice ("NoEMA") ships no VAE, so it uses a standalone one. The
# caller picks per scene via the `model` arg; all render manhwa/anime in their own way.
MODELS = {
    "solstice":    {"ckpt": "solstice_manhwa_v10.safetensors",
                    "vae":  "vae-ft-mse-840000-ema-pruned.safetensors"},  # Korean webtoon/manhwa — atmospheric nights
    "counterfeit": {"ckpt": "Counterfeit_V3.safetensors", "vae": ""},     # clean anime; best paired with the manhwa LoRA
    "dreamshaper": {"ckpt": "DreamShaper_8.safetensors",  "vae": ""},     # soft painterly
}
DEFAULT_MODEL = os.environ.get("WEBCOMIC_BG_MODEL", "solstice")

# Optional style LoRA (filename in models/loras). Empty = off. Shifts the model's
# native render toward a trained style (e.g. webtoon/manhwa). These env values are
# the *defaults*; both are overridable per call via generate(lora=..., lora_strength=...).
LORA = os.environ.get("WEBCOMIC_BG_LORA", "")
LORA_STRENGTH = float(os.environ.get("WEBCOMIC_BG_LORA_STRENGTH", "0.8"))

# --- Auto-launch config -----------------------------------------------------
# When ComfyUI isn't reachable, the server can start it itself so any MCP
# client (Claude Code, Codex, Antigravity, …) works without manual setup.
COMFY_DIR = os.environ.get("WEBCOMIC_BG_COMFY_DIR", r"C:\AI\ComfyUI_windows_portable")
COMFY_LAUNCH = os.environ.get("WEBCOMIC_BG_COMFY_LAUNCH", "run_nvidia_gpu.bat")
# Set WEBCOMIC_BG_AUTOLAUNCH=0 to disable and require a manually-started ComfyUI.
AUTOLAUNCH = os.environ.get("WEBCOMIC_BG_AUTOLAUNCH", "1").lower() not in ("0", "false", "no", "")
LAUNCH_TIMEOUT = int(os.environ.get("WEBCOMIC_BG_LAUNCH_TIMEOUT", "180"))


class ComfyUIError(RuntimeError):
    pass


def comfy_is_up(timeout: float = 2.0) -> bool:
    """True if ComfyUI answers /system_stats."""
    try:
        return requests.get(f"{COMFY_URL}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


def _spawn_comfy() -> None:
    """Start ComfyUI as a detached background process (survives this server)."""
    launch_path = COMFY_LAUNCH
    if not os.path.isabs(launch_path):
        launch_path = os.path.join(COMFY_DIR, launch_path)
    if not os.path.isfile(launch_path):
        raise ComfyUIError(
            f"Cannot auto-launch ComfyUI: launcher not found at {launch_path}. "
            f"Set WEBCOMIC_BG_COMFY_DIR / WEBCOMIC_BG_COMFY_LAUNCH, or start ComfyUI manually."
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
    """Make sure ComfyUI is reachable, auto-launching and waiting if needed."""
    if comfy_is_up():
        return
    if not AUTOLAUNCH:
        raise ComfyUIError(
            f"ComfyUI not reachable at {COMFY_URL} and auto-launch is disabled "
            f"(WEBCOMIC_BG_AUTOLAUNCH=0). Start it manually (e.g. run_nvidia_gpu.bat)."
        )
    _spawn_comfy()
    t0 = time.time()
    while time.time() - t0 < LAUNCH_TIMEOUT:
        time.sleep(2.0)
        if comfy_is_up():
            return
    raise ComfyUIError(
        f"Auto-launched ComfyUI but it was not ready within {LAUNCH_TIMEOUT}s at {COMFY_URL}. "
        f"Check the ComfyUI window for errors."
    )


def _upload_image(path: str) -> str:
    """Upload a local image into ComfyUI's input folder; return its filename."""
    if not os.path.isfile(path):
        raise ComfyUIError(f"Image not found: {path}")
    with open(path, "rb") as f:
        files = {"image": (os.path.basename(path), f, "application/octet-stream")}
        data = {"overwrite": "true"}
        r = requests.post(f"{COMFY_URL}/upload/image", files=files, data=data, timeout=30)
    if r.status_code != 200:
        raise ComfyUIError(f"Upload failed ({r.status_code}): {r.text[:200]}")
    return r.json()["name"]


# Largest side (px) we let SD1.5 generate at — bigger canvases are scaled down
# for generation and the user upscales the soft background back in their editor.
CHAR_MAX_SIDE = 832


def _prepare_character(path: str, tmp_dir: str):
    """Normalise a character image into (rgb_png, mask_png, gen_w, gen_h).

    The mask is white where the character is and black where the background
    should be generated. Uses the alpha channel if present; otherwise segments
    the character from a solid (near-white) backdrop by flood-filling inward
    from the canvas corners, which correctly keeps white *inside* the character.
    """
    try:
        from PIL import Image, ImageDraw
        import numpy as np
    except ImportError as e:
        raise ComfyUIError(
            "character_path needs Pillow and numpy in the server venv. "
            "Install them: <venv>/python -m pip install pillow numpy"
        ) from e

    im = Image.open(path)
    char = None
    if "A" in im.getbands():
        alpha = np.array(im.convert("RGBA").getchannel("A"))
        if int(alpha.min()) < 250:  # genuine transparency present
            char = (alpha > 16).astype("uint8") * 255

    rgb = im.convert("RGB")
    if char is None:
        # No usable alpha — treat a near-white, corner-connected region as bg.
        work = rgb.copy()
        SENT = (255, 0, 255)
        for pt in [(0, 0), (work.width - 1, 0), (0, work.height - 1), (work.width - 1, work.height - 1)]:
            ImageDraw.floodfill(work, pt, SENT, thresh=40)
        arr = np.array(work)
        bg = np.all(arr == np.array(SENT), axis=-1)
        char = (~bg).astype("uint8") * 255

    # Scale to an SD-friendly size (multiple of 8), preserving aspect.
    w, h = rgb.size
    scale = min(1.0, CHAR_MAX_SIDE / max(w, h))
    gw = max(8, int(round(w * scale / 8)) * 8)
    gh = max(8, int(round(h * scale / 8)) * 8)
    rgb = rgb.resize((gw, gh), Image.LANCZOS)
    mask_img = Image.fromarray(char, mode="L").resize((gw, gh), Image.NEAREST)

    rgb_path = os.path.join(tmp_dir, "char_rgb.png")
    mask_path = os.path.join(tmp_dir, "char_mask.png")
    rgb.save(rgb_path)
    mask_img.save(mask_path)
    return rgb_path, mask_path, gw, gh


def build_graph(
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    sketch_name: str | None,
    controlnet_strength: float,
    ckpt_name: str,
    vae_name: str = "",
    char_rgb_name: str | None = None,
    char_mask_name: str | None = None,
    location_ref_name: str | None = None,
    location_denoise: float = 0.65,
    lora_name: str | None = None,
    lora_strength: float | None = None,
) -> dict:
    """Assemble the ComfyUI API graph. Style comes from the checkpoint (+ optional
    LoRA); composition from an optional ControlNet sketch. (No IP-Adapter — the
    model's native render carries the aesthetic.)

    If location_ref_name is given (World Builder), the canonical image of an
    established location seeds the latent via img2img at location_denoise, so a new
    panel of that place stays recognisably the same — lower denoise = closer to canon."""
    g = {
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt_name}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
    }

    base_model, base_clip = ["4", 0], ["4", 1]

    # VAE: checkpoint's own by default, or a standalone one (for VAE-less checkpoints).
    vae_ref = ["4", 2]
    if vae_name:
        g["41"] = {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}}
        vae_ref = ["41", 0]

    # --- optional style LoRA (shifts the model's native render toward a trained style) ---
    use_lora = LORA if lora_name is None else lora_name        # None = env default, "" = off
    use_lora_strength = LORA_STRENGTH if lora_strength is None else lora_strength
    if use_lora:
        g["40"] = {"class_type": "LoraLoader",
                   "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": use_lora,
                              "strength_model": use_lora_strength, "strength_clip": use_lora_strength}}
        base_model, base_clip = ["40", 0], ["40", 1]

    g["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": base_clip}}
    g["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": base_clip}}

    model_ref = base_model
    pos_ref, neg_ref = ["6", 0], ["7", 0]

    # --- ControlNet branch (angle/composition) ---
    if sketch_name:
        g["11"] = {"class_type": "ControlNetLoader",
                   "inputs": {"control_net_name": CONTROLNET_SCRIBBLE}}
        g["10"] = {"class_type": "LoadImage", "inputs": {"image": sketch_name}}
        g["12"] = {"class_type": "ControlNetApplyAdvanced",
                   "inputs": {"positive": pos_ref, "negative": neg_ref,
                              "control_net": ["11", 0], "image": ["10", 0],
                              "strength": controlnet_strength,
                              "start_percent": 0.0, "end_percent": 1.0}}
        pos_ref, neg_ref = ["12", 0], ["12", 1]

    # --- Character branch: generate a background PLATE around a drawn character ---
    # The character is only a spatial guide (scale / perspective / horizon); it is
    # NOT in the output. Two inpaint passes: (1) generate the scene around the
    # locked character, (2) fill the character's silhouette with matching
    # background so the user can drop their own character layer on top.
    if char_rgb_name and char_mask_name:
        GROW = 12
        g["30"] = {"class_type": "LoadImage", "inputs": {"image": char_rgb_name}}
        g["31"] = {"class_type": "LoadImageMask",
                   "inputs": {"image": char_mask_name, "channel": "red"}}  # 1 = character
        g["32"] = {"class_type": "InvertMask", "inputs": {"mask": ["31", 0]}}  # 1 = background
        # Pass 1 — inpaint the background around the locked character
        g["33"] = {"class_type": "VAEEncodeForInpaint",
                   "inputs": {"pixels": ["30", 0], "vae": vae_ref,
                              "mask": ["32", 0], "grow_mask_by": GROW}}
        g["34"] = {"class_type": "KSampler",
                   "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                              "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
                              "model": model_ref, "positive": pos_ref, "negative": neg_ref,
                              "latent_image": ["33", 0]}}
        g["35"] = {"class_type": "VAEDecode", "inputs": {"samples": ["34", 0], "vae": vae_ref}}
        # Pass 2 — fill the character's silhouette with continuous background
        g["36"] = {"class_type": "VAEEncodeForInpaint",
                   "inputs": {"pixels": ["35", 0], "vae": vae_ref,
                              "mask": ["31", 0], "grow_mask_by": GROW}}
        g["37"] = {"class_type": "KSampler",
                   "inputs": {"seed": seed + 1, "steps": steps, "cfg": cfg,
                              "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
                              "model": model_ref, "positive": pos_ref, "negative": neg_ref,
                              "latent_image": ["36", 0]}}
        g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["37", 0], "vae": vae_ref}}
        g["9"] = {"class_type": "SaveImage",
                  "inputs": {"images": ["8", 0], "filename_prefix": "background"}}
        return g

    # --- World Builder branch: seed the latent from an established location's
    # canonical image (img2img) so a new panel stays consistent with prior canon.
    latent_ref, denoise = ["5", 0], 1.0
    if location_ref_name:
        g["20"] = {"class_type": "LoadImage", "inputs": {"image": location_ref_name}}
        g["21"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": vae_ref}}
        latent_ref, denoise = ["21", 0], location_denoise

    g["3"] = {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": denoise,
                         "model": model_ref, "positive": pos_ref, "negative": neg_ref,
                         "latent_image": latent_ref}}
    g["8"] = {"class_type": "VAEDecode",
              "inputs": {"samples": ["3", 0], "vae": vae_ref}}
    g["9"] = {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": "background"}}
    return g


# Strong character/person suppression — manhwa checkpoints (esp. Solstice) are
# character-trained and will drop figures into open scenes without firm negatives.
DEFAULT_NEGATIVE = (
    "people, person, character, figure, man, woman, girl, boy, 1girl, 1boy, "
    "face, portrait, crowd, silhouette of person, text, watermark, signature, "
    "blurry, low quality"
)

# Extra suppression for World Builder (img2img) mode. At higher location_denoise
# (~0.65+) the manhwa checkpoint reasserts its character training and drops a
# figure into the scene; these terms are appended on top of DEFAULT_NEGATIVE when
# a location reference is used.
LOCATION_EXTRA_NEGATIVE = (
    "1girl, 1boy, woman, man, person, character, figure, portrait, "
    "standing figure, foreground person, anime girl, anime boy"
)


def generate(
    prompt: str,
    out_dir: str,
    negative: str = DEFAULT_NEGATIVE,
    width: int = 768,
    height: int = 512,
    seed: int | None = None,
    steps: int = 25,
    cfg: float = 7.0,
    sketch_path: str | None = None,
    character_path: str | None = None,
    model: str = DEFAULT_MODEL,
    controlnet_strength: float = 1.0,
    location_ref_path: str | None = None,
    location_denoise: float = 0.65,
    lora: str | None = None,
    lora_strength: float | None = None,
    hires: bool = False,
    timeout: int = 300,
) -> str:
    """Run the pipeline; return the path to the saved PNG.

    lora: None = env default (WEBCOMIC_BG_LORA), "" = force off, or a filename in
    models/loras. hires: after the base render, upscale 1.5x and re-detail with a
    light img2img pass (fixes softness on dense architectural panels)."""
    ensure_comfy_running()

    if model not in MODELS:
        raise ComfyUIError(f"Unknown model '{model}'. Options: {', '.join(MODELS)}")
    ckpt_name = MODELS[model]["ckpt"]
    vae_name = MODELS[model]["vae"]

    if seed is None:
        seed = uuid.uuid4().int % (2**31)

    sketch_name = _upload_image(sketch_path) if sketch_path else None
    location_ref_name = _upload_image(location_ref_path) if location_ref_path else None
    # In World Builder mode, partial denoise lets the checkpoint reassert its
    # character bias — reinforce the figure suppression.
    if location_ref_name:
        negative = f"{negative}, {LOCATION_EXTRA_NEGATIVE}"

    char_rgb_name = char_mask_name = None
    if character_path:
        tmp_dir = tempfile.mkdtemp(prefix="wbgchar_")
        rgb_path, mask_path, width, height = _prepare_character(character_path, tmp_dir)
        char_rgb_name = _upload_image(rgb_path)
        char_mask_name = _upload_image(mask_path)

    graph = build_graph(prompt, negative, width, height, seed, steps, cfg,
                        sketch_name, controlnet_strength, ckpt_name, vae_name,
                        char_rgb_name, char_mask_name,
                        location_ref_name, location_denoise,
                        lora, lora_strength)

    data = _submit_and_wait(graph, timeout)
    os.makedirs(out_dir, exist_ok=True)
    # Avoid clobbering an earlier render with the same seed (e.g. a
    # fixed-seed denoise sweep) — add a numeric suffix if the name exists.
    base = os.path.join(out_dir, f"background_{seed}")
    out_path = base + ".png"
    n = 1
    while os.path.exists(out_path):
        out_path = f"{base}_{n}.png"
        n += 1
    with open(out_path, "wb") as f:
        f.write(data)

    if hires:
        return hires_pass(out_path, prompt, negative, model=model, seed=seed,
                          lora=lora, lora_strength=lora_strength, timeout=timeout)
    return out_path


def _submit_and_wait(graph: dict, timeout: int = 300, output_node: str = "9") -> bytes:
    """Submit a graph, poll history, return the saved image's bytes.

    `output_node` is the SaveImage node id — "9" for this module's SD1.5
    graphs; flux_workflow.py passes its own, since FLUX's graph numbering
    differs. Defaulted so every existing SD1.5 caller is unaffected."""
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
            if output_node not in outs:
                raise ComfyUIError("Generation produced no image (check ComfyUI log).")
            img = outs[output_node]["images"][0]
            params = {"filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]}
            return requests.get(f"{COMFY_URL}/view", params=params, timeout=60).content
    raise ComfyUIError(f"Timed out after {timeout}s")


def hires_pass(
    image_path: str,
    prompt: str,
    negative: str = DEFAULT_NEGATIVE,
    model: str = DEFAULT_MODEL,
    scale: float = 1.5,
    denoise: float = 0.35,
    seed: int | None = None,
    steps: int = 25,
    cfg: float = 7.0,
    lora: str | None = None,
    lora_strength: float | None = None,
    out_path: str | None = None,
    timeout: int = 300,
) -> str:
    """Upscale a finished render and re-detail it with a light img2img pass.

    SD1.5 runs out of pixels on dense architectural panels at its native size —
    lanczos-upscale by `scale`, then re-sample at low denoise so the model sharpens
    the detail at the new resolution instead of stretching pixels. Prompt should
    match (or resemble) the one used for the base render; add "sharp focus"-type
    terms rather than changing the scene."""
    ensure_comfy_running()
    if model not in MODELS:
        raise ComfyUIError(f"Unknown model '{model}'. Options: {', '.join(MODELS)}")
    m = MODELS[model]
    if seed is None:
        seed = uuid.uuid4().int % (2**31)

    # target size: multiple of 8 at ~scale x the source
    try:
        from PIL import Image
        w0, h0 = Image.open(image_path).size
    except ImportError as e:
        raise ComfyUIError("hires_pass needs Pillow in the server venv.") from e
    tw = max(8, int(round(w0 * scale / 8)) * 8)
    th = max(8, int(round(h0 * scale / 8)) * 8)

    img_name = _upload_image(image_path)
    base_model, base_clip = ["4", 0], ["4", 1]
    g = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": m["ckpt"]}}}
    vae_ref = ["4", 2]
    if m["vae"]:
        g["41"] = {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}}
        vae_ref = ["41", 0]
    use_lora = LORA if lora is None else lora
    use_strength = LORA_STRENGTH if lora_strength is None else lora_strength
    if use_lora:
        g["40"] = {"class_type": "LoraLoader",
                   "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": use_lora,
                              "strength_model": use_strength, "strength_clip": use_strength}}
        base_model, base_clip = ["40", 0], ["40", 1]
    g.update({
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt + ", sharp focus, crisp detail", "clip": base_clip}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative + ", blurry, soft focus", "clip": base_clip}},
        "10": {"class_type": "LoadImage", "inputs": {"image": img_name}},
        "11": {"class_type": "ImageScale", "inputs": {"image": ["10", 0], "upscale_method": "lanczos",
                                                       "width": tw, "height": th, "crop": "disabled"}},
        "12": {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": vae_ref}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": denoise,
                         "model": base_model, "positive": ["6", 0], "negative": ["7", 0],
                         "latent_image": ["12", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": vae_ref}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "hires"}},
    })
    data = _submit_and_wait(g, timeout)
    if out_path is None:
        root, ext = os.path.splitext(image_path)
        out_path = f"{root}_hires{ext or '.png'}"
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path
