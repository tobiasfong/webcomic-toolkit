"""
cloud_video.py — paid image-to-video through the Higgsfield API.

The free path is LTX on the local card. This is the paid one, for the shots LTX
cannot do: an action that has to actually happen (a full kick, a thrust, a
sprint) rather than drift, and faces and hands that have to survive it. Nothing
here touches the GPU or ComfyUI — it is HTTPS calls to Higgsfield, so it can run
while the card is busy with something else.

One account reaches several video models (Seedance, Kling, and more) through one
request lifecycle, which is why this replaced the direct BytePlus (Seedance-only)
client on 2026-10-26. MODELS below is the curated set this server will call,
each mapped from its own documented schema; a model is added here only after
its page at docs.higgsfield.ai/docs/models has been read.

⚠ EVERY TAKE COSTS MONEY, and none of these models takes a seed, so a take
cannot be reproduced and "run three seeds" means "pay for three takes". The
server defaults to ONE take per call. Failed and moderated (nsfw) requests are
not charged.

⚠ THE PANEL LEAVES THE MACHINE. Each image (or clip, for an edit) is uploaded
to Higgsfield's storage (tagged temporary) and passed to the model by its public
URL.

Two kinds of request:
    image-to-video (MODELS)       animate a panel, optionally toward an end pose
    video edit (EDIT_MODELS)      redo an existing take from a prompt, keeping
                                  its motion: the route for an LTX take whose
                                  motion is right but whose faces or hands smear

API (docs.higgsfield.ai, 2026-10):
    auth      Authorization: Key {HF_API_KEY_ID}:{HF_API_KEY_SECRET}
    upload    POST /files/generate-upload-url {content_type}, then PUT the bytes
              to upload_url with upload_headers (and NO credentials)
    estimate  POST /estimate/{endpoint} with the request body -> {"usd": "..."}
    submit    POST /{endpoint} with an Idempotency-Key -> request_id, status_url
    poll      GET status_url until completed / failed / nsfw / canceled;
              a finished video is at ["video"]["url"]
Outputs are deleted seven days after a request finishes, so the clip is
downloaded as soon as it completes.
"""

from __future__ import annotations

import io
import os
import random
import re
import subprocess
import tempfile
import time
import uuid

import requests
from PIL import Image

from tools.motion import _dedupe_guard

API_URL = os.environ.get("WEBCOMIC_ANIME_HF_URL", "https://api.higgsfield.ai")
# The variable names Higgsfield's own examples use. Never logged or returned.
KEY_ID_ENV, KEY_SECRET_ENV = "HF_API_KEY_ID", "HF_API_KEY_SECRET"
# Their TypeScript client reads both halves from one "id:secret" variable.
KEY_PAIR_ENV = "HF_CREDENTIALS"

# name -> how its documented schema spells each field.
#   endpoint    the path after the API root (also the estimate path)
#   first/last  the first- and last-frame URL fields
#   durations   (min, max) seconds
#   resolutions accepted "resolution" values; None = the model has no such
#               field (Kling's tier is the endpoint itself)
#   audio       (field, value) that turns generated sound OFF — the soundtrack
#               comes from the music server, and most of these default it ON
#   fixed       fields sent as-is on every request
MODELS: dict[str, dict] = {
    "seedance-2.5": {
        "endpoint": "bytedance/seedance-2.5/image-to-video",
        "first": "image_url", "last": "end_image_url", "durations": (4, 30),
        "resolutions": ("480p", "720p", "1080p"), "audio": ("generate_audio", False),
        "fixed": {"bitrate_mode": "high"},
    },
    "seedance-2.0": {
        "endpoint": "bytedance/seedance-2.0/image-to-video",
        "first": "image_url", "last": "end_image_url", "durations": (4, 15),
        "resolutions": ("480p", "720p", "1080p", "4k"), "audio": ("generate_audio", False),
        "fixed": {},
    },
    "kling-3.0-std": {
        "endpoint": "kling-video/v3.0/std/image-to-video",
        "first": "image_url", "last": "last_image_url", "durations": (3, 15),
        "resolutions": None, "audio": ("sound", "off"), "fixed": {},
    },
    "kling-3.0-pro": {
        "endpoint": "kling-video/v3.0/pro/image-to-video",
        "first": "image_url", "last": "last_image_url", "durations": (3, 15),
        "resolutions": None, "audio": ("sound", "off"), "fixed": {},
    },
    # Kling O3's first-and-last-frame workflow. Its own field names differ from
    # Kling 3.0's (first_frame_url, not image_url), and its tier is a field.
    "kling-o3": {
        "endpoint": "kling-video/o3/first-last-frame",
        "first": "first_frame_url", "last": "last_frame_url", "durations": (3, 15),
        "resolutions": None, "audio": ("sound", "off"), "fixed": {"mode": "pro"},
    },
}

# Video edit: the take goes in, a redone take comes out with its timing.
#   video        the source clip field; a list field takes exactly one URL
#   seconds      (min, max) source length the endpoint accepts. Seedance pads a
#                shorter clip to 4 s itself; stretching it here first keeps
#                that padding under our control (see edit_source)
#   max_images   reference images (the panel, to keep faces on model)
EDIT_MODELS: dict[str, dict] = {
    "seedance-2.5-edit": {
        "endpoint": "bytedance/seedance-2.5/video-edit",
        "video": "video_url", "video_is_list": False, "seconds": (4, 30),
        "max_images": 30, "resolutions": ("480p", "720p", "1080p"),
        "audio": ("generate_audio", False), "fixed": {"bitrate_mode": "high"},
    },
    # Duration is derived from the clip; the endpoint takes 3-15.5 s, 200 MB.
    "kling-o3-edit": {
        "endpoint": "kling-video/o3/video-edit",
        "video": "video_urls", "video_is_list": True, "seconds": (3, 15.5),
        "max_images": 4, "resolutions": None, "audio": None, "fixed": {"mode": "pro"},
    },
}
EDIT_MAX_BYTES = 200 * 1024 * 1024

UPLOAD_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
TERMINAL = ("completed", "failed", "nsfw", "canceled")


class CloudError(RuntimeError):
    pass


def _credentials() -> tuple[str, str] | None:
    kid, secret = os.environ.get(KEY_ID_ENV), os.environ.get(KEY_SECRET_ENV)
    if kid and secret:
        return kid, secret
    pair = os.environ.get(KEY_PAIR_ENV, "")
    if ":" in pair:
        kid, secret = pair.split(":", 1)
        return kid, secret
    return None


def has_key() -> bool:
    return _credentials() is not None


def _headers() -> dict:
    cred = _credentials()
    if not cred:
        raise CloudError(f"No Higgsfield key. Create one at console.higgsfield.ai and set "
                         f"{KEY_ID_ENV} and {KEY_SECRET_ENV} for this server.")
    return {"Authorization": f"Key {cred[0]}:{cred[1]}", "Content-Type": "application/json"}


def model_spec(model: str) -> dict:
    spec = MODELS.get(model) or EDIT_MODELS.get(model)
    if spec is None:
        raise ValueError(f"Unknown model {model!r}; one of {sorted(MODELS) + sorted(EDIT_MODELS)}.")
    return spec


def payload(model: str, prompt: str, first_url: str, last_url: str | None = None,
            duration: int = 5, resolution: str | None = "720p") -> dict:
    """The request body for one take, from already-uploaded image URLs.

    No network; testable on its own. `resolution` is ignored by models without
    the field (Kling), and refused when a model has the field but not the value.
    """
    if model not in MODELS:
        raise ValueError(f"{model!r} is not an image-to-video model; one of {sorted(MODELS)}.")
    spec = MODELS[model]
    if not prompt or not prompt.strip():
        # Kling requires one, and an unprompted take is money spent on a guess.
        raise ValueError("Give a prompt: camera first, the motion, then what stays still.")
    if not first_url:
        raise ValueError("A first frame (the panel) is required.")
    lo, hi = spec["durations"]
    if not lo <= int(duration) <= hi:
        raise ValueError(f"{model} makes {lo}-{hi} s clips.")
    body = {"prompt": prompt, spec["first"]: first_url, "duration": int(duration)}
    if last_url:
        body[spec["last"]] = last_url
    if spec["resolutions"] is not None and resolution is not None:
        if resolution not in spec["resolutions"]:
            raise ValueError(f"{model} resolution must be one of {spec['resolutions']}.")
        body["resolution"] = resolution
    field, off = spec["audio"]
    body[field] = off
    body.update(spec["fixed"])
    return body


def edit_payload(model: str, prompt: str, video_url: str, image_urls: list[str] | None = None,
                 resolution: str | None = "720p") -> dict:
    """The request body for one video-edit take. No network; testable on its own."""
    if model not in EDIT_MODELS:
        raise ValueError(f"{model!r} is not a video-edit model; one of {sorted(EDIT_MODELS)}.")
    spec = EDIT_MODELS[model]
    if not prompt or not prompt.strip():
        raise ValueError("Give a prompt: what to keep (the motion, the camera), then what to redo.")
    if not video_url:
        raise ValueError("A source clip is required.")
    image_urls = list(image_urls or [])
    if len(image_urls) > spec["max_images"]:
        raise ValueError(f"{model} takes at most {spec['max_images']} reference images.")
    body = {"prompt": prompt, spec["video"]: [video_url] if spec["video_is_list"] else video_url}
    if image_urls:
        body["image_urls"] = image_urls
    if spec["resolutions"] is not None and resolution is not None:
        if resolution not in spec["resolutions"]:
            raise ValueError(f"{model} resolution must be one of {spec['resolutions']}.")
        body["resolution"] = resolution
    if spec["audio"]:
        field, off = spec["audio"]
        body[field] = off
    body.update(spec["fixed"])
    return body


def edit_source(clip_path: str, out_mp4: str, model: str, fit: str = "slow") -> dict:
    """Write the take as the mp4 an edit endpoint will accept.

    LTX takes run about 2 s, under both endpoints' minimum. fit "slow" plays the
    same frames at a lower rate until the clip is long enough, so the model sees
    the whole motion, slowed; fit "pad" holds the last frame instead. Either way
    the result is put back to the take's own length by to_view(speed=,
    max_seconds=); the returned dict carries both values.
    """
    from tools import repair   # the clip reader and writer the repair tools use

    if fit not in ("slow", "pad"):
        raise ValueError('fit must be "slow" or "pad".')
    lo, hi = EDIT_MODELS[model]["seconds"]
    frames, fps = repair.read_clip(clip_path)
    if not frames:
        raise ValueError(f"No frames in {clip_path}")
    seconds = len(frames) / fps
    if seconds > hi:
        raise ValueError(f"{os.path.basename(clip_path)} runs {seconds:.1f} s; {model} takes at "
                         f"most {hi} s. Cut it first.")
    # A small margin, so rounding in the encoder never lands under the minimum.
    target = lo + 0.25
    speed, out_fps = 1.0, fps
    if seconds < target:
        if fit == "slow":
            out_fps = len(frames) / target
            speed = fps / out_fps
        else:
            frames = frames + [frames[-1]] * (int(target * fps + 0.999) - len(frames))
    # libx264 needs even sides.
    w, h = frames[0].size
    if w % 2 or h % 2:
        frames = [f.crop((0, 0, w - w % 2, h - h % 2)) for f in frames]
    repair.write_clip(frames, out_fps, out_mp4)
    if os.path.getsize(out_mp4) > EDIT_MAX_BYTES:
        raise ValueError(f"{out_mp4} is over {EDIT_MAX_BYTES >> 20} MB.")
    return {"mp4": out_mp4, "source_seconds": round(seconds, 3),
            "sent_seconds": round(len(frames) / out_fps, 3), "speed": speed, "fit": fit}


def upload(path: str) -> str:
    """Upload one image or mp4 to Higgsfield storage; returns its public URL."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")
    if path.lower().endswith(".mp4"):
        with open(path, "rb") as f:
            return _put(f.read(), "video/mp4")
    with Image.open(path) as im:
        ctype = UPLOAD_TYPES.get(im.format or "")
        if ctype:
            with open(path, "rb") as f:
                data = f.read()
        else:
            # Anything else is re-encoded as PNG, losslessly.
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "PNG")
            ctype, data = "image/png", buf.getvalue()
    return _put(data, ctype)


def _put(data: bytes, ctype: str) -> str:
    r = requests.post(f"{API_URL}/files/generate-upload-url", json={"content_type": ctype},
                      headers=_headers(), timeout=60)
    if r.status_code != 200:
        raise CloudError(f"Upload URL refused ({r.status_code}): {r.text[:400]}")
    slot = r.json()
    # The presigned URL gets only the headers Higgsfield returned — never the key.
    put = requests.put(slot["upload_url"], data=data,
                       headers=slot.get("upload_headers") or {"Content-Type": ctype}, timeout=300)
    if put.status_code not in (200, 201, 204):
        raise CloudError(f"Upload failed ({put.status_code}): {put.text[:400]}")
    return slot["public_url"]


def estimate_usd(model: str, body: dict) -> float | None:
    """Higgsfield's own price for this exact request, before it is submitted."""
    r = requests.post(f"{API_URL}/estimate/{model_spec(model)['endpoint']}", json=body,
                      headers=_headers(), timeout=60)
    if r.status_code != 200:
        raise CloudError(f"Estimate refused ({r.status_code}): {r.text[:400]}")
    usd = r.json().get("usd")
    return round(float(usd), 4) if usd is not None else None


def submit(model: str, body: dict, attempts: int = 4) -> dict:
    """Queue one generation. Retries a lost, 5xx or queue-full submission with
    the SAME Idempotency-Key, so a retry can never be billed as a second take."""
    url = f"{API_URL}/{model_spec(model)['endpoint']}"
    headers = {**_headers(), "Idempotency-Key": str(uuid.uuid4())}
    delay, err = 2.0, ""
    for attempt in range(attempts):
        try:
            r = requests.post(url, json=body, headers=headers, timeout=120)
        except requests.RequestException as e:
            err = f"network: {e}"
        else:
            if r.status_code in (200, 201, 202):
                return r.json()
            if r.status_code == 403:
                raise CloudError("Higgsfield refused the request: insufficient balance (403). "
                                 "Top up at console.higgsfield.ai.")
            if r.status_code not in (429, 500, 502, 503):
                raise CloudError(f"Higgsfield rejected the request ({r.status_code}): {r.text[:600]}")
            err = f"{r.status_code}: {r.text[:200]}"
            retry_after = r.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = max(delay, float(retry_after))
        if attempt < attempts - 1:
            time.sleep(delay + random.uniform(0, 0.5))
            delay = min(delay * 2, 60.0)
    raise CloudError(f"Submission failed after {attempts} tries ({err}).")


def wait(handle: dict, timeout: int = 1800) -> dict:
    """Poll until the request ends. Returns the record on completion.

    Never cancels. A request still running at the timeout keeps running (and is
    billed if it finishes); the error names it so it can be looked up.
    """
    rid = handle.get("request_id")
    status_url = handle.get("status_url") or f"{API_URL}/requests/{rid}/status"
    t0, delay = time.time(), 2.0
    while time.time() - t0 < timeout:
        time.sleep(delay + random.uniform(0, 0.5))
        delay = min(delay * 1.5, 10.0)
        try:
            r = requests.get(status_url, headers=_headers(), timeout=30)
        except requests.RequestException:
            continue  # transient; the request keeps running on their side
        if r.status_code >= 500:
            continue
        if r.status_code != 200:
            raise CloudError(f"Status lookup failed ({r.status_code}): {r.text[:400]}")
        rec = r.json()
        status = rec.get("status")
        if status == "completed":
            return rec
        if status in ("failed", "nsfw"):
            raise CloudError(f"Request {rid} ended {status}: "
                             f"{rec.get('error') or 'no reason given'} (not charged).")
        if status == "canceled":
            raise CloudError(f"Request {rid} was canceled.")
    raise CloudError(f"Request {rid} still running after {timeout}s. It may finish and be "
                     f"billed anyway; its output stays at Higgsfield for seven days.")


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
    return float(m.group(1)) if m else 24.0


def to_view(mp4: str, dst: str, ffmpeg: str, fps: int = 12,
            last_png: str | None = None, speed: float = 1.0,
            max_seconds: float | None = None) -> dict:
    """Resample the mp4 to an animated webp at `fps`, the pipeline's clip format.

    The shot library, contact sheets, effects and the assembler all read
    animated webp at 12 fps (anime on twos), so a cloud take is converted once
    here and is then indistinguishable from an LTX take downstream.
    `last_png` also saves the clip's final frame at full rate — a ready-made
    first frame for the next shot.
    `speed` plays the clip that many times faster and `max_seconds` keeps only
    that much of the result: how an edit sent slowed or padded (edit_source)
    gets its own timing back.

    Resampled in Python, not with ffmpeg's fps filter: the ffmpeg this machine
    uses is Remotion's slimmed build, which ships without it.
    """
    src_fps = _probe_fps(mp4, ffmpeg) * speed
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([ffmpeg, "-v", "error", "-i", mp4,
                        os.path.join(tmp, "f%05d.png")], check=True)
        names = sorted(n for n in os.listdir(tmp) if n.endswith(".png"))
        if not names:
            raise CloudError(f"ffmpeg extracted no frames from {mp4}")
        if max_seconds is not None:
            names = names[:max(1, int(round(max_seconds * src_fps)))]
        if last_png:
            Image.open(os.path.join(tmp, names[-1])).convert("RGB").save(last_png)
        n_out = max(1, int(round(len(names) * fps / src_fps)))
        picks = [names[min(len(names) - 1, int(round(k * src_fps / fps)))] for k in range(n_out)]
        # Pillow's WebP writer drops identical consecutive frames, which would
        # silently shorten a held pose; nudge them apart as retime() does.
        frames = _dedupe_guard([Image.open(os.path.join(tmp, n)).convert("RGB") for n in picks])
        frames[0].save(dst, save_all=True, append_images=frames[1:],
                       duration=[int(round(1000 / fps))] * len(frames), loop=0, quality=90)
    return {"path": dst, "frames": len(frames), "fps": fps, "source_fps": src_fps,
            "size": list(frames[0].size)}
