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


def _background_mask(arr, bg_thresh=245, dark_ring_thresh=180, min_hole_size=30, edge_dilate=12):
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

       dark_ring_thresh=180, not 120: a pose-gap's ring is the character's
       own black linework, but at only 4px of dilation that ring can also
       pick up a slice of nearby light-toned fill (e.g. a soft drop shadow
       or a white sock right at the gap's edge), pulling the mean up past a
       tight threshold even though real linework dominates the immediate
       border. Measured on a flowing-robe pose: a true gap
       between white-socked legs, walled off from the canvas border by her
       shadow, rang in at 157 (real holes elsewhere in the same image ran
       83-135); real kept content (a highlight with no enclosing outline at
       all) rang in at 239-240. 180 sits in the wide gap between those two
       clusters.

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


def _darken_drop_shadow(arr, bg_mask, strength=0.6, sat_max=12, bright_range=(150, 230), min_size=2000):
    """Multiply the largest neutral-gray blob outside bg_mask by `strength`,
    so a flat-rendered floor shadow reads as an actual shadow instead of a
    mid-gray smudge once composited onto a background that has no real
    floor of its own.

    Restricted to one large, uniform, near-neutral connected blob rather
    than every matching pixel: the same low-saturation mid-brightness band
    also shows up as ordinary fabric-fold shading scattered in small
    patches all over a costume — darkening every match indiscriminately
    speckles the whole figure. Measured on a flowing-robe pose:
    fold shading forms hundreds of small (tens-to-low-hundreds-px) patches
    at this band, while her drop shadow is one contiguous ~29k-px blob —
    picking only the largest match separates the two cleanly.
    """
    kept = ~bg_mask
    sat = arr.max(axis=2).astype(int) - arr.min(axis=2).astype(int)
    bright = arr.mean(axis=2)
    candidate = kept & (sat <= sat_max) & (bright >= bright_range[0]) & (bright <= bright_range[1])
    labeled, n = ndimage.label(candidate, structure=np.ones((3, 3)))
    if n == 0:
        return arr
    sizes = ndimage.sum(candidate, labeled, range(1, n + 1))
    biggest = int(np.argmax(sizes)) + 1
    if sizes[biggest - 1] < min_size:
        return arr
    out = arr.copy()
    shadow_mask = labeled == biggest
    out[shadow_mask] = (out[shadow_mask] * strength).astype(arr.dtype)
    return out


def outline_fill_mask(arr, box, not_white_thresh=245, search_dilate=2):
    """Within `box` (x0, y0, x1, y1), find the largest connected non-near-
    white blob (its line-art outline) and fill its interior solid.

    For content drawn almost as pale as the white canvas itself — a bare
    steel blade with only a thin contour stroke and faint shading, no
    saturated fill color — _background_mask can't tell "this near-white
    pixel is the object's interior" from "this near-white pixel is empty
    page": the object's own fill is literally the same near-white the
    border-connected background is made of, and merges into it as one
    component through gaps in the outline (same failure as extract_alpha's
    white-sock case, but here it swallows real content instead of a real
    gap). Since color can't resolve this, geometry does: an object drawn
    with a closed outline stroke has a fillable interior; binary_fill_holes
    on the outline recovers the shape directly, independent of how close
    its fill sits to bg_thresh. `box` scopes the search to avoid grabbing
    unrelated linework (hair, a garment edge) elsewhere in the frame —
    pick it loosely around the object; a couple hundred px of empty margin
    inside the box is harmless as long as no other line art falls in it.
    """
    x0, y0, x1, y1 = box
    region_mask = np.zeros(arr.shape[:2], dtype=bool)
    region_mask[y0:y1, x0:x1] = True
    not_white = ~np.all(arr >= not_white_thresh, axis=2)
    lines = not_white & region_mask
    labeled, n = ndimage.label(lines, structure=np.ones((3, 3)))
    if n == 0:
        return np.zeros(arr.shape[:2], dtype=bool)
    sizes = ndimage.sum(lines, labeled, range(1, n + 1))
    biggest = int(np.argmax(sizes)) + 1
    comp = labeled == biggest
    return ndimage.binary_fill_holes(ndimage.binary_dilation(comp, iterations=search_dilate))


def extract_alpha(path, darken_shadow=None, protect_boxes=None, force_bg_boxes=None, force_bg_thresh=230, **kwargs):
    """Return an RGBA image with the white background made transparent —
    see _background_mask for the two-pass border/dark-ring-hole logic.

    darken_shadow: strength multiplier applied to the pose's own drop
    shadow (see _darken_drop_shadow), or None (default) to leave it
    untouched. Opt-in, not opt-on-by-default: the shadow-vs-fold-shading
    split it relies on (one big blob vs many small ones) held for the
    flowing-robe action pose it was built against, but a flat standing
    turnaround crop with no rendered floor shadow at all can have its own
    skirt shading form the biggest neutral-gray blob instead, in which case
    this darkens the skirt in a blotchy partial pattern (whatever part of
    the fold shading happens to fall inside the matched blob) instead of a
    shadow. Only pass a strength when the source image is known to have an
    actual drop shadow to darken.

    protect_boxes: optional list of (x0, y0, x1, y1) boxes, each run
    through outline_fill_mask and forced to stay opaque regardless of what
    _background_mask decided — for near-white content (see
    outline_fill_mask) that would otherwise be erased as background.

    force_bg_boxes: optional list of (x0, y0, x1, y1) boxes where any pixel
    at or above force_bg_thresh gets forced transparent regardless of what
    _background_mask decided — the opposite problem from protect_boxes: a
    small pose-gap ringed by the character's own bright anatomy (pale skin,
    a light-colored sock or wrap) rather than dark fabric defeats
    _background_mask's dark_ring_thresh test no matter how it's tuned,
    since a real gap ringed by skin and a real highlight ringed by
    skin/fabric look identical by color alone (this hit twice on Park Ri
    Hwa alone: white-socked legs, then bandaged ankles — tuning the
    threshold for one case just moves which case breaks). Pick the box by
    eye around the gap, same as protect_boxes/screen_blend's position —
    there's no automatic detection for either direction. Still
    color-gated by force_bg_thresh (not an unconditional cut) so a loosely
    drawn box can overlap the edge of real, darker content (skin, a dark
    outline) without slicing a visible rectangular notch into it.
    force_bg_thresh: brightness floor for the above; lower than the
    default bg_thresh since this is deliberately scoped to a small
    hand-picked box, not the whole image — pick it per box by checking
    where the local background/content brightness clusters actually split
    (a global near_white>=245 miss is exactly why this box exists)."""
    im = Image.open(path).convert("RGB")
    arr = np.array(im)
    bg_mask = _background_mask(arr, **kwargs)
    if protect_boxes:
        protect = np.zeros(arr.shape[:2], dtype=bool)
        for box in protect_boxes:
            protect |= outline_fill_mask(arr, box)
        bg_mask = bg_mask & ~protect
    if force_bg_boxes:
        bright = arr.min(axis=2)
        for x0, y0, x1, y1 in force_bg_boxes:
            region = np.zeros(arr.shape[:2], dtype=bool)
            region[y0:y1, x0:x1] = True
            bg_mask |= region & (bright >= force_bg_thresh)
    if darken_shadow is not None:
        arr = _darken_drop_shadow(arr, bg_mask, strength=darken_shadow)
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


def composite_on_gradient(char_path, out_path, top_color, bottom_color, protect_boxes=None, darken_shadow=None, **kwargs):
    """Cut char_path's white background out and place it over a fresh
    top_color->bottom_color vertical gradient. For a pose with a glowing VFX
    element, pick a light-toned pair (close to white at the end nearer the
    glow) or the leftover soft-white fade will show as a faint halo.

    protect_boxes: see extract_alpha — pass boxes around any near-white
    content (a bare steel blade, etc.) that needs protecting from being
    read as background.

    darken_shadow: see extract_alpha — leave as None unless char_path is
    known to render an actual drop shadow under the figure.

    **kwargs: forwarded to _background_mask (bg_thresh, dark_ring_thresh,
    min_hole_size, edge_dilate) — e.g. bg_thresh for a source render whose
    "white" backdrop is actually a slightly off-white ~240ish (seen on crops
    pulled from a turnaround sheet that weren't flattened to pure 255): the
    default bg_thresh=245 then matches nothing at all, so the mask stays
    empty and the original backdrop shows through fully opaque instead of
    the gradient."""
    char = extract_alpha(char_path, protect_boxes=protect_boxes, darken_shadow=darken_shadow, **kwargs)
    bg = make_gradient(char.size, top_color, bottom_color).convert("RGBA")
    bg.alpha_composite(char)
    bg.convert("RGB").save(out_path)
    return out_path


def _edge_feather_mask(shape, feather):
    """1.0 in the interior, ramping linearly to 0.0 within `feather` px of
    each edge of `shape` (h, w). Multiplying a VFX layer by this before a
    screen blend means its crop boundary itself fades toward black-i.e.-
    no-op instead of ending in genuine bright pixels, so the rectangle the
    crop was cut from stops being visible as a hard seam against whatever
    it's screened onto."""
    h, w = shape
    ramp_y = np.minimum(np.arange(h), np.arange(h)[::-1]) / max(feather, 1)
    ramp_x = np.minimum(np.arange(w), np.arange(w)[::-1]) / max(feather, 1)
    fade = np.minimum(ramp_y[:, None], ramp_x[None, :])
    return np.clip(fade, 0.0, 1.0)


def screen_blend(base, vfx, position=(0, 0), feather=40):
    """Screen-blend a VFX layer (glow, spell effect, etc. rendered on a
    plain BLACK background) onto a base image at (x, y). This is the
    intended long-term fix for the glow-halo problem (ARCHITECTURE.md
    8b.11/8b.12): generate the character with no effect baked in — it cuts
    out cleanly via extract_alpha, same as any other plain pose — then
    render the effect separately on black and add it here as its own layer,
    instead of trying to cut a glow out of a WHITE-background render (which
    is what produced the halo: light-on-white needs fragile unmixing to
    recover; light-on-black needs none).

    Screen blend is the correct math for that: result = 255 - (255-base) *
    (255-vfx) / 255. A pure-black vfx pixel (0,0,0) leaves the base
    completely unchanged (255-0=255, the base term passes through
    untouched); a pure-white vfx pixel forces the result to white (a fully
    saturated glow core); everything between adds light proportionally. No
    background-removal step, no fringe, no halo — it's just added light.

    That math is only seamless if the vfx layer actually fades to black
    before its own crop boundary. In practice an effect asset is cropped
    from a larger render (to exclude, say, a floor reflection) and still
    has real bright pixels reaching the crop's edge — screening that in
    produces a visible rectangle where the crop boundary sits, since
    pixels just inside it screen in real light and pixels just outside it
    (nonexistent, no-op) don't. `feather` fixes this at blend time rather
    than requiring every vfx asset to be pre-faded: it multiplies the vfx
    layer by a mask that ramps from 1.0 in the interior down to 0.0 at the
    crop's own edges, so the boundary itself always blends to a no-op.

    Args:
        base: PIL Image (RGB) or a path to one — the already-composited
            scene (character already placed on its background/gradient).
        vfx: path to the effect image, rendered on a plain black backdrop.
        position: (x, y) top-left where the vfx layer should land on base.
            Pick this by eye from the character's pose (e.g. where a raised
            hand sits) — no auto-alignment, the effect and the pose were
            generated independently.
        feather: px width of the fade-to-black margin applied around the
            vfx layer's own edges before blending (0 disables it).

    Returns:
        A new PIL Image (RGB) — caller saves it (this function doesn't take
        an out_path, since it's meant to be chainable with more layers).
    """
    base_im = Image.open(base).convert("RGB") if isinstance(base, str) else base.convert("RGB")
    vfx_im = Image.open(vfx).convert("RGB")

    base_arr = np.array(base_im).astype(np.int16)
    vfx_arr = np.array(vfx_im).astype(np.int16)

    if feather > 0:
        fade = _edge_feather_mask(vfx_arr.shape[:2], feather)
        vfx_arr = (vfx_arr * fade[:, :, None]).astype(np.int16)

    x, y = position
    bh, bw = base_arr.shape[:2]
    vh, vw = vfx_arr.shape[:2]
    # clip to the actual overlap in case the vfx layer would extend past
    # base's edges at this position
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + vw, bw), min(y + vh, bh)
    if x1 <= x0 or y1 <= y0:
        return base_im  # no overlap — nothing to do

    vx0, vy0 = x0 - x, y0 - y
    region = base_arr[y0:y1, x0:x1]
    vfx_region = vfx_arr[vy0:vy0 + (y1 - y0), vx0:vx0 + (x1 - x0)]

    screened = 255 - (255 - region) * (255 - vfx_region) // 255
    base_arr[y0:y1, x0:x1] = screened
    return Image.fromarray(base_arr.astype(np.uint8), mode="RGB")


def alpha_overlay_vfx(base, vfx, position=(0, 0), feather=40, alpha_gain=1.0, black_point=40):
    """Paste a VFX layer (rendered on plain BLACK) onto `base` as real
    colored content, using the VFX pixel's own brightness as its opacity —
    the on-white counterpart to screen_blend.

    screen_blend only ever *adds* light (result = 255 - (255-base)*
    (255-vfx)/255), which is the right math for compositing onto a colored
    or dark backdrop — a black vfx pixel is a true no-op, a bright one adds
    a believable glow. But that same math is a hard no-op everywhere the
    base is already pure white: 255-base=0, so the result is 255 no matter
    what the vfx layer contains, regardless of how bright or saturated it
    is. No amount of tuning the vfx asset fixes this — screen blending
    fundamentally cannot render anything additive on top of a base with no
    headroom left to add to.

    This function instead treats brightness as alpha and does a normal
    over-composite: out = base*(1-a) + vfx*a, a = vfx_brightness/255 (times
    `alpha_gain`, times the same edge-feather mask screen_blend uses).
    Since it replaces pixels rather than trying to brighten them, it
    renders visibly against a white (or any) background.

    Args:
        base / vfx / position / feather: see screen_blend.
        alpha_gain: multiplier on the brightness-derived alpha, for making
            a dim effect asset opaque enough to read without regenerating
            it — 1.0 uses the vfx's own brightness untouched.
        black_point: brightness floor subtracted (and rescaled) before
            computing alpha. A vfx asset's "black" background is rarely
            pure (0,0,0) — a faint ambient gradient, a floor reflection —
            and without a floor that residual brightness still contributes
            a small nonzero alpha across the whole box, visible as a faint
            rectangular wash against a plain white base (there's no dark
            backdrop here to hide it in, unlike screen_blend's use case).
            Raising black_point clips that ambient floor to true zero
            alpha so only the actual bright effect content shows.
    """
    base_im = Image.open(base).convert("RGB") if isinstance(base, str) else base.convert("RGB")
    vfx_im = Image.open(vfx).convert("RGB")

    base_arr = np.array(base_im).astype(np.float32)
    vfx_arr = np.array(vfx_im).astype(np.float32)

    bright = vfx_arr.mean(axis=2)
    alpha = np.clip((bright - black_point) / max(255 - black_point, 1) * alpha_gain, 0.0, 1.0)
    if feather > 0:
        alpha *= _edge_feather_mask(vfx_arr.shape[:2], feather)

    x, y = position
    bh, bw = base_arr.shape[:2]
    vh, vw = vfx_arr.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + vw, bw), min(y + vh, bh)
    if x1 <= x0 or y1 <= y0:
        return base_im

    vx0, vy0 = x0 - x, y0 - y
    region = base_arr[y0:y1, x0:x1]
    vfx_region = vfx_arr[vy0:vy0 + (y1 - y0), vx0:vx0 + (x1 - x0)]
    a = alpha[vy0:vy0 + (y1 - y0), vx0:vx0 + (x1 - x0)][:, :, None]

    base_arr[y0:y1, x0:x1] = region * (1 - a) + vfx_region * a
    return Image.fromarray(base_arr.astype(np.uint8), mode="RGB")
