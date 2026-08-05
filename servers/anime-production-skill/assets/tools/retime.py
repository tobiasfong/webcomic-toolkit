"""
retime.py — re-save an LTX clip at a watchable frame rate.

ltx_run.py's SaveAnimatedWEBP writes at 24fps, so a 17-frame clip plays in
0.7 seconds — far too fast to judge, and it reads as "nothing happened" even
when the motion is fine. Always retime before showing a clip to anyone.

12fps is the limited-animation rate this project works in.

Usage:
  python retime.py --clip punchB_613 --out punch.webp
  python retime.py --clip punchB_613 --out punch.webp --fps 8 --pingpong
"""
import argparse, glob, os
from PIL import Image, ImageSequence

S = os.environ.get("SCRATCH", ".")
OUT = os.environ.get("COMFY_OUTPUT",
                       os.path.expanduser(r"C:\AI\ComfyUI_windows_portable\ComfyUI\output"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--clip", required=True, help="prefix or path of the source clip")
    p.add_argument("--out", required=True)
    p.add_argument("--fps", type=int, default=12)
    p.add_argument("--pingpong", action="store_true",
                   help="play forward then backward — useful for judging subtle motion")
    p.add_argument("--hold", type=int, default=0, help="extra ms held on the last frame")
    a = p.parse_args()

    path = a.clip
    if not os.path.exists(path):
        hits = sorted(glob.glob(os.path.join(OUT, a.clip + "*.webp"))) or \
               sorted(glob.glob(os.path.join(S, a.clip + "*.webp")))
        if not hits:
            raise SystemExit("no clip matching " + a.clip)
        path = hits[-1]

    fr = [f.convert("RGB") for f in ImageSequence.Iterator(Image.open(path))]
    if a.pingpong:
        fr = fr + fr[::-1][1:]
    dur = [int(1000 / a.fps)] * len(fr)
    if a.hold:
        dur[-1] += a.hold

    dst = os.path.join(S, a.out)
    fr[0].save(dst, save_all=True, append_images=fr[1:], duration=dur, loop=0, quality=90)
    print(dst, os.path.getsize(dst) // 1024, "KB |", len(fr), "frames @", a.fps, "fps",
          f"= {len(fr)/a.fps:.1f}s")


if __name__ == "__main__":
    main()
