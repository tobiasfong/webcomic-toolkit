"""
cloud_video.py — paid image-to-video through BytePlus ModelArk (Seedance 2.0).

The free path is LTX on the local card. This is the paid one, for the shots LTX
cannot do: an action that has to actually happen (a full kick, a thrust) rather
than drift, and hands that have to survive it. Nothing here touches the GPU or
ComfyUI — it is an HTTPS call to ByteDance's own API, so it can run while the
card is busy with something else.

⚠ EVERY CALL COSTS MONEY, AND SEEDANCE 2.0 HAS NO SEED. The API only accepts a
seed for its 1.x models, so a take cannot be reproduced and "run three seeds"
means "pay for three takes". The server defaults to ONE take per call.

⚠ THE PANEL LEAVES THE MACHINE. Each request uploads the artwork to BytePlus.

The three modes, as BytePlus documents them (2026-10):
    first frame                   animate forward from the panel
    first frame + last frame      interpolate between two drawings — the mode
                                  for an action LTX refuses: draw or render the
                                  END pose, let the model fill in the motion
    reference images (1-9)        "omni reference", with NO fixed first frame
The docs list these as separate modes, so this module refuses to mix reference
images with a first or last frame rather than spend a request finding out.

API: POST {ARK_URL}/contents/generations/tasks, then poll
GET {ARK_URL}/contents/generations/tasks/{id}. Output URLs expire after 24 h,
so the clip is downloaded as soon as the task succeeds.
"""

from __future__ import annotations

import base64
import io
import os
import re
import subprocess
import tempfile
import time

import requests
from PIL import Image

from tools.motion import _dedupe_guard

ARK_URL = os.environ.get("WEBCOMIC_ANIME_ARK_URL", "https://ark.ap-southeast.bytepluses.com/api/v3")
# The variable name BytePlus's own examples use. Never logged or returned.
API_KEY_ENV = "ARK_API_KEY"
# The Seedance 2.0 ID shown in BytePlus's examples. The fast and mini tiers have
# their own IDs; copy the exact string from the ModelArk console and set
# WEBCOMIC_ANIME_ARK_MODEL to use one.
MODEL = os.environ.get("WEBCOMIC_ANIME_ARK_MODEL", "dreamina-seedance-2-0-260128")

RESOLUTIONS = ("480p", "720p", "1080p")
# USD per second of output, for the ESTIMATE in each result. From a third-party
# pricing guide (Sept 2026), not from BytePlus: the bill in the ModelArk console
# is the real number. 480p had no published figure.
PRICE_PER_SEC = {"720p": 0.15, "1080p": 0.37}

# The API takes images up to 30 MB, but the whole request must stay under
# 64 MB and base64 adds a third; re-encode anything larger than this as JPEG.
MAX_INLINE_BYTES = 15 * 1024 * 1024


class CloudError(RuntimeError):
    pass


def has_key() -> bool:
    return bool(os.environ.get(API_KEY_ENV))


def estimate_usd(duration: int, resolution: str) -> float | None:
    per = PRICE_PER_SEC.get(resolution)
    return round(per * duration, 2) if per else None


def _data_uri(path: str) -> str:
    """The image inline, as the API's `data:image/<fmt>;base64,` form."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Image not found: {path}")
    with Image.open(path) as im:
        w, h = im.size
        if not (300 <= w <= 6000 and 300 <= h <= 6000):
            raise ValueError(f"{path} is {w}x{h}; BytePlus needs 300-6000 px per side.")
        if not 0.4 <= w / h <= 2.5:
            raise ValueError(f"{path} has aspect {w / h:.2f}; BytePlus needs 0.4-2.5.")
        if os.path.getsize(path) <= MAX_INLINE_BYTES and im.format in ("PNG", "JPEG", "WEBP"):
            fmt = im.format.lower()
            with open(path, "rb") as f:
                data = f.read()
        else:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=95)
            fmt, data = "jpeg", buf.getvalue()
    return f"data:image/{fmt};base64,{base64.b64encode(data).decode()}"


def payload(prompt: str, first_frame: str | None = None, last_frame: str | None = None,
            refs: list[str] | None = None, duration: int = 5, resolution: str = "720p",
            model: str = MODEL) -> dict:
    """The request body for one take. No network; testable on its own."""
    refs = refs or []
    if refs and (first_frame or last_frame):
        raise ValueError("BytePlus documents reference images as a separate mode with no "
                         "first or last frame. Pass either frames or refs, not both.")
    if not refs and not first_frame:
        raise ValueError("Give a first frame (the panel), or reference images.")
    if last_frame and not first_frame:
        raise ValueError("A last frame needs a first frame.")
    if len(refs) > 9:
        raise ValueError("Seedance 2.0 takes at most 9 reference images.")
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution must be one of {RESOLUTIONS}")
    if not 4 <= int(duration) <= 15:
        raise ValueError("Seedance 2.0 makes 4-15 s clips.")

    content: list[dict] = [{"type": "text", "text": prompt}]
    if first_frame:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(first_frame)},
                        "role": "first_frame"})
    if last_frame:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(last_frame)},
                        "role": "last_frame"})
    for r in refs:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(r)},
                        "role": "reference_image"})
    return {
        "model": model,
        "content": content,
        "resolution": resolution,
        # "adaptive" takes the aspect from the first frame, so a panel is never
        # stretched — the same rule pick_size enforces for LTX.
        "ratio": "adaptive",
        "duration": int(duration),
        # The soundtrack comes from the music server; generated audio would be
        # thrown away, and the API turns it ON unless told otherwise.
        "generate_audio": False,
        "watermark": False,
        # The end frame of one shot is a ready-made first frame for the next.
        "return_last_frame": True,
    }


def _headers() -> dict:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise CloudError(f"No BytePlus key. Create one in the ModelArk console and set the "
                         f"{API_KEY_ENV} environment variable for this server.")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def create(body: dict) -> str:
    r = requests.post(f"{ARK_URL}/contents/generations/tasks", json=body,
                      headers=_headers(), timeout=120)
    if r.status_code != 200:
        raise CloudError(f"BytePlus rejected the request ({r.status_code}): {r.text[:600]}")
    return r.json()["id"]


def wait(task_id: str, timeout: int = 1800, poll: float = 10.0) -> dict:
    """Poll until the task ends. Returns the task record on success."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(poll)
        try:
            r = requests.get(f"{ARK_URL}/contents/generations/tasks/{task_id}",
                             headers=_headers(), timeout=60)
        except requests.RequestException:
            continue  # transient; the task keeps running on their side
        if r.status_code != 200:
            raise CloudError(f"Task lookup failed ({r.status_code}): {r.text[:400]}")
        task = r.json()
        status = task.get("status")
        if status == "succeeded":
            return task
        if status in ("failed", "expired", "cancelled"):   # the API's own spelling
            raise CloudError(f"Task {task_id} {status}: {task.get('error')}")
    raise CloudError(f"Task {task_id} still running after {timeout}s. It may finish and be "
                     f"billed anyway; look it up in the ModelArk console within 24 h.")


def download(url: str, dest: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


def _probe_fps(mp4: str, ffmpeg: str) -> float:
    """The clip's frame rate, read from ffmpeg's own stream report."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", mp4], capture_output=True, text=True)
    m = re.search(r"(\d+(?:\.\d+)?) fps", r.stderr)
    # Seedance reports duration as frames / 24, so 24 is the right fallback.
    return float(m.group(1)) if m else 24.0


def to_view(mp4: str, dst: str, ffmpeg: str, fps: int = 12) -> dict:
    """Resample the mp4 to an animated webp at `fps`, the pipeline's clip format.

    The shot library, contact sheets, effects and the assembler all read
    animated webp at 12 fps (anime on twos), so a cloud take is converted once
    here and is then indistinguishable from an LTX take downstream.

    Resampled in Python, not with ffmpeg's fps filter: the ffmpeg this machine
    uses is Remotion's slimmed build, which ships without it.
    """
    src_fps = _probe_fps(mp4, ffmpeg)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([ffmpeg, "-v", "error", "-i", mp4,
                        os.path.join(tmp, "f%05d.png")], check=True)
        names = sorted(n for n in os.listdir(tmp) if n.endswith(".png"))
        if not names:
            raise CloudError(f"ffmpeg extracted no frames from {mp4}")
        n_out = max(1, int(round(len(names) * fps / src_fps)))
        picks = [names[min(len(names) - 1, int(round(k * src_fps / fps)))] for k in range(n_out)]
        # Pillow's WebP writer drops identical consecutive frames, which would
        # silently shorten a held pose; nudge them apart as retime() does.
        frames = _dedupe_guard([Image.open(os.path.join(tmp, n)).convert("RGB") for n in picks])
        frames[0].save(dst, save_all=True, append_images=frames[1:],
                       duration=[int(round(1000 / fps))] * len(frames), loop=0, quality=90)
    return {"path": dst, "frames": len(frames), "fps": fps, "source_fps": src_fps,
            "size": list(frames[0].size)}
