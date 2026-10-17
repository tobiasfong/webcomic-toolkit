"""
klein_edit.py — edit an illustration or a video frame with FLUX 3 Image Klein.

Why this exists: LTX cannot animate eye- or mouth-scale features. Measured on
2026-08-05 — a blink is ~0.2% of frame pixels and roughly 4 latent pixels wide
after the VAE's 8x compression, so there is nothing there for it to move. No
seed and no prompt wording changes that. Blinks and mouth flaps therefore come
from generated KEYFRAMES (this script) played back by the frame player, not
from video generation. The same script repairs the hands LTX breaks.

Replaces kontext_edit.py (FLUX.1 Kontext), retired 2026-10-17.

Usage:
  # repair one region; only the box comes back, every other pixel untouched
  python klein_edit.py --image frame.png --out repairs \
      --edit "redraw her right hand as a clean fist wrapped around the hilt" \
      --box 560,290,710,400 --seeds 1,2,3

  # no box: the full redrawn frame, to composite a smaller region yourself
  # (pipeline.framing.composite_patch, e.g. just the eye interiors for a blink)
  python klein_edit.py --image panel.png --out keys --edit "close her eyes"

Needs Klein's own ComfyUI (v0.41+, default http://127.0.0.1:8189) with
flux3_image_klein_sd_int8_convrot, qwen3vl_4b_int8_convrot and flux2-vae from
BFL's flux-3-image-klein-comfy repo. INT8, not FP8: an Ampere card has INT8
tensor cores and no native FP8.

⚠ NEVER SHIP THE FULL FRAME. Klein redraws the WHOLE frame even for a boxed
edit (18.5 of mean change outside the box, measured). With --box this script
pastes back only the box; without one, composite the region yourself.

⚠ A BOX SETS SIZE AS WELL AS PLACE. A hand asked to fill a 220x166 box came
back 220x166 and swollen. Fit the box to the thing you want drawn.

⚠ NEVER RUN IT DURING AN LTX JOB. Klein and LTX sit on different ComfyUIs, so
neither queue orders them, and both models land on one small card at once. One
edit submitted during an LTX batch once thrashed until it hung, for five hours.

Measured on a damaged LTX frame (1920x1088, hand blurred to a smudge on a sword
hilt): ~97 s per seed on a 6 GB card, and exactly zero change outside the box.
Hands are still the weak point — expect to discard some seeds.
"""
import argparse, json, os, sys, time, uuid, urllib.error, urllib.parse, urllib.request

from PIL import Image, ImageFilter

HOST = os.environ.get("KLEIN_URL", "http://127.0.0.1:8189")
MODEL = "flux3_image_klein_sd_int8_convrot.safetensors"
TEXT_ENCODER = "qwen3vl_4b_int8_convrot.safetensors"
VAE = "flux2-vae.safetensors"


def busy(url):
    try:
        q = json.loads(urllib.request.urlopen(url + "/queue", timeout=3).read().decode())
    except Exception:
        return 0
    return len(q.get("queue_running", [])) + len(q.get("queue_pending", []))


def upload(path):
    """Push the image into Klein's input folder (multipart, stdlib only)."""
    name = f"{uuid.uuid4().hex[:8]}_{os.path.basename(path)}"
    bnd = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + \
           (f"\r\n--{bnd}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
            f"\r\n--{bnd}--\r\n").encode()
    req = urllib.request.Request(HOST + "/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())["name"]


def snap(v):
    return max(16, int(round(v / 16.0)) * 16)


def build(uploaded, text, w, h, seed, mp, steps):
    # ComfyUI v0.41's image_flux3_klein_distilled template with one reference:
    # cfg 1, euler. Its prompt upsampler is left OFF — it rewrites the prompt.
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "flux3", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "21": {"class_type": "LoadImage", "inputs": {"image": uploaded}},
        "7": {"class_type": "ReferenceMultiLatent", "inputs": {
            "positive": ["4", 0], "negative": ["5", 0], "vae": ["3", 0],
            "resolution": "resize", "resolution.megapixels": mp, "images.image1": ["21", 0]}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["6", 0], "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "klein_edit"}},
    }


def run(graph):
    req = urllib.request.Request(HOST + "/prompt", data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())["prompt_id"]
    except urllib.error.HTTPError as e:
        sys.exit("REJECTED:\n" + e.read().decode()[:2500])
    t0 = time.time()
    while time.time() - t0 < 1800:
        time.sleep(2)
        h = json.loads(urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=30).read().decode())
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                sys.exit("ERROR: " + json.dumps(st.get("messages", []))[:2000])
            img = h[pid]["outputs"]["10"]["images"][0]
            q = urllib.parse.urlencode({k: img[k] for k in ("filename", "subfolder", "type")})
            return urllib.request.urlopen(f"{HOST}/view?{q}", timeout=60).read()
    sys.exit("timed out")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True, help="path to the frame or illustration")
    p.add_argument("--edit", required=True, help="instruction, phrased positively")
    p.add_argument("--out", default="klein_edits", help="output folder")
    p.add_argument("--box", help="l,t,r,b of the region to change; only it comes back")
    p.add_argument("--seeds", default="1,2,3", help="comma-separated")
    p.add_argument("--steps", type=int, default=16)
    p.add_argument("--ltx-url", default="http://127.0.0.1:8188",
                   help="the LTX ComfyUI, checked so the two never run at once")
    a = p.parse_args()

    if busy(a.ltx_url):
        sys.exit(f"An LTX job is running on {a.ltx_url}. Wait for it: LTX and Klein "
                 f"cannot share a small card.")
    src = Image.open(a.image).convert("RGB")
    W, H = src.size
    text = f"Image 1 is the picture to edit. {a.edit.rstrip()} Keep everything else in the picture exactly as it is."
    box = [int(v) for v in a.box.split(",")] if a.box else None
    if box:
        x0, y0, x1, y1 = box
        row = {"id": "obj_1", "desc": "the region to redraw", "bbox": [
            round(y0 / H * 1000), round(x0 / W * 1000), round(y1 / H * 1000), round(x1 / W * 1000)]}
        text = f"{text} {json.dumps([row])}"

    os.makedirs(a.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.image))[0]
    uploaded = upload(a.image)
    print(f"klein: {a.image} {W}x{H} | box={box} | \"{a.edit}\"")
    for seed in [int(s) for s in a.seeds.split(",")]:
        t0 = time.time()
        raw = os.path.join(a.out, f"{stem}_edit_s{seed}_full.png")
        with open(raw, "wb") as f:
            f.write(run(build(uploaded, text, snap(W), snap(H), seed, W * H / (1024 * 1024), a.steps)))
        new = Image.open(raw).convert("RGB")
        if new.size != (W, H):
            # at most 15 px off from snapping to 16; the reference keeps the
            # source aspect, so a straight resize is the exact inverse
            new = new.resize((W, H), Image.LANCZOS)
            new.save(raw)
        out = raw
        if box:
            m = Image.new("L", (W, H), 0)
            m.paste(255, (max(0, x0 - 24), max(0, y0 - 24), min(W, x1 + 24), min(H, y1 + 24)))
            out = os.path.join(a.out, f"{stem}_edit_s{seed}.png")
            Image.composite(new, src, m.filter(ImageFilter.GaussianBlur(14))).save(out)
        print(f"  seed {seed}: {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
