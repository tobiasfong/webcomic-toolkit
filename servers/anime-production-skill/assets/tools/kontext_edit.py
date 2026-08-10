"""
kontext_edit.py — edit an illustration with FLUX.1 Kontext (instruction-driven).

Why this exists: LTX cannot animate eye- or mouth-scale features. Measured on
2026-08-05 — a blink is ~0.2% of frame pixels and roughly 4 latent pixels wide
after the VAE's 8x compression, so there is nothing there for it to move. No
seed and no prompt wording changes that. Blinks and mouth flaps therefore come
from generated KEYFRAMES (this script) played back by the frame player, not
from video generation.

Usage:
  python kontext_edit.py --image panel.png \
      --edit "close her eyes, keep everything else identical" \
      --prefix panel_eyes_closed

  # sweep several seeds to pick the least-drifted result
  python kontext_edit.py --image panel.png --edit "..." --seeds 1,2,3

⚠ VERIFY EVERY RESULT AGAINST THE ORIGINAL. Kontext regenerates the WHOLE
frame, so it can quietly restyle linework, shift colour, or alter parts of the
image you never asked about. The intended use is to composite ONLY the changed
region (the eye or mouth patch) back over the original art, never to ship the
regenerated frame wholesale.

⚠ RUN Q6_K, NOT A LOW QUANT. Measured 2026-08-10 on six damaged frames at three
seeds each, identical prompt and region: `Q3_K_S` (~3.3 bits/weight) produced
ZERO usable repairs in 18 attempts, while `Q6_K` produced a usable take for
EVERY frame it was given. Same ~233 s per edit, 5127 MiB of 6144 peak VRAM.

Bit depth bites hardest exactly here, because repair reconstructs destroyed
structure from corrupted pixels — the edge of what the model can do. (Ordinary
generation showed NO difference between the two, so this is specific to repair.)
And VRAM is not the reason to quantise low: ComfyUI streams weights from system
RAM, and the card this was measured on runs a 14.2 GB model routinely.

Still expect to discard takes — about a third of Q6 output is unusable, fused
fingers included. Run three seeds; only one has to land.
"""
import argparse, json, os, time, urllib.request, urllib.error

HOST = "http://127.0.0.1:8188"
UNET = "flux1-kontext-dev-Q6_K.gguf"
T5   = "t5xxl_fp8_e4m3fn.safetensors"
CLIP_L = "clip_l.safetensors"
VAE  = "ae.safetensors"


def build(a, seed):
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": CLIP_L, "clip_name2": T5, "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": a.image}},

        # Kontext expects one of its supported resolutions; this snaps to the
        # nearest without changing the aspect ratio.
        "5": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["4", 0]}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},

        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": a.edit, "clip": ["2", 0]}},
        # ReferenceLatent is what makes this an EDIT rather than a fresh
        # generation — it pins the conditioning to the source image's latent.
        "8": {"class_type": "ReferenceLatent",
              "inputs": {"conditioning": ["7", 0], "latent": ["6", 0]}},
        "9": {"class_type": "FluxGuidance",
              "inputs": {"conditioning": ["8", 0], "guidance": a.guidance}},
        # Flux is distilled-guidance: cfg stays 1.0 and the negative is a
        # zeroed-out copy of the positive rather than a real negative prompt.
        "10": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["7", 0]}},

        "11": {"class_type": "KSampler",
               "inputs": {"model": ["1", 0], "seed": seed, "steps": a.steps, "cfg": 1.0,
                          "sampler_name": "euler", "scheduler": "simple",
                          "positive": ["9", 0], "negative": ["10", 0],
                          "latent_image": ["6", 0], "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["12", 0], "filename_prefix": f"{a.prefix}_{seed}"}},
    }


def run(a, seed):
    t0 = time.time()
    req = urllib.request.Request(HOST + "/prompt",
                                 data=json.dumps({"prompt": build(a, seed)}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("REJECTED:\n" + e.read().decode()[:2500]); raise SystemExit(1)
    while True:
        time.sleep(3)
        h = json.loads(urllib.request.urlopen(f"{HOST}/history/{pid}", timeout=30).read().decode())
        if pid in h:
            for m in h[pid].get("status", {}).get("messages", []):
                if m[0] == "execution_error":
                    print("ERROR:", json.dumps(m[1], indent=1)[:2000]); raise SystemExit(1)
            files = [f["filename"] for o in h[pid].get("outputs", {}).values()
                     for f in o.get("images", [])]
            print(f"  seed {seed}: {time.time()-t0:.0f}s -> {files or '(none)'}")
            return files
        if time.time() - t0 > 1800:
            raise SystemExit("timed out")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True, help="filename inside ComfyUI/input/")
    p.add_argument("--edit", required=True, help="instruction, e.g. 'close her eyes'")
    p.add_argument("--prefix", default="kontext")
    p.add_argument("--seeds", default="1", help="comma-separated")
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--guidance", type=float, default=2.5,
                   help="Kontext guidance. Lower preserves the original more; "
                        "higher follows the instruction harder and drifts more.")
    a = p.parse_args()
    seeds = [int(s) for s in a.seeds.split(",")]
    print(f"kontext: {a.image} | steps={a.steps} guidance={a.guidance} | \"{a.edit}\"")
    for s in seeds:
        run(a, s)


if __name__ == "__main__":
    main()
