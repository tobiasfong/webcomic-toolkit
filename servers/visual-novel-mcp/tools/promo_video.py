"""Render a promo video from a title screen: the cover, its ambience, a track.

    python promo_video.py <config.json> <out.mp4> [--fps N] [--preview SEC]

WHY RENDER IT RATHER THAN SCREEN-CAPTURE THE GAME
-------------------------------------------------
Capturing the real menu gives you the menu at whatever framerate the recorder
managed, with the cursor in it, at whatever moment the music happened to be.
Rendering it means the video is deterministic, matches the track sample for
sample, and can hold the menu back until the end -- which is the point of a
promo: sell the picture first, reveal that it is a game second.

The ambience is the SAME animation the title screen runs, driven from the same
numbers. The config carries the glow positions and beats so this file stays
free of any particular project's content, but they are meant to be copied from
the game's own transforms. If they drift apart, the video stops being a
truthful advertisement for the thing it is advertising.

⚠ THE BEATS ARE UNEVEN ON PURPOSE. Fire read as a pulsing bulb when its beats
were equal; three unequal ones read as a flame. Two flames on the SAME beats
read as one light with two bulbs, so each carries its own. Ice runs slower and
shallower on a period unrelated to the flame's, so they never fall into step.
Copy the asymmetry along with the numbers.

FRAMES ARE PIPED, NOT WRITTEN. A 90-second 1080p sequence is thousands of PNGs
and several gigabytes on disk for a file that exists to be deleted; the frames
go straight to ffmpeg's stdin as raw RGB instead.

CONFIG
------
    {
      "cover":  "path/to/cover.png",
      "audio":  "path/to/theme.ogg",
      "size":   [1920, 1080],
      "kenburns": 1.05,
      "snow":   {"sprite": "path/spark.png", "count": 45, "size": 26,
                 "yspeed": [26, 62], "xspeed": [-14, 14]},
      "glows":  [{"sprite": "path/glow_warm.png", "x": 0.516, "y": 0.393,
                  "size": 560, "alpha": 0.52,
                  "beats": [[0.55, 0.78, 1.08], [0.40, 0.46, 0.97]]}],
      "menu":   {"at": 72.0, "fade": 2.5, "panel": "path/panel_soft.png",
                 "font": "path/DejaVuSans.ttf", "size": 44, "scale": 1.5,
                 "x": 22, "yalign": 0.72, "spacing": 10, "pad": [34, 30],
                 "items": ["Start", "Load", "Preferences", "About"]}
    }

Each beat is [seconds, target_alpha, target_zoom], eased, looping.
"""
import io
import json
import math
import os
import random
import subprocess
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


def find_ffmpeg():
    """The bundled binary, so this does not depend on a system install."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    for dirpath, _dirs, files in os.walk(os.path.join(root, "servers")):
        for f in files:
            if f.startswith("ffmpeg") and f.endswith(".exe"):
                return os.path.join(dirpath, f)
    return "ffmpeg"


def ease(t):
    """Smoothstep. Ren'Py's `ease` is not linear and a linear ramp here reads
    as a light being dimmed by hand rather than as something breathing."""
    return t * t * (3.0 - 2.0 * t)


class Pulse:
    """One glow's alpha/zoom over time, from a looping list of eased beats."""

    def __init__(self, alpha0, beats):
        self.beats = beats
        self.period = sum(b[0] for b in beats) or 1.0
        self.a0, self.z0 = alpha0, 1.0

    def at(self, t):
        t %= self.period
        a, z = self.a0, self.z0
        for dur, ta, tz in self.beats:
            if t <= dur:
                k = ease(t / dur if dur else 1.0)
                return a + (ta - a) * k, z + (tz - z) * k
            t -= dur
            a, z = ta, tz
        return a, z


def add_sprite(base, sprite, cx, cy, size, alpha):
    """Composite one sprite ADDITIVELY at a center point.

    Only the affected rectangle is touched. Building a full-frame layer per
    glow per frame is the obvious way to write this and it is far too slow for
    a few thousand frames.
    """
    if alpha <= 0.003 or size < 2:
        return
    s = sprite.resize((int(size), int(size)), Image.BILINEAR)
    if alpha < 1.0:
        r, g, b, a = s.split()
        s = Image.merge("RGBA", (r, g, b, a.point(lambda v: int(v * alpha))))
    x0, y0 = int(cx - s.width / 2), int(cy - s.height / 2)
    x1, y1 = x0 + s.width, y0 + s.height
    bx0, by0 = max(0, x0), max(0, y0)
    bx1, by1 = min(base.width, x1), min(base.height, y1)
    if bx0 >= bx1 or by0 >= by1:
        return
    s = s.crop((bx0 - x0, by0 - y0, bx1 - x0, by1 - y0))
    region = base.crop((bx0, by0, bx1, by1))
    lit = Image.new("RGB", s.size, (0, 0, 0))
    lit.paste(s.convert("RGB"), (0, 0), s)
    base.paste(ImageChops.add(region, lit), (bx0, by0))


def flutter(frame, region, t):
    """Ripple one rectangle of the frame, periodically.

    WHY DRAWN RATHER THAN GENERATED. Video models will animate cloth, but they
    redraw everything else while they are at it -- a test here came back with
    hair and robe moving correctly and the HANDS torn apart, because an open
    hand holding something is the hardest thing in frame. Worse for a loop, the
    clip does not return to where it started, so it snaps.

    A displacement wave has neither problem. It moves only the pixels inside
    its own rectangle, so hands and faces are untouchable by construction, and
    its period divides the loop exactly, so the last cycle meets the first.

    ⚠ SUB-PIXEL, AND CHECK THE PER-FRAME DELTA. A first version rounded the
    shift to whole pixels. At 5 px of amplitude over a 4.4 s period at 24 fps
    that is 0.29 px of movement per frame, which rounds to ZERO -- the clip
    animated correctly against the still image and was completely frozen on
    screen. The test that matters is the difference between CONSECUTIVE
    frames, not the difference from the source.

    `anchor` is the edge the fabric hangs from: displacement is zero there and
    grows toward the free end, because a sleeve does not slide sideways whole.
    """
    import numpy as np

    x0, y0, x1, y1 = region["box"]
    amp = float(region.get("amp", 6.0))
    wav = float(region.get("wavelength", 220.0))
    per = float(region.get("period", 6.0))
    patch = np.asarray(frame.crop((x0, y0, x1, y1)), dtype=np.float32)
    h, w, _ = patch.shape
    rows = np.arange(h, dtype=np.float32)
    f = rows / max(1.0, h - 1.0)
    if region.get("anchor", "top") == "bottom":
        f = 1.0 - f
    phase = 2 * math.pi * (t / per) + float(region.get("phase", 0.0))
    dx = amp * f * np.sin(2 * math.pi * rows / wav + phase)

    cols = np.arange(w, dtype=np.float32)[None, :] - dx[:, None]
    cols = np.clip(cols, 0, w - 1.001)
    lo = np.floor(cols).astype(np.int32)
    frac = (cols - lo)[..., None]
    r = np.arange(h)[:, None]
    out = patch[r, lo] * (1.0 - frac) + patch[r, lo + 1] * frac

    # ⚠ MOVE THE FIGURE, NOT THE FRAME. A rectangle displaces everything inside
    # it, and on this kind of cover the background is most of the rectangle --
    # 58% of one measured frame. Rippling sky does not read as cloth, it reads
    # as HAZE over the whole band. So the warped pixels are kept only where the
    # source is not background; everywhere else the original stands.
    if region.get("mask") is not None:
        keep = region["mask"][y0:y1, x0:x1][..., None]
        out = out * keep + patch * (1.0 - keep)
    frame.paste(Image.fromarray(out.astype("uint8"), "RGB"), (x0, y0))


def build_menu(cfg, size):
    """The game's own menu bar, drawn once and faded in later.

    Rebuilt rather than screen-grabbed so it lands at the same place and the
    same size regardless of what the recorder would have done to it.
    """
    m = cfg.get("menu")
    if not m:
        return None
    sc = m.get("scale", 1.5)
    font = ImageFont.truetype(m["font"], int(m["size"] * sc))
    pad_x, pad_y = [int(v * sc) for v in m.get("pad", [34, 30])]
    spacing = int(m.get("spacing", 10) * sc)
    items = m["items"]
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    widths, heights = [], []
    for it in items:
        b = d0.textbbox((0, 0), it, font=font)
        widths.append(b[2] - b[0])
        heights.append(b[3] - b[1])
    line = max(heights) + int(12 * sc)
    w = max(widths) + pad_x * 2
    h = line * len(items) + spacing * (len(items) - 1) + pad_y * 2

    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if m.get("panel") and os.path.exists(m["panel"]):
        tile = Image.open(m["panel"]).convert("RGBA").resize((w, h), Image.BILINEAR)
        panel.alpha_composite(tile)
    else:
        panel.paste((10, 12, 20, 128), (0, 0, w, h))

    d = ImageDraw.Draw(panel)
    y = pad_y
    for it in items:
        # Outlines, as the game's style has them: white text over a bright
        # cover is unreadable without one.
        for ox in (-2, 0, 2):
            for oy in (-2, 0, 2):
                if ox or oy:
                    d.text((pad_x + ox, y + oy), it, font=font, fill=(0, 0, 0, 190))
        d.text((pad_x, y), it, font=font, fill=(255, 255, 255, 255))
        y += line + spacing
    return panel, (int(m.get("x", 22) * sc),
                   int(size[1] * m.get("yalign", 0.72) - h / 2))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if len(args) < 2:
        sys.exit("usage: python promo_video.py <config.json> <out.mp4> "
                 "[--fps N] [--preview SEC]")
    cfg = json.load(io.open(args[0], encoding="utf-8"))
    out = args[1]
    fps = 24
    preview = 0.0
    for f in flags:
        if f.startswith("--fps="):
            fps = int(f.split("=", 1)[1])
        if f.startswith("--preview="):
            preview = float(f.split("=", 1)[1])

    W, H = cfg.get("size", [1920, 1080])
    ff = find_ffmpeg()
    dur = float(subprocess.run(
        [ff, "-hide_banner", "-i", cfg["audio"]], capture_output=True,
        text=True).stderr.split("Duration: ")[1].split(",")[0].split(":")[-1]) \
        + 60 * float(subprocess.run(
        [ff, "-hide_banner", "-i", cfg["audio"]], capture_output=True,
        text=True).stderr.split("Duration: ")[1].split(",")[0].split(":")[1])
    if preview:
        dur = min(dur, preview)
    frames = int(dur * fps)
    print("cover  %s" % os.path.basename(cfg["cover"]))
    print("audio  %s  %.2f s" % (os.path.basename(cfg["audio"]), dur))
    print("video  %dx%d @ %d fps  = %d frames" % (W, H, fps, frames))

    cover = Image.open(cfg["cover"]).convert("RGB")
    glows = []
    for g in cfg.get("glows", []):
        glows.append((Image.open(g["sprite"]).convert("RGBA"), g,
                      Pulse(g.get("alpha", 0.5), g["beats"])))
    snow_cfg = cfg.get("snow")
    snow_img = flakes = None
    if snow_cfg:
        snow_img = Image.open(snow_cfg["sprite"]).convert("RGBA")
        rng = random.Random(7)
        flakes = [(rng.uniform(0, W), rng.uniform(-H, H),
                   rng.uniform(*snow_cfg.get("xspeed", [-14, 14])),
                   rng.uniform(*snow_cfg.get("yspeed", [26, 62])),
                   rng.uniform(0.45, 1.0))
                  for _ in range(snow_cfg.get("count", 45))]
    # One figure mask for the whole run: background is flat, bright and
    # blue-dominant on this artwork, so "not background" is the figure.
    if cfg.get("flutter"):
        import numpy as np
        arr = np.asarray(cover).astype(np.int16)
        r_, g_, b_ = arr[..., 0], arr[..., 1], arr[..., 2]
        bg = (b_ > r_ + 28) & (b_ > 110)
        fig = (~bg).astype(np.float32)
        # Feather, so the warp fades in at a silhouette edge instead of
        # tearing a hard line down it.
        fig = np.asarray(Image.fromarray((fig * 255).astype("uint8"))
                         .filter(ImageFilter.GaussianBlur(2))).astype(np.float32) / 255.0
        print("figure mask: %.1f%% of frame is figure" % (100 * (fig > 0.5).mean()))
        for reg in cfg["flutter"]:
            reg["mask"] = fig

    menu = build_menu(cfg, (W, H))
    kb = float(cfg.get("kenburns", 1.05))

    cmd = [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", "%dx%d" % (W, H), "-r", str(fps), "-i", "-",
           "-i", cfg["audio"],
           "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-shortest", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(frames):
        t = i / float(fps)
        # A slow push in. Held under about 6% over the whole run: any more and
        # it stops reading as drift and starts reading as a zoom.
        z = 1.0 + (kb - 1.0) * (t / dur if dur else 0)
        cw, ch = int(W * z), int(H * z)
        frame = cover.resize((cw, ch), Image.BILINEAR).crop(
            ((cw - W) // 2, (ch - H) // 2, (cw - W) // 2 + W, (ch - H) // 2 + H))
        for reg in cfg.get("flutter", []):
            flutter(frame, reg, t)   # regions carry their figure mask
        for sprite, g, pulse in glows:
            a, zz = pulse.at(t)
            add_sprite(frame, sprite, g["x"] * W, g["y"] * H, g["size"] * zz, a)
        if flakes:
            sz = snow_cfg.get("size", 26)
            for fx, fy, vx, vy, fa in flakes:
                x = (fx + vx * t) % (W + 160) - 80
                y = (fy + vy * t) % (H + 160) - 80
                add_sprite(frame, snow_img, x, y, sz, fa * 0.8)
        if menu:
            mcfg = cfg["menu"]
            at, fade = mcfg.get("at", dur - 16), mcfg.get("fade", 2.5)
            if t >= at:
                k = min(1.0, (t - at) / fade) if fade else 1.0
                panel, (px, py) = menu
                lay = panel.copy()
                if k < 1.0:
                    r, g2, b, al = lay.split()
                    lay = Image.merge("RGBA", (r, g2, b, al.point(lambda v: int(v * k))))
                frame.paste(lay, (px, py), lay)
        proc.stdin.write(frame.tobytes())
        if i % (fps * 10) == 0:
            print("  %5.1f s / %.1f s" % (t, dur), flush=True)
    proc.stdin.close()
    proc.wait()
    print("wrote %s  (%.1f MB)" % (out, os.path.getsize(out) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
