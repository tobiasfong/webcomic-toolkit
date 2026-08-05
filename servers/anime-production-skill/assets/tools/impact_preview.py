"""
impact_preview.py — speed lines / flash / camera shake over a finished clip.

This is a PREVIEW of what src/effects/Impact.tsx does at assembly time. It
mirrors that component's envelope (instant attack, (1-t)^1.8 decay), its 84
radial lines, and its clear centre so the figure is never buried. The real
render goes through Remotion at 1080x1920 and also has debris.

Why anime does this: it does not animate the punch travelling, it sells the
MOMENT OF CONTACT. One drawing plus lines, flash and shake reads as an impact.
That is why this project never needed a paid image-to-video service.

⚠ Shake uses OVERSCAN, never ImageChops.offset. offset() wraps circularly, so
pixels pushed off one edge reappear on the other as a black seam. Every frame
is scaled into an M-pixel margin and cropped inside it, shake or not, so there
is no wrap and no size pop when the effect starts.

Usage:
  python impact_preview.py --clip punchD_638 --out punch_fx.webp --fx 0.20,0.41
  python impact_preview.py --clip ice_final3.webp --out ice_fx.webp \
      --fx 0.27,0.40 --color 205,232,255 --at 3
"""
import argparse, glob, math, os, random as pyr
from PIL import Image, ImageSequence, ImageDraw, ImageFilter, ImageChops

S = os.environ.get("SCRATCH", ".")
OUT = os.environ.get("COMFY_OUTPUT",
                       os.path.expanduser(r"C:\AI\ComfyUI_windows_portable\ComfyUI\output"))


def envelope(local, attack, decay):
    """Matches Impact.tsx: full strength on the contact frame, then decays."""
    if local < 0:
        return 0.0
    if attack > 0 and local < attack:
        return local / attack
    t = (local - attack) / max(1, decay)
    return 0.0 if t >= 1 else (1 - t) ** 1.8


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--clip", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--fx", default="0.5,0.5", help="focal point as x,y fractions of the frame")
    p.add_argument("--at", type=int, default=2, help="frame the impact lands on")
    p.add_argument("--attack", type=int, default=1)
    p.add_argument("--decay", type=int, default=9)
    p.add_argument("--color", default="235,235,235", help="speed-line/flash colour r,g,b")
    p.add_argument("--lines", type=float, default=1.0, help="speed-line strength 0-1+")
    p.add_argument("--flash", type=float, default=1.0)
    p.add_argument("--shake", type=float, default=1.0)
    p.add_argument("--fps", type=int, default=12)
    p.add_argument("--margin", type=int, default=18, help="overscan the shake moves into")
    a = p.parse_args()

    path = a.clip
    if not os.path.exists(path):
        hits = sorted(glob.glob(os.path.join(OUT, a.clip + "*.webp"))) or \
               sorted(glob.glob(os.path.join(S, a.clip + "*.webp"))) or \
               sorted(glob.glob(os.path.join(S, a.clip)))
        if not hits:
            raise SystemExit("no clip matching " + a.clip)
        path = hits[-1]

    fr = [x.convert("RGB") for x in ImageSequence.Iterator(Image.open(path))]
    W, H = fr[0].size
    diag = math.hypot(W, H)
    fxx, fxy = (float(v) for v in a.fx.split(","))
    OXp, OYp = fxx * W, fxy * H
    col = tuple(int(v) for v in a.color.split(","))
    M = a.margin

    pyr.seed(7)
    rnd = [(pyr.random(), pyr.random(), pyr.random(), pyr.random()) for _ in range(84)]

    def speedlines(s):
        ov = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(ov)
        for i, (ra, ri, rl, rt) in enumerate(rnd):
            ang = (i / 84) * math.tau + ra * 0.06
            inner = diag * (0.14 + ri * 0.16) * (1 - s * 0.35)   # clear centre
            ln = diag * (0.35 + rl * 0.5)
            th = max(1, int((2.5 + rt * 13 * s) * 0.5))
            x0, y0 = OXp + math.cos(ang) * inner, OYp + math.sin(ang) * inner
            x1, y1 = x0 + math.cos(ang) * ln, y0 + math.sin(ang) * ln
            for k in range(8):                                    # fade along the tail
                t0, t1 = k / 8, (k + 1) / 8
                f = s * (t0 ** 1.3)
                v = tuple(min(255, int(c * f)) for c in col)
                if max(v) < 5:
                    continue
                d.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                        (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)], fill=v, width=th)
        return ov.filter(ImageFilter.GaussianBlur(1.6))

    out = []
    for i, im in enumerate(fr):
        s = envelope(i - a.at, a.attack, a.decay)
        f = im
        if s > 0.01:
            if a.lines > 0:
                f = ImageChops.screen(f, speedlines(s * a.lines))
            if a.flash > 0:
                fl = s * s * a.flash * 0.6
                tint = tuple(min(255, int(c * fl)) for c in col)
                if max(tint) > 2:
                    f = ImageChops.screen(f, Image.new("RGB", (W, H), tint))
        big = f.resize((W + 2 * M, H + 2 * M), Image.LANCZOS)     # constant overscan
        dx = int(math.sin(i * 2.9) * 13 * s * a.shake)
        dy = int(math.cos(i * 3.7) * 13 * s * a.shake)
        out.append(big.crop((M + dx, M + dy, M + dx + W, M + dy + H)))

    dst = os.path.join(S, a.out)
    out[0].save(dst, save_all=True, append_images=out[1:],
                duration=int(1000 / a.fps), loop=0, quality=90)
    print(dst, os.path.getsize(dst) // 1024, "KB |", len(out), "frames")


if __name__ == "__main__":
    main()
