"""
klein.py — FLUX 3 Image Klein edits: the keyframe and repair path since 2026-10-17.

Replaces kontext_workflow.py (FLUX.1 Kontext, Q6_K GGUF, on the main ComfyUI).
The character and background servers had already moved to Klein; this server
was the last thing loading FLUX.1, and moving it is what lets FLUX.1 be
uninstalled.

Why this path exists at all: LTX cannot animate eye- or mouth-scale features.
A blink is roughly 0.2% of frame pixels and about four latent pixels wide after
the VAE's 8x compression — there is nothing there for it to move, and no seed or
prompt wording changes that. Blinks and mouth flaps therefore come from
generated KEYFRAMES (this module), played back by a frame player. The same
call repairs LTX's damaged hands frame by frame.

It runs on Klein's OWN ComfyUI (v0.41, port 8189) — one install shared with the
character and background servers. The main ComfyUI (v0.25.1, port 8188) keeps
LTX and the music model, which run through add-ons never tested on v0.41.

⚠ TWO COMFYUIS MEANS TWO QUEUES. With Kontext and LTX on one ComfyUI, its
serial queue at least ordered them; across two processes nothing does, and both
models land on the same 6 GB card at once. One Kontext call submitted during an
LTX batch once thrashed until the job hung and cost five hours. `busy()` is
what server.py checks before starting either one.

What carries over from Kontext, and what does not — measured on Klein by the
character server, 2026-10-17 (AGENTS.md has the detail):

  * Klein ALSO redraws the whole frame, even for a boxed edit — 18.5 of mean
    change outside the box. Never ship the raw frame. With a `box`, `edit()`
    pastes back only that region (change outside it: exactly 0); without one,
    follow with composite_patch as before.
  * A layout box sets an object's SIZE as well as its place. A hand asked to
    fill a 220x166 box came back 220x166 and swollen. Size the box to the thing.
  * Hands are still the weak point: six region repairs on figures produced one
    clean hand. Run three seeds and expect to discard most.
  * There is no guidance dial. The model is step-distilled at cfg 1, so
    Kontext's `guidance` (preservation vs obedience) has no equivalent.

NOT YET MEASURED on this server's own work: hand repair on LTX frames, and
blinks. Kontext Q6_K's numbers (every damaged frame rescued at least once in
three seeds) are not Klein's numbers. Judge the first runs by eye.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import time
import uuid

import requests
from PIL import Image, ImageFilter

KLEIN_URL = os.environ.get("WEBCOMIC_ANIME_KLEIN_URL", "http://127.0.0.1:8189")
KLEIN_DIR = os.environ.get("WEBCOMIC_ANIME_KLEIN_DIR", r"C:\AI\ComfyUI_flux3")
KLEIN_PORT = KLEIN_URL.rsplit(":", 1)[-1].split("/")[0]
LAUNCH_TIMEOUT = int(os.environ.get("WEBCOMIC_ANIME_KLEIN_LAUNCH_TIMEOUT", "180"))
# Set WEBCOMIC_ANIME_KLEIN_AUTOLAUNCH=0 to require a manually started Klein ComfyUI.
AUTOLAUNCH = os.environ.get("WEBCOMIC_ANIME_KLEIN_AUTOLAUNCH", "1").lower() not in ("0", "false", "no", "")

# BFL's black-forest-labs/flux-3-image-klein-comfy files, the same three the
# other servers load. INT8, not FP8: an Ampere card has INT8 tensor cores and no
# native FP8. The _sd_ file is the step-distilled model.
MODEL = os.environ.get("WEBCOMIC_ANIME_KLEIN_MODEL", "flux3_image_klein_sd_int8_convrot.safetensors")
TEXT_ENCODER = os.environ.get("WEBCOMIC_ANIME_KLEIN_TE", "qwen3vl_4b_int8_convrot.safetensors")
VAE = os.environ.get("WEBCOMIC_ANIME_KLEIN_VAE", "flux2-vae.safetensors")

# Where each file must sit inside the Klein install, for check_status.
FILES = {"diffusion_models": MODEL, "text_encoders": TEXT_ENCODER, "vae": VAE}


class KleinError(RuntimeError):
    pass


def is_up(timeout: float = 2.0) -> bool:
    try:
        return requests.get(f"{KLEIN_URL}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


def busy(url: str = KLEIN_URL) -> int:
    """Jobs running or waiting on the ComfyUI at `url`; 0 when it is not up."""
    try:
        q = requests.get(f"{url}/queue", timeout=3).json()
    except Exception:
        return 0
    return len(q.get("queue_running", [])) + len(q.get("queue_pending", []))


def missing_files() -> list[str]:
    """Klein model files absent from the Klein install's models folders."""
    root = os.path.join(KLEIN_DIR, "ComfyUI", "models")
    return [f"{folder}/{name}" for folder, name in FILES.items()
            if not os.path.isfile(os.path.join(root, folder, name))]


def ensure_running() -> None:
    """Start the Klein ComfyUI if it is not up.

    Launches the embedded interpreter directly with the working directory set:
    the portable .bat uses relative paths and fails silently when started from
    anywhere else. DETACHED, so it outlives this server's process — an
    auto-launched ComfyUI that is a child of its launcher dies with it. Output
    goes to a log beside the install, because a crash otherwise leaves no trace.
    """
    if is_up():
        return
    if not AUTOLAUNCH:
        raise KleinError(f"Klein ComfyUI is not running at {KLEIN_URL} and autolaunch is off.")
    py = os.path.join(KLEIN_DIR, "python_embeded", "python.exe")
    if not os.path.isfile(py):
        raise KleinError(f"Klein ComfyUI not found at {KLEIN_DIR} (set WEBCOMIC_ANIME_KLEIN_DIR).")
    log = open(os.path.join(KLEIN_DIR, "comfy_klein.log"), "ab")
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    subprocess.Popen([py, "-s", "ComfyUI/main.py", "--windows-standalone-build", "--port", KLEIN_PORT],
                     cwd=KLEIN_DIR, creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=log, stderr=log, close_fds=True)
    t0 = time.time()
    while time.time() - t0 < LAUNCH_TIMEOUT:
        time.sleep(2.0)
        if is_up():
            return
    raise KleinError(f"Launched Klein ComfyUI but it was not ready within {LAUNCH_TIMEOUT}s; "
                     f"see {os.path.join(KLEIN_DIR, 'comfy_klein.log')}.")


def _upload(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{KLEIN_URL}/upload/image",
                          files={"image": (f"{uuid.uuid4().hex[:8]}_{os.path.basename(path)}", f,
                                           "application/octet-stream")},
                          data={"overwrite": "true"}, timeout=60)
    if r.status_code != 200:
        raise KleinError(f"Upload failed ({r.status_code}): {r.text[:200]}")
    return r.json()["name"]


def _submit(graph: dict, output_node: str, timeout: int) -> bytes:
    # The timeout counts QUEUE time as well as rendering: if the character or
    # background server has a job in, this one waits behind it.
    r = requests.post(f"{KLEIN_URL}/prompt", json={"prompt": graph}, timeout=30)
    if r.status_code != 200:
        raise KleinError(f"Prompt rejected ({r.status_code}): {r.text[:400]}")
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2.0)
        try:
            h = requests.get(f"{KLEIN_URL}/history/{pid}", timeout=30).json()
        except Exception:
            continue  # transient; ComfyUI is busy sampling
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                raise KleinError("Render failed: " + json.dumps(st.get("messages", []))[:800])
            outs = h[pid].get("outputs", {})
            if output_node not in outs:
                raise KleinError("Render produced no image (check comfy_klein.log).")
            img = outs[output_node]["images"][0]
            return requests.get(f"{KLEIN_URL}/view", timeout=60, params={
                "filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]}).content
    raise KleinError(f"Timed out after {timeout}s")


def _snap(v: int) -> int:
    return max(16, int(round(v / 16.0)) * 16)


def _layout(prompt: str, box, width: int, height: int) -> str:
    """Append one layout row the way ComfyUI's Flux3LayoutPrompt does.

    Klein was trained on [ymin, xmin, ymax, xmax] rows on a 0-1000 grid.
    """
    x0, y0, x1, y1 = box
    row = {"id": "obj_1", "desc": "the region to redraw", "bbox": [
        round(min(y0, y1) / height * 1000), round(min(x0, x1) / width * 1000),
        round(max(y0, y1) / height * 1000), round(max(x0, x1) / width * 1000)]}
    return f"{prompt.rstrip()} {json.dumps([row], ensure_ascii=False)}"


def graph(uploaded: str, text: str, width: int, height: int, seed: int,
          megapixels: float, steps: int = 16, prefix: str = "anime_klein") -> dict:
    """ComfyUI API graph for one reference-conditioned Klein render.

    Follows ComfyUI v0.41's image_flux3_klein_distilled template with one
    reference: cfg 1, 16 steps, euler. The template's prompt upsampler is left
    OFF — it rewrites the prompt before the model sees it.
    """
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "flux3", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "21": {"class_type": "LoadImage", "inputs": {"image": uploaded}},
        "7": {"class_type": "ReferenceMultiLatent", "inputs": {
            "positive": ["4", 0], "negative": ["5", 0], "vae": ["3", 0],
            "resolution": "resize", "resolution.megapixels": float(megapixels),
            "images.image1": ["21", 0]}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["6", 0], "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }


def edit(image_path: str, instruction: str, out_dir: str, seed: int, box=None,
         steps: int = 16, feather: int = 14, pad: int = 24, timeout: int = 900) -> dict:
    """Edit one frame; the source file is never modified.

    Always writes the FULL redrawn frame (`full`), resized to the source's exact
    size so composite_patch can take any region of it — the eye interiors for a
    blink, say — without re-registering.

    box: (x0, y0, x1, y1) in the source's pixels. It is both told to the model
        as a layout box (where to draw, and how big) and used to paste back
        ONLY that region, grown by `pad` and feathered, as `path`.
    """
    ensure_running()
    src = Image.open(image_path).convert("RGB")
    W, H = src.size
    text = (f"Image 1 is the picture to edit. {instruction.rstrip()} "
            f"Keep everything else in the picture exactly as it is.")
    if box is not None:
        text = _layout(text, box, W, H)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    t0 = time.time()
    data = _submit(graph(_upload(image_path), text, _snap(W), _snap(H), seed,
                         W * H / (1024 * 1024), steps, prefix=f"anime_{stem}"),
                   "10", timeout)
    new = Image.open(io.BytesIO(data)).convert("RGB")
    if new.size != (W, H):
        # At most 15 px off, from snapping to 16; the reference is encoded at
        # the source's own aspect, so a straight resize is the exact inverse.
        new = new.resize((W, H), Image.LANCZOS)

    os.makedirs(out_dir, exist_ok=True)
    full = os.path.join(out_dir, f"{stem}_edit_s{seed}_full.png")
    new.save(full)
    out = {"seed": seed, "full": full, "path": full, "seconds": round(time.time() - t0, 1)}
    if box is not None:
        x0, y0, x1, y1 = [int(v) for v in box]
        m = Image.new("L", (W, H), 0)
        m.paste(255, (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)))
        m = m.filter(ImageFilter.GaussianBlur(feather))
        path = os.path.join(out_dir, f"{stem}_edit_s{seed}.png")
        Image.composite(new, src, m).save(path)
        out["path"] = path
    return out


def recipe(image_path: str, edit_text: str, *, box=None, steps: int = 16, **_ignored) -> dict:
    return {"image": image_path, "edit": edit_text, "box": list(box) if box else None,
            "steps": steps, "model": MODEL}
