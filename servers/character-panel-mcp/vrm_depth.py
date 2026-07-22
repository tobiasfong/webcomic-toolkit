"""
vrm_depth.py — synthesizes a FLUX-ControlNet-ready depth map from a real,
posable VRM mesh (assets/Base_Male.vrm), as an alternative to mannequin.py's
line-skeleton OpenPose maps. Same "3D model instead of 2D-photo guessing"
philosophy as mannequin.py (ARCHITECTURE.md §8b.7) and citygen.py/props.py in
the sibling webcomic-background-mcp server, but rendering an actual skinned
mesh's depth/relief instead of projecting joint coordinates — validated
2026-07-22/23 (ARCHITECTURE.md §8b.9) to reach genuine back views more
reliably than the mannequin skeleton (3/3 seeds vs. ~2/3) once the depth
map's near/far calibration was fixed (see blender_scripts/vrm_pose_depth.py's
docstring for that story).

Requires a separate Blender install (NOT pip-installable as a Python module
for this project's Python version — pip's `bpy` package skips 3.12 entirely,
jumping from 3.11 to 3.13 — so this drives a real Blender executable via
subprocess instead, exactly like workflow.py drives a separate ComfyUI
process). One-time setup:

    1. Download & extract the portable Blender 5.2 LTS zip from
       https://www.blender.org/download/ (or download.blender.org's release
       mirror directly) — no installer needed, just unzip anywhere.
    2. Install the community VRM Add-on for Blender (saturday06/VRM-Addon-
       for-Blender, the "Extension" package, not the legacy "-addon" one) —
       one-time headless install + enable + save preferences so it persists
       across Blender launches:

           blender.exe --background --python-expr "
           import bpy
           bpy.ops.extensions.package_install_files(
               filepath=r'<path to VRM_Addon_for_Blender-Extension-*.zip>',
               repo='user_default', enable_on_install=True)
           bpy.ops.wm.save_userpref()"

    3. Set WEBCOMIC_CHAR_BLENDER to the blender.exe path (see BLENDER_EXE
       below for the default this project was built/tested against).

Only the "standing" pose (arms at sides) is implemented — see
blender_scripts/vrm_pose_depth.py's docstring.

IMPORTANT usage note (the actual finding behind ARCHITECTURE.md §8b.9's
"costume geometry" fix): the VRM mesh wears a plain t-shirt, not any
particular character's actual costume. Describing a different outfit (e.g. a
blazer) in the *text prompt* while conditioning on this mesh's depth map
causes a text-vs-geometry conflict — the model tries to paint a garment the
depth silhouette doesn't have room for, producing ragged texture-clash
artifacts. Use this depth map for pose/direction/anatomy ONLY (a
costume-neutral prompt), then dress the result in the character's actual
described costume via edit_character_image as a separate pass.
"""

import os
import subprocess
import sys

import OpenEXR
import Imath
import numpy as np
from PIL import Image

BLENDER_EXE = os.environ.get(
    "WEBCOMIC_CHAR_BLENDER", r"C:\AI\blender-5.2.0-windows-x64\blender.exe")
VRM_ASSET_PATH = os.environ.get(
    "WEBCOMIC_CHAR_VRM_ASSET",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "Base_Male.vrm"))
_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "blender_scripts", "vrm_pose_depth.py")


class VrmDepthError(RuntimeError):
    pass


def _run_blender(yaw: float, width: int, height: int, out_depth_exr: str,
                 out_normal_exr: str, timeout: int = 180) -> None:
    if not os.path.isfile(BLENDER_EXE):
        raise VrmDepthError(
            f"Blender not found at {BLENDER_EXE}. Set WEBCOMIC_CHAR_BLENDER to "
            f"your blender.exe path — see vrm_depth.py's docstring for setup."
        )
    if not os.path.isfile(VRM_ASSET_PATH):
        raise VrmDepthError(f"VRM asset not found: {VRM_ASSET_PATH}")
    os.makedirs(os.path.dirname(out_depth_exr), exist_ok=True)

    cmd = [
        BLENDER_EXE, "--background", "--python", _SCRIPT_PATH, "--",
        VRM_ASSET_PATH, str(yaw), out_depth_exr, out_normal_exr, str(width), str(height),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0 or not os.path.isfile(out_depth_exr):
        raise VrmDepthError(
            f"Blender render failed (exit {result.returncode}):\n"
            f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}"
        )


def _read_exr_channel(exr_path: str, channel_name: str) -> np.ndarray:
    f = OpenEXR.InputFile(exr_path)
    dw = f.header()["dataWindow"]
    w, h = dw.max.x - dw.min.x + 1, dw.max.y - dw.min.y + 1
    FLOAT = Imath.PixelType(Imath.PixelType.FLOAT)
    return np.frombuffer(f.channel(channel_name, FLOAT), dtype=np.float32).reshape(h, w)


def render_depth_map(yaw: float = 180.0, width: int = 832, height: int = 1216,
                     out: str | None = None) -> str:
    """Render a depth map from the VRM mesh, standing pose, at the given yaw
    (0 = facing camera, 180 = back view — same convention as
    mannequin.render_pose_map). Returns the saved PNG path.

    Feed the output to generate_character_pose(pose_ref_path=<this path>,
    pose_preprocess=False, model="flux_manwha", pose_control_type="depth").
    pose_preprocess MUST be False — this is already a depth map, not a photo
    to extract a skeleton from."""
    if out is None:
        out = os.path.join(os.getcwd(), f"vrm_depth_yaw{int(yaw)}.png")
    base = os.path.splitext(out)[0]
    depth_exr = base + "_depth.exr"
    normal_exr = base + "_normal.exr"

    _run_blender(yaw, width, height, depth_exr, normal_exr)

    arr = _read_exr_channel(depth_exr, "depth.V")
    arr = np.clip(arr, 0.0, 1.0)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    Image.fromarray((arr * 255).astype(np.uint8), mode="L").save(out)

    os.remove(depth_exr)
    os.remove(normal_exr)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=180.0)
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    print(render_depth_map(a.yaw, a.width, a.height, a.out))
