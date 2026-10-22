"""
ltx_run.py — animate one illustration with LTX-2.5, image-to-video, locally.

Standalone driver for the skill: stdlib + Pillow only. The anime-production MCP
server's `animate_shot` does the same with a shot library and a seed hunt on
top; use that when you have it.

Usage:
  python ltx_run.py --image panel.png --out takes \
      --prompt "The camera holds locked off. She lowers her sword slowly. ..."
  python ltx_run.py --image panel.png --out takes --len 97 --seed 2 --prompt "..."
  # first-and-last-frame: panel -> a Klein-made END pose (boxed edit for hand-drawn art)
  python ltx_run.py --image panel.png --last end_pose.png --out takes --prompt "..."

Needs a ComfyUI of v0.32+ with LTX-2.5's official files (see ltx-setup.md and
fetch-ltx.sh). This project runs it on the same v0.41 ComfyUI as FLUX 3 Klein,
port 8189. No custom nodes.

Writes <stem>_s<seed>.webp (24 fps, every frame) and <stem>_s<seed>_12fps.webp
(every other frame, true speed on twos — judge from this one).

THE SETTINGS THAT MATTER, all measured on a 6 GB RTX 3060 Laptop, 32 GB RAM:
  * 24 fps and 49 (2 s) or 97 (4 s) frames. NEVER 17: with three latent frames
    every take sat still to frame 8, lurched at frame 9 and tore faces.
  * Size from the ARTWORK'S OWN SHAPE at ~2 MP (the default here). The model
    stretches the input to whatever size it is given, with no letterboxing.
  * ~3.5 min a 49-frame take, ~7 min a 97. The first take of a session loads
    ~37 GB of weights and is slower.
  * Prompt for MOTION ONLY: camera first, the motion, then what stays still,
    4-8 sentences, positive phrasing. "Blink" became eyes closed for good on
    three seeds; "her eyes close, then open wide, then close again" blinked.

⚠ NEVER RUN IT WHILE ANOTHER BIG MODEL IS ON THE CARD. It refuses while the
other ComfyUI (--other-url, the music/matting install here) is busy, and asks
that idle one to unload: an idle ComfyUI still holds its model in system RAM,
and one take with another model resident took 694 s instead of 176 s.
"""
import argparse, io, json, os, sys, time, uuid, urllib.error, urllib.parse, urllib.request

from PIL import Image, ImageSequence

MODEL = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
TEXT_ENCODER = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
VAE = "ltx-2.5-video-vae-bf16.safetensors"
AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"
UPSCALER = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
REF_LONG_SIDE = 1536      # the template's reference-image resize
SIGMAS_1 = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
SIGMAS_2 = "0.85, 0.7250, 0.4219, 0.0"
LEAD = "Use the provided start image as the first frame. "


def pick_size(w, h, target=2_200_000, align=64, max_dim=1920):
    """Largest size at the art's own aspect near `target` pixels, both sides /64."""
    aspect = w / h
    best = None
    for hh in range(align * 4, max_dim + 1, align):
        ww = round(hh * aspect / align) * align
        if ww < align * 4 or ww > max_dim or ww * hh > target:
            continue
        err = abs(ww / hh - aspect) / aspect
        if err <= 0.01 and (best is None or ww * hh > best[0] * best[1]):
            best = (ww, hh)
    if not best:
        raise SystemExit(f"no size within 1% of the art's aspect {aspect:.3f}; pass --w/--h")
    return best


def fit(img, w, h):
    """Cover-fit to exactly w x h, centered — first-and-last-frame pins both
    pictures at the render size."""
    s = max(w / img.width, h / img.height)
    r = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x, y = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


def busy(url):
    try:
        q = json.loads(urllib.request.urlopen(url + "/queue", timeout=3).read().decode())
    except Exception:
        return 0
    return len(q.get("queue_running", [])) + len(q.get("queue_pending", []))


def upload(host, img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    name, bnd = f"{uuid.uuid4().hex[:8]}_ltx_ref.png", uuid.uuid4().hex
    body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + buf.getvalue() + \
           (f"\r\n--{bnd}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
            f"\r\n--{bnd}--\r\n").encode()
    req = urllib.request.Request(host + "/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())["name"]


def build(image, prompt, seed, w, h, length, fps, strength, prefix):
    # ComfyUI's own video_ltx2_5_i2v template: stage 1 at half size, then a 2x
    # latent upscale and a short refine. Its prompt enhancer is left OFF (it
    # rewrites the prompt). Both cfgs are 1, so the negative is inert. The model
    # makes audio jointly; its latent must exist but is never decoded.
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "ltxv", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "5": {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": UPSCALER}},
        "6": {"class_type": "LoadImage", "inputs": {"image": image}},
        "7": {"class_type": "LTXVPreprocess", "inputs": {"image": ["6", 0], "img_compression": 18}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": LEAD + prompt, "clip": ["2", 0]}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "10": {"class_type": "LTXVConditioning",
               "inputs": {"positive": ["8", 0], "negative": ["9", 0], "frame_rate": fps}},
        "11": {"class_type": "LTXVDualCFGGuider",
               "inputs": {"model": ["1", 0], "positive": ["10", 0], "negative": ["10", 1],
                          "video_cfg": 1.0, "audio_cfg": 1.0}},
        "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},
        "20": {"class_type": "EmptyLTXVLatentVideo",
               "inputs": {"width": w // 2, "height": h // 2, "length": length, "batch_size": 1}},
        "21": {"class_type": "LTXVImgToVideoInplace",
               "inputs": {"vae": ["3", 0], "image": ["7", 0], "latent": ["20", 0],
                          "strength": strength, "bypass": False}},
        "22": {"class_type": "LTXVEmptyLatentAudio",
               "inputs": {"frames_number": length, "frame_rate": fps, "batch_size": 1,
                          "audio_vae": ["4", 0]}},
        "23": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["21", 0], "audio_latent": ["22", 0]}},
        "24": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "25": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS_1}},
        "26": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["24", 0], "guider": ["11", 0], "sampler": ["12", 0],
                          "sigmas": ["25", 0], "latent_image": ["23", 0]}},
        "27": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["26", 0]}},
        "30": {"class_type": "LTXVLatentUpsampler",
               "inputs": {"samples": ["27", 0], "upscale_model": ["5", 0], "vae": ["3", 0]}},
        "31": {"class_type": "LTXVImgToVideoInplace",
               "inputs": {"vae": ["3", 0], "image": ["7", 0], "latent": ["30", 0],
                          "strength": 1.0, "bypass": False}},
        "32": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["31", 0], "audio_latent": ["27", 1]}},
        "33": {"class_type": "RandomNoise", "inputs": {"noise_seed": 42}},
        "34": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS_2}},
        "35": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["33", 0], "guider": ["11", 0], "sampler": ["12", 0],
                          "sigmas": ["34", 0], "latent_image": ["32", 0]}},
        "36": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["35", 0]}},
        "40": {"class_type": "VAEDecodeTiled",
               "inputs": {"samples": ["36", 0], "vae": ["3", 0], "tile_size": 512,
                          "overlap": 64, "temporal_size": 64, "temporal_overlap": 16}},
        "41": {"class_type": "SaveAnimatedWEBP",
               "inputs": {"images": ["40", 0], "filename_prefix": prefix, "fps": 24.0,
                          "lossless": False, "quality": 90, "method": "default"}},
    }


FLF_LEAD = ("Use the provided start image as the first frame and the provided end "
            "image as the final frame anchor. ")


def build_flf(first, last, prompt, seed, width, height, length, fps, strength, prefix):
    # FIRST-AND-LAST-FRAME, ComfyUI's video_ltx2_5_flf2v template: one stage at
    # full size, both pictures pinned with LTXVAddGuide (frame 0 and -1), and
    # LTXVCropGuides removing those guide frames before decode. Identical to the
    # MCP server's lw.build25_flf.
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "ltxv", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "6": {"class_type": "LoadImage", "inputs": {"image": first}},
        "7": {"class_type": "LoadImage", "inputs": {"image": last}},
        "8": {"class_type": "LTXVPreprocess", "inputs": {"image": ["6", 0], "img_compression": 18}},
        "9": {"class_type": "LTXVPreprocess", "inputs": {"image": ["7", 0], "img_compression": 18}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"text": FLF_LEAD + prompt, "clip": ["2", 0]}},
        # Inert: both guider cfgs are 1, which discards the negative branch.
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "12": {"class_type": "LTXVConditioning",
               "inputs": {"positive": ["10", 0], "negative": ["11", 0], "frame_rate": fps}},
        "20": {"class_type": "EmptyLTXVLatentVideo",
               "inputs": {"width": width, "height": height, "length": length, "batch_size": 1}},
        "21": {"class_type": "LTXVAddGuide",
               "inputs": {"positive": ["12", 0], "negative": ["12", 1], "vae": ["3", 0],
                          "latent": ["20", 0], "image": ["8", 0],
                          "frame_idx": 0, "strength": strength}},
        "22": {"class_type": "LTXVAddGuide",
               "inputs": {"positive": ["21", 0], "negative": ["21", 1], "vae": ["3", 0],
                          "latent": ["21", 2], "image": ["9", 0],
                          "frame_idx": -1, "strength": strength}},
        "23": {"class_type": "LTXVEmptyLatentAudio",
               "inputs": {"frames_number": length, "frame_rate": fps, "batch_size": 1,
                          "audio_vae": ["4", 0]}},
        "24": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["22", 2], "audio_latent": ["23", 0]}},
        "25": {"class_type": "LTXVDualCFGGuider",
               "inputs": {"model": ["1", 0], "positive": ["22", 0], "negative": ["22", 1],
                          "video_cfg": 1.0, "audio_cfg": 1.0}},
        "26": {"class_type": "SamplerEulerAncestral", "inputs": {"eta": 0.0, "s_noise": 1.0}},
        "27": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "28": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS_1}},
        "29": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["27", 0], "guider": ["25", 0], "sampler": ["26", 0],
                          "sigmas": ["28", 0], "latent_image": ["24", 0]}},
        # The template separates the DENOISED output (index 1) here.
        "30": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["29", 1]}},
        "31": {"class_type": "LTXVCropGuides",
               "inputs": {"positive": ["22", 0], "negative": ["22", 1], "latent": ["30", 0]}},
        "40": {"class_type": "VAEDecodeTiled",
               "inputs": {"samples": ["31", 2], "vae": ["3", 0], "tile_size": 512,
                          "overlap": 64, "temporal_size": 64, "temporal_overlap": 16}},
        "41": {"class_type": "SaveAnimatedWEBP",
               "inputs": {"images": ["40", 0], "filename_prefix": prefix, "fps": 24.0,
                          "lossless": False, "quality": 90, "method": "default"}},
    }


def run(host, graph, timeout=3600):
    req = urllib.request.Request(host + "/prompt", data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())["prompt_id"]
    except urllib.error.HTTPError as e:
        sys.exit("REJECTED:\n" + e.read().decode()[:2500])
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        h = json.loads(urllib.request.urlopen(f"{host}/history/{pid}", timeout=30).read().decode())
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                sys.exit("ERROR: " + json.dumps(st.get("messages", []))[:2000])
            img = h[pid]["outputs"]["41"]["images"][0]
            q = urllib.parse.urlencode({k: img[k] for k in ("filename", "subfolder", "type")})
            return urllib.request.urlopen(f"{host}/view?{q}", timeout=120).read()
    sys.exit("timed out")


def preview(raw, dst, step=2, fps=12):
    frames = [f.convert("RGB") for f in ImageSequence.Iterator(Image.open(raw))][::step]
    # Pillow's WebP writer merges identical neighbors; nudge them apart.
    for i in range(1, len(frames)):
        if frames[i].tobytes() == frames[i - 1].tobytes():
            frames[i] = frames[i].copy()
            frames[i].putpixel((0, 0), tuple((c + 1) % 256 for c in frames[i].getpixel((0, 0))))
    frames[0].save(dst, save_all=True, append_images=frames[1:],
                   duration=int(round(1000 / fps)), loop=0, quality=90)
    return len(frames)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True, help="path to the illustration")
    p.add_argument("--prompt", required=True, help="motion only; camera first; what stays still")
    p.add_argument("--out", default="ltx_takes")
    p.add_argument("--len", dest="length", type=int, default=49, help="49 or 97 (8n+1); never 17")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--strength", type=float, default=0.7, help="stage-1 image strength (template)")
    p.add_argument("--fps", type=float, default=24.0)
    p.add_argument("--w", type=int, help="override the size; must keep the art's aspect, /64")
    p.add_argument("--h", type=int)
    p.add_argument("--last", help="the picture the shot should END on (first-and-last-frame mode)")
    p.add_argument("--host", default=os.environ.get("LTX_URL", "http://127.0.0.1:8189"))
    p.add_argument("--other-url", default="http://127.0.0.1:8188",
                   help="the other ComfyUI on this card, checked and unloaded first")
    a = p.parse_args()
    if (a.length - 1) % 8:
        sys.exit("--len must be 8n+1, e.g. 49 or 97")

    if busy(a.other_url):
        sys.exit(f"A job is running on {a.other_url}. Wait for it: two models cannot share a small card.")
    try:  # idle, so free its RAM for LTX; harmless if that ComfyUI is not up
        urllib.request.urlopen(urllib.request.Request(
            a.other_url + "/free", data=b'{"unload_models": true, "free_memory": true}',
            headers={"Content-Type": "application/json"}), timeout=10)
    except Exception:
        pass

    src = Image.open(a.image).convert("RGB")
    w, h = (a.w, a.h) if a.w and a.h else pick_size(*src.size)
    if w % 64 or h % 64:
        sys.exit(f"{w}x{h}: both sides must divide by 64 (stage 1 renders at half size)")
    if a.last:
        end = Image.open(a.last).convert("RGB")
        if abs(src.width / src.height - end.width / end.height) / (src.width / src.height) > 0.02:
            sys.exit("the end frame's shape does not match the panel's; one would be cropped")
        first_up, last_up = upload(a.host, fit(src, w, h)), upload(a.host, fit(end, w, h))
    else:
        s = REF_LONG_SIDE / max(src.size)
        ref = src.resize((round(src.width * s), round(src.height * s)), Image.LANCZOS) if s < 1 else src
        uploaded = upload(a.host, ref)

    os.makedirs(a.out, exist_ok=True)
    stem = f"{os.path.splitext(os.path.basename(a.image))[0]}_s{a.seed}"
    print(f"ltx-2.5: {a.image} -> {w}x{h}, {a.length} frames at {a.fps:g} fps, seed {a.seed}")
    t0 = time.time()
    raw = os.path.join(a.out, stem + ".webp")
    with open(raw, "wb") as f:
        g = (build_flf(first_up, last_up, a.prompt, a.seed, w, h, a.length, a.fps,
                       a.strength, "ltx25_" + stem) if a.last else
             build(uploaded, a.prompt, a.seed, w, h, a.length, a.fps, a.strength, "ltx25_" + stem))
        f.write(run(a.host, g))
    n = preview(raw, os.path.join(a.out, stem + "_12fps.webp"), step=max(1, round(a.fps / 12)))
    print(f"  {time.time() - t0:.0f}s -> {raw} (+ {n}-frame 12 fps preview)")


if __name__ == "__main__":
    main()
