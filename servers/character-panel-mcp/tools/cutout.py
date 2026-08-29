"""Key a character/prop off a flat backdrop into an RGBA cutout.

This is the keying step for the solo-generate + composite route: generate a
thing on its own, cut it out, paste it into the panel. Doing it by hand with a
magic wand is the tedious part, and the part that does not scale to 15 panels.

The keying is deliberately not a single global color distance. Anime cel art
puts near-identical values in unrelated places -- a boot's cream sole and human
skin sit within a few RGB points of each other -- so a plain "select similar"
either eats the sole or keeps the leg. Instead each unwanted class gets its own
rule, and skin is separated from cream by HUE rather than brightness: skin is
pink (R-B around 50), cream leather is near-neutral (R-B around 14).

    python cutout.py SRC OUT --box x0 y0 x1 y1 [--drop-skin] [--keep-largest]
"""
import argparse

import numpy as np
from PIL import Image, ImageFilter


def key_cutout(src: str, out: str, box=None, drop_skin: bool = False,
               keep_largest: bool = True, feather: float = 0.6,
               flat_backdrop: bool = True, backdrop_tol: float = 120.0) -> str:
    im = Image.open(src).convert("RGB")
    if box:
        im = im.crop(box)
    a = np.array(im).astype(int)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]

    if flat_backdrop:
        # A whole character on a flat pale backdrop cannot be keyed by hue.
        # Tried and failed: "blue leads red" eats black hair and navy trousers
        # (near-black is slightly blue), and a neutral-gray rule eats the white
        # shirt. Those rules were written for a brown boot on a forest wash.
        #
        # Instead: background is what is CONNECTED TO THE BORDER and close to
        # the corner color. That keeps white, black and skin inside the figure
        # no matter their value, and it takes the cast shadow with it, because
        # the shadow touches the border too.
        corner = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), axis=0)
        dist = np.sqrt(((a - corner) ** 2).sum(axis=2))
        # Distance alone is not enough: pale SKIN sits about as close to a white
        # backdrop as a gray shadow does, so a tolerance that caught the shadow
        # also erased the character's face and hands. What separates them is
        # temperature -- skin is warm (red leads blue by ~25), while the
        # backdrop and its cast shadow are neutral. Requiring neutrality keeps
        # skin and still takes the shadow, which is the whole point of the
        # generous tolerance.
        # Measured on a real solo render rather than guessed: backdrop white is
        # (255,255,255); its cast shadow is (190,196,203) -- distance ~101 and
        # COOL, blue leading red by 13; skin is (253,236,218) -- distance ~42
        # but WARM, red leading blue by 35. So the tolerance has to reach past
        # 100 to take the shadow, and the thing that protects skin at that
        # distance is the sign of red-minus-blue, not its magnitude.
        not_warm = (r - b) < 10
        backdrop = _border_reachable((dist < backdrop_tol) & not_warm)
    else:
        # Warm prop against the blue/green forest wash.
        backdrop = (b > r + 8) | ((g > r + 8) & (b > r - 30))

    keep = ~backdrop
    if drop_skin:
        # Pink, not cream. The R-B spread is what tells them apart; brightness
        # does not, which is why a value-based key fails on cel art.
        keep &= ~((r > 195) & (g > 150) & (b > 120) & (r - b > 35))

    if keep_largest:
        keep = _largest_blob(keep)
    # Interior holes are always keying mistakes -- the boot's white sole has
    # warm pixels that trip the skin rule, leaving pinholes mid-object.
    # Reclaiming anything not reachable from the border fixes them without
    # loosening the skin threshold, which would start keeping actual leg.
    keep |= ~_border_reachable(~keep)

    alpha = Image.fromarray((keep * 255).astype(np.uint8))
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    rgba = im.convert("RGBA")
    rgba.putalpha(alpha)
    rgba.save(out)
    return out


def measure_backdrop_tol(src: str, box=None) -> tuple[float, dict]:
    """Suggest a `backdrop_tol` for this specific image instead of guessing one.

    Tolerance is per-image and has to be measured -- a pale costume sits ~20 RGB
    from a white backdrop while a cast shadow sits ~100, so one global default
    either eats the costume or keeps the shadow. Live values ranged 14 to 120
    across two characters, which is why this exists.

    Method: take the backdrop color from the border, build the distance map,
    and split it with Otsu. The backdrop is the near mode, the figure the far
    one; the threshold that separates them IS the tolerance. Returns the value
    plus the stats behind it, so a caller can report the number rather than
    silently applying it.
    """
    im = Image.open(src).convert("RGB")
    if box:
        im = im.crop(box)
    a = np.array(im).astype(float)

    # Backdrop color = median of a border ring, robust to a figure touching an edge.
    k = max(2, min(a.shape[0], a.shape[1]) // 50)
    ring = np.concatenate([a[:k].reshape(-1, 3), a[-k:].reshape(-1, 3),
                           a[:, :k].reshape(-1, 3), a[:, -k:].reshape(-1, 3)])
    bg = np.median(ring, axis=0)

    dist = np.sqrt(((a - bg) ** 2).sum(2)).ravel()
    hist, edges = np.histogram(dist, bins=256, range=(0, 442))
    hist = hist.astype(float)
    total = hist.sum()
    if total == 0:
        return 120.0, {"backdrop_rgb": tuple(bg.round().astype(int)), "note": "empty"}

    # Otsu: maximize between-class variance over the distance histogram.
    w0 = np.cumsum(hist) / total
    centres = (edges[:-1] + edges[1:]) / 2
    m0 = np.cumsum(hist * centres) / total
    mt = m0[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mt * w0 - m0) ** 2 / (w0 * (1 - w0))
    between[~np.isfinite(between)] = 0
    tol = float(centres[int(np.argmax(between))])

    # Otsu finds the valley between backdrop and figure, but it runs high when
    # the FIGURE contains near-backdrop values -- silver hair on a 236-gray
    # backdrop measured 135 and ate a wedge out of the hair, where 40-90 all
    # keyed it cleanly. Cap at 110 and flag the risk rather than trusting it.
    raw = tol
    tol = float(min(max(tol, 10.0), 110.0))
    covered = float((dist < tol).mean())
    return tol, {
        "backdrop_rgb": tuple(int(v) for v in bg.round()),
        "tolerance": round(tol, 1),
        "otsu_raw": round(raw, 1),
        "backdrop_fraction": round(covered, 3),
        "pale_figure_risk": bool(raw > 110.0),
    }


def _largest_blob(mask: np.ndarray) -> np.ndarray:
    """Keep only the biggest connected region, dropping keying speckle.

    Iterative two-pass labelling rather than scipy, which this server does not
    depend on.
    """
    h, w = mask.shape
    label = np.zeros((h, w), int)
    cur = 0
    sizes = {}
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or label[y, x]:
                continue
            cur += 1
            stack = [(y, x)]
            label[y, x] = cur
            n = 0
            while stack:
                cy, cx = stack.pop()
                n += 1
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not label[ny, nx]:
                        label[ny, nx] = cur
                        stack.append((ny, nx))
            sizes[cur] = n
    if not sizes:
        return mask
    return label == max(sizes, key=sizes.get)


def _border_reachable(mask: np.ndarray) -> np.ndarray:
    """Flood the mask inward from the image border."""
    h, w = mask.shape
    seen = np.zeros((h, w), bool)
    stack = [(y, x) for y in (0, h - 1) for x in range(w) if mask[y, x]]
    stack += [(y, x) for x in (0, w - 1) for y in range(h) if mask[y, x]]
    for y, x in stack:
        seen[y, x] = True
    while stack:
        cy, cx = stack.pop()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                stack.append((ny, nx))
    return seen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--box", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--drop-skin", action="store_true",
                    help="also key out skin (for a prop overlapping a limb)")
    ap.add_argument("--no-keep-largest", dest="keep_largest", action="store_false")
    ap.add_argument("--feather", type=float, default=0.6)
    ap.add_argument("--forest-backdrop", dest="flat_backdrop", action="store_false",
                    help="key a warm prop off the blue/green forest wash instead "
                         "of a flat studio backdrop")
    ap.add_argument("--backdrop-tol", type=float, default=120.0)
    a = ap.parse_args()
    print(key_cutout(a.src, a.out, tuple(a.box) if a.box else None,
                     a.drop_skin, a.keep_largest, a.feather,
                     a.flat_backdrop, a.backdrop_tol))


if __name__ == "__main__":
    main()
