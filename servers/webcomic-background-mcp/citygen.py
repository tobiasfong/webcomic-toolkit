"""
citygen.py — procedural 3D gothic city, rendered headless to a ControlNet sketch.

The "Metropolis mode" of the background generator: builds a seeded, reproducible
3D city (street canyon converging on a landmark cathedral, layered skyline) and
renders a flat-gray *lineart pass* with a tiny software rasterizer — no GPU, no
browser, no 3D engine. The render is only a composition skeleton: its Canny edge
map drives ControlNet, and the checkpoint paints all the beauty on top.

Because the city is deterministic per seed, the same city can be re-rendered
from any camera for structurally consistent giant panels (and, later, camera
paths for animation).

Pipeline:  build_city(seed) -> render_lineart(camera) -> sketch (Canny)
"""

import math
import os

import numpy as np
import cv2


# ---------------------------------------------------------------- RNG (LCG) --
class _Rng:
    """Deterministic park-miller LCG so a city is reproducible per seed."""
    def __init__(self, seed: int):
        self.s = (int(seed) % 2147483647) or 42

    def rand(self) -> float:
        self.s = (self.s * 16807) % 2147483647
        return (self.s - 1) / 2147483646

    def rr(self, a, b):
        return a + self.rand() * (b - a)

    def ri(self, a, b):
        return int(self.rr(a, b + 1))


# ------------------------------------------------------------------ geometry --
def _box(cx, base_y, cz, w, h, d):
    """Axis-aligned box: verts (8,3) + quad faces."""
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = base_y, base_y + h
    z0, z1 = cz - d / 2, cz + d / 2
    v = np.array([[x0,y0,z0],[x1,y0,z0],[x1,y0,z1],[x0,y0,z1],
                  [x0,y1,z0],[x1,y1,z0],[x1,y1,z1],[x0,y1,z1]], dtype=np.float64)
    f = [(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7),(4,5,6,7),(0,3,2,1)]
    return v, f


def _pyramid(cx, base_y, cz, w, h, d):
    """4-sided spire/roof: rectangular base + apex."""
    x0, x1 = cx - w / 2, cx + w / 2
    z0, z1 = cz - d / 2, cz + d / 2
    v = np.array([[x0,base_y,z0],[x1,base_y,z0],[x1,base_y,z1],[x0,base_y,z1],
                  [cx,base_y+h,cz]], dtype=np.float64)
    f = [(0,1,4),(1,2,4),(2,3,4),(3,0,4),(0,3,2,1)]
    return v, f


class _Mesh:
    __slots__ = ("v", "f", "grey")
    def __init__(self, v, f, grey):
        self.v, self.f, self.grey = v, f, grey


def _grey(i: int) -> int:
    """Distinct flat gray per mesh -> silhouette edges everywhere, no shading."""
    g = 0.15 + 0.65 * ((i * 2654435761) % 97) / 97
    return int(g * 255)


# ---------------------------------------------------------------- city model --
def build_city(seed: int = 40001):
    """Procedural city: flanked avenue -> landmark cathedral -> far skyline.
    Returns a list of _Mesh. Same seed = same city, forever."""
    meshes = []
    add = _adder(meshes)
    rng = _Rng(seed)
    _district_old_city(rng, add, (0.0, 0.0))
    return meshes


def _adder(meshes):
    """Appender that assigns each mesh its distinct flat gray."""
    def add(v, f):
        meshes.append(_Mesh(v, f, _grey(len(meshes))))
    return add


def _building(rng, add, x, z, tier):
    w, d = rng.rr(8, 22), rng.rr(8, 22)
    h = rng.rr(14, 42) * (1 + tier * 0.55)          # taller tiers = taller mass
    add(*_box(x, 0, z, w, h, d))
    add(*_pyramid(x, h, z, w * 0.72, rng.rr(4, 9), d * 0.72))       # gabled roof
    for _ in range(rng.ri(0, 2)):                                    # chimneys
        add(*_box(x + rng.rr(-w/3, w/3), h, z + rng.rr(-d/3, d/3),
                  1.2, rng.rr(3, 6), 1.2))
    if rng.rand() < 0.30:                                            # side tower
        tw, th = rng.rr(3, 6), h * rng.rr(1.25, 1.8)
        tx, tz = x + w/2 + tw/2 - 1, z + rng.rr(-d/3, d/3)
        add(*_box(tx, 0, tz, tw, th, tw))
        add(*_pyramid(tx, th, tz, tw * 0.8, rng.rr(8, 16), tw * 0.8))


def _cathedral(rng, add, x, z, s):
    add(*_box(x, 0, z, 26*s, 46*s, 60*s))                            # nave
    add(*_box(x, 46*s, z, 27*s, 8*s, 62*s))                          # roof block
    for sx in (-11*s, 11*s):                                         # twin towers
        add(*_box(x+sx, 0, z+34*s, 9*s, 78*s, 9*s))
        add(*_pyramid(x+sx, 78*s, z+34*s, 8.5*s, 30*s, 8.5*s))
    add(*_pyramid(x, 46*s, z-6*s, 6*s, 38*s, 6*s))                   # fleche


# ------------------------------------------------------------ district types --
def _district_old_city(rng, add, origin, rows=26, landmark=True):
    """The founding layout: flanked avenue converging on a cathedral + far skyline."""
    ox, oz = origin
    AVE = 26
    for row in range(rows):
        z = oz - 30 - row * 26 + rng.rr(-4, 4)
        tier = 0 if row < 6 else 1 if row < 14 else 2
        for side in (-1, 1):
            off = AVE/2 + rng.rr(4, 10)
            for _ in range(2 if tier == 0 else 3):
                _building(rng, add, ox + side * (off + rng.rr(0, 6)), z, tier)
                off += rng.rr(16, 30)
    if landmark:
        _cathedral(rng, add, ox + 6, oz - 560, 2.1)
    for _ in range(70):                                              # far skyline
        _building(rng, add, ox + rng.rr(-500, 500), oz + rng.rr(-620, -900), 2)


def _district_block(rng, add, origin, size=(220, 220), tier=0, density=1.0,
                    landmark=False):
    """A rectangular fill of buildings — the growable unit (neighborhood/district).
    origin is the block's near corner; buildings fill [-size] in z, [+size] in x."""
    ox, oz = origin
    w, d = size
    step = 34 / max(0.25, density)
    for gz in np.arange(oz - d, oz, step):
        for gx in np.arange(ox, ox + w, step):
            if rng.rand() < 0.85 * density:
                _building(rng, add, gx + rng.rr(-6, 6), gz + rng.rr(-6, 6), tier)
    if landmark:
        _cathedral(rng, add, ox + w/2, oz - d/2, rng.rr(1.3, 1.9))


DISTRICT_TYPES = {"old_city": _district_old_city, "block": _district_block}


def build_from_plan(plan: dict):
    """Assemble the whole persistent city from its plan (the editable master file).

    The plan is the World Builder's growable 3D model: a JSON list of districts,
    each with its own seed, position and parameters. Appending a district grows
    the city; every earlier district re-renders identically because each has its
    own RNG stream. Returns a list of _Mesh."""
    meshes = []
    add = _adder(meshes)
    for d in plan.get("districts", []):
        kind = d.get("type", "block")
        if kind not in DISTRICT_TYPES:
            raise ValueError(f"unknown district type '{kind}'; options: {', '.join(DISTRICT_TYPES)}")
        rng = _Rng(d.get("seed", 1))
        origin = tuple(d.get("origin", (0, 0)))
        if kind == "old_city":
            _district_old_city(rng, add, origin,
                               rows=int(d.get("rows", 26)),
                               landmark=bool(d.get("landmark", True)))
        else:
            _district_block(rng, add, origin,
                            size=tuple(d.get("size", (220, 220))),
                            tier=int(d.get("tier", 0)),
                            density=float(d.get("density", 1.0)),
                            landmark=bool(d.get("landmark", False)))
    return meshes


def plan_centroid(plan: dict, focus: str | None = None):
    """A point worth looking at: a named district's center, or the plan centroid."""
    ds = plan.get("districts", [])
    if not ds:
        return (0.0, -400.0)
    if focus:
        for d in ds:
            if d.get("id") == focus:
                ox, oz = d.get("origin", (0, 0))
                if d.get("type", "block") == "old_city":
                    return (ox, oz - 400.0)          # mid-avenue, toward the cathedral
                w, dd = d.get("size", (220, 220))
                return (ox + w / 2, oz - dd / 2)
        raise ValueError(f"no district with id '{focus}' in the plan")
    pts = []
    for d in ds:
        ox, oz = d.get("origin", (0, 0))
        pts.append((ox, oz - 300.0))
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


# ------------------------------------------------------------------- cameras --
CAMERAS = {
    "street": {"pos": (0, 9, 30),     "look": (0, 26, -560),  "fov": 58},
    "vista":  {"pos": (-90, 70, -40), "look": (6, 40, -560),  "fov": 50},
    "high":   {"pos": (0, 150, 120),  "look": (0, 20, -500),  "fov": 48},
    "canyon": {"pos": (26, 5, -120),  "look": (-40, 60, -420), "fov": 65},
}

# Preset geometry expressed relative to a focus point, so the same four shot
# types work anywhere in a growing city: (pos - look) delta, look height, fov.
_CAM_REL = {
    "street": {"delta": (0, -17, 590),   "look_y": 26, "fov": 58},
    "vista":  {"delta": (-96, 30, 520),  "look_y": 40, "fov": 50},
    "high":   {"delta": (0, 130, 620),   "look_y": 20, "fov": 48},
    "canyon": {"delta": (66, -55, 300),  "look_y": 60, "fov": 65},
}


def camera_for(preset: str, focus) -> dict:
    """Build an absolute camera from a relative preset aimed at `focus` (x, z)."""
    if preset not in _CAM_REL:
        raise ValueError(f"unknown camera '{preset}'; options: {', '.join(_CAM_REL)}")
    c = _CAM_REL[preset]
    fx, fz = focus
    look = (fx, c["look_y"], fz)
    d = c["delta"]
    return {"pos": (fx + d[0], c["look_y"] + d[1], fz + d[2]),
            "look": look, "fov": c["fov"]}


# ---------------------------------------------------------------- rasterizer --
# One world unit ≈ 0.37 m (buildings are 14-42 units ≈ 4-12 stories), so a
# standing adult is ~4.6 units tall. Used by the character anchor.
HUMAN_HEIGHT = 4.6


def _resolve_cam(camera):
    return CAMERAS[camera] if isinstance(camera, str) else camera


def _cam_basis(cam, width, height):
    pos = np.array(cam["pos"], dtype=np.float64)
    look = np.array(cam["look"], dtype=np.float64)
    fwd = look - pos
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, np.array([0.0, 1.0, 0.0]))
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    focal = (height / 2) / math.tan(math.radians(cam["fov"]) / 2)
    return pos, right, up, fwd, focal


def _ground(pos):
    """Ground plane quad, ending just before the camera so it never straddles near."""
    gz = pos[2] - 2
    gv = np.array([[-1500, 0, gz], [1500, 0, gz],
                   [1500, 0, -1500], [-1500, 0, -1500]], dtype=np.float64)
    return gv, [(0, 1, 2, 3)]


def _rasterize(draw, cam, width, height, near, background):
    """Painter's-algorithm flat fill: draw = [(verts, faces, value), ...]."""
    pos, right, up, fwd, focal = _cam_basis(cam, width, height)
    img = np.full((height, width), background, dtype=np.uint8)
    faces = []  # (mean_depth, pts2d, value)
    for verts, flist, val in draw:
        rel = verts - pos
        vc = np.stack([rel @ right, rel @ up, rel @ fwd], axis=1)  # camera space
        for face in flist:
            fv = vc[list(face)]
            if np.any(fv[:, 2] < near):        # crude near-clip: drop the face
                continue
            sx = width / 2 + focal * fv[:, 0] / fv[:, 2]
            sy = height / 2 - focal * fv[:, 1] / fv[:, 2]
            if (np.all(sx < 0) or np.all(sx >= width) or
                    np.all(sy < 0) or np.all(sy >= height)):
                continue
            pts = np.stack([sx, sy], axis=1).astype(np.int32)
            faces.append((float(fv[:, 2].mean()), pts, val))
    faces.sort(key=lambda t: -t[0])            # painter: far -> near
    for _, pts, val in faces:
        cv2.fillConvexPoly(img, pts, int(val))
    return img


def render_lineart(meshes, camera="vista", width=1344, height=732,
                   near=0.5) -> np.ndarray:
    """Flat-gray painter's-algorithm render on white — the lineart pass.
    Good enough for Canny; not a beauty render (SD supplies the beauty)."""
    cam = _resolve_cam(camera)
    gv, gf = _ground(np.array(cam["pos"], dtype=np.float64))
    draw = [(gv, gf, 110)] + [(m.v, m.f, m.grey) for m in meshes]
    return _rasterize(draw, cam, width, height, near, 255)


def render_anchor(meshes, camera, anchor_x, anchor_z, width=1344, height=732,
                  anchor_height=HUMAN_HEIGHT, near=0.5):
    """Character placement anchor: a human-scale box at (anchor_x, anchor_z),
    rendered through the same camera WITH occlusion by the city.

    Returns (mask, info): mask is a uint8 image — white where the character
    stands, black elsewhere (buildings in front of the spot occlude it); info
    reports the anchor's on-screen bounding box and pixel height so the artist
    knows exactly how large to draw the character and where the feet sit."""
    cam = _resolve_cam(camera)
    av, af = _box(anchor_x, 0, anchor_z,
                  anchor_height * 0.35, anchor_height, anchor_height * 0.22)
    gv, gf = _ground(np.array(cam["pos"], dtype=np.float64))
    draw = ([(gv, gf, 0)] + [(m.v, m.f, 0) for m in meshes] + [(av, af, 255)])
    mask = _rasterize(draw, cam, width, height, near, 0)

    # unoccluded screen bbox of the anchor (where the character *would* be)
    pos, right, up, fwd, focal = _cam_basis(cam, width, height)
    rel = av - pos
    vc = np.stack([rel @ right, rel @ up, rel @ fwd], axis=1)
    info = None
    if np.all(vc[:, 2] >= near):
        sx = width / 2 + focal * vc[:, 0] / vc[:, 2]
        sy = height / 2 - focal * vc[:, 1] / vc[:, 2]
        info = {"bbox": (float(sx.min()), float(sy.min()),
                         float(sx.max()), float(sy.max())),
                "height_px": float(sy.max() - sy.min()),
                "feet_y_px": float(sy.max()),
                "visible": bool(mask.max() > 0)}
    return mask, info


# ------------------------------------------------------------------ pipeline --
def city_sketch(out_dir: str, city_seed: int = 40001, camera: str = "vista",
                width: int = 1344, height: int = 732,
                low: int = 60, high: int = 140,
                meshes=None, tag: str | None = None) -> tuple[str, str]:
    """Build city -> render lineart -> Canny sketch. Returns (sketch, lineart).
    Pass `meshes` (e.g. from build_from_plan) to render a persistent plan city
    instead of the one-shot seeded city."""
    if isinstance(camera, str) and camera not in CAMERAS:
        raise ValueError(f"unknown camera '{camera}'; options: {', '.join(CAMERAS)}")
    os.makedirs(out_dir, exist_ok=True)
    if meshes is None:
        meshes = build_city(city_seed)
    lineart = render_lineart(meshes, camera, width, height)

    cam_name = camera if isinstance(camera, str) else "custom"
    stem = tag or f"city_{city_seed}"
    line_path = os.path.join(out_dir, f"{stem}_{cam_name}_lineart.png")
    cv2.imwrite(line_path, lineart)

    blurred = cv2.GaussianBlur(lineart, (3, 3), 0)
    edges = cv2.Canny(blurred, low, high)
    sketch_path = os.path.join(out_dir, f"{stem}_{cam_name}_sketch.png")
    cv2.imwrite(sketch_path, edges)
    return sketch_path, line_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=40001)
    ap.add_argument("--camera", default="vista", choices=list(CAMERAS))
    ap.add_argument("--out", default="output/city")
    a = ap.parse_args()
    s, l = city_sketch(a.out, a.seed, a.camera)
    print("sketch: ", s)
    print("lineart:", l)
