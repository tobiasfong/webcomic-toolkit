"""
setup_models.py — download the models this server needs into a ComfyUI install.

Usage:
    python setup_models.py --comfy "C:/AI/ComfyUI_windows_portable/ComfyUI"

**FLUX is required.** As of v2.0.0 this server has no Stable Diffusion path —
the SD1.5 pipeline was removed so that plates match the FLUX-generated figures
from the sibling character-panel server. There is no lower-quality fallback;
without these models the server cannot render.

Downloads (skips anything already present):
  - FLUX.1-dev unet (GGUF) -> models/unet        the renderer
  - FLUX Kontext dev (GGUF)-> models/unet        image editing (edit_background)
  - T5-XXL + CLIP-L        -> models/clip        FLUX's dual text encoders
  - FLUX VAE               -> models/vae
  - ControlNet Union Pro 2 -> models/controlnet  composition / sketch control
  - manwha_style LoRA      -> models/loras       the manhwa aesthetic

Disk/VRAM: these are the Q6_K quantisations (~9.85 GB each). They do NOT need
to fit in VRAM — ComfyUI streams unet weights from system RAM, so VRAM was
never the constraint, and the old "Q3_K_S so FLUX fits a 6 GB card" reasoning
was wrong (see CLAUDE.md, quantisation). Q6 buys nothing for plain generation;
it was adopted because bit depth measurably matters for Kontext editing.
You need ONE of the dev unets to generate; Kontext is only needed for
edit_background.

Requires a ComfyUI-GGUF custom node install (city96/ComfyUI-GGUF) — the stock
loader cannot read .gguf.

No API token needed for Civitai; Hugging Face links are public.
"""
import argparse
import os
import urllib.request

# (subfolder, dest_filename, url) — dest_filename must match the entries in
# flux_workflow.py's FLUX_MODELS registry, so downloads land under the names
# the tool expects.
MODELS = [
    ("unet", "flux1-dev-Q6_K.gguf",
     "https://huggingface.co/city96/FLUX.1-dev-gguf/resolve/main/flux1-dev-Q6_K.gguf"),
    ("unet", "flux1-kontext-dev-Q6_K.gguf",                      # for edit_background
     "https://huggingface.co/QuantStack/FLUX.1-Kontext-dev-GGUF/resolve/main/flux1-kontext-dev-Q6_K.gguf"),
    ("clip", "t5xxl_fp8_e4m3fn.safetensors",
     "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors"),
    ("clip", "clip_l.safetensors",
     "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors"),
    ("vae", "ae.safetensors",
     "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors"),
    ("controlnet", "flux_controlnet_union_pro2.safetensors",
     "https://huggingface.co/Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0/resolve/main/diffusion_pytorch_model.safetensors"),
    ("loras", "manwha_style.safetensors",
     "https://civitai.com/api/download/models/793264"),
]


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    # sanity: catch an HTML login/error page saved under a model filename
    with open(dest, "rb") as f:
        if dest.endswith(".gguf"):
            if f.read(4) != b"GGUF":
                raise RuntimeError("downloaded file is not a valid GGUF (login page?)")
        else:
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
