"""
bg_composite.py — cut a flat-white-background character render onto a plain
two-color gradient backdrop. Zero GPU, zero tokens (pure PIL/numpy).

Scope note: an earlier version of this module also composited characters
onto full illustrated scene backgrounds (generated separately, no character
in the prompt). That path is deliberately NOT here — any pose with a glowing
VFX element (a spell effect, ice magic) renders in the source art as a soft
fade to white with no hard edge, and no cutout-based fix (edge blur, mask
dilation, additive recompositing) removed the resulting halo cleanly against
a high-contrast illustrated background. Plain gradients sidestep this: pair
a glow pose with a light-toned gradient and the leftover fade is invisible,
since the problem was never "background vs. no background," only contrast
between the glow's white fade and whatever sits behind it (see
ARCHITECTURE.md 8b.11 for the full investigation). Revisit illustrated-scene
compositing only when panel generation is built properly, where a glowing
effect should be generated within the conditioned scene directly rather
than cut from a white-background render.
"""
import numpy as np
from PIL import Image
from scipy import ndimage


def _background_mask(arr, bg_thresh=245, dark_ring_thresh=120, min_hole_size=30, edge_dilate=12):
    """Boolean mask, True = background (to be made transparent).

    Two passes:
    1. Any near-white region connected to the image border is background —
       handles the ordinary surrounding whitespace, including cases like a
       gap between shoes that reaches the bottom edge off-center (not at a
       corner pixel) — seeding from the WHOLE border, not just the four
       corners, is what catches that.
    2. A near-white region NOT connected to the border (a true topological
       hole — background peeking through a pose, e.g. between crossed legs
       or under a raised arm) still needs removing, but a plain white shirt
       is ALSO an unconnected near-white region and must NOT be removed.
       These are told apart by what surrounds them: a pose-gap is ringed by
       dark fabric (black trousers), a shirt is ringed by bright fabric/skin.
       Ring mean brightness < dark_ring_thresh -> treat as another
       background hole (measured on real ring-pixel colors, not guessed).

    Finally, the mask is dilated by edge_dilate px: this source art
    anti-aliases its edges against white down through a medium-gray band
    (measured ~200-244) before the line art proper starts, invisible on
    white but a visible fringe on any other backdrop. Dilating the
    already-correct background boundary eats that fringe by proximity
    rather than by a global brightness threshold (a lower threshold was
    tried and rejected — it also erases genuinely light in-scene content,
    e.g. a pale glow effect, which is in the same brightness range).
    """
    near_white = np.all(arr >= bg_thresh, axis=2)
    labeled, n = ndimage.label(near_white, structure=np.ones((3, 3)))

    border_labels = set(labeled[0, :]) | set(labeled[-1, :]) | set(labeled[:, 0]) | set(labeled[:, -1])
    border_labels.discard(0)

    bg_labels = set(border_labels)
    for lbl in range(1, n + 1):
        if lbl in bg_labels:
            continue
        comp = labeled == lbl
        if comp.sum() < min_hole_size:
            continue
        ring = ndimage.binary_dilation(comp, iterations=4) & ~comp
        if not ring.any():
            continue
        if arr[ring].mean() < dark_ring_thresh:
            bg_labels.add(lbl)

    bg_mask = np.isin(labeled, list(bg_labels)) if bg_labels else np.zeros_like(near_white)
    return ndimage.binary_dilation(bg_mask, iterations=edge_dilate)


def extract_alpha(path, **kwargs):
    """Return an RGBA image with the white background made transparent —
    see _background_mask for the two-pass border/dark-ring-hole logic."""
    im = Image.open(path).convert("RGB")
    arr = np.array(im)
    bg_mask = _background_mask(arr, **kwargs)
    alpha = np.where(bg_mask, 0, 255).astype(np.uint8)
    rgba = np.dstack([arr, alpha])
    return Image.fromarray(rgba, mode="RGBA")


def make_gradient(size, top_color, bottom_color):
    """A simple vertical two-color gradient, same size as the character
    image it'll sit behind."""
    w, h = size
    top = np.array(top_color, dtype=float)
    bottom = np.array(bottom_color, dtype=float)
    t = np.linspace(0, 1, h)[:, None]
    row = (top[None, :] * (1 - t) + bottom[None, :] * t).astype(np.uint8)
    arr = np.repeat(row[:, None, :], w, axis=1)
    return Image.fromarray(arr, mode="RGB")


def composite_on_gradient(char_path, out_path, top_color, bottom_color):
    """Cut char_path's white background out and place it over a fresh
    top_color->bottom_color vertical gradient. For a pose with a glowing VFX
    element, pick a light-toned pair (close to white at the end nearer the
    glow) or the leftover soft-white fade will show as a faint halo."""
    char = extract_alpha(char_path)
    bg = make_gradient(char.size, top_color, bottom_color).convert("RGBA")
    bg.alpha_composite(char)
    bg.convert("RGB").save(out_path)
    return out_path
