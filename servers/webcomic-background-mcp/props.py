"""
props.py — parametric 3D props, placed in-scene and rendered headless to a
ControlNet sketch (the citygen.py treatment, extended from buildings to
objects).

Why this exists: diffusion models are bad at *geometry* — rows of repeated
objects (bicycles, carts, market stalls) come out fused, cropped, or mutated
when the model has to invent their structure. Buildings never had this problem
here because citygen.py hands SD a projection-correct sketch and lets it paint.
Props get the same deal: real 3D meshes, real camera, real occlusion via the
painter's algorithm, one coherent Canny sketch — SD only paints.

World scale matches citygen.py: 1 unit ≈ 0.37 m, a standing adult ≈ 4.6 units.
A bicycle wheel here is r=0.92 units ≈ 0.34 m (a 26" wheel), saddle ≈ 2.2
units ≈ 0.8 m. Props therefore drop into city scenes at the correct size.

Pipeline:  build_props(objects) [+ build_shelter] -> auto_camera -> lineart
           -> Canny sketch -> workflow.generate paints it.
"""

import math
import os

import numpy as np
import cv2

import citygen as cg


# ------------------------------------------------------------- mesh helpers --
def _mesh(v, f, grey):
    return cg._Mesh(np.array(v, dtype=np.float64), f, grey)


def _tube(p0, p1, width, z=0.0):
    """Thin quad joining two (x, y) points in a prop's local X-Y plane."""
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1e-6
    px, py = -dy / length * width / 2, dx / length * width / 2
    v = [[x0 + px, y0 + py, z], [x1 + px, y1 + py, z],
         [x1 - px, y1 - py, z], [x0 - px, y0 - py, z]]
    return v, [(0, 1, 2, 3)]


def _disc(cx, cy, r, n=28, z=0.0):
    ang = np.linspace(0, 2 * math.pi, n, endpoint=False)
    v = [[cx + r * math.cos(a), cy + r * math.sin(a), z] for a in ang]
    return v, [tuple(range(n))]


# ------------------------------------------------------------------ bicycle --
def build_bicycle(index: int = 0, r: float = 0.92):
    """One parked bicycle, local space: standing on y=0, its side profile in
    the X-Y plane (a flat cutout — correct for a sketch pass), facing -X.

    Geometry tuned against a real road-bike reference across a full session of
    A/B renders (see CHANGELOG v1.8.0): thin tire (rim at 0.82r — a fat ring
    reads as a motorcycle/millstone), true diamond frame with fork, chain stay
    and seat stay, saddle, and a straight T-bar handlebar mounted HIGHER than
    the saddle (a curved drop-bar hook kept getting painted as a second
    saddle).

    `index` offsets this bike's flat grays so neighbouring bikes in a row stay
    separable at the Canny stage instead of fusing — the same per-mesh-shade
    trick citygen uses for adjacent buildings.
    """
    d = 1.4 * r                                   # half wheelbase
    tube_w = 0.09 * r
    rear_hub = (-d, r)
    front_hub = (d, r)
    bb = (-d * 0.12, r * 0.45)                    # bottom bracket
    seat_top = (-d * 0.62, r * 1.95)
    head_bottom = (d * 0.72, r * 1.05)
    head_top = (d * 0.62, r * 1.62)
    handle = (d * 0.95, r * 2.15)                 # above saddle height

    base = cg._grey(index * 2 + 1)
    tire_g = max(12, base - 35)
    rim_g = min(230, base + 25)
    frame_g = max(15, base - 15)

    meshes = []
    for hub in (rear_hub, front_hub):
        meshes.append(_mesh(*_disc(hub[0], hub[1], r), grey=tire_g))
        meshes.append(_mesh(*_disc(hub[0], hub[1], r * 0.82, z=-0.01), grey=rim_g))
        meshes.append(_mesh(*_disc(hub[0], hub[1], r * 0.08, z=-0.02), grey=max(10, tire_g - 10)))

    for p0, p1 in [(bb, seat_top), (seat_top, head_top), (head_top, bb),
                   (bb, head_bottom), (head_bottom, head_top),
                   (seat_top, rear_hub), (bb, rear_hub),
                   (head_bottom, front_hub)]:
        meshes.append(_mesh(*_tube(p0, p1, tube_w), grey=frame_g))

    sx, sy = seat_top                              # saddle
    meshes.append(_mesh(*_tube((sx - 0.22 * r, sy + 0.1 * r),
                               (sx + 0.12 * r, sy + 0.1 * r), 0.16 * r), grey=frame_g))
    hx, hy = handle                                # stem + straight T-bar
    bar_half = r * 0.42
    meshes.append(_mesh(*_tube(head_top, handle, tube_w), grey=frame_g))
    meshes.append(_mesh(*_tube((hx - bar_half, hy), (hx + bar_half, hy),
                               tube_w * 0.85), grey=frame_g))
    meshes.append(_mesh(*_disc(bb[0], bb[1], r * 0.16, z=-0.015), grey=frame_g))  # crank
    meshes.append(_mesh(*_tube(bb, (bb[0] + 0.22 * r, bb[1] - 0.1 * r), 0.08 * r), grey=frame_g))

    for m in meshes:                               # face -X (matches reference)
        m.v[:, 0] *= -1
    return meshes


PROPS = {"bicycle": build_bicycle}


# ---------------------------------------------------------------- placement --
def place(meshes, x=0.0, z=0.0, yaw_deg=0.0, scale=1.0):
    """Copy prop meshes into world space: scale, rotate about Y, translate."""
    yaw = math.radians(yaw_deg)
    c, s = math.cos(yaw), math.sin(yaw)
    out = []
    for m in meshes:
        v = m.v.copy() * scale
        xr = v[:, 0] * c - v[:, 2] * s
        zr = v[:, 0] * s + v[:, 2] * c
        v[:, 0] = xr + x
        v[:, 2] = zr + z
        out.append(cg._Mesh(v, m.f, m.grey))
    return out


def build_props(objects):
    """objects: [{"type": "bicycle", "x": 0, "z": 0, "yaw": 0, "scale": 1}, ...]
    Unknown types raise ValueError listing what exists."""
    meshes = []
    for i, ob in enumerate(objects):
        kind = ob.get("type", "bicycle")
        if kind not in PROPS:
            raise ValueError(f"unknown prop '{kind}'; available: {', '.join(PROPS)}")
        prop = PROPS[kind](index=i)
        meshes += place(prop, ob.get("x", 0.0), ob.get("z", 0.0),
                        ob.get("yaw", 0.0), ob.get("scale", 1.0))
    return meshes


def bike_row(n=4, spacing=2.2, x=0.0, z0=0.0, yaw=0.0, jitter=4.0):
    """Convenience: a parked row — n bicycles side by side along Z, real-rack
    spacing (~0.8 m). `jitter` alternates a few degrees of yaw per bike: real
    parked bikes are never perfectly parallel, and it guarantees no flat
    cutout is ever seen exactly edge-on (which renders as a sliver — flat
    props need the camera ≥ ~25° off their plane, see auto_camera)."""
    return [{"type": "bicycle", "x": x, "z": z0 + i * spacing,
             "yaw": yaw + (jitter if i % 2 else -jitter)}
            for i in range(n)]


# ------------------------------------------------------------------ shelter --
def build_shelter(meshes_bbox, grey_wall=70, grey_post=50, grey_roof=60):
    """A simple carport over the props: back wall, posts, flat roof slab.
    Deliberately crude — SD paints the gothic detail; this only gives the
    sketch believable large forms. Sized from the props' bounding box."""
    pts_min, pts_max = meshes_bbox
    x0, z0, z1 = pts_max[0] + 1.2, pts_min[2] - 2.5, pts_max[2] + 2.5
    depth = z1 - z0
    meshes = []
    wv, wf = cg._box((x0 + 1.0), 0, (z0 + z1) / 2, 2.0, 9.5, depth + 4)   # back wall
    meshes.append(cg._Mesh(wv, wf, grey_wall))
    n_posts = max(2, int(depth // 5))
    for i in range(n_posts + 1):
        pz = z0 + depth * i / n_posts
        pv, pf = cg._box(pts_min[0] - 0.8, 0, pz, 0.55, 7.0, 0.55)        # posts
        meshes.append(cg._Mesh(pv, pf, grey_post))
    rv, rf = cg._box((x0 + pts_min[0] - 0.8) / 2, 7.0, (z0 + z1) / 2,      # roof slab
                     (x0 - pts_min[0]) + 2.6, 0.5, depth + 2)
    meshes.append(cg._Mesh(rv, rf, grey_roof))
    return meshes


# ------------------------------------------------------------------- camera --
def auto_camera(meshes, width, height, angle_deg=28.0, elev_deg=9.0,
                fov=42.0, fill=0.82, frame_on=None):
    """Fit a camera so every vertex of `frame_on` (default: all meshes) lands
    inside the frame with breathing room. This is what prevents the clipped-
    wheel failure: framing is computed from the geometry, never eyeballed.

    angle_deg: yaw of the camera around the subject (0 = looking straight at
    the props' side profiles from -X; positive swings toward +Z, a 3/4 view).
    fill: max fraction of each half-axis of the frame the subject may occupy.
    """
    frame_meshes = frame_on if frame_on is not None else meshes
    pts = np.vstack([m.v for m in frame_meshes])
    center = (pts.min(axis=0) + pts.max(axis=0)) / 2
    yaw, el = math.radians(angle_deg), math.radians(elev_deg)
    direction = np.array([-math.cos(yaw) * math.cos(el),
                          math.sin(el),
                          -math.sin(yaw) * math.cos(el)])   # centroid -> camera
    dist = 6.0
    cam = None
    for _ in range(60):
        pos = center + direction * dist
        cam = {"pos": tuple(pos), "look": tuple(center), "fov": fov}
        p, r, u, f, focal = cg._cam_basis(cam, width, height)
        rel = pts - p
        x, y, z = rel @ r, rel @ u, rel @ f
        if np.any(z < 1.0):
            dist *= 1.25
            continue
        sx = focal * x / z
        sy = focal * y / z
        if (np.abs(sx).max() <= (width / 2) * fill and
                np.abs(sy).max() <= (height / 2) * fill):
            return cam
        dist *= 1.12
    return cam


# ----------------------------------------------------------------- pipeline --
def prop_sketch(out_dir, objects, setting="shelter", width=1344, height=1008,
                angle_deg=28.0, elev_deg=9.0, fov=42.0,
                low=60, high=140, tag="props"):
    """Build props (+ optional shelter) -> auto-framed lineart -> Canny sketch.
    Returns (sketch_path, lineart_path). The camera frames the PROPS; the
    shelter may run past the frame edges (walls always do)."""
    os.makedirs(out_dir, exist_ok=True)
    prop_meshes = build_props(objects)
    meshes = list(prop_meshes)
    if setting == "shelter":
        pts = np.vstack([m.v for m in prop_meshes])
        meshes += build_shelter((pts.min(axis=0), pts.max(axis=0)))
    elif setting not in (None, "", "none"):
        raise ValueError(f"unknown setting '{setting}'; use 'shelter' or 'none'")

    cam = auto_camera(meshes, width, height, angle_deg, elev_deg, fov,
                      frame_on=prop_meshes)
    lineart = cg.render_lineart(meshes, camera=cam, width=width, height=height)
    line_path = os.path.join(out_dir, f"{tag}_lineart.png")
    cv2.imwrite(line_path, lineart)

    blurred = cv2.GaussianBlur(lineart, (3, 3), 0)
    edges = cv2.Canny(blurred, low, high)
    sketch_path = os.path.join(out_dir, f"{tag}_sketch.png")
    cv2.imwrite(sketch_path, edges)
    return sketch_path, line_path
