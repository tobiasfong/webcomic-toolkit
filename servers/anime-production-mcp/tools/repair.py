"""
repair.py — find and fix the few smeared frames in a finished take or a whole video.

THE WORKFLOW (agreed with the author, 2026-10-26). Detection by statistic missed most of the smears a person
caught by eye, and a person watching at speed cannot name the exact frame either. So the person gives a
ROUGH moment ("around 0:57"), `inspect` cuts that stretch into a slow-motion clip with a large frame number
burned into every frame, the person reads off the bad numbers while it plays, and `repair` replaces exactly
those frames. The detector's guesses are drawn as a red border in the inspect clip: a hint to confirm or
ignore, never a verdict.

TRANSIENT DIPS, NOT COLLAPSE. artifacts.scan looks for a take that falls apart and stays broken (where to
truncate). A smear is different: two or three frames lose their lines, then the drawing comes back. So the
hint here compares each frame's edge energy, per tile, with its neighbors on both sides. Fast motion also
dips this way, which is why it stays a hint.

REPAIR MODES.
  hold    — replace each bad frame with the nearest clean one before it. At 12 fps limited animation a held
            drawing reads as an ordinary anime beat. Always available.
  interp  — redraw the bad frames as in-betweens of the clean frames on either side (RIFE, via the
            rife-ncnn-vulkan executable named by WEBCOMIC_ANIME_RIFE). Nothing is redrawn in a new style:
            every pixel comes from the two clean drawings.

Works on the take files (12 fps webp) and on finished videos (mp4, any fps; the audio is carried over).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageSequence

from .assemble import find_ffmpeg

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm")


# ---------------------------------------------------------------------------------------------- reading
def _probe_fps(ffmpeg: str, path: str) -> float:
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    for tok in out.split(","):
        tok = tok.strip()
        if tok.endswith(" fps"):
            return float(tok.split()[0])
    raise ValueError(f"could not read the frame rate of {path}")


def read_clip(path: str, start: int = 0, count: int | None = None) -> tuple[list[Image.Image], float]:
    """Frames [start, start + count) as stored (all of them by default), and the frame rate.

    Webp/gif through Pillow, video through ffmpeg. For a video, a window is decoded on its own (an accurate
    seek), so inspecting two seconds of a two-minute video does not decode the whole thing."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if path.lower().endswith(VIDEO_EXT):
        ff = find_ffmpeg()
        fps = _probe_fps(ff, path)
        tmp = tempfile.mkdtemp(prefix="repair_")
        try:
            cmd = [ff, "-loglevel", "error"]
            if start:
                cmd += ["-ss", f"{start / fps:.6f}"]
            cmd += ["-i", path, "-vsync", "0"]
            if count is not None:
                cmd += ["-frames:v", str(count)]
            subprocess.run(cmd + [os.path.join(tmp, "f_%06d.png")], check=True)
            names = sorted(os.listdir(tmp))
            return [Image.open(os.path.join(tmp, n)).convert("RGB") for n in names], fps
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    im = Image.open(path)
    frames, durs = [], []
    for f in ImageSequence.Iterator(im):
        frames.append(f.convert("RGB"))
        durs.append(f.info.get("duration") or 83)
    end = None if count is None else start + count
    return frames[start:end], 1000.0 / float(np.median(durs))


def write_clip(frames: list[Image.Image], fps: float, out_path: str, audio_from: str | None = None) -> str:
    if out_path.lower().endswith(VIDEO_EXT):
        ff = find_ffmpeg()
        cmd = [ff, "-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "bmp", "-framerate", str(fps), "-i", "-"]
        if audio_from and audio_from.lower().endswith(VIDEO_EXT):
            cmd += ["-i", audio_from, "-map", "0:v", "-map", "1:a?", "-c:a", "copy"]
        cmd += ["-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", out_path]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for f in frames:
            buf = io.BytesIO()
            f.save(buf, format="BMP")
            p.stdin.write(buf.getvalue())
        p.stdin.close()
        if p.wait() != 0:
            raise RuntimeError("ffmpeg failed writing " + out_path)
        return out_path
    frames[0].save(out_path, save_all=True, append_images=frames[1:], duration=round(1000.0 / fps), loop=0,
                   quality=92)
    return out_path


# ---------------------------------------------------------------------------------------------- the hint
def _tile_energy(img: Image.Image, cols: int, rows: int) -> np.ndarray:
    a = np.asarray(img.convert("L").resize((480, 270)), np.float32)
    gy, gx = np.gradient(a)
    g = np.hypot(gx, gy)
    h, w = g.shape
    return np.array([[g[r * h // rows:(r + 1) * h // rows, c * w // cols:(c + 1) * w // cols].mean()
                      for c in range(cols)] for r in range(rows)])


def transient_dips(frames: list[Image.Image], threshold: float = 0.7, cols: int = 4, rows: int = 3,
                   reach: int = 3) -> dict:
    """Frames whose linework drops well below the drawings on BOTH sides in some tile: a smear that recovers.

    Works on DRAWINGS, not frames: consecutive identical frames (a 24 fps video's doubles, holds) count once.
    Each drawing is compared with the sharpest of the `reach` drawings before it and the sharpest of the
    `reach` after (in the same shot), per tile; a smear usually spans two or three drawings, so comparing
    with the next frame alone measured one smeared drawing against another (a real smear scored 0.86 that
    way, 0.63 this way). Score = the lowest tile ratio; below `threshold` is flagged.

    MEASURED LIMIT (2026-10-26, a camera push-in with a real two-drawing smear): the smear scored 0.62-0.69,
    but clean drawings in the same fast move scored 0.65-0.75. At 0.7 it flagged the smear plus two clean
    drawings: it narrows where to look, it cannot tell motion from damage."""
    small = [np.asarray(f.convert("L").resize((96, 54)), np.float32) for f in frames]
    starts = [0] + [i for i in range(1, len(frames)) if np.abs(small[i] - small[i - 1]).mean() >= 1.0]
    owner = np.zeros(len(frames), int)                     # frame index -> drawing index
    for d, s in enumerate(starts):
        owner[s:] = d
    e = [_tile_energy(frames[s], cols, rows) for s in starts]
    sm = [small[s] for s in starts]
    nd = len(starts)

    def same_shot(a, b):                                   # a drawing across a cut is a different picture
        return float(np.abs(sm[a] - sm[b]).mean()) < 30.0

    dscore = [1.0] * nd
    for d in range(nd):
        before = [e[j] for j in range(d - reach, d) if j >= 0 and same_shot(d, j)]
        after = [e[j] for j in range(d + 1, d + 1 + reach) if j < nd and same_shot(d, j)]
        if not before or not after:
            continue
        ref = (np.max(before, axis=0) + np.max(after, axis=0)) / 2
        dscore[d] = float(np.min(e[d] / np.maximum(ref, 1e-6)))
    score = [dscore[owner[i]] for i in range(len(frames))]
    flagged = [i for i, s in enumerate(score) if s < threshold]
    return {"scores": [round(s, 3) for s in score], "flagged": flagged, "threshold": threshold}


# ---------------------------------------------------------------------------------------------- inspect
def inspect(clip_path: str, center_s: float, window_s: float = 1.0, slow: int = 4, out_path: str | None = None,
            threshold: float = 0.7) -> dict:
    """A slow-motion clip of [center - window, center + window] with each frame's number burned in large, and
    the hint's suspects outlined in red. Frame numbers are the clip's OWN (0-based, at its own frame rate), the
    numbers `repair` takes."""
    _, fps = read_clip(clip_path, 0, 1)
    a = max(0, int((center_s - window_s) * fps))
    b = int((center_s + window_s) * fps) + 1
    pad = int(fps * 0.35) + 1                              # room for three drawings each side, for the hint
    lo = max(0, a - pad)
    window = read_clip(clip_path, lo, b + pad - lo)[0]
    if not window or a - lo >= len(window):
        raise ValueError(f"{center_s}s is outside the clip")
    frames = {lo + i: f for i, f in enumerate(window)}
    b = min(b, lo + len(window))
    hint = transient_dips(window, threshold)
    flagged = {lo + i for i in hint["flagged"] if a <= lo + i < b}
    try:
        font = ImageFont.truetype("arialbd.ttf", 72)
        small = ImageFont.truetype("arialbd.ttf", 30)
    except OSError:
        font = small = ImageFont.load_default()
    out = []
    for i in range(a, b):
        f = frames[i].copy()
        d = ImageDraw.Draw(f)
        W, H = f.size
        label = str(i)
        d.rectangle((0, 0, 40 + 44 * len(label), 96), fill=(0, 0, 0))
        d.text((20, 10), label, font=font, fill=(255, 255, 0))
        d.text((24, H - 46), f"{i / fps:6.2f}s", font=small, fill=(255, 255, 0), stroke_width=3,
               stroke_fill=(0, 0, 0))
        if i in flagged:
            d.rectangle((0, 0, W - 1, H - 1), outline=(255, 0, 0), width=12)
        out.append(f)
    if out_path is None:
        base, _ = os.path.splitext(clip_path)
        out_path = f"{base}_inspect_{center_s:.2f}s.webp"
    out_path = out_path if out_path.lower().endswith(".webp") else os.path.splitext(out_path)[0] + ".webp"
    write_clip(out, fps / slow, out_path)
    return {"inspect_clip": out_path, "frames": [a, b - 1], "fps": round(fps, 3), "slowed": slow,
            "suspects": sorted(flagged),
            "note": "Red borders are the detector's suspects: a hint, not a verdict. Name the frames you see."}


# ---------------------------------------------------------------------------------------------- repair
def _runs(bad: list[int]) -> list[tuple[int, int]]:
    bad = sorted(set(bad))
    runs, s = [], None
    for i, x in enumerate(bad):
        if s is None:
            s = x
        if i == len(bad) - 1 or bad[i + 1] != x + 1:
            runs.append((s, x))
            s = None
    return runs


def _rife(rife: str, a: Image.Image, b: Image.Image, t: float) -> Image.Image:
    tmp = tempfile.mkdtemp(prefix="rife_")
    try:
        pa, pb, po = (os.path.join(tmp, n) for n in ("a.png", "b.png", "o.png"))
        a.save(pa)
        b.save(pb)
        model = os.environ.get("WEBCOMIC_ANIME_RIFE_MODEL", "rife-v4.6")
        exe_dir = os.path.dirname(rife)
        subprocess.run([rife, "-0", pa, "-1", pb, "-o", po, "-s", f"{t:.4f}", "-m",
                        os.path.join(exe_dir, model)], check=True, capture_output=True)
        return Image.open(po).convert("RGB").copy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def repair(clip_path: str, bad_frames: list[int], mode: str = "hold", out_path: str | None = None) -> dict:
    """Replace the named frames. Runs of consecutive bad frames are fixed together, from the clean frames on
    either side. Frames that are byte-identical to a bad one (the 24 fps double of a 12 fps drawing) are
    replaced along with it, so a smear cannot survive as its own double."""
    frames, fps = read_clip(clip_path)
    n = len(frames)
    bad = sorted({i for i in bad_frames if 0 <= i < n})
    if not bad:
        raise ValueError("no frames to repair inside the clip")
    extra = set()
    for i in bad:                                          # pull in exact doubles next to a bad frame
        for j in (i - 1, i + 1):
            if 0 <= j < n and j not in bad and np.array_equal(np.asarray(frames[j]), np.asarray(frames[i])):
                extra.add(j)
    bad = sorted(set(bad) | extra)
    rife = os.environ.get("WEBCOMIC_ANIME_RIFE")
    if mode == "interp" and not (rife and os.path.isfile(rife)):
        raise FileNotFoundError("interp needs rife-ncnn-vulkan: set WEBCOMIC_ANIME_RIFE to the executable. "
                                "mode='hold' works without it.")
    out = list(frames)
    for s, e in _runs(bad):
        before, after = s - 1, e + 1
        if before < 0 and after >= n:
            raise ValueError("every frame is marked bad; nothing clean to repair from")
        for k in range(s, e + 1):
            if mode == "hold" or before < 0 or after >= n:
                out[k] = frames[before] if before >= 0 else frames[after]
            else:
                out[k] = _rife(rife, frames[before], frames[after], (k - before) / (after - before))
    if out_path is None:
        base, ext = os.path.splitext(clip_path)
        out_path = f"{base}_repaired{ext}"
    write_clip(out, fps, out_path, audio_from=clip_path)
    return {"repaired_clip": out_path, "replaced": bad, "mode": mode, "fps": round(fps, 3)}
