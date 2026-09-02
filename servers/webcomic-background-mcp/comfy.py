"""
comfy.py — ComfyUI connection plumbing, shared by every generation path.

Model-agnostic on purpose: URL/launcher config, the auto-launch logic, image
upload, and graph submit/poll. Extracted from the old workflow.py when the
SD1.5 pipeline was retired in v2.0.0 — the SD1.5-specific graph building went
with it, this did not.
"""

import os
import time
import subprocess
import requests

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")

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


