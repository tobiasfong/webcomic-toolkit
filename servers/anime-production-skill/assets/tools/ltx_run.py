"""
ltx_run.py — submit an LTX-2.3 image-to-video job to ComfyUI and wait for it.

Builds the graph in API format and POSTs to /prompt, then polls /history.
Keeps every tunable at the top so OOM hunting is a one-line edit.

Usage:
  python ltx_run.py [--image ltx_test.png] [--w 832] [--h 576] [--len 25]
                    [--steps 8] [--variant distilled|dev] [--prompt "..."]
"""
import argparse, json, time, urllib.request, urllib.error

HOST = "http://127.0.0.1:8188"

VARIANTS = {
    "distilled": {
        "unet": "ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf",
        "connector": "ltx-2.3-22b-distilled_embeddings_connectors.safetensors",
        "vae": "ltx-2.3-22b-distilled_video_vae.safetensors",
        "steps": 8, "cfg": 1.0,
    },
    "dev": {
        "unet": "ltx-2.3-22b-dev-Q4_K_M.gguf",
        "connector": "ltx-2.3-22b-dev_embeddings_connectors.safetensors",
        "vae": "ltx-2.3-22b-dev_video_vae.safetensors",
        "steps": 25, "cfg": 3.0,
    },
}
GEMMA = "gemma-3-12b-it-Q3_K_M.gguf"

NEG = "blurry, distorted, deformed hands, extra limbs, warped face, watermark, text"


def build(a, v):
    """ComfyUI API-format graph. Node ids are strings; links are [node_id, output_index]."""
    return {
        # --- loaders ---
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": v["unet"]}},
        # ⚠ GGUF text encoders MUST go through city96's loader. The core
        # LTXAVTextEncoderLoader reads models/checkpoints/, and ComfyUI's
        # supported_pt_extensions has no .gguf — so it can never list one.
        "2": {"class_type": "DualCLIPLoaderGGUF",
              "inputs": {"clip_name1": GEMMA, "clip_name2": v["connector"], "type": "ltxv"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": v["vae"]}},
        "4": {"class_type": "LoadImage", "inputs": {"image": a.image}},

        # --- conditioning ---
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": a.prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 0]}},

        # image -> video latent (also rewrites the conditioning)
        "7": {"class_type": "LTXVImgToVideo",
              "inputs": {"positive": ["5", 0], "negative": ["6", 0], "vae": ["3", 0],
                         "image": ["4", 0], "width": a.w, "height": a.h,
                         "length": a.length, "batch_size": 1, "strength": 1.0}},
        "8": {"class_type": "LTXVConditioning",
              "inputs": {"positive": ["7", 0], "negative": ["7", 1], "frame_rate": 24.0}},

        # --- sampling ---
        "9": {"class_type": "ModelSamplingLTXV",
              "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95,
                         "latent": ["7", 2]}},
        "10": {"class_type": "LTXVScheduler",
               "inputs": {"steps": a.steps, "max_shift": 2.05, "base_shift": 0.95,
                          "stretch": True, "terminal": 0.1, "latent": ["7", 2]}},
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "12": {"class_type": "SamplerCustom",
               "inputs": {"model": ["9", 0], "add_noise": True, "noise_seed": a.seed,
                          "cfg": v["cfg"], "positive": ["8", 0], "negative": ["8", 1],
                          "sampler": ["11", 0], "sigmas": ["10", 0],
                          "latent_image": ["7", 2]}},

        # --- out ---
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "SaveAnimatedWEBP",
               "inputs": {"images": ["13", 0], "filename_prefix": "ltx_test",
                          "fps": 24.0, "lossless": False, "quality": 90,
                          "method": "default"}},
    }


def post(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", default="ltx_test.png")
    p.add_argument("--w", type=int, default=832)
    p.add_argument("--h", type=int, default=576)   # >=540: below that linework mushes
    p.add_argument("--len", dest="length", type=int, default=25)  # must be 8n+1
    p.add_argument("--steps", type=int, default=0)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--variant", default="distilled", choices=list(VARIANTS))
    p.add_argument("--cfg", type=float, default=0.0, help="override variant cfg; higher sticks harder to the input image (and reduces motion)")
    p.add_argument("--prompt", default="anime illustration, the character moves slightly, "
                                       "hair and clothes sway, subtle natural motion, "
                                       "cel shaded, clean linework")
    a = p.parse_args()
    v = VARIANTS[a.variant]
    if not a.steps:
        a.steps = v["steps"]
    if a.cfg:
        v = dict(v, cfg=a.cfg)
    if (a.length - 1) % 8:
        raise SystemExit(f"--len must be 8n+1 (got {a.length}); try 25, 49, 73, 97")
    for d in (a.w, a.h):
        if d % 32:
            raise SystemExit(f"width/height must be divisible by 32 (got {a.w}x{a.h})")

    print(f"variant={a.variant} {a.w}x{a.h} len={a.length} steps={a.steps} cfg={v['cfg']}")
    t0 = time.time()
    try:
        r = post("/prompt", {"prompt": build(a, v)})
    except urllib.error.HTTPError as e:
        print("REJECTED by ComfyUI:\n" + e.read().decode()[:3000])
        raise SystemExit(1)
    pid = r["prompt_id"]
    print("queued", pid)

    while True:
        time.sleep(3)
        h = post("/history/" + pid) if False else json.loads(
            urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=30).read().decode())
        if pid in h:
            entry = h[pid]
            st = entry.get("status", {})
            if st.get("status_str") == "error" or not st.get("completed", True):
                for m in st.get("messages", []):
                    if m[0] in ("execution_error", "execution_interrupted"):
                        print("ERROR:", json.dumps(m[1], indent=1)[:2500])
                        raise SystemExit(1)
            outs = entry.get("outputs", {})
            files = [f for o in outs.values() for f in o.get("images", [])]
            print(f"DONE in {time.time()-t0:.0f}s ->",
                  [f["filename"] for f in files] or "(no file)")
            return
        el = time.time() - t0
        print(f"  ...{el:.0f}s", flush=True)
        if el > 3600:
            raise SystemExit("timed out after 1h")


if __name__ == "__main__":
    main()
