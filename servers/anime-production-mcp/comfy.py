"""
comfy.py — shared ComfyUI plumbing for the anime-production server.

Deliberately a near-copy of music-generation-mcp's comfy.py: same auto-launch
contract, same env-var shape, same "no code dependency on the sibling server"
rule. Duplicated rather than imported because each server folder must stay
independently installable (README convention, ARCHITECTURE.md §2.5).

What differs from the music server: outputs come back from /history as an
`images` list (LTX's SaveAnimatedWEBP and Kontext's SaveImage both report under
that key, animated or not), and this server needs to PUSH an illustration into
ComfyUI's input folder before it can be referenced by LoadImage.

Everything here is model-agnostic. Graph construction lives in ltx_workflow.py
and kontext_workflow.py; nothing in this module knows what LTX or Kontext is.
"""

from __future__ import annotations

import os
import subprocess
import time

import requests


COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")

COMFY_DIR = os.environ.get("WEBCOMIC_ANIME_COMFY_DIR", r"C:\AI\ComfyUI_windows_portable")
COMFY_LAUNCH = os.environ.get("WEBCOMIC_ANIME_COMFY_LAUNCH", "run_nvidia_gpu.bat")
AUTOLAUNCH = os.environ.get("WEBCOMIC_ANIME_AUTOLAUNCH", "1").lower() not in ("0", "false", "no", "")
LAUNCH_TIMEOUT = int(os.environ.get("WEBCOMIC_ANIME_LAUNCH_TIMEOUT", "180"))

# A 17-frame distilled LTX take is ~65 s on a 6 GB card, but `dev` at len 25 and
# a Kontext seed sweep both run far longer, and the first call of a session also
# pays model load. 1800 s is the same headroom the music server allows.
DEFAULT_TIMEOUT = int(os.environ.get("WEBCOMIC_ANIME_TIMEOUT", "1800"))


class ComfyUIError(RuntimeError):
    pass


def comfy_is_up(timeout: float = 2.0) -> bool:
    try:
        return requests.get(f"{COMFY_URL}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


def system_stats() -> dict:
    try:
        return requests.get(f"{COMFY_URL}/system_stats", timeout=5).json()
    except Exception as e:
        raise ComfyUIError(f"Could not read ComfyUI system stats: {e}") from e


def _spawn_comfy() -> None:
    """Start ComfyUI as a detached background process (survives this server)."""
    launch_path = COMFY_LAUNCH
    if not os.path.isabs(launch_path):
        launch_path = os.path.join(COMFY_DIR, launch_path)
    if not os.path.isfile(launch_path):
        raise ComfyUIError(
            f"Cannot auto-launch ComfyUI: launcher not found at {launch_path}. "
            f"Set WEBCOMIC_ANIME_COMFY_DIR / WEBCOMIC_ANIME_COMFY_LAUNCH, or start "
            f"ComfyUI manually."
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
            f"(WEBCOMIC_ANIME_AUTOLAUNCH=0). Start it manually."
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


def list_models(folder: str) -> list[str]:
    """What ComfyUI currently believes is on disk for a given loader.

    NOTE: ComfyUI caches some folder listings at startup. After adding a model
    file, a stale list here means ComfyUI needs restarting — re-querying will
    keep returning the old one. This cost real time on the LTX install.

    `unet_gguf` and `clip_gguf` are city96's ComfyUI-GGUF loaders. They are a
    THIRD-PARTY dependency, not core: if these raise, the custom node is not
    installed and the whole LTX path is unavailable.
    """
    node, field = {
        "diffusion_models": ("UNETLoader", "unet_name"),
        "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
        "text_encoders": ("CLIPLoader", "clip_name"),
        "vae": ("VAELoader", "vae_name"),
        "unet_gguf": ("UnetLoaderGGUF", "unet_name"),
        "clip_gguf": ("DualCLIPLoaderGGUF", "clip_name1"),
    }[folder]
    try:
        info = requests.get(f"{COMFY_URL}/object_info/{node}", timeout=15).json()
        return list(info[node]["input"]["required"][field][0])
    except Exception as e:
        raise ComfyUIError(f"Could not list {folder} (node {node}): {e}") from e


def upload_image(path: str) -> str:
    """Copy a local image into ComfyUI's input folder, returning the name
    LoadImage expects.

    Callers pass ordinary filesystem paths — an illustration lives in the
    artist's Pictures folder, not in ComfyUI's input dir, and making every
    caller pre-stage files there by hand is exactly the friction this server
    exists to remove.

    Ensures ComfyUI is up first. Uploading is the FIRST thing a generation does,
    so leaving the auto-launch to submit_and_wait meant a cold ComfyUI failed
    here with a bare connection-refused and never got the chance to start.
    """
    if not os.path.isfile(path):
        raise ComfyUIError(f"Image not found: {path}")
    ensure_comfy_running()
    with open(path, "rb") as f:
        files = {"image": (os.path.basename(path), f, "application/octet-stream")}
        data = {"overwrite": "true", "type": "input"}
        r = requests.post(f"{COMFY_URL}/upload/image", files=files, data=data, timeout=120)
    if r.status_code != 200:
        raise ComfyUIError(f"Upload failed ({r.status_code}): {r.text[:200]}")
    return r.json()["name"]


def submit_and_wait(graph: dict, timeout: int = DEFAULT_TIMEOUT,
                    poll: float = 3.0) -> dict[str, list[dict]]:
    """Run a graph, block until it finishes, return {node_id: [file_ref, ...]}.

    ComfyUI runs prompts SERIALLY — a second job submitted while one is running
    just waits in queue and burns its timeout there. Callers must submit one job
    at a time. This is why the seed hunt in animate_shot is a sequential loop
    and not a fan-out.
    """
    ensure_comfy_running()
    r = requests.post(f"{COMFY_URL}/prompt", json={"prompt": graph}, timeout=60)
    if r.status_code != 200:
        raise ComfyUIError(f"ComfyUI rejected the graph ({r.status_code}): {r.text[:800]}")
    prompt_id = r.json()["prompt_id"]

    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(poll)
        try:
            h = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=30).json()
        except Exception:
            continue  # transient; ComfyUI is busy sampling
        if prompt_id not in h:
            continue
        entry = h[prompt_id]
        status = entry.get("status", {})
        for m in status.get("messages", []):
            if m[0] in ("execution_error", "execution_interrupted"):
                raise ComfyUIError(f"ComfyUI reported an error: {str(m[1])[:800]}")
        if status.get("status_str") == "error":
            raise ComfyUIError(f"ComfyUI reported an error: {str(status)[:800]}")
        outputs = entry.get("outputs") or {}
        found = {nid: out["images"] for nid, out in outputs.items() if "images" in out}
        if found:
            return found
        if status.get("completed"):
            raise ComfyUIError(
                f"Graph completed but produced no image output. Status: {str(status)[:400]}"
            )
    raise ComfyUIError(
        f"Timed out after {timeout}s waiting for ComfyUI. Raise WEBCOMIC_ANIME_TIMEOUT, "
        f"or check the ComfyUI window for an OOM."
    )


def fetch(file_ref: dict, out_path: str) -> str:
    """Download one output file from ComfyUI to out_path."""
    params = {
        "filename": file_ref["filename"],
        "subfolder": file_ref.get("subfolder", ""),
        "type": file_ref.get("type", "output"),
    }
    r = requests.get(f"{COMFY_URL}/view", params=params, timeout=300)
    if r.status_code != 200:
        raise ComfyUIError(f"Could not fetch {file_ref['filename']} ({r.status_code})")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path
