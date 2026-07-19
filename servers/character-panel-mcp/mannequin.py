"""
mannequin.py — a 3D posable humanoid skeleton that SYNTHESIZES OpenPose control
maps from any viewing angle, instead of extracting them from 2D art.

Why this exists (ARCHITECTURE.md §8b.7): the back-view campaign established that
this stack can only reach genuine back views when the pose conditioning itself
unambiguously encodes "seen from behind" — and the OpenposePreprocessor can't
produce that from 2D art, because it guesses left/right limb assignment from
appearance and drops facing information. This module sidesteps extraction
entirely: a low-poly 3D skeleton is posed, rotated to any yaw, orthographically
projected, and drawn in the exact COCO-18 OpenPose color convention the
ControlNet was trained on. At yaw 180 the left/right color assignment flips and
the face keypoints are occluded (omitted) — which is precisely how a real
back-view OpenPose annotation looks, and something no prompt wording achieved.

Same mesh-to-control-map pattern as webcomic-background-mcp's citygen.py
(3D city -> sketch) and props.py (parametric prop -> Canny) — applied to the
character's body. Pure numpy + PIL, no ComfyUI, no GPU.

The output map must be fed to ControlNet DIRECTLY (workflow.generate's
pose_preprocess=False) — running the OpenposePreprocessor over an already-
synthesized map would try to find a human in a stick figure and fail.

Usage:
    python mannequin.py --preset standing --yaw 180 --out back_view_map.png
"""

import os
import math
import argparse

# COCO-18 keypoint order (index = OpenPose convention).
KEYPOINTS = [
    "nose", "neck",
    "r_shoulder", "r_elbow", "r_wrist",
    "l_shoulder", "l_elbow", "l_wrist",
    "r_hip", "r_knee", "r_ankle",
    "l_hip", "l_knee", "l_ankle",
    "r_eye", "l_eye", "r_ear", "l_ear",
]

# Neutral coordinate system: y up, character FACES +z at yaw 0 (toward the
# viewer), anatomical LEFT along +x — so at yaw 0 the right shoulder projects
# to screen-left, exactly like a real front-view OpenPose annotation, and at
# yaw 180 the assignment flips to screen-right, exactly like a real back view.
# Heights in ~metres for a 1.75-unit figure.
_BASE = {
    "nose":       (0.000, 1.620, 0.080),
    "neck":       (0.000, 1.480, 0.000),
    "r_shoulder": (-0.200, 1.440, 0.000),
    "r_elbow":    (-0.240, 1.160, 0.010),
    "r_wrist":    (-0.250, 0.900, 0.020),
    "l_shoulder": (0.200, 1.440, 0.000),
    "l_elbow":    (0.240, 1.160, 0.010),
    "l_wrist":    (0.250, 0.900, 0.020),
    "r_hip":      (-0.100, 0.920, 0.000),
    "r_knee":     (-0.110, 0.500, 0.010),
    "r_ankle":    (-0.120, 0.080, 0.000),
    "l_hip":      (0.100, 0.920, 0.000),
    "l_knee":     (0.110, 0.500, 0.010),
    "l_ankle":    (0.120, 0.080, 0.000),
    "r_eye":      (-0.035, 1.660, 0.075),
    "l_eye":      (0.035, 1.660, 0.075),
    "r_ear":      (-0.080, 1.620, 0.010),
    "l_ear":      (0.080, 1.620, 0.010),
}

# Pose presets = joint overrides on the neutral skeleton. Explicit coordinates,
# no IK — poses are hand-authored the same way citygen hand-authors buildings.
POSES = {
    "standing": {},
    "t_pose": {
        "r_elbow": (-0.450, 1.440, 0.000), "r_wrist": (-0.700, 1.440, 0.000),
        "l_elbow": (0.450, 1.440, 0.000),  "l_wrist": (0.700, 1.440, 0.000),
    },
    "hands_behind_back": {
        "r_elbow": (-0.240, 1.150, -0.100), "r_wrist": (0.030, 0.950, -0.160),
        "l_elbow": (0.240, 1.150, -0.100),  "l_wrist": (-0.030, 0.950, -0.160),
    },
    "arms_crossed": {
        "r_elbow": (-0.200, 1.150, 0.120), "r_wrist": (0.120, 1.250, 0.160),
        "l_elbow": (0.200, 1.130, 0.120),  "l_wrist": (-0.120, 1.220, 0.180),
    },
    "walking": {
        "r_knee": (-0.110, 0.550, 0.120), "r_ankle": (-0.120, 0.120, 0.280),
        "l_knee": (0.110, 0.480, -0.100), "l_ankle": (0.120, 0.100, -0.260),
        "r_elbow": (-0.240, 1.160, -0.080), "r_wrist": (-0.250, 0.920, -0.180),
        "l_elbow": (0.240, 1.160, 0.100),  "l_wrist": (0.250, 0.940, 0.220),
    },
}

# Canonical COCO-18 limb pairs (0-indexed) and their draw colors, matching
# controlnet_aux's draw_bodypose — the visualization the ControlNet was
# trained on. Order matters only for matching the convention.
_LIMBS = [
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7),
    (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
    (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
]
_LIMB_COLORS = [
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0),
    (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255),
    (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
    (255, 0, 170), (255, 0, 255),
]
_JOINT_COLORS = _LIMB_COLORS + [(255, 0, 85)]  # 18 joint colors

# Face-keypoint visibility thresholds on the yaw-rotated z (toward-viewer
# component). Nose/eyes vanish from behind; ears survive a wide range — the
# same occlusion behavior real back-view OpenPose annotations show.
_VISIBILITY_Z = {"nose": 0.02, "r_eye": 0.01, "l_eye": 0.01,
                 "r_ear": -0.06, "l_ear": -0.06}


def _pose_joints(preset: str) -> dict:
    if preset not in POSES:
        raise ValueError(f"Unknown pose preset '{preset}'. Options: {', '.join(POSES)}")
    joints = dict(_BASE)
    joints.update(POSES[preset])
    return joints


def render_pose_map(preset: str = "standing", yaw: float = 0.0,
                    width: int = 832, height: int = 1216,
                    out: str | None = None) -> str:
    """Render the posed, yaw-rotated skeleton as an OpenPose-format control map.

    yaw in degrees: 0 = facing the viewer, 90 = their left side toward viewer,
    180 = seen from behind. Returns the saved PNG path."""
    import numpy as np
    from PIL import Image, ImageDraw

    joints3d = _pose_joints(preset)
    th = math.radians(yaw)
    cos_t, sin_t = math.cos(th), math.sin(th)

    projected: dict[str, tuple[float, float] | None] = {}
    for name, (x, y, z) in joints3d.items():
        rx = x * cos_t + z * sin_t          # rotation about the y axis
        rz = -x * sin_t + z * cos_t         # toward-viewer component after rotation
        if name in _VISIBILITY_Z and rz < _VISIBILITY_Z[name]:
            projected[name] = None          # occluded — omit, like real annotations
        else:
            projected[name] = (rx, y)

    # Fit the figure to ~85% of canvas height, centered.
    ys = [joints3d[k][1] for k in joints3d]
    y_min, y_max = min(ys) - 0.08, max(ys) + 0.14   # margin for feet/head-top
    scale = (height * 0.85) / (y_max - y_min)
    cx, cy = width / 2.0, height / 2.0
    y_mid = (y_min + y_max) / 2.0

    def to_px(p):
        return (cx + p[0] * scale, cy - (p[1] - y_mid) * scale)

    pts = {k: (to_px(v) if v is not None else None) for k, v in projected.items()}

    stick = max(2, round(4 * height / 512))          # convention: 4px at 512
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for (a, b), color in zip(_LIMBS, _LIMB_COLORS):
        pa, pb = pts[KEYPOINTS[a]], pts[KEYPOINTS[b]]
        if pa is None or pb is None:
            continue
        draw.line([pa, pb], fill=color, width=stick)
        # rounded caps so thick limbs read like the convention's ellipses
        for p in (pa, pb):
            r = stick / 2
            draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)

    # Convention: limbs dimmed to 0.6, joint circles full-brightness on top.
    arr = (np.asarray(canvas, dtype=np.float32) * 0.6).astype(np.uint8)
    canvas = Image.fromarray(arr)
    draw = ImageDraw.Draw(canvas)
    r = stick
    for i, name in enumerate(KEYPOINTS):
        p = pts[name]
        if p is None:
            continue
        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=_JOINT_COLORS[i])

    if out is None:
        out = os.path.join(os.getcwd(), f"pose_map_{preset}_yaw{int(yaw)}.png")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    canvas.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="standing", choices=sorted(POSES))
    ap.add_argument("--yaw", type=float, default=0.0,
                    help="0=facing viewer, 90=left side, 180=from behind")
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=1216)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    print(render_pose_map(a.preset, a.yaw, a.width, a.height, a.out))
