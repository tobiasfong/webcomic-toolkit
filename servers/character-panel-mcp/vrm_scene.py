"""
vrm_scene.py — render a multi-figure, arbitrarily-posed VRM scene to a
ControlNet-ready depth map.

The multi-character sibling of vrm_depth.py. That module renders one figure in
one hardcoded standing pose at a chosen yaw, which is what reference-sheet
turnarounds need. This one drives blender_scripts/vrm_scene_depth.py with a
JSON scene spec, so two characters can be posed against each other and rendered
as a single depth map with correct per-pixel ordering between them.

Why depth rather than the author's line sketch: see vrm_scene_depth.py's
docstring for the full evidence trail. Short version — a line map cannot say
which outline is a leg and which is a sleeve, so FLUX welds crossing limbs
together, and that failure reproduces with a single figure in frame, which
rules out "the bodies overlap" as the cause. Depth encodes ordering per pixel,
so it disambiguates limb identity natively.

Shares vrm_depth.py's Blender setup (executable path, VRM add-on) and its
costume-neutral constraint: the base mesh wears a plain t-shirt, so describe
pose and framing in the prompt, not the character's actual outfit, then apply
costume and identity in a later edit_image pass.

Usage:
    from vrm_scene import render_scene_depth
    png = render_scene_depth({
        "width": 1216, "height": 1088,
        "camera": {"yaw": 0, "dist": 4.0, "ortho_scale": 3.0, "target_z": 1.0},
        "figures": [
            {"location": [-0.7, 0, 0], "yaw": 20,
             "bones": {"J_Bip_R_UpperArm": {"X": -40, "Z": 25}}},
            {"location": [0.7, 0, 0], "yaw": -110,
             "bones": {"J_Bip_R_UpperLeg": {"X": -85}}},
        ],
    }, out="kick.png")
"""

import json
import os
import subprocess
import tempfile

import OpenEXR
import Imath
import numpy as np
from PIL import Image

from vrm_depth import BLENDER_EXE, VRM_ASSET_PATH, VrmDepthError

_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "blender_scripts", "vrm_scene_depth.py")


def _mask_hands(arr: np.ndarray, marks: list, feather: float = 0.45) -> np.ndarray:
    """Fade the depth map to background over each hand.

    FLUX draws hands well on its own — that capability is why this project
    moved off SD1.5/SDXL — but Base_Male.vrm's hands are low-poly mittens, and
    conditioning on them makes hands measurably worse than leaving them
    unconstrained (claws and fused fingers, live 2026-07-28). Fading them out
    of the control map hands that region back to the base model.

    The region is BLURRED, not painted over. Two earlier attempts both failed
    the same way (live, 2026-07-28): fading the disc to background made a
    bright-rim/dark-centre gradient, which is the depth signature of a sphere —
    the model drew a translucent bubble over every hand. Flattening it to wrist
    depth instead produced haloed discs. The lesson is that compositing any
    CIRCLE into a region spanning both body and background yields a circular
    artifact, however it is shaded, because the shape is not in the geometry.

    Blur adds nothing. It only removes the high-frequency finger detail that
    was driving the claws, while preserving the local mean and the silhouette,
    so there is no new edge for ControlNet to find. FLUX then fills in hand
    detail from its own prior, which is what it is good at.
    """
    from PIL import ImageFilter

    h, w = arr.shape
    yy, xx = np.mgrid[0:h, 0:w]
    # m["r"] is a wrist-to-fingertip span, i.e. already the whole hand
    radii = [max(4.0, m["r"] * w * 0.75) for m in marks]
    if not radii:
        return arr
    blurred = np.asarray(
        Image.fromarray((arr * 255).astype(np.uint8), mode="L").filter(
            ImageFilter.GaussianBlur(radius=max(2.0, float(np.mean(radii)) * 0.5))),
        dtype=np.float32) / 255.0

    weight = np.zeros((h, w), dtype=np.float32)
    for m, r in zip(marks, radii):
        d = np.sqrt((xx - m["x"] * w) ** 2 + (yy - m["y"] * h) ** 2)
        # 1 at the hand, easing to 0 by the edge of the disc
        weight = np.maximum(weight, np.clip((r - d) / max(1e-6, r * feather), 0.0, 1.0))
    return arr * (1.0 - weight) + blurred * weight


def render_scene_depth(spec: dict, out: str | None = None, timeout: int = 300,
                       mask_hands: bool = True) -> str:
    """Render `spec` to a grayscale depth PNG (near = white, far = black).

    Figures may omit "vrm" to use the default base mesh. With mask_hands the
    hands are faded out of the control map so FLUX draws them unconstrained —
    see _mask_hands. Returns the PNG path.
    """
    if not os.path.isfile(BLENDER_EXE):
        raise VrmDepthError(
            f"Blender not found at {BLENDER_EXE}. Set WEBCOMIC_CHAR_BLENDER — "
            f"see vrm_depth.py's docstring for setup.")
    if not spec.get("figures"):
        raise VrmDepthError("scene spec has no 'figures'")

    spec = json.loads(json.dumps(spec))  # don't mutate the caller's dict
    spec["mask_hands"] = bool(mask_hands)
    for fig in spec["figures"]:
        fig.setdefault("vrm", VRM_ASSET_PATH)
        if not os.path.isfile(fig["vrm"]):
            raise VrmDepthError(f"VRM asset not found: {fig['vrm']}")

    if out is None:
        out = os.path.join(os.getcwd(), "vrm_scene_depth.png")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    exr = os.path.splitext(out)[0] + "_depth.exr"

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(spec, f)
        spec_path = f.name
    try:
        result = subprocess.run(
            [BLENDER_EXE, "--background", "--python", _SCRIPT_PATH, "--", spec_path, exr],
            capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0 or not os.path.isfile(exr):
            raise VrmDepthError(
                f"Blender render failed (exit {result.returncode}):\n"
                f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        # surface the measured depth window — a near-flat map is the known
        # failure mode, and this is the number that reveals it
        for line in result.stdout.splitlines():
            if line.startswith("DEPTH WINDOW"):
                print(line)
    finally:
        os.unlink(spec_path)

    f = OpenEXR.InputFile(exr)
    dw = f.header()["dataWindow"]
    w, h = dw.max.x - dw.min.x + 1, dw.max.y - dw.min.y + 1
    arr = np.clip(np.frombuffer(
        f.channel("depth.V", Imath.PixelType(Imath.PixelType.FLOAT)),
        dtype=np.float32).reshape(h, w), 0.0, 1.0)

    hands_json = os.path.splitext(exr)[0] + "_hands.json"
    if mask_hands and os.path.isfile(hands_json):
        with open(hands_json) as fh:
            marks = json.load(fh)
        arr = _mask_hands(arr, marks)
        print(f"masked {len(marks)} hand(s) out of the depth map")
        os.remove(hands_json)

    Image.fromarray((arr * 255).astype(np.uint8), mode="L").save(out)
    os.remove(exr)
    return out
