"""
setup_models.py — download the models this server needs into a ComfyUI install.

Usage:
    python setup_models.py --comfy "C:/AI/ComfyUI_windows_portable/ComfyUI"

Downloads (skips anything already present):
  - Solstice checkpoint   -> models/checkpoints   (default render model: Korean manhwa)
  - SD1.5 VAE             -> models/vae           (Solstice ships no VAE)
  - ControlNet scribble   -> models/controlnet    (composition / sketch control)
  - Manhwa LoRA (optional)-> models/loras         (extra manhwa push)

No API token needed. Civitai allows unauthenticated downloads via its API.
The IP-Adapter is NOT used by this server, so its models are not required.
"""
import argparse
import os
import urllib.request

# (subfolder, dest_filename, url) — dest_filename must match the entries in
# workflow.py's MODELS registry, so downloads land under the names the tool expects.
MODELS = [
    ("checkpoints", "solstice_manhwa_v10.safetensors",
     "https://civitai.com/api/download/models/66975"),          # default render model
    ("checkpoints", "Counterfeit_V3.safetensors",
     "https://huggingface.co/gsdf/Counterfeit-V3.0/resolve/main/Counterfeit-V3.0_fp16.safetensors"),
    ("checkpoints", "DreamShaper_8.safetensors",
     "https://huggingface.co/Lykon/DreamShaper/resolve/main/DreamShaper_8_pruned.safetensors"),
    ("vae", "vae-ft-mse-840000-ema-pruned.safetensors",
     "https://huggingface.co/stabilityai/sd-vae-ft-mse-original/resolve/main/vae-ft-mse-840000-ema-pruned.safetensors"),
    ("controlnet", "control_v11p_sd15_scribble_fp16.safetensors",
     "https://huggingface.co/comfyanonymous/ControlNet-v1-1_fp16_safetensors/resolve/main/control_v11p_sd15_scribble_fp16.safetensors"),
    ("loras", "ManhwaUltimate.safetensors",
     "https://civitai.com/api/download/models/14973"),
]


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    # sanity: safetensors begin with an 8-byte header length then '{'
    with open(dest, "rb") as f:
        f.seek(8)
        if f.read(1) != b"{":
            raise RuntimeError("downloaded file is not a valid safetensors (login page?)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy", required=True, help="path to the ComfyUI folder (contains models/)")
    a = ap.parse_args()
    models_root = os.path.join(a.comfy, "models")
    if not os.path.isdir(models_root):
        raise SystemExit(f"no models/ under {a.comfy}")

    for sub, name, url in MODELS:
        folder = os.path.join(models_root, sub)
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
            print(f"skip (present): {sub}/{name}")
            continue
        print(f"downloading {sub}/{name} ...", flush=True)
        try:
            _download(url, dest)
            print(f"  done: {os.path.getsize(dest) // (1<<20)} MB")
        except Exception as e:
            if os.path.exists(dest):
                os.remove(dest)
            print(f"  FAILED: {e}")
    print("Done.")


if __name__ == "__main__":
    main()
