"""FLUX 3 Image Klein -- the background server's rendering model since v3.0.0.

Replaces FLUX.1-dev (GGUF unet + manwha_style LoRA + ControlNet Union Pro 2 +
Kontext), which the character-panel server had already left. Plates and
figures now come from the same model, for the same reason SD1.5 went in
v2.0.0: a plate from one model under figures from another reads as a
composite.

It runs on its OWN ComfyUI (v0.41+, port 8189), the same install the
character-panel server uses -- one Klein ComfyUI serves both. The main
ComfyUI (v0.25.1, port 8188) is left alone: LTX, the music model and matting
run there through add-ons never tested on v0.41.

What replaced each FLUX.1 part, measured 2026-10-17 on this server's own cases:

  * STYLE. FLUX.1 LoRAs cannot load in Klein (0 of manwha_style's 494 layers
    exist). The look comes from a positive style tail instead -- the same
    sentence the character server uses, so plates and figures match. On the
    murim bible's own prompts (an Anhui canal lane, the Mount Hua stair) it
    held crisp inked cel shading at eye level AND on the summit vista, the shot
    that pulled FLUX.1 photoreal.

  * CONTROLNET -> SKETCH AS REFERENCE. There is no Klein ControlNet. The
    white-on-black composition sketch is passed as reference image 1 with a
    lead sentence saying what it is. On the 3D bike-row sketch Klein put all
    four bicycles and the bollard exactly where the sketch drew them -- real
    bicycles, the case FLUX.1 needed the 3D proxy pipeline AND ControlNet for.
    Two wording traps, both measured:
      - "Render it as a finished, fully colored scene" came back PHOTOREAL.
        Saying "draw ... as a manhwa background illustration" fixed it.
      - The sketch's black was read as EMPTY SPACE: a city floated in a gray
        void until the lead said the black areas are ground, walls and sky.
    SKETCH_LEAD below is the wording that passed both.

  * LOCATION (img2img at 0.65 denoise) -> LOCATION AS REFERENCE. The canonical
    plate is reference image 1. The round library tower, asked for "the same
    room from a new angle, looking up toward the gallery and dome", kept its
    curved shelving, lattice gallery and radial coffered dome from a camera the
    canon never showed. FLUX.1's img2img could only nudge the canon's own
    framing (bible note 11: a clearing could not be got out of a path plate).

  * KONTEXT -> edit_region(). Klein redraws the WHOLE frame even for a boxed
    edit (character server measured 18.5 of mean change outside the box), so a
    region edit composites only its region back -- the change outside the box
    is exactly zero, which Kontext never managed.

  * SPEED. 14 s per plate text-to-image, 30-100 s with a reference, on the 6 GB
    card. FLUX.1 took ~225 s and timed out the MCP call on 1152x704 interiors.

The 9B prompt upsampler in BFL's repo is left OFF: it rewrites the prompt
before generation, and every prompting rule in this server assumes the prompt
the model sees is the one that was written.
"""
import io
import json
import os
import subprocess
import time
import uuid

import requests
from PIL import Image, ImageFilter

KLEIN_URL = os.environ.get("WEBCOMIC_BG_KLEIN_URL", "http://127.0.0.1:8189")
KLEIN_DIR = os.environ.get("WEBCOMIC_BG_KLEIN_DIR", r"C:\AI\ComfyUI_flux3")
KLEIN_PORT = KLEIN_URL.rsplit(":", 1)[-1].split("/")[0]
LAUNCH_TIMEOUT = int(os.environ.get("WEBCOMIC_BG_KLEIN_LAUNCH_TIMEOUT", "180"))
# Set WEBCOMIC_BG_AUTOLAUNCH=0 to require a manually started Klein ComfyUI.
AUTOLAUNCH = os.environ.get("WEBCOMIC_BG_AUTOLAUNCH", "1").lower() not in ("0", "false", "no", "")

# BFL's black-forest-labs/flux-3-image-klein-comfy files. INT8, not FP8: an
# Ampere card has INT8 tensor cores and no native FP8; NVFP4 needs Blackwell.
# The _sd_ file is the step-distilled model.
MODEL = os.environ.get("WEBCOMIC_BG_KLEIN_MODEL", "flux3_image_klein_sd_int8_convrot.safetensors")
TEXT_ENCODER = os.environ.get("WEBCOMIC_BG_KLEIN_TE", "qwen3vl_4b_int8_convrot.safetensors")
VAE = os.environ.get("WEBCOMIC_BG_KLEIN_VAE", "flux2-vae.safetensors")

# Identical to the character server's tail on purpose: plates and figures are
# meant to look like one drawing. Stated as positives -- Klein, like FLUX.1,
# does nothing useful with negatives.
STYLE = ("Manhwa illustration, crisp black outlines and hard-edged flat color, "
         "every edge in sharp focus.")

SKETCH_LEAD = ("Image 1 is a white-on-black line drawing that fixes the exact composition, "
               "camera angle and the outline of every object. Draw the scene it lays out as a "
               "manhwa background illustration, keeping every object exactly where and as large "
               "as image 1 draws it; the black areas of image 1 are not empty, fill them with "
               "the ground, walls and sky of the scene: ")


def location_lead(name: str) -> str:
    """Lead for a new view of a registered place (reference image 1)."""
    return (f"Image 1 shows {name}, an established place in this story. Keep it "
            f"recognizably the same place, with the same architecture, materials and "
            f"colors, while showing what follows: ")


class KleinError(RuntimeError):
    pass


def is_up(timeout: float = 2.0) -> bool:
    try:
        return requests.get(f"{KLEIN_URL}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


def port_in_use(timeout: float = 1.0) -> bool:
    """Something is LISTENING on the Klein port, whether or not it answers HTTP.

    A ComfyUI deep in an LTX render on this RAM-starved laptop can take longer
    than is_up()'s 2 s to answer /system_stats. Taking that as "not running"
    launched a SECOND ComfyUI mid-render (2026-10-24): it pinned ~13 GB of RAM
    before dying on the database lock, and the render it starved took 3 h 12 min
    instead of ~4. Never launch over an occupied port.
    """
    import socket
    host = KLEIN_URL.split("://", 1)[-1].split(":", 1)[0]
    try:
        with socket.create_connection((host, int(KLEIN_PORT)), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_running() -> None:
    """Start the Klein ComfyUI if it is not up.

    Launches the embedded interpreter directly with the working directory set:
    the portable .bat uses relative paths and fails silently when started from
    anywhere else. Output goes to a log beside the install, because a crash
    here otherwise leaves no trace.
    """
    if is_up():
        return
    if port_in_use():
        # Busy, not down: wait for it to answer instead of starting a second one.
        t0 = time.time()
        while time.time() - t0 < LAUNCH_TIMEOUT:
            if is_up(timeout=15.0):
                return
            time.sleep(5.0)
        raise KleinError(f"Something holds port {KLEIN_PORT} but has not answered for {LAUNCH_TIMEOUT}s; "
                         "not launching a second ComfyUI over it.")
    if not AUTOLAUNCH:
        raise KleinError(f"Klein ComfyUI is not running at {KLEIN_URL} and autolaunch is off.")
    py = os.path.join(KLEIN_DIR, "python_embeded", "python.exe")
    if not os.path.isfile(py):
        raise KleinError(f"Klein ComfyUI not found at {KLEIN_DIR} "
                         f"(set WEBCOMIC_BG_KLEIN_DIR; see setup_models.py).")
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
    if not os.path.isfile(path):
        raise KleinError(f"Image not found: {path}")
    with open(path, "rb") as f:
        r = requests.post(f"{KLEIN_URL}/upload/image",
                          files={"image": (f"{uuid.uuid4().hex[:8]}_{os.path.basename(path)}", f,
                                           "application/octet-stream")},
                          data={"overwrite": "true"}, timeout=60)
    if r.status_code != 200:
        raise KleinError(f"Upload failed ({r.status_code}): {r.text[:200]}")
    return r.json()["name"]


def _submit(graph: dict, output_node: str, timeout: int) -> bytes:
    # The timeout counts QUEUE time as well as rendering: if the character
    # server has a job in, this one waits behind it.
    r = requests.post(f"{KLEIN_URL}/prompt", json={"prompt": graph}, timeout=30)
    if r.status_code != 200:
        raise KleinError(f"Prompt rejected ({r.status_code}): {r.text[:400]}")
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2.0)
        h = requests.get(f"{KLEIN_URL}/history/{pid}", timeout=30).json()
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


def _save(data: bytes, out_dir: str, stem: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, stem)
    path, n = base + ".png", 1
    while os.path.exists(path):
        path, n = f"{base}_{n}.png", n + 1
    with open(path, "wb") as f:
        f.write(data)
    return path


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _snap(v: int) -> int:
    return max(16, int(round(v / 16.0)) * 16)


def generate(prompt: str, out_dir: str, width: int = 1024, height: int = 768,
             seed: int | None = None, refs: list[str] | None = None,
             megapixels: float = 1.0, steps: int | None = None, stem: str = "klein",
             add_style: bool = True, timeout: int = 900) -> str:
    """Render with Klein; return the saved PNG path.

    refs: reference images, referred to in the prompt as "image 1", "image 2"
        in the order given, each encoded at `megapixels` (1.0 is ~1024x1024,
        aspect kept). The caller writes the lead that says what each one is --
        SKETCH_LEAD or location_lead() -- because Klein does what the words say
        a reference is for.

    Graph follows ComfyUI v0.41's image_flux3_klein_distilled templates: cfg 1,
    15 steps text-to-image with er_sde, 16 with references with euler.
    """
    ensure_running()
    width, height = _snap(width), _snap(height)
    if seed is None:
        seed = uuid.uuid4().int % (2 ** 31)
    text = f"{prompt.rstrip()} {STYLE}" if add_style else prompt
    refs = refs or []
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "flux3", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "bg_" + stem}},
    }
    pos, neg = ["4", 0], ["5", 0]
    if refs:
        ri = {"positive": ["4", 0], "negative": ["5", 0], "vae": ["3", 0],
              "resolution": "resize", "resolution.megapixels": float(megapixels)}
        for i, r in enumerate(refs, 1):
            g[str(20 + i)] = {"class_type": "LoadImage", "inputs": {"image": _upload(r)}}
            ri[f"images.image{i}"] = [str(20 + i), 0]
        g["7"] = {"class_type": "ReferenceMultiLatent", "inputs": ri}
        pos, neg = ["7", 0], ["7", 1]
    g["8"] = {"class_type": "KSampler", "inputs": {
        "model": ["1", 0], "seed": seed, "steps": steps or (16 if refs else 15), "cfg": 1.0,
        "sampler_name": "euler" if refs else "er_sde", "scheduler": "simple",
        "positive": pos, "negative": neg, "latent_image": ["6", 0], "denoise": 1.0}}
    return _save(_submit(g, "10", timeout), out_dir, f"{stem}_{seed}")


def _layout(prompt: str, box, width: int, height: int) -> str:
    """Append one layout row the way ComfyUI's Flux3LayoutPrompt does.

    Klein was trained on [ymin, xmin, ymax, xmax] rows on a 0-1000 grid. A box
    sets an object's SIZE as well as its place -- size it to what should be
    drawn.
    """
    x0, y0, x1, y1 = box
    row = {"id": "obj_1", "desc": "the region to redraw", "bbox": [
        round(min(y0, y1) / height * 1000), round(min(x0, x1) / width * 1000),
        round(max(y0, y1) / height * 1000), round(max(x0, x1) / width * 1000)]}
    return f"{prompt.rstrip()} {json.dumps([row], ensure_ascii=False)}"


def edit(image_path: str, instruction: str, out_dir: str, box=None, seed: int | None = None,
         restyle: bool = False, feather: int = 14, pad: int = 24, timeout: int = 900) -> str:
    """Edit an existing plate; the source file is never modified.

    box: (x0, y0, x1, y1) in the source's pixels. Klein redraws the whole frame
        from the source as a reference, then ONLY the box (grown by `pad`,
        edges feathered) is composited back, so nothing outside it changes.
        Without a box the whole redrawn frame is returned.
    restyle: append the house style tail -- for pulling an off-style plate
        (photoreal, painterly) back to the inked look. Leave off for content
        edits, so the tail does not restyle what should stay.
    """
    src = Image.open(image_path).convert("RGB")
    W, H = src.size
    text = f"Image 1 is the picture to edit. {instruction.rstrip()}"
    if box is not None:
        text = _layout(f"{text} Keep everything else in the picture exactly as it is.", box, W, H)
    elif not restyle:
        text = f"{text} Keep everything else in the picture exactly as it is."
    raw = generate(text, out_dir, W, H, seed=seed, refs=[image_path],
                   megapixels=W * H / (1024 * 1024), stem="edit_raw",
                   add_style=restyle, timeout=timeout)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    new = Image.open(raw).convert("RGB")
    if new.size != (W, H):
        new = new.resize((W, H), Image.LANCZOS)
    if box is None:
        out = new
    else:
        x0, y0, x1, y1 = [int(v) for v in box]
        m = Image.new("L", (W, H), 0)
        m.paste(255, (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)))
        m = m.filter(ImageFilter.GaussianBlur(feather))
        out = Image.composite(new, src, m)
    os.remove(raw)
    return _save(_png(out), out_dir, f"{stem}_edit")
