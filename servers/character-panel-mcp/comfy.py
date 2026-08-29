"""
comfy.py — shared ComfyUI plumbing for this server.

Extracted from the former workflow.py when the SD1.5/SDXL path was retired in
favour of FLUX (see CHANGELOG). Everything here is model-agnostic: connecting to
ComfyUI, auto-launching it, uploading images, the clean-backdrop prompt suffix
that makes a render matte cleanly, and rembg matting.

Graph construction and generation live in flux_workflow.py. Nothing in this
module knows what a checkpoint is.

Shares its ComfyUI connection (COMFY_URL) with webcomic-background-mcp by
convention — both point at the same local install by default — but there is no
code dependency on that server.
"""

import os
import time
import subprocess

import requests


COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")

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

# NOTE the words that are deliberately absent: "studio", "even lighting" and
# "sharp edges" all read as photography to FLUX and fought the manhwa LoRA hard
# enough to return photoreal people (measured 2026-08-01, live). Say what the
# BACKDROP is; say nothing about the medium here — flux_workflow's
# FLUX_STYLE_SUFFIX owns that.
CLEAN_BACKDROP_SUFFIX = (
    ", solo, full body, standing pose, plain flat light-gray background, "
    "solid colour background, no scenery"
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


# rembg's DEFAULT session is u2net, which is trained on photographs and must be
# downloaded from GitHub on first use — a download that fails behind SSL
# interception with SSLCertVerificationError, from inside rembg, so it does not
# look like a matting error at all. isnet-anime is the right model for this art
# anyway (drawn/cel-shaded, not photographic).
REMBG_MODEL = os.environ.get("WEBCOMIC_CHAR_REMBG_MODEL", "isnet-anime")


def matte(image_path: str, out_path: str | None = None) -> str:
    """Auto-remove the clean backdrop, producing an RGBA cutout.

    Prefers ComfyUI-RMBG (RMBG-2.0) when that custom node is installed, and
    falls back to `rembg` otherwise. RMBG is preferred because it lands ON the
    lineart: measured as the brightness of the 2 px rim just inside the
    silhouette against the figure's interior, RMBG scores -28.7 where a
    brightness-keyed cutout scores -11.5 and leaves a white fringe.

    Neither path keys on color or brightness, which matters: brightness cannot
    distinguish a white shirt from a white backdrop, and cleanup passes built on
    that assumption have deleted an entire garment (65,026 px, 24% of a figure)
    and punched 32,592 px of holes through a mid-gray t-shirt. A learned matte
    also removes backdrop TRAPPED inside the silhouette — between the legs, or
    between an arm and the torso — which is the failure those passes existed to
    patch up.

    Raises ComfyUIError with a usable message if neither path works. It must
    never return the un-matted RGB path: callers composite the result, and an
    RGB image with an opaque backdrop is only discovered much later.
    """
    from PIL import Image

    if out_path is None:
        root, _ = os.path.splitext(image_path)
        out_path = f"{root}_matted.png"

    try:
        return _matte_rmbg(image_path, out_path)
    except ComfyUIError:
        pass        # node absent or ComfyUI down — try the local model

    try:
        from rembg import remove, new_session
    except ImportError as e:
        raise ComfyUIError(
            "Matting needs either the ComfyUI-RMBG custom node (see README Step 3) "
            "or `rembg` in the server venv: <venv>/python -m pip install rembg pillow"
        ) from e

    try:
        session = new_session(REMBG_MODEL)
        cut = remove(Image.open(image_path).convert("RGBA"), session=session)
    except Exception as e:
        raise ComfyUIError(
            f"Matting failed. ComfyUI-RMBG is not available, and rembg could not run "
            f"model '{REMBG_MODEL}': {type(e).__name__}: {e}\n"
            f"  rembg downloads its model on first use, which fails behind SSL "
            f"interception. Fetch it manually into ~/.u2net/, set "
            f"WEBCOMIC_CHAR_REMBG_MODEL to a model already there, or install "
            f"ComfyUI-RMBG (README Step 3)."
        ) from e
    cut.save(out_path)
    return out_path


def _matte_rmbg(image_path: str, out_path: str, model: str = "RMBG-2.0") -> str:
    """Matte via the ComfyUI-RMBG custom node. Raises ComfyUIError if absent."""
    import json
    import urllib.request

    ensure_comfy_running()
    try:
        with urllib.request.urlopen(f"{COMFY_URL}/object_info/RMBG", timeout=10) as r:
            if not json.load(r):
                raise ComfyUIError("ComfyUI-RMBG node not installed")
    except ComfyUIError:
        raise
    except Exception as e:
        raise ComfyUIError(f"could not query ComfyUI for the RMBG node: {e}") from e

    # imported here, not at module scope: flux_workflow imports this module
    from flux_workflow import _submit_and_wait

    uploaded = _upload_image(image_path)
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": uploaded}},
        "2": {"class_type": "RMBG",
              "inputs": {"image": ["1", 0], "model": model,
                         "sensitivity": 1.0, "process_res": 1024,
                         "mask_blur": 0, "mask_offset": 0,
                         "invert_output": False, "refine_foreground": True,
                         "background": "Alpha", "background_color": "#222222"}},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "matte"}},
    }
    data = _submit_and_wait(g, "3", timeout=300)
    with open(out_path, "wb") as fh:
        fh.write(data)
    return out_path
