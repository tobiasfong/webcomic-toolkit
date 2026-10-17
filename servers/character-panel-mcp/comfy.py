"""
comfy.py — the main ComfyUI (port 8188), which this server uses for MATTING only.

Rendering moved to FLUX 3 Klein on its own ComfyUI (klein_workflow.py) and
FLUX.1 was removed in v2.0.0. What stays here is model-agnostic: connecting to
the main install, auto-launching it, uploading images, and the learned matte.

Shares its ComfyUI connection (COMFY_URL) with the other servers by convention,
with no code dependency on them.
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


# rembg's DEFAULT session is u2net, which is trained on photographs and must be
# downloaded from GitHub on first use — a download that fails behind SSL
# interception with SSLCertVerificationError, from inside rembg, so it does not
# look like a matting error at all. isnet-anime is the right model for this art
# anyway (drawn/cel-shaded, not photographic).
REMBG_MODEL = os.environ.get("WEBCOMIC_CHAR_REMBG_MODEL", "isnet-anime")


def _submit_and_wait(graph: dict, output_node: str, timeout: int = 300) -> bytes:
    """Submit a graph and return the output image's bytes. The timeout counts
    QUEUE time as well as running time -- keep jobs serial (AGENTS.md)."""
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
                # The RMBG node's own failures (a weight download that died, for
                # one) surface ONLY here, in /history, never to the client.
                msgs = h[prompt_id].get("status", {}).get("messages", [])
                raise ComfyUIError("Matting produced no image (check the ComfyUI log): "
                                   + str(msgs)[:400])
            img = outs[output_node]["images"][0]
            params = {"filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]}
            return requests.get(f"{COMFY_URL}/view", params=params, timeout=60).content
    raise ComfyUIError(f"Timed out after {timeout}s")


def _save(data: bytes, out_dir: str, stem: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, stem)
    out_path, n = base + ".png", 1
    while os.path.exists(out_path):
        out_path, n = f"{base}_{n}.png", n + 1
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


# ⚠ THE DEFAULT IS BiRefNet-general, AND THAT IS A LICENSE DECISION. RMBG-2.0 is
# BRIA's and its downloadable weights are for non-commercial use only; a game
# meant for sale cannot ship a sprite cut with it. BiRefNet -- the model RMBG-2.0
# is a fine-tune of -- is MIT, and recovered 100.0% of RMBG-2.0's mask on a jade
# slab with 0.2% extra and corners at exactly 0. BEN2 and INSPYRENET are MIT too;
# BEN2 left stray blobs at the corners of a flat backdrop and dropped a tray.
# Check a model's license at its ORIGINAL source the day it enters the pipeline.
#
# This line was the gap: the 2026-09-16 replacement switched the FLUX.1 module's
# matte_image() and never this module's matte(), which went on calling RMBG-2.0
# for every pose, expression and regenerated sprite. Both now go through here.
MATTE_MODEL = os.environ.get("WEBCOMIC_CHAR_MATTE_MODEL", "BiRefNet-general")


def _rmbg_bytes(image_path: str, model: str, sensitivity: float = 1.0,
                process_res: int = 1024, mask_blur: int = 0, mask_offset: int = 0,
                refine_foreground: bool = True, timeout: int = 300) -> bytes:
    """Run ComfyUI-RMBG's node on one image. Raises ComfyUIError if it is absent."""
    import json
    import urllib.request

    ensure_comfy_running()
    # The pack carries two nodes with the same shape of inputs: `RMBG` (RMBG-2.0,
    # INSPYRENET, BEN, BEN2) and `BiRefNetRMBG` (the BiRefNet family, which takes
    # no process_res -- it sizes from its own config).
    node_type = "BiRefNetRMBG" if model.startswith("BiRefNet") else "RMBG"
    try:
        with urllib.request.urlopen(f"{COMFY_URL}/object_info/{node_type}", timeout=10) as r:
            if not json.load(r):
                raise ComfyUIError(f"ComfyUI-RMBG's {node_type} node is not installed")
    except ComfyUIError:
        raise
    except Exception as e:
        raise ComfyUIError(f"could not query ComfyUI for the {node_type} node: {e}") from e

    inputs = {"image": ["1", 0], "model": model, "sensitivity": sensitivity,
              "mask_blur": mask_blur, "mask_offset": mask_offset, "invert_output": False,
              "refine_foreground": refine_foreground, "background": "Alpha",
              "background_color": "#222222"}
    if node_type == "RMBG":
        inputs["process_res"] = process_res
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": _upload_image(image_path)}},
        "2": {"class_type": node_type, "inputs": inputs},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "matte"}},
    }
    return _submit_and_wait(g, "3", timeout)


def matte_image(image_path: str, out_dir: str, model: str = MATTE_MODEL,
                sensitivity: float = 1.0, process_res: int = 1024,
                mask_blur: int = 0, mask_offset: int = 0,
                refine_foreground: bool = True, timeout: int = 300) -> str:
    """Cut an EXISTING image out onto transparency; saves <stem>_rgba.png in out_dir.

    The only route that works on art already made -- locked panels, approved
    concept panels, anything the author drew. ~4 s. Validated on the case color
    keying provably fails: a white robe with white boots on a white field came
    back with both intact, corners exactly 0.0000. Callers still keep the
    largest connected region plus a soft-edge band before cropping.

    refine_foreground: Fast Foreground Color Estimation, which suppresses halos
    on light subjects. Leave it on.

    Needs ComfyUI-RMBG's weights placed MANUALLY -- its auto-downloader fails
    against huggingface_hub 1.x, and that error surfaces only in ComfyUI's
    /history. Repo ids and folders are in custom_nodes/ComfyUI-RMBG/py/
    AILab_RMBG.py's AVAILABLE_MODELS; everything lands under models/RMBG/.

    Moved here from flux_workflow.py when FLUX.1 was removed.
    """
    data = _rmbg_bytes(image_path, model, sensitivity, process_res, mask_blur,
                       mask_offset, refine_foreground, timeout)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return _save(data, out_dir, stem + "_rgba")


def matte(image_path: str, out_path: str | None = None) -> str:
    """Auto-remove the clean backdrop, producing an RGBA cutout at out_path
    (default <image>_matted.png).

    Uses ComfyUI-RMBG with MATTE_MODEL (BiRefNet-general) and falls back to
    `rembg`'s isnet-anime when that node is not available. A learned matte lands
    ON the lineart where a brightness key leaves a white fringe, and it does not
    key on color: brightness cannot tell a white shirt from a white backdrop, and
    cleanup passes built on that assumption deleted a whole garment (65,026 px,
    24% of a figure). It also removes backdrop trapped inside the silhouette.
    For Klein renders, follow with klein_workflow.clean_matte(), which removes
    the pale fringe a learned matte leaves between hair strands.

    Raises ComfyUIError if neither path works. It must never return the
    un-matted RGB path: callers composite the result, and an RGB image with an
    opaque backdrop is only discovered much later.
    """
    from PIL import Image

    if out_path is None:
        root, _ = os.path.splitext(image_path)
        out_path = f"{root}_matted.png"

    try:
        data = _rmbg_bytes(image_path, MATTE_MODEL)
        with open(out_path, "wb") as fh:
            fh.write(data)
        return out_path
    except ComfyUIError:
        pass        # node absent or ComfyUI down -- try the local model

    try:
        from rembg import remove, new_session
    except ImportError as e:
        raise ComfyUIError(
            "Matting needs either the ComfyUI-RMBG custom node (see README) "
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
            f"ComfyUI-RMBG (README)."
        ) from e
    cut.save(out_path)
    return out_path
