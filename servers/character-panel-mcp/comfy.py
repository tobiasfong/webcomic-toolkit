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
