"""
parallax.py — turn a still illustration + depth map into a subtle 2.5D
camera-drift clip (MP4, optionally GIF) for promo videos.

Near pixels (white in the depth map) shift more than far ones as a virtual
camera moves, so a flat illustration gains depth — the signature look of
webnovel/manhwa promo shorts. A gentle base zoom hides the displaced borders.
Keep `--strength` subtle: naive depth warping smears at strong settings.

The clips are ingredients: string them together (music, text) in a video
pipeline such as Remotion.

Usage:
    python parallax.py <image> <depth> [--motion push|pan|drift|lift]
        [--seconds 4] [--fps 30] [--strength 18] [--out clip.mp4] [--gif]
"""
import os
import argparse

import numpy as np
import cv2

MOTIONS = ("push", "pan", "drift", "lift")
MAX_SIDE = 1920


def _ease(t: float) -> float:
    """Smoothstep — no hard starts/stops."""
    return t * t * (3 - 2 * t)


def _camera(motion: str, t: float):
    """(dx, dy, zoom) of the virtual camera at eased time t in [0, 1]."""
    e = _ease(t)
    if motion == "push":    # slow push-in, hair of sideways drift
        return 0.25 * e, 0.10 * e, 1.0 + 0.055 * e
    if motion == "pan":     # lateral track, constant scale
        return (e - 0.5) * 2.0, 0.0, 1.025
    if motion == "drift":   # diagonal drift + gentle push
        return 0.8 * e - 0.4, 0.5 * e - 0.25, 1.0 + 0.04 * e
    if motion == "lift":    # crane up, slight pull-back feel
        return 0.0, 0.45 - 0.9 * e, 1.045 - 0.02 * e
    raise ValueError(f"unknown motion '{motion}'; options: {', '.join(MOTIONS)}")


def parallax(image, depth, out=None, motion="push", seconds=4.0, fps=30,
             strength=18.0, gif=False):
    img = cv2.imread(image, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"could not read image: {image}")
    dep = cv2.imread(depth, cv2.IMREAD_GRAYSCALE)
    if dep is None:
        raise SystemExit(f"could not read depth map: {depth}")

    # cap resolution for reasonable encode times
    h, w = img.shape[:2]
    scale = min(1.0, MAX_SIDE / max(w, h))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    dep = cv2.resize(dep, (w, h), interpolation=cv2.INTER_LINEAR)

    # normalised depth, softened so displacement stays smooth at object edges
    d = cv2.GaussianBlur(dep, (0, 0), sigmaX=max(2, w // 300)).astype(np.float32) / 255.0
    d -= 0.35   # pivot: far background moves slightly opposite to the near subject

    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2.0, h / 2.0
    base_zoom = 1.06   # constant crop margin that hides displaced borders

    out = out or os.path.splitext(image)[0] + f"_{motion}.mp4"
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not vw.isOpened():
        raise SystemExit("could not open video writer (mp4v)")

    frames_for_gif = []
    n = max(2, int(round(seconds * fps)))
    for i in range(n):
        dx, dy, zoom = _camera(motion, i / (n - 1))
        z = base_zoom * zoom
        # camera translation in px, scaled per-pixel by depth (near moves more)
        ox = dx * strength * d
        oy = dy * strength * d
        map_x = (xs - cx) / z + cx - ox
        map_y = (ys - cy) / z + cy - oy
        frame = cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT)
        vw.write(frame)
        if gif and i % 3 == 0:   # 10 fps gif
            frames_for_gif.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    vw.release()

    gif_path = None
    if gif:
        from PIL import Image
        gw = 640
        gh = int(h * gw / w)
        ims = [Image.fromarray(f).resize((gw, gh), Image.LANCZOS) for f in frames_for_gif]
        gif_path = os.path.splitext(out)[0] + ".gif"
        ims[0].save(gif_path, save_all=True, append_images=ims[1:],
                    duration=100, loop=0)
    return out, gif_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("depth")
    ap.add_argument("--motion", default="push", choices=MOTIONS)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--strength", type=float, default=18.0,
                    help="max parallax displacement in px (subtle is good)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--gif", action="store_true", help="also write a 640px preview GIF")
    a = ap.parse_args()
    mp4, g = parallax(a.image, a.depth, a.out, a.motion, a.seconds, a.fps,
                      a.strength, a.gif)
    print(mp4)
    if g:
        print(g)
