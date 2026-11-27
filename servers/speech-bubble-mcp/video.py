"""
video.py — bubbles animated over a clip or a still, for manga videos.

ONE DRAWING, TWO USES. Each bubble is drawn once, by the same code that letters
a still page, and kept as a transparent sprite. A video frame is the source
frame with those sprites pasted on at the opacity, offset and scale their
animation calls for at that moment. The type is never redrawn per frame, so a
bubble in the video is pixel for pixel the bubble on the page.

ONE FUNCTION MAKES THE PREVIEW AND THE ENCODE. `compose()` builds the frame at
time t; the encode calls it for every frame and a preview calls it for the few
frames asked for. A preview made by a second implementation would only prove
that the two agree with themselves.

FFMPEG ONLY DECODES AND ENCODES. The compositing is done here, in Pillow,
because the ffmpeg this toolkit runs on is a reduced build with no overlay,
fade or pad filters. Frames come OUT as raw RGB over image2pipe and go IN as
PNG over image2pipe -- the same route anime-production's assembly proved works
on that build (its rawvideo demuxer is missing, so raw frames cannot go in).

TIMING. Each bubble appears after the one before it has had time to be read,
and every bubble stays up until the shot ends -- the way a manga page fills in
as you read it. If the lines need longer than the motion lasts, the last frame
is held. The reading-time rule below is a starting default, not a decision:
pass `start`/`end` on any bubble to set it by hand.

Animations (`in`): fade (default), slide-up, slide-down, slide-left,
slide-right (each also fades; the name is the direction of travel), pop (grows
from 80% while fading), none. `out`: none (default, stays to the end) or fade.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess

from PIL import Image

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
ANIMS = ("fade", "slide-up", "slide-down", "slide-left", "slide-right", "pop", "none")


def find_ffmpeg() -> str:
    for cand in (os.environ.get("SPEECH_BUBBLE_FFMPEG"),
                 os.environ.get("WEBCOMIC_ANIME_FFMPEG"), shutil.which("ffmpeg")):
        if cand and os.path.isfile(cand):
            return cand
    raise FileNotFoundError(
        "No ffmpeg found. Put one on PATH or set SPEECH_BUBBLE_FFMPEG. "
        "Still lettering works without it; only video needs it.")


def _ffprobe(ffmpeg: str) -> str | None:
    side = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe" if os.name == "nt" else "ffprobe")
    if os.path.isfile(side):
        return side
    return shutil.which("ffprobe")


def probe(path: str, ffmpeg: str | None = None) -> dict:
    """Size, duration, frame rate and audio of a clip; a still reports none."""
    if path.lower().endswith(IMAGE_EXT):
        with Image.open(path) as im:
            return {"still": True, "width": im.width, "height": im.height,
                    "duration": None, "fps": None, "audio": False}
    ffmpeg = ffmpeg or find_ffmpeg()
    fp = _ffprobe(ffmpeg)
    if fp:
        r = subprocess.run([fp, "-v", "error", "-show_streams", "-show_format",
                            "-of", "json", path], capture_output=True, text=True)
        if r.returncode == 0:
            d = json.loads(r.stdout)
            vs = next(s for s in d["streams"] if s["codec_type"] == "video")
            num, den = vs.get("r_frame_rate", "24/1").split("/")
            fps = float(num) / float(den or 1)
            dur = float(d.get("format", {}).get("duration") or vs.get("duration") or 0)
            return {"still": False, "width": int(vs["width"]), "height": int(vs["height"]),
                    "duration": dur, "fps": round(fps, 3),
                    "audio": any(s["codec_type"] == "audio" for s in d["streams"])}
    # No ffprobe: read what `ffmpeg -i` prints.
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True)
    err = r.stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    v = re.search(r"Video: .*?(\d{2,5})x(\d{2,5}).*?([\d.]+) fps", err)
    if not v:
        raise RuntimeError(f"Could not read video stream of {path}")
    return {"still": False, "width": int(v.group(1)), "height": int(v.group(2)),
            "duration": dur, "fps": float(v.group(3)), "audio": "Audio:" in err}


def decode(path: str, info: dict, ffmpeg: str | None = None):
    """Yield the clip's frames as RGB images, in order."""
    ffmpeg = ffmpeg or find_ffmpeg()
    W, H = info["width"], info["height"]
    n = W * H * 3
    proc = subprocess.Popen([ffmpeg, "-v", "error", "-i", path, "-f", "image2pipe",
                             "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            yield Image.frombytes("RGB", (W, H), buf)
    finally:
        proc.stdout.close()
        proc.wait()


def grab_frame(path: str, out_png: str, at_end: bool = True, ffmpeg: str | None = None):
    """The first or last frame of a clip, saved as PNG."""
    info = probe(path, ffmpeg)
    last = None
    for fr in decode(path, info, ffmpeg):
        last = fr
        if not at_end:
            break
    if last is None:
        raise RuntimeError(f"No frames decoded from {path}")
    last.save(out_png)
    return out_png


def fit(img: Image.Image, size) -> Image.Image:
    """Scale to fit the output frame, letterboxed in black if the shape differs."""
    if img.size == tuple(size):
        return img.convert("RGB")
    W, H = size
    s = min(W / img.width, H / img.height)
    w, h = max(1, round(img.width * s)), max(1, round(img.height * s))
    out = Image.new("RGB", (W, H), (0, 0, 0))
    out.paste(img.convert("RGB").resize((w, h), Image.LANCZOS), ((W - w) // 2, (H - h) // 2))
    return out


# --- timing -------------------------------------------------------------------

def read_seconds(text: str, lang: str) -> float:
    """Time to read one bubble. Roughly 3 words a second for English and 7
    characters a second for CJK, plus a beat to find the bubble. Clamped to
    1.5-6 s, which puts an ordinary line in the 2-4 s range."""
    if lang in ("ja", "zh"):
        n = len([c for c in text if not c.isspace()])
        t = 0.9 + n * 0.15
    else:
        t = 0.9 + len(text.split()) * 0.3
    return max(1.5, min(6.0, t))


def schedule(specs: list[dict], texts: list[str], lang: str, base: float | None,
             lead: float = 0.5, tail: float = 0.8, wait_for_motion: bool = False,
             fade: float = 0.45, hold: str | float = "auto") -> tuple[list[dict], float, float]:
    """Start and end times for every bubble, the clip's total length, and how
    long the last frame is held. `base` is the source length (None for a still)."""
    t = (base if (wait_for_motion and base) else 0.0) + lead
    times = []
    for spec, text in zip(specs, texts):
        start = float(spec["start"]) if spec.get("start") is not None else t
        rs = float(spec.get("read", read_seconds(text, lang)))
        times.append({"start": round(start, 3), "end": spec.get("end"), "read": round(rs, 2)})
        t = start + fade + rs
    need = t + tail - fade if times else (base or 2.0)
    if hold in ("auto", None):
        total = max(base or 0.0, need)
    else:
        total = (base or 0.0) + float(hold)
    held = max(0.0, total - base) if base else 0.0
    for tm in times:
        tm["end"] = round(float(tm["end"]) if tm["end"] is not None else total, 3)
    return times, round(total, 3), round(held, 3)


# --- compositing ----------------------------------------------------------------

def _ease_left(t: float, start: float, dur: float) -> float:
    """1 at the start of an entrance, easing out to 0 when it lands."""
    p = min(1.0, max(0.0, (t - start) / dur)) if dur > 0 else 1.0
    return (1.0 - p) ** 3


def state_at(s: dict, t: float, total: float, fade: float, W: int):
    """(opacity, dx, dy, scale) of one sprite at time t, or None if not shown."""
    if t < s["start"]:
        return None
    if s["end"] < total - 1e-6 and t >= s["end"]:
        return None
    anim = s.get("in", "fade")
    if anim == "none":
        op = 1.0
    else:
        op = min(1.0, (t - s["start"]) / fade) if fade > 0 else 1.0
    if s.get("out") == "fade" and s["end"] < total - 1e-6:
        op = min(op, max(0.0, (s["end"] - t) / fade) if fade > 0 else 1.0)
    e = _ease_left(t, s["start"], max(fade, 0.3)) if anim != "none" else 0.0
    dist = 0.05 * W
    dx = {"slide-left": dist * e, "slide-right": -dist * e}.get(anim, 0.0)
    dy = {"slide-up": dist * e, "slide-down": -dist * e}.get(anim, 0.0)
    sc = 1.0 - 0.2 * e if anim == "pop" else 1.0
    return op, dx, dy, sc


def _blit(frame: Image.Image, sprite: Image.Image, x: int, y: int):
    """alpha_composite that tolerates a sprite hanging off the frame."""
    W, H = frame.size
    l, t = max(0, -x), max(0, -y)
    r, b = min(sprite.width, W - x), min(sprite.height, H - y)
    if r <= l or b <= t:
        return
    frame.alpha_composite(sprite.crop((l, t, r, b)), (x + l, y + t))


def compose(base: Image.Image, sprites: list[dict], t: float, total: float,
            fade: float) -> Image.Image:
    """The lettered frame at time t. sprites: [{image, x0, y0, ax, ay, start,
    end, in, out}], (ax, ay) being the bubble's center inside its sprite as a
    fraction, which is the point a pop grows from."""
    frame = base.convert("RGBA")
    W = frame.width
    for s in sprites:
        st = state_at(s, t, total, fade, W)
        if st is None:
            continue
        op, dx, dy, sc = st
        if op <= 0.002:
            continue
        img = s["image"]
        x0, y0 = s["x0"], s["y0"]
        if sc != 1.0:
            w, h = max(1, round(img.width * sc)), max(1, round(img.height * sc))
            cx, cy = x0 + s["ax"] * img.width, y0 + s["ay"] * img.height
            img = img.resize((w, h), Image.LANCZOS)
            x0, y0 = cx - s["ax"] * w, cy - s["ay"] * h
        if op < 0.998:
            r, g, b, a = img.split()
            img = Image.merge("RGBA", (r, g, b, a.point(lambda v, k=op: round(v * k))))
        _blit(frame, img, round(x0 + dx), round(y0 + dy))
    return frame.convert("RGB")


def _animating(sprites, t, fade, total) -> bool:
    for s in sprites:
        if s["start"] - 1e-6 <= t < s["start"] + max(fade, 0.3) + 1e-6:
            return True
        if s.get("out") == "fade" and s["end"] - fade <= t <= s["end"] and s["end"] < total - 1e-6:
            return True
        if abs(t - s["start"]) < 1e-6 or abs(t - s["end"]) < 1e-6:
            return True
    return False


def frames(source: str, info: dict, size, fps: float, total: float):
    """(t, base frame, unchanged) for every output frame. The source is
    resampled to the output rate by picking the frame showing at each moment;
    past its end the last frame is held. `unchanged` is True when the base is
    the same picture as the previous frame's."""
    n = max(1, int(round(total * fps)))
    if info["still"]:
        with Image.open(source) as im:
            still = fit(im, size)
        for i in range(n):
            yield i / fps, still, i > 0
        return
    src_fps = info["fps"] or fps
    it = decode(source, info)
    cur, cur_idx, done, fitted, fitted_idx = None, -1, False, None, None
    for i in range(n):
        t = i / fps
        want = int(t * src_fps + 1e-6)
        while not done and cur_idx < want:
            nxt = next(it, None)
            if nxt is None:
                done = True
                break
            cur, cur_idx = nxt, cur_idx + 1
        if cur is None:
            raise RuntimeError(f"No frames decoded from {source}")
        same = fitted_idx == cur_idx
        if not same:
            fitted, fitted_idx = fit(cur, size), cur_idx
        yield t, fitted, same


def render(source: str, info: dict, size, fps: float, total: float, held: float,
           sprites: list[dict], out: str, fade: float = 0.45,
           preview_at: list[float] | None = None, crf: int = 18) -> dict:
    """Encode the lettered clip, or (with preview_at) only stills at those times."""
    stem = os.path.splitext(out)[0]
    if preview_at:
        want = sorted(min(max(0.0, float(t)), max(0.0, total - 1.0 / fps)) for t in preview_at)
        shots, k = [], 0
        for t, base, _ in frames(source, info, size, fps, total):
            while k < len(want) and t + 0.5 / fps >= want[k]:
                png = f"{stem}_preview_{want[k]:06.2f}s.png"
                compose(base, sprites, want[k], total, fade).save(png)
                shots.append(png)
                k += 1
            if k >= len(want):
                break
        return {"previews": shots, "seconds": total, "held": held}

    ffmpeg = find_ffmpeg()
    cmd = [ffmpeg, "-y", "-hide_banner", "-f", "image2pipe", "-vcodec", "png",
           "-framerate", f"{fps}", "-i", "-"]
    if info.get("audio"):
        cmd += ["-i", source, "-map", "0:v", "-map", "1:a?", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    log_path = stem + ".ffmpeg.log"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    count = 0
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=log)
        last_png, last_vis = None, None
        try:
            for t, base, same in frames(source, info, size, fps, total):
                # While nothing moves -- a held frame or a still, with no bubble
                # entering or leaving -- the frame is the same bytes as the last.
                vis = tuple(state_at(s, t, total, fade, size[0]) is not None for s in sprites)
                if (same and last_png is not None and vis == last_vis
                        and not _animating(sprites, t, fade, total)):
                    proc.stdin.write(last_png)
                else:
                    buf = io.BytesIO()
                    compose(base, sprites, t, total, fade).save(buf, format="PNG", compress_level=1)
                    last_png = buf.getvalue()
                    proc.stdin.write(last_png)
                last_vis = vis
                count += 1
        finally:
            proc.stdin.close()
            rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed (exit {rc}) — see {log_path}")
    return {"path": out, "seconds": total, "held": held, "frames": count,
            "mb": round(os.path.getsize(out) / 1e6, 2), "log": log_path}
