"""FLUX 3 Image Klein -- the character server's default model since 2026-10-17.

It runs on its OWN ComfyUI (v0.41, port 8189), not the main one (v0.25.1, port
8188). The main install carries LTX, the music model and the matting model
through add-ons that were never tested on v0.41, and upgrading it in place
would risk all three to gain nothing Klein needs. Matting therefore still goes
to the main ComfyUI through comfy.matte(); only generation comes here.

Graphs follow v0.41's own image_flux3_klein_distilled_* templates: the
step-distilled INT8 model (the GeForce build -- Ampere has INT8 tensor cores
but no native FP8), the Qwen3-VL 4B INT8 text encoder, the flux2 VAE, cfg 1,
15 steps for text-to-image and 16 with references. The template's prompt
upsampler is left OFF: it rewrites the prompt before generation, and the
prompting rules in AGENTS.md only hold for the prompt that was written.

What Klein changes, all measured 2026-10-17 (AGENTS.md has the detail):
  * Multi-reference HOLDS identity through a pose change -- two characters in
    one render, re-posed, with no attribute bleed, on 3 of 3 seeds. FLUX.1's
    rule of one reference per generation does not apply here.
  * But when the prompt asks for the pose a reference already shows, Klein
    COPIES the reference, flaws included.
  * Layout boxes place objects precisely (98% of a placed effect inside its
    box) and set their SIZE too -- an oversized box gives an oversized hand.
    They do not decide which side of a hand a thumb grows on.
  * Even a boxed edit redraws the whole frame (18.5 of mean change outside
    the box). edit_region() makes it local by pasting back only the region.
  * FLUX.1 LoRAs cannot load: 0 of manwha_style's 494 layers exist here.
"""
import io
import json
import os
import subprocess
import time
import uuid

import numpy as np
import requests
from PIL import Image, ImageFilter

KLEIN_URL = os.environ.get("WEBCOMIC_CHAR_KLEIN_URL", "http://127.0.0.1:8189")
KLEIN_DIR = os.environ.get("WEBCOMIC_CHAR_KLEIN_DIR", r"C:\AI\ComfyUI_flux3")
KLEIN_PORT = KLEIN_URL.rsplit(":", 1)[-1].split("/")[0]
LAUNCH_TIMEOUT = int(os.environ.get("WEBCOMIC_CHAR_KLEIN_LAUNCH_TIMEOUT", "180"))

MODEL = os.environ.get("WEBCOMIC_CHAR_KLEIN_MODEL", "flux3_image_klein_sd_int8_convrot.safetensors")
TEXT_ENCODER = os.environ.get("WEBCOMIC_CHAR_KLEIN_TE", "qwen3vl_4b_int8_convrot.safetensors")
VAE = os.environ.get("WEBCOMIC_CHAR_KLEIN_VAE", "flux2-vae.safetensors")

# The style tail every Klein render in the 2026-10-17 evaluation used. It is
# stated as positives on purpose -- see "Never write soft" in AGENTS.md.
STYLE = ("Manhwa illustration, crisp black outlines and hard-edged flat color, "
         "every edge in sharp focus.")


class KleinError(RuntimeError):
    pass


def is_up(timeout: float = 2.0) -> bool:
    try:
        return requests.get(f"{KLEIN_URL}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


def ensure_running() -> None:
    """Start the Klein ComfyUI if it is not up.

    Launches the embedded interpreter directly with the working directory set,
    the way AGENTS.md says ComfyUI must be launched on this machine -- the
    portable .bat uses relative paths and fails silently from anywhere else.
    Output goes to a log beside the install, because a crash here otherwise
    leaves no trace at all.
    """
    if is_up():
        return
    py = os.path.join(KLEIN_DIR, "python_embeded", "python.exe")
    if not os.path.isfile(py):
        raise KleinError(f"Klein ComfyUI not found at {KLEIN_DIR} (set WEBCOMIC_CHAR_KLEIN_DIR).")
    log = open(os.path.join(KLEIN_DIR, "comfy_klein.log"), "ab")
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    subprocess.Popen([py, "-s", "ComfyUI/main.py", "--windows-standalone-build", "--port", KLEIN_PORT],
                     cwd=KLEIN_DIR, creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=log, stderr=log, close_fds=True)
    t0 = time.time()
    while time.time() - t0 < LAUNCH_TIMEOUT:
        time.sleep(2.0)
        if is_up():
            return
    raise KleinError(f"Launched Klein ComfyUI but it was not ready within {LAUNCH_TIMEOUT}s; "
                     f"see {os.path.join(KLEIN_DIR, 'comfy_klein.log')}.")


def _upload(path: str) -> str:
    if not os.path.isfile(path):
        raise KleinError(f"Image not found: {path}")
    with open(path, "rb") as f:
        r = requests.post(f"{KLEIN_URL}/upload/image",
                          files={"image": (f"{uuid.uuid4().hex[:8]}_{os.path.basename(path)}", f,
                                           "application/octet-stream")},
                          data={"overwrite": "true"}, timeout=60)
    if r.status_code != 200:
        raise KleinError(f"Upload failed ({r.status_code}): {r.text[:200]}")
    return r.json()["name"]


def _submit(graph: dict, output_node: str, timeout: int) -> bytes:
    # The timeout counts QUEUE time as well as rendering, same as the main
    # server's _submit_and_wait -- keep jobs serial (AGENTS.md, Practical).
    r = requests.post(f"{KLEIN_URL}/prompt", json={"prompt": graph}, timeout=30)
    if r.status_code != 200:
        raise KleinError(f"Prompt rejected ({r.status_code}): {r.text[:400]}")
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2.0)
        h = requests.get(f"{KLEIN_URL}/history/{pid}", timeout=30).json()
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                raise KleinError("Render failed: " + json.dumps(st.get("messages", []))[:800])
            outs = h[pid].get("outputs", {})
            if output_node not in outs:
                raise KleinError("Render produced no image (check comfy_klein.log).")
            img = outs[output_node]["images"][0]
            return requests.get(f"{KLEIN_URL}/view", timeout=60, params={
                "filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]}).content
    raise KleinError(f"Timed out after {timeout}s")


def _save(data: bytes, out_dir: str, stem: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, stem)
    path, n = base + ".png", 1
    while os.path.exists(path):
        path, n = f"{base}_{n}.png", n + 1
    with open(path, "wb") as f:
        f.write(data)
    return path


def _snap(v: int) -> int:
    return max(16, int(round(v / 16.0)) * 16)


def layout(prompt: str, boxes, width: int, height: int) -> str:
    """Append a layout table the way ComfyUI's Flux3LayoutPrompt does.

    boxes: [(description, (x0, y0, x1, y1)), ...] in PIXELS of the output
    canvas -- the same convention as edit_image's mask_box. Converted to the
    [ymin, xmin, ymax, xmax] 0-1000 rows the model was trained on. Cite box N in
    the prompt as <obj_N> to tie words to it.

    A box sets an object's SIZE as well as its place: a hand asked to fill a
    220x166 box came back 220x166. Size boxes to what should be drawn.
    """
    rows = []
    for i, (desc, (x0, y0, x1, y1)) in enumerate(boxes):
        rows.append({"id": f"obj_{i + 1}", "desc": desc, "bbox": [
            round(min(y0, y1) / height * 1000), round(min(x0, x1) / width * 1000),
            round(max(y0, y1) / height * 1000), round(max(x0, x1) / width * 1000)]})
    return f"{prompt.rstrip()} {json.dumps(rows, ensure_ascii=False)}" if rows else prompt


def generate(prompt: str, out_dir: str, width: int = 832, height: int = 1216,
             seed: int | None = None, refs: list[str] | None = None, boxes=None,
             megapixels: float = 1.0, steps: int | None = None, stem: str = "klein",
             add_style: bool = True, timeout: int = 900) -> str:
    """Render with Klein; return the saved PNG path.

    refs: reference images, referred to in the prompt as "image 1", "image 2"
        in the order given. Each is encoded at `megapixels` (1.0 is about
        1024x1024, aspect kept). Identity comes from these; the description in
        the prompt still matters -- resolve it from the bible, never retype it.
    boxes: optional layout boxes, see layout().
    """
    ensure_running()
    width, height = _snap(width), _snap(height)
    if seed is None:
        seed = uuid.uuid4().int % (2 ** 31)
    text = f"{prompt.rstrip()} {STYLE}" if add_style else prompt
    if boxes:
        text = layout(text, boxes, width, height)
    refs = refs or []
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "flux3", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "klein_" + stem}},
    }
    pos, neg = ["4", 0], ["5", 0]
    if refs:
        ri = {"positive": ["4", 0], "negative": ["5", 0], "vae": ["3", 0],
              "resolution": "resize", "resolution.megapixels": float(megapixels)}
        for i, r in enumerate(refs, 1):
            g[str(20 + i)] = {"class_type": "LoadImage", "inputs": {"image": _upload(r)}}
            ri[f"images.image{i}"] = [str(20 + i), 0]
        g["7"] = {"class_type": "ReferenceMultiLatent", "inputs": ri}
        pos, neg = ["7", 0], ["7", 1]
    g["8"] = {"class_type": "KSampler", "inputs": {
        "model": ["1", 0], "seed": seed, "steps": steps or (16 if refs else 15), "cfg": 1.0,
        "sampler_name": "euler" if refs else "er_sde", "scheduler": "simple",
        "positive": pos, "negative": neg, "latent_image": ["6", 0], "denoise": 1.0}}
    return _save(_submit(g, "10", timeout), out_dir, f"{stem}_{seed}")


def edit_region(image_path: str, instruction: str, out_dir: str, box, seed: int | None = None,
                feather: int = 14, pad: int = 24, erase: bool = False, timeout: int = 900) -> str:
    """Redraw one region of an existing image, leaving every other pixel as it was.

    box: (x0, y0, x1, y1) in the source image's pixels -- what to redraw, and
        how big the new thing should be. Klein redraws the whole frame from the
        source as a reference, then only `box` (grown by `pad`, edges feathered)
        is composited back, so the change outside it is exactly zero.

    erase: fill the box with the color around it first, so the model cannot
        build on what is there. That is what fixed a wrong hand on a pale floor
        -- but on a dark textured floor the flat patch was read as the new
        hand's SILHOUETTE and filled as a flat cutout. Default off; when a
        stubborn defect survives, reroll the whole render instead of patching.
    """
    src = Image.open(image_path).convert("RGB")
    W, H = src.size
    x0, y0, x1, y1 = [int(v) for v in box]
    work = src
    if erase:
        a = np.asarray(src).astype(np.float32)
        ring = np.concatenate([a[max(0, y0 - 12):y0, x0:x1].reshape(-1, 3),
                               a[y1:min(H, y1 + 12), x0:x1].reshape(-1, 3),
                               a[y0:y1, max(0, x0 - 12):x0].reshape(-1, 3),
                               a[y0:y1, x1:min(W, x1 + 12)].reshape(-1, 3)])
        a[y0:y1, x0:x1] = np.median(ring, 0)
        work = Image.fromarray(a.clip(0, 255).astype(np.uint8))
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, f"_klein_region_src_{uuid.uuid4().hex[:8]}.png")
    work.save(tmp)
    try:
        raw = generate(f"{instruction.rstrip()} Keep everything else in the picture exactly as it is.",
                       out_dir, W, H, seed=seed, refs=[tmp], megapixels=W * H / (1024 * 1024),
                       boxes=[("the region to redraw", (x0, y0, x1, y1))], stem="klein_region_raw",
                       add_style=False, timeout=timeout)
    finally:
        os.remove(tmp)
    new = Image.open(raw).convert("RGB").resize((W, H), Image.LANCZOS)
    m = Image.new("L", (W, H), 0)
    m.paste(255, (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)))
    m = m.filter(ImageFilter.GaussianBlur(feather))
    # Feather onto the WORKING image: blending the edge against the original
    # let the old fingertips show through the new ones as ghosts.
    out = Image.composite(new, work, m)
    os.remove(raw)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return _save(_png(out), out_dir, f"{stem}_region")


def clean_matte(raw_path: str, rgba_path: str, tol: float = 26.0) -> str:
    """Remove the pale backdrop the matting model leaves along a Klein figure's edge.

    The learned matte keeps slivers of backdrop as OPAQUE pixels between hair
    strands and along the outline, which read as a white halo over anything
    darker. Un-premultiplying against the backdrop cannot fix that -- it trusts
    the matte's alpha, and the alpha is what is wrong (tried: it turned the
    flecks into a pale glow).

    What separates them is the art style: Klein draws a crisp black outline
    round everything, on a flat backdrop. So the backdrop is flood-filled from
    the frame edge through backdrop-colored pixels, which stops dead at the ink
    line; the pixels just outside it get their alpha from how much ink they
    hold; and the learned matte stays responsible for enclosed gaps (between an
    arm and the body) that the flood cannot reach. Measured: the brightness of
    the outermost 2 px fell from 51 to 19 and from 30 to 15 -- the ink itself.

    Overwrites rgba_path and returns it.
    """
    raw = np.asarray(Image.open(raw_path).convert("RGB")).astype(np.float32)
    al = np.asarray(Image.open(rgba_path).convert("RGBA"))[..., 3].astype(np.float32) / 255.0
    if raw.shape[:2] != al.shape:
        return rgba_path
    from scipy import ndimage
    border = np.concatenate([raw[:6].reshape(-1, 3), raw[-6:].reshape(-1, 3),
                             raw[:, :6].reshape(-1, 3), raw[:, -6:].reshape(-1, 3)])
    B = np.median(border, 0)
    near_bg = np.linalg.norm(raw - B, axis=2) < tol
    lab, _ = ndimage.label(near_bg)
    edges = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    outside = np.isin(lab, edges[edges > 0])
    lumB, ink = B.mean(), 25.0
    a_ink = np.clip((lumB - raw.mean(2)) / (lumB - ink), 0, 1)
    ring = ndimage.binary_dilation(outside, iterations=2) & ~outside
    outer = np.ones_like(al)
    outer[outside] = 0.0
    outer[ring] = a_ink[ring]
    a = np.minimum(al, outer)
    F = raw.copy()
    e = (a > 0.02) & (a < 0.98)
    a3 = np.clip(a, 1e-3, 1)[..., None]
    F[e] = ((raw - (1 - a3) * B) / a3)[e]          # color now consistent with the corrected alpha
    Image.fromarray(np.dstack([F.clip(0, 255), a * 255]).astype(np.uint8), "RGBA").save(rgba_path)
    return rgba_path


# Expression wordings, 2026-10-17. Deliberately SMALL: a first pass asking for
# "cheeks raised" and "mouth dropped open" came back "way too cartoonish". The
# keys are the names the game already uses -- do not add new ones without the
# author, or every expression has to be rewired in the game.
EXPRESSIONS = {
    "smile": "a small closed-mouth smile, the corners of the mouth lifted only slightly",
    "anger": "a slight scowl: the brows drawn together, the corners of the mouth turned down a "
             "little, the mouth small and tight",
    # untested -- the game has one laugh body; review it before keeping
    "laugh": "a light laugh: the mouth open in a small happy smile, the eyes a little narrowed "
             "by it",
}


def paste_face(base_rgba_path: str, candidate_path: str, out_path: str, face_box) -> dict:
    """Paste ONLY the face of a candidate render onto the base body.

    NOT how the visual novel makes expressions. The author's rule (2026-10-17):
    "Body can move" -- an expression is a whole new body, rendered from scratch
    (generate_expression). Kept for a case where a body truly must not move,
    and because existing scripts call it.

    The candidate is a whole new render with the expression drawn in context --
    which is why it follows the head's tilt on its own. But even the closest
    candidate moves the body a little (a mean of 0.5 to 3 out of 255), and a
    sprite that shifts when its face swaps visibly jumps. So only the face is
    taken; every other pixel, and the alpha, stays the base's.

    Returns {"path", "changed_outside_face", "alpha_identical"}.
    """
    base = Image.open(base_rgba_path).convert("RGBA")
    ba = np.asarray(base).astype(np.float32)
    cand = Image.open(candidate_path).convert("RGB").resize(base.size, Image.LANCZOS)
    x0, y0, x1, y1 = [int(v) for v in face_box]
    m = Image.new("L", base.size, 0)
    m.paste(255, (x0 - 3, y0 - 3, x1 + 3, y1 + 3))
    mf = np.asarray(m.filter(ImageFilter.GaussianBlur(4)), np.float32)[..., None] / 255.0
    rgb = ba[..., :3] * (1 - mf) + np.asarray(cand, np.float32) * mf
    out = np.dstack([rgb.round(), ba[..., 3]]).clip(0, 255).astype(np.uint8)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    Image.fromarray(out, "RGBA").save(out_path)
    diff = np.abs(out.astype(np.int32) - ba.astype(np.int32)).max(2)
    return {"path": out_path,
            "changed_outside_face": int((diff[~(mf[..., 0] > 0)] > 0).sum()),
            "alpha_identical": bool((out[..., 3] == ba[..., 3]).all())}


def find_face_box(body_path: str) -> tuple[int, int, int, int]:
    """A first guess at the face: skin in the top fifth of the figure, its height
    capped near its width so the neck is not counted. It drifts when hair covers
    one side of the face -- pass an explicit face_box whenever you can."""
    a = np.asarray(Image.open(body_path).convert("RGBA")).astype(np.int32)
    al = a[..., 3] > 128
    ys, _ = np.nonzero(al)
    top, bottom = ys.min(), ys.max()
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    head = np.zeros_like(al)
    head[top:top + int((bottom - top) * 0.20)] = True
    skin = head & al & (r > 170) & (r - b > 25) & (g > 120) & (r - g < 60)
    sy, sx = np.nonzero(skin)
    if not len(sy):
        raise KleinError("No face found -- pass face_box explicitly.")
    x0, x1, y0 = int(sx.min()), int(sx.max()), int(sy.min())
    y1 = min(int(sy.max()), y0 + int((x1 - x0) * 1.3))
    return x0, y0, x1, y1


TURNAROUND_VIEWS = [
    ("front", "front view, facing the viewer"),
    ("three_quarter", "three-quarter view, turned to the left"),
    ("profile", "side profile, facing the left edge of the picture"),
    ("back", "back view, seen from directly behind"),
]


def turnaround_sheet(ref_path: str, description: str, out_dir: str, width: int = 2560,
                     height: int = 1024, seed: int | None = None, extra_prompt: str = "",
                     timeout: int = 900) -> tuple[str, dict[str, str]]:
    """Front, three-quarter, profile and back in ONE render, each view in its own box.

    Measured 2026-10-17: four separate figures, each wholly inside its box
    (0.0% of figure pixels outside all four), true views including a genuine
    profile -- the angle FLUX.1 sheets kept collapsing to near-front -- and no
    strangers. Because the boxes hold, every panel is cut out EXACTLY by its
    box; FLUX.1 sheets needed a gap search that kept slicing trailing hems.

    Panels go in a folder named after the sheet, never loose in _concepts/:
    several registered references point at files called panel_back.png.

    Returns (sheet_path, {view: panel_path}).
    """
    width, height = _snap(width), _snap(height)
    slot = int(width * 0.203)
    gap = (width - 4 * slot) // 5
    boxes, names = [], []
    for i, (name, view) in enumerate(TURNAROUND_VIEWS):
        x0 = gap + i * (slot + gap)
        boxes.append((f"the character from image 1, full body, {view}",
                      (x0, int(height * 0.04), x0 + slot, height - int(height * 0.03))))
        names.append(name)
    extra = f" {extra_prompt.strip()}" if extra_prompt.strip() else ""
    prompt = ("A character turnaround sheet: the character from image 1 shown four times, standing side "
              "by side in a row with clear empty space between the views, full body from head to feet in "
              "every view, on a plain flat pale gray backdrop: <obj_1>, <obj_2>, <obj_3>, <obj_4>. The "
              "same character in every view: " + description.rstrip(". ") + "." + extra + " Every view "
              "keeps the face, hair and costume of the reference image. Lit from the upper left.")
    sheet = generate(prompt, out_dir, width, height, seed=seed, refs=[ref_path], boxes=boxes,
                     stem="turnaround", timeout=timeout)
    panel_dir = os.path.splitext(sheet)[0]
    os.makedirs(panel_dir, exist_ok=True)
    im = Image.open(sheet)
    panels = {}
    for name, (_, (x0, y0, x1, y1)) in zip(names, boxes):
        p = os.path.join(panel_dir, f"panel_{name}.png")
        im.crop((x0, 0, x1, height)).save(p)
        panels[name] = p
    return sheet, panels


def _png(im: Image.Image) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def size_of(path: str) -> tuple[int, int]:
    return Image.open(path).size


def megapixels_of(path: str) -> float:
    w, h = size_of(path)
    return w * h / (1024 * 1024)


__all__ = ["KLEIN_URL", "STYLE", "KleinError", "is_up", "ensure_running", "layout",
           "generate", "edit_region", "clean_matte", "turnaround_sheet", "TURNAROUND_VIEWS",
           "paste_face", "EXPRESSIONS", "find_face_box",
           "megapixels_of"]
