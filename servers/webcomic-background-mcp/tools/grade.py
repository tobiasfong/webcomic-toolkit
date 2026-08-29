"""
grade.py — color-grade a finished plate for mood, deterministically.

WHY THIS EXISTS (the v1.9.0 lesson): asking FLUX for mood in the prompt
("grimdark", "dim lighting", "deep shadow", "muted cool palette") is what made
plates render semi-realistic and murky in the first place — it drags the model
off the manhwa aesthetic entirely. Measured: deleting that language moved the
same sketch+seed from mean luminance 0.133 to 0.335 and produced clean
cel-shaded anime.

So: GENERATE CLEAN, GRADE FOR MOOD AFTERWARDS. Grading is deterministic (no
seed lottery), instant (CPU, no GPU, no ComfyUI), reversible (the master plate
is never touched), and adjustable per panel. Prompting for mood is none of
those things. This is also just how real production works — you light and
shoot clean, then grade.

Usage:
    python grade.py plate.png --preset grimdark
    python grade.py plate.png --preset night --out dark_plate.png
    python grade.py plate.png --exposure 0.6 --contrast 1.2 --temp -0.3

Presets are starting points, not rules — tune with the individual knobs.
"""
import argparse
import os

import cv2
import numpy as np

# Each preset is (exposure, contrast, temperature, saturation, vignette).
#   exposure    <1 darkens, >1 brightens
#   contrast    >1 expands the tonal range around mid-gray
#   temperature <0 cools toward blue, >0 warms toward orange
#   saturation  <1 desaturates, 0 = grayscale
#   vignette    0 = none, 1 = heavy corner falloff
PRESETS = {
    # The one this module was written for: Starry Knight's hive interiors.
    "grimdark":  dict(exposure=0.45, contrast=1.25, temp=-0.10, saturation=0.75, vignette=0.35),
    "night":     dict(exposure=0.30, contrast=1.15, temp=-0.35, saturation=0.65, vignette=0.45),
    "dusk":      dict(exposure=0.65, contrast=1.10, temp=+0.25, saturation=0.95, vignette=0.25),
    "overcast":  dict(exposure=0.85, contrast=0.90, temp=-0.15, saturation=0.70, vignette=0.10),
    "warm_lamp": dict(exposure=0.70, contrast=1.15, temp=+0.40, saturation=1.05, vignette=0.30),
    # Sanity check / no-op, useful for measuring the ungraded master.
    "none":      dict(exposure=1.0, contrast=1.0, temp=0.0, saturation=1.0, vignette=0.0),
}


def _vignette_mask(h, w, amount):
    """Radial falloff, 1.0 at center down to (1-amount) at the corners."""
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2, (w - 1) / 2
    r = np.sqrt(((yy - cy) / cy) ** 2 + ((xx - cx) / cx) ** 2)
    return (1.0 - amount * np.clip(r / np.sqrt(2), 0, 1) ** 1.5)[..., None]


def grade(img_bgr, exposure=1.0, contrast=1.0, temp=0.0, saturation=1.0,
          vignette=0.0):
    """Apply a grade to a BGR uint8 image; return BGR uint8.

    Order matters: exposure -> contrast -> temperature -> saturation ->
    vignette. Contrast pivots around mid-gray so darkening doesn't also crush
    the highlights."""
    x = img_bgr.astype(np.float32) / 255.0

    x *= exposure
    x = (x - 0.5) * contrast + 0.5
    if temp:
        # BGR order: warm pushes red up / blue down, cool the reverse.
        x[..., 2] *= (1.0 + 0.30 * temp)     # R
        x[..., 0] *= (1.0 - 0.30 * temp)     # B
    if saturation != 1.0:
        luma = (x * [0.114, 0.587, 0.299]).sum(2, keepdims=True)
        x = luma + (x - luma) * saturation
    if vignette:
        x *= _vignette_mask(x.shape[0], x.shape[1], vignette)

    return (np.clip(x, 0, 1) * 255).astype(np.uint8)


def grade_file(in_path, out_path=None, preset=None, **overrides):
    """Grade a file on disk. The source is never modified — a graded COPY is
    written next to it (or to out_path)."""
    img = cv2.imread(in_path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"could not read image: {in_path}")

    params = dict(PRESETS["none"])
    if preset:
        if preset not in PRESETS:
            raise SystemExit(f"unknown preset '{preset}'; options: {', '.join(PRESETS)}")
        params.update(PRESETS[preset])
    params.update({k: v for k, v in overrides.items() if v is not None})

    out = grade(img, **params)
    if out_path is None:
        stem, ext = os.path.splitext(in_path)
        out_path = f"{stem}_{preset or 'graded'}{ext}"
    cv2.imwrite(out_path, out)
    return out_path, params


def luminance_stats(path):
    """(mean, std) of perceptual luminance — the character-panel server's
    trick for checking tone with a number instead of an argument. This
    server's approved SD1.5 bike plate sits at mean 0.138 / std 0.123."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"could not read image: {path}")
    x = img.astype(np.float32) / 255.0
    lum = (x * [0.114, 0.587, 0.299]).sum(2)
    return float(lum.mean()), float(lum.std())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", default=None)
    ap.add_argument("--preset", default=None, choices=sorted(PRESETS))
    ap.add_argument("--exposure", type=float, default=None)
    ap.add_argument("--contrast", type=float, default=None)
    ap.add_argument("--temp", type=float, default=None)
    ap.add_argument("--saturation", type=float, default=None)
    ap.add_argument("--vignette", type=float, default=None)
    a = ap.parse_args()

    before = luminance_stats(a.input)
    out, params = grade_file(a.input, a.out, a.preset, exposure=a.exposure,
                             contrast=a.contrast, temp=a.temp,
                             saturation=a.saturation, vignette=a.vignette)
    after = luminance_stats(out)
    print(out)
    print(f"  params: {params}")
    print(f"  luminance mean/std: {before[0]:.3f}/{before[1]:.3f} -> "
          f"{after[0]:.3f}/{after[1]:.3f}")
