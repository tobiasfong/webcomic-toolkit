"""
setup_models.py — download the FLUX 3 Klein files this server needs.

Usage:
    set HF_TOKEN=hf_...           (PowerShell: $env:HF_TOKEN = "hf_...")
    python setup_models.py --comfy "C:/AI/ComfyUI_flux3/ComfyUI"

**Klein is required.** As of v3.0.0 this server renders only with FLUX 3 Image
Klein; FLUX.1-dev, its manhwa LoRA, ControlNet and Kontext were removed. There
is no fallback model.

Before running this:

1. **A ComfyUI of v0.41.0 or later** (or the 0.41.1 backport). Klein's nodes do
   not exist in older builds. A separate portable install is the safe choice if
   your existing ComfyUI carries add-ons you rely on: this project keeps Klein
   at C:/AI/ComfyUI_flux3 on port 8189, and the server starts it on first use
   (WEBCOMIC_BG_KLEIN_DIR / WEBCOMIC_BG_KLEIN_URL to change either).
2. **Accept the license on Hugging Face.** The repo is gated: open
   https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy, accept,
   then create a read token at https://huggingface.co/settings/tokens. Each BFL
   repo needs its own click -- accepting the main Klein repo does not cover
   this one.

Downloads (skips anything already present), ~11 GB in all:
  - flux3_image_klein_sd_int8_convrot   -> models/diffusion_models   the renderer
  - qwen3vl_4b_int8_convrot             -> models/text_encoders      text encoder
  - flux2-vae                           -> models/vae

INT8 is the build for RTX 30/40-series (Ampere and Ada have INT8 tensor cores;
FP8 needs Ada or later to run natively, NVFP4 needs Blackwell). It runs on a
6 GB laptop card; the repo also has FP8 and NVFP4 builds if your card suits
them -- point WEBCOMIC_BG_KLEIN_MODEL / WEBCOMIC_BG_KLEIN_TE at them.

License: FLUX Kommunity License v1.0. Commercial use of OUTPUTS is permitted
for users under US$5M gross annual revenue; above that, BFL's self-hosted
license or API applies. Read it on the repo page before relying on it.
"""
import argparse
import os
import urllib.request

REPO = "https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/resolve/main"

# (models subfolder, path in the repo, saved-as name). The saved-as names are
# what klein.py and the character-panel server load. The diffusion model is
# saved under the name ComfyUI's docs give it; BFL's repo now calls the same
# file flux3-image-klein-int8-convrot (byte-identical, 5,827,874,779 bytes).
# It is the step-DISTILLED model -- not the -base- file beside it, which is for
# fine-tuning and needs many more steps.
MODELS = [
    ("diffusion_models", "diffusion_models/flux3-image-klein-int8-convrot.safetensors",
     "flux3_image_klein_sd_int8_convrot.safetensors"),
    ("text_encoders", "text_encoders/qwen3vl_4b_int8_convrot.safetensors",
     "qwen3vl_4b_int8_convrot.safetensors"),
    ("vae", "vae/flux2-vae.safetensors", "flux2-vae.safetensors"),
]


def _download(url, dest, token):
    headers = {"User-Agent": "Mozilla/5.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    # Catch an HTML login/error page saved under a model filename: a real
    # .safetensors starts with an 8-byte header length followed by JSON.
    with open(dest, "rb") as f:
        f.seek(8)
        if f.read(1) != b"{":
            raise RuntimeError("not a valid safetensors file -- license not accepted, or bad token?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy", required=True,
                    help="the Klein install's ComfyUI folder (the one containing models/)")
    a = ap.parse_args()
    models_root = os.path.join(a.comfy, "models")
    if not os.path.isdir(models_root):
        raise SystemExit(f"no models/ under {a.comfy}")
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("HF_TOKEN is not set -- the repo is gated, so downloads will fail. "
              "See the instructions at the top of this file.")

    for sub, repo_path, name in MODELS:
        folder = os.path.join(models_root, sub)
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
            print(f"skip (present): {sub}/{name}")
            continue
        print(f"downloading {sub}/{name} ...", flush=True)
        try:
            _download(f"{REPO}/{repo_path}", dest, token)
            print(f"  done: {os.path.getsize(dest) // (1 << 20)} MB")
        except Exception as e:
            if os.path.exists(dest):
                os.remove(dest)
            print(f"  FAILED: {e}")
    print("Done.")


if __name__ == "__main__":
    main()
