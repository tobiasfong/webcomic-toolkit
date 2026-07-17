"""
fix_green.py — remove the IP-Adapter green/teal artifact from a generated
background by INPAINTING only the vivid green/teal region (HSV-masked) from
surrounding texture.

The artifact does NOT respond to negative prompts or seed changes (latent
IP-Adapter quirk at high-contrast silhouette edges with cool style refs). We
target only SATURATED green/teal hues — near-white snow is low-saturation and is
left untouched.

Usage:
    python fix_green.py <image> [out.png] [--sat 45] [--show]
SAFE ONLY on cool/blue palettes (ice/night). Do NOT run on forest/green scenes.
"""
import sys
import cv2
import numpy as np


def fix(src, out=None, sat=45, show=False):
    img = cv2.imread(src, cv2.IMREAD_COLOR)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    # OpenCV hue 0-179; green..cyan ~ 35-95. Require real saturation to skip snow.
    mask = ((h >= 35) & (h <= 95) & (s >= sat) & (v >= 40)).astype(np.uint8)
    n = int(mask.sum())
    if show:
        print(f"matched {n} px")
        return
    if n:
        mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)
        img = cv2.inpaint(img, mask, 4, cv2.INPAINT_TELEA)
    cv2.imwrite(out or src, img)
    print(f"inpainted {n} green px -> {out or src}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sat = 45
    if "--sat" in sys.argv:
        sat = int(sys.argv[sys.argv.index("--sat") + 1])
    show = "--show" in sys.argv
    fix(args[0], args[1] if len(args) > 1 else None, sat, show)
