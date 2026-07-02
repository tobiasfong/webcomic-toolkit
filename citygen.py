"""
citygen.py — procedural 3D gothic city, rendered headless to a ControlNet sketch.

The "Metropolis mode" of the background generator: builds a seeded, reproducible
3D city (street canyon converging on a landmark cathedral, layered skyline) and
renders a flat-grey *lineart pass* with a tiny software rasterizer — no GPU, no
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
    """Distinct flat grey per mesh -> silhouette edges everywhere, no shading."""
    g = 0.15 + 0.65 * ((i * 2654435761) % 97) / 97
    return int(g * 255)


# ---------------------------------------------------------------- city model --
def build_city(seed: int = 40001):
    """Procedural city: flanked avenue -> landmark cathedral -> far skyline.
    Returns a list of _Mesh. Same seed = same city, forever."""
    rng = _Rng(seed)
    meshes = []
    mi = [0]

    def add(v, f):
        meshes.append(_Mesh(v, f, _grey(mi[0])))
        mi[0] += 1

    def building(x, z, tier):
        w, d = rng.rr(8, 22), rng.rr(8, 22)
        h = rng.rr(14, 42) * (1 + tier * 0.55)      # taller further back
        add(*_box(x, 0, z, w, h, d))
        add(*_pyramid(x, h, z, w * 0.72, rng.rr(4, 9), d * 0.72))   # gabled roof
        for _ in range(rng.ri(0, 2)):                                # chimneys
            cw = 1.2
            add(*_box(x + rng.rr(-w/3, w/3), h, z + rng.rr(-d/3, d/3),
                      cw, rng.rr(3, 6), cw))
        if rng.rand() < 0.30:                                        # side tower
            tw, th = rng.rr(3, 6), h * rng.rr(1.25, 1.8)
            tx, tz = x + w/2 + tw/2 - 1, z + rng.rr(-d/3, d/3)
            add(*_box(tx, 0, tz, tw, th, tw))
            add(*_pyramid(tx, th, tz, tw * 0.8, rng.rr(8, 16), tw * 0.8))

    def cathedral(x, z, s):
        add(*_box(x, 0, z, 26*s, 46*s, 60*s))                        # nave
        add(*_box(x, 46*s, z, 27*s, 8*s, 62*s))                      # roof block
        for sx in (-11*s, 11*s):                                     # twin towers
            add(*_box(x+sx, 0, z+34*s, 9*s, 78*s, 9*s))
            add(*_pyramid(x+sx, 78*s, z+34*s, 8.5*s, 30*s, 8.5*s))
        add(*_pyramid(x, 46*s, z-6*s, 6*s, 38*s, 6*s))               # fleche

    # flanked avenue, denser + taller with distance
    AVE = 26
    for row in range(26):
        z = -30 - row * 26 + rng.rr(-4, 4)
        tier = 0 if row < 6 else 1 if row < 14 else 2
        for side in (-1, 1):
            off = AVE/2 + rng.rr(4, 10)
            for _ in range(2 if tier == 0 else 3):
                building(side * (off + rng.rr(0, 6)), z, tier)
                off += rng.rr(16, 30)

    cathedral(6, -560, 2.1)                                          # landmark

    for _ in range(70):                                              # far skyline
        building(rng.rr(-500, 500), rng.rr(-620, -900), 2)

    return meshes


# ------------------------------------------------------------------- cameras --
CAMERAS = {
    "street": {"pos": (0, 9, 30),     "look": (0, 26, -560),  "fov": 58},
    "vista":  {"pos": (-90, 70, -40), "look": (6, 40, -560),  "fov": 50},
    "high":   {"pos": (0, 150, 120),  "look": (0, 20, -500),  "fov": 48},
    "canyon": {"pos": (26, 5, -120),  "look": (-40, 60, -420), "fov": 65},
}


# ---------------------------------------------------------------- rasterizer --
def render_lineart(meshes, camera="vista", width=1344, height=732,
                   near=0.5) -> np.ndarray:
    """Flat-grey painter's-algorithm render on white — the lineart pass.
    Good enough for Canny; not a beauty render (SD supplies the beauty)."""
    cam = CAMERAS[camera] if isinstance(camera, str) else camera
    pos = np.array(cam["pos"], dtype=np.float64)
    look = np.array(cam["look"], dtype=np.float64)

    fwd = look - pos
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, np.array([0.0, 1.0, 0.0]))
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    focal = (height / 2) / math.tan(math.radians(cam["fov"]) / 2)

    img = np.full((height, width), 255, dtype=np.uint8)

    # ground plane (ends just before the camera so it never straddles near)
    gz = pos[2] - 2
    gv = np.array([[-1500, 0, gz], [1500, 0, gz],
                   [1500, 0, -1500], [-1500, 0, -1500]], dtype=np.float64)
    draw = [(gv, [(0, 1, 2, 3)], 110)]
    draw += [(m.v, m.f, m.grey) for m in meshes]

    faces = []  # (mean_depth, pts2d, grey)
    for verts, flist, grey in draw:
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
            faces.append((float(fv[:, 2].mean()), pts, grey))

    faces.sort(key=lambda t: -t[0])            # painter: far -> near
    for _, pts, grey in faces:
        cv2.fillConvexPoly(img, pts, int(grey))
    return img


# ------------------------------------------------------------------ pipeline --
def city_sketch(out_dir: str, city_seed: int = 40001, camera: str = "vista",
                width: int = 1344, height: int = 732,
                low: int = 60, high: int = 140) -> tuple[str, str]:
    """Build city -> render lineart -> Canny sketch. Returns (sketch, lineart)."""
    if isinstance(camera, str) and camera not in CAMERAS:
        raise ValueError(f"unknown camera '{camera}'; options: {', '.join(CAMERAS)}")
    os.makedirs(out_dir, exist_ok=True)
    meshes = build_city(city_seed)
    lineart = render_lineart(meshes, camera, width, height)

    cam_name = camera if isinstance(camera, str) else "custom"
    line_path = os.path.join(out_dir, f"city_{city_seed}_{cam_name}_lineart.png")
    cv2.imwrite(line_path, lineart)

    blurred = cv2.GaussianBlur(lineart, (3, 3), 0)
    edges = cv2.Canny(blurred, low, high)
    sketch_path = os.path.join(out_dir, f"city_{city_seed}_{cam_name}_sketch.png")
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
