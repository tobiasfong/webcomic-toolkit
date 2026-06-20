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
import requests

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")

# Model filenames as installed in ComfyUI/models/*
CHECKPOINT = os.environ.get("WEBCOMIC_BG_CHECKPOINT", "Counterfeit_V3.safetensors")
CONTROLNET_SCRIBBLE = "control_v11p_sd15_scribble_fp16.safetensors"


class ComfyUIError(RuntimeError):
    pass


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


def build_graph(
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    sketch_name: str | None,
    style_ref_name: str | None,
    ipa_weight: float,
    controlnet_strength: float,
) -> dict:
    """Assemble the ComfyUI API graph, including optional branches."""
    g = {
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CHECKPOINT}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
    }

    model_ref = ["4", 0]

    # --- IP-Adapter branch (style) ---
    if style_ref_name:
        g["20"] = {"class_type": "IPAdapterUnifiedLoader",
                   "inputs": {"model": ["4", 0], "preset": "STANDARD (medium strength)"}}
        g["21"] = {"class_type": "LoadImage", "inputs": {"image": style_ref_name}}
        g["22"] = {"class_type": "IPAdapter",
                   "inputs": {"model": ["20", 0], "ipadapter": ["20", 1], "image": ["21", 0],
                              "weight": ipa_weight, "start_at": 0.0, "end_at": 1.0,
                              "weight_type": "style transfer"}}
        model_ref = ["22", 0]

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

    g["3"] = {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
                         "model": model_ref, "positive": pos_ref, "negative": neg_ref,
                         "latent_image": ["5", 0]}}
    g["8"] = {"class_type": "VAEDecode",
              "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    g["9"] = {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": "background"}}
    return g


def generate(
    prompt: str,
    out_dir: str,
    negative: str = "people, person, character, figure, text, watermark, blurry, low quality",
    width: int = 768,
    height: int = 512,
    seed: int | None = None,
    steps: int = 25,
    cfg: float = 7.0,
    sketch_path: str | None = None,
    style_ref_path: str | None = None,
    ipa_weight: float = 0.7,
    controlnet_strength: float = 1.0,
    timeout: int = 300,
) -> str:
    """Run the pipeline; return the path to the saved PNG."""
    if seed is None:
        seed = uuid.uuid4().int % (2**31)

    sketch_name = _upload_image(sketch_path) if sketch_path else None
    style_ref_name = _upload_image(style_ref_path) if style_ref_path else None

    graph = build_graph(prompt, negative, width, height, seed, steps, cfg,
                        sketch_name, style_ref_name, ipa_weight, controlnet_strength)

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
            data = requests.get(f"{COMFY_URL}/view", params=params, timeout=30).content
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"background_{seed}.png")
            with open(out_path, "wb") as f:
                f.write(data)
            return out_path
    raise ComfyUIError(f"Timed out after {timeout}s")
