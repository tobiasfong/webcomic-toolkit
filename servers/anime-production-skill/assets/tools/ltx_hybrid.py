"""
ltx_hybrid.py — two-model split-sigma pass: distilled early, dev late.

Rationale. In a diffusion/flow model the EARLY (high-noise) steps decide
large-scale structure and motion; the LATE (low-noise) steps decide fine
detail. Measured here: distilled moves (30.6) and dev does not (2.6), while dev
holds faces and linework better. So run distilled over the high sigmas to
commit the motion, then hand the latent to dev over the low sigmas to clean it
up.

(The version circulating online puts dev first "for structure". That ordering
cannot work: dev would lock in stillness during exactly the steps where motion
is decided, and distilled could not add it back afterwards.)

Each variant needs its OWN connector and VAE, so both conditioning chains are
built separately. Both 13GB models are touched in one graph — on a 6GB card
ComfyUI must swap them, so expect this to be slow.

Usage:
  python ltx_hybrid.py [--split 3] [--steps 10] [--w 832] [--h 576]
                       [--image ltx_test.png] [--prompt "..."]
"""
import argparse, json, time, urllib.request, urllib.error

HOST = "http://127.0.0.1:8188"
GEMMA = "gemma-3-12b-it-Q3_K_M.gguf"
NEG = "blurry, distorted, deformed hands, extra limbs, warped face, watermark, text"

V = {
    "distilled": ("ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf",
                  "ltx-2.3-22b-distilled_embeddings_connectors.safetensors",
                  "ltx-2.3-22b-distilled_video_vae.safetensors"),
    "dev": ("ltx-2.3-22b-dev-Q4_K_M.gguf",
            "ltx-2.3-22b-dev_embeddings_connectors.safetensors",
            "ltx-2.3-22b-dev_video_vae.safetensors"),
}


def chain(tag, variant, a, base):
    """Loaders + conditioning + img2video latent for one variant. Returns (nodes, ids)."""
    unet, conn, vae = V[variant]
    n = {
        f"{base}0": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet}},
        f"{base}1": {"class_type": "DualCLIPLoaderGGUF",
                     "inputs": {"clip_name1": GEMMA, "clip_name2": conn, "type": "ltxv"}},
        f"{base}2": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        f"{base}3": {"class_type": "CLIPTextEncode",
                     "inputs": {"text": a.prompt, "clip": [f"{base}1", 0]}},
        f"{base}4": {"class_type": "CLIPTextEncode",
                     "inputs": {"text": NEG, "clip": [f"{base}1", 0]}},
        f"{base}5": {"class_type": "LTXVImgToVideo",
                     "inputs": {"positive": [f"{base}3", 0], "negative": [f"{base}4", 0],
                                "vae": [f"{base}2", 0], "image": ["99", 0],
                                "width": a.w, "height": a.h, "length": a.length,
                                "batch_size": 1, "strength": 1.0}},
        f"{base}6": {"class_type": "LTXVConditioning",
                     "inputs": {"positive": [f"{base}5", 0], "negative": [f"{base}5", 1],
                                "frame_rate": 24.0}},
        f"{base}7": {"class_type": "ModelSamplingLTXV",
                     "inputs": {"model": [f"{base}0", 0], "max_shift": 2.05,
                                "base_shift": 0.95, "latent": [f"{base}5", 2]}},
    }
    ids = dict(model=[f"{base}7", 0], pos=[f"{base}6", 0], neg=[f"{base}6", 1],
               vae=[f"{base}2", 0], latent=[f"{base}5", 2])
    return n, ids


def build(a):
    g = {"99": {"class_type": "LoadImage", "inputs": {"image": a.image}}}
    dn, dist = chain("distilled", "distilled", a, "1")
    vn, dev = chain("dev", "dev", a, "2")
    g.update(dn); g.update(vn)

    g.update({
        # one shared sigma schedule, then split it
        "30": {"class_type": "LTXVScheduler",
               "inputs": {"steps": a.steps, "max_shift": 2.05, "base_shift": 0.95,
                          "stretch": True, "terminal": 0.1, "latent": dist["latent"]}},
        "31": {"class_type": "SplitSigmas", "inputs": {"sigmas": ["30", 0], "step": a.split}},
        "32": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "33": {"class_type": "RandomNoise", "inputs": {"noise_seed": a.seed}},
        "34": {"class_type": "DisableNoise", "inputs": {}},

        # PASS 1 — distilled over the HIGH sigmas: commit the motion
        "35": {"class_type": "CFGGuider",
               "inputs": {"model": dist["model"], "positive": dist["pos"],
                          "negative": dist["neg"], "cfg": a.cfg1}},
        "36": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["33", 0], "guider": ["35", 0], "sampler": ["32", 0],
                          "sigmas": ["31", 0], "latent_image": dist["latent"]}},

        # PASS 2 — dev over the LOW sigmas: clean up detail, no fresh noise
        # ⚠ Reuse distilled's conditioning here. It carries the frame-0 image
        # guide; pairing dev's conditioning with distilled's latent loses the
        # pinning and frame 0 comes out as raw noise. Only the model changes.
        "37": {"class_type": "CFGGuider",
               "inputs": {"model": dev["model"], "positive": dist["pos"],
                          "negative": dist["neg"], "cfg": a.cfg2}},
        "38": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["34", 0], "guider": ["37", 0], "sampler": ["32", 0],
                          "sigmas": ["31", 1], "latent_image": ["36", 0]}},

        "39": {"class_type": "VAEDecode", "inputs": {"samples": ["38", 0], "vae": dist["vae"]}},
        "40": {"class_type": "SaveAnimatedWEBP",
               "inputs": {"images": ["39", 0], "filename_prefix": "ltx_hybrid",
                          "fps": 24.0, "lossless": False, "quality": 90,
                          "method": "default"}},
    })
    return g


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", default="ltx_test.png")
    p.add_argument("--w", type=int, default=832)
    p.add_argument("--h", type=int, default=576)
    p.add_argument("--len", dest="length", type=int, default=25)
    p.add_argument("--steps", type=int, default=10)
    p.add_argument("--split", type=int, default=3, help="steps of distilled before handing to dev")
    p.add_argument("--cfg1", type=float, default=1.0, help="cfg for the distilled (motion) pass")
    p.add_argument("--cfg2", type=float, default=3.0, help="cfg for the dev (detail) pass")
    p.add_argument("--seed", type=int, default=777)
    p.add_argument("--prompt", default="anime fight scene, the woman in the white hanfu kicks "
                                       "the boy in the red blazer, her leg sweeps upward, he "
                                       "recoils backward, dynamic motion, cel shaded, clean linework")
    a = p.parse_args()
    print(f"hybrid: distilled steps 0-{a.split} -> dev steps {a.split}-{a.steps} "
          f"| {a.w}x{a.h} len={a.length} cfg {a.cfg1}/{a.cfg2}")
    t0 = time.time()
    req = urllib.request.Request(HOST + "/prompt",
                                 data=json.dumps({"prompt": build(a)}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("REJECTED:\n" + e.read().decode()[:3000]); raise SystemExit(1)
    print("queued", pid)
    while True:
        time.sleep(5)
        h = json.loads(urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=30).read().decode())
        if pid in h:
            st = h[pid].get("status", {})
            for m in st.get("messages", []):
                if m[0] == "execution_error":
                    print("ERROR:", json.dumps(m[1], indent=1)[:2500]); raise SystemExit(1)
            files = [f for o in h[pid].get("outputs", {}).values() for f in o.get("images", [])]
            print(f"DONE in {time.time()-t0:.0f}s ->", [f['filename'] for f in files] or "(none)")
            return
        print(f"  ...{time.time()-t0:.0f}s", flush=True)
        if time.time() - t0 > 3600:
            raise SystemExit("timed out")


if __name__ == "__main__":
    main()
