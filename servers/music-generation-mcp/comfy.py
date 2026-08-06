"""
comfy.py — shared ComfyUI plumbing for the music server.

Deliberately a near-copy of character-panel-mcp's comfy.py: same auto-launch
contract, same env-var shape, same "no code dependency on the sibling server"
rule. Duplicated rather than imported because each server folder must stay
independently installable (README convention, ARCHITECTURE.md §2.5).

What is NOT shared with the image servers: audio outputs come back from
ComfyUI's /history as an `audio` list rather than `images`, and a single graph
can emit several files (we save FLAC and MP3 off one sampling pass). Hence the
local _submit_and_wait rather than reusing the image one.

Everything here is model-agnostic. Graph construction lives in ace_workflow.py;
nothing in this module knows what ACE-Step is.
"""

import os
import time
import subprocess

import requests


COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")

COMFY_DIR = os.environ.get("WEBCOMIC_MUSIC_COMFY_DIR", r"C:\AI\ComfyUI_windows_portable")
COMFY_LAUNCH = os.environ.get("WEBCOMIC_MUSIC_COMFY_LAUNCH", "run_nvidia_gpu.bat")
AUTOLAUNCH = os.environ.get("WEBCOMIC_MUSIC_AUTOLAUNCH", "1").lower() not in ("0", "false", "no", "")
LAUNCH_TIMEOUT = int(os.environ.get("WEBCOMIC_MUSIC_LAUNCH_TIMEOUT", "180"))

# Sampling a 2-minute song on a 6 GB card takes minutes, and the 1.5 path runs an
# autoregressive audio-code LLM before sampling even starts. The image servers'
# 300 s default is far too tight here.
DEFAULT_TIMEOUT = int(os.environ.get("WEBCOMIC_MUSIC_TIMEOUT", "1800"))


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
    """Start ComfyUI as a detached background process (survives this server).
    No-op path if a sibling server already has it running — ensure_comfy_running()
    only calls this when ComfyUI isn't already up."""
    launch_path = COMFY_LAUNCH
    if not os.path.isabs(launch_path):
        launch_path = os.path.join(COMFY_DIR, launch_path)
    if not os.path.isfile(launch_path):
        raise ComfyUIError(
            f"Cannot auto-launch ComfyUI: launcher not found at {launch_path}. "
            f"Set WEBCOMIC_MUSIC_COMFY_DIR / WEBCOMIC_MUSIC_COMFY_LAUNCH, or start "
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
            f"(WEBCOMIC_MUSIC_AUTOLAUNCH=0). Start it manually."
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
    keep returning the old one. (Learned on the LTX install; see CLAUDE.md.)
    """
    node, field = {
        "diffusion_models": ("UNETLoader", "unet_name"),
        "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
        "text_encoders": ("CLIPLoader", "clip_name"),
        "vae": ("VAELoader", "vae_name"),
    }[folder]
    try:
        info = requests.get(f"{COMFY_URL}/object_info/{node}", timeout=15).json()
        return list(info[node]["input"]["required"][field][0])
    except Exception as e:
        raise ComfyUIError(f"Could not list {folder}: {e}") from e


def upload_audio(path: str) -> str:
    """Upload a local audio file into ComfyUI's input folder, returning the name
    LoadAudio expects. Used by the 1.5 reference-timbre path."""
    if not os.path.isfile(path):
        raise ComfyUIError(f"Audio not found: {path}")
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
    at a time (CLAUDE.md, 'Practical').
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
        if status.get("status_str") == "error" or (status.get("completed") is False
                                                   and "error" in str(status).lower()):
            raise ComfyUIError(f"ComfyUI reported an error: {str(status)[:800]}")
        outputs = entry.get("outputs") or {}
        found = {nid: out["audio"] for nid, out in outputs.items() if "audio" in out}
        if found:
            return found
        if status.get("completed"):
            raise ComfyUIError(
                f"Graph completed but produced no audio output. Status: {str(status)[:400]}"
            )
    raise ComfyUIError(
        f"Timed out after {timeout}s waiting for ComfyUI. A long track on a small "
        f"card can legitimately exceed this — raise WEBCOMIC_MUSIC_TIMEOUT, or "
        f"check the ComfyUI window for an OOM."
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
