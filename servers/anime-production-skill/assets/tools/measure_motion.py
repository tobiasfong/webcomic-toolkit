"""
measure_motion.py — quantify how much an LTX clip actually moves, and dump its
frames so the number can be checked against what the eye sees.

⚠ THE NUMBER IS NOT QUALITY. It measures CHANGE. A clip whose characters
dissolve into smears scores very high. A high score means "something happened",
never "it looks good". Always open the dumped frames before believing a result.

⚠⚠ THE WHOLE-FRAME NUMBER CANNOT SEE SMALL FEATURES. Two eyes are ~0.2% of a
1024x768 frame, so even a perfect blink moves the whole-frame mean by ~0.2 —
an order of magnitude BELOW the ~2.0 floor of a completely static clip. Judging
a blink or a mouth by the whole-frame span is meaningless. Use --box.

⚠⚠⚠ span (frame0 vs frameLast) CANNOT SEE ROUND TRIPS. A blink returns to
open, so it lands back at ~0. `maxdev` — the largest deviation of ANY frame
from frame 0 — is the statistic that sees it, and WHERE it peaks is the tell:
a real blink peaks mid-clip and comes back; monotonic drift peaks at the last
frame. Always read the peak frame index, not just the magnitude.

Usage:
  python measure_motion.py --latest                  # newest ltx_* clip in output/
  python measure_motion.py path/to/clip.webp
  python measure_motion.py --latest --dump frames/   # also write per-frame PNGs
  python measure_motion.py clip.webp --box 230,275,350,350   # eyes/mouth only
"""
import argparse, glob, os
from PIL import Image, ImageSequence, ImageChops, ImageStat

OUT = os.environ.get("COMFY_OUTPUT",
                       os.path.expanduser(r"C:\AI\ComfyUI_windows_portable\ComfyUI\output"))


def frames_of(path):
    im = Image.open(path)
    return [f.convert("L") for f in ImageSequence.Iterator(im)], Image.open(path)


def mean_abs_diff(a, b):
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("path", nargs="?")
    p.add_argument("--latest", action="store_true", help="use newest ltx_* file in ComfyUI output/")
    p.add_argument("--dump", help="directory to write per-frame PNGs (full colour, native res)")
    p.add_argument("--box", help="restrict measurement to L,T,R,B — required for eye/mouth-scale "
                                 "features, which the whole-frame mean cannot resolve")
    a = p.parse_args()

    path = a.path
    if a.latest or not path:
        cands = glob.glob(os.path.join(OUT, "ltx_*.webp")) + glob.glob(os.path.join(OUT, "ltx_*.png"))
        if not cands:
            raise SystemExit("no ltx_* clips in " + OUT)
        path = max(cands, key=os.path.getmtime)

    grey, colour = frames_of(path)
    n = len(grey)
    if n < 2:
        raise SystemExit(f"{os.path.basename(path)}: only {n} frame(s)")

    label = "whole frame"
    if a.box:
        box = tuple(int(x) for x in a.box.split(","))
        grey = [g.crop(box) for g in grey]
        pct = (box[2] - box[0]) * (box[3] - box[1]) / (colour.size[0] * colour.size[1]) * 100
        label = f"box {box} = {pct:.2f}% of frame"

    span = mean_abs_diff(grey[0], grey[-1])
    consec = [mean_abs_diff(grey[i], grey[i + 1]) for i in range(n - 1)]
    peak = max(consec)
    dev = [mean_abs_diff(grey[0], g) for g in grey]
    mx = max(dev); mxi = dev.index(mx)

    print(f"{os.path.basename(path)}  {colour.size[0]}x{colour.size[1]}  {n} frames  [{label}]")
    print(f"  span (frame0 vs frameLast) : {span:6.2f}   <- blind to round trips")
    print(f"  maxdev (frame0 vs any)     : {mx:6.2f}  at frame {mxi}"
          f"   <- {'MID-CLIP: consistent with a round trip (blink/gesture)' if 0 < mxi < n - 1 else 'LAST FRAME: monotonic drift, not a round trip'}")
    print(f"  peak consecutive delta     : {peak:6.2f}  (at frame {consec.index(peak)+1})")
    print(f"  per-frame: " + " ".join(f"{d:.1f}" for d in consec))

    if a.dump:
        os.makedirs(a.dump, exist_ok=True)
        for i, f in enumerate(ImageSequence.Iterator(Image.open(path))):
            f.convert("RGB").save(os.path.join(a.dump, f"f{i:02d}.png"))
        print(f"  dumped {n} frames -> {a.dump}")


if __name__ == "__main__":
    main()
