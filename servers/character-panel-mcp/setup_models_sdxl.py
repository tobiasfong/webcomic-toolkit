"""
setup_models_sdxl.py — download the SDXL prototype stack (2026-07-19) into a
ComfyUI install. Separate from setup_models.py (Tier-2 SD1.5 models) because
this is a much larger, explicitly optional download (~11 GB) most users of
this server won't want by default — see README.md's "SDXL prototype" section
for why this exists (SD1.5 could not produce genuine back views or clean
full-body anatomy no matter how Tier-1/2 was tuned; this tests whether SDXL,
specifically the Midjourney Manga Art Style LoRA, does better).

Usage:
    python setup_models_sdxl.py --comfy "C:/AI/ComfyUI_windows_portable/ComfyUI" [--stage1-only]

--stage1-only downloads just the checkpoint + VAE + LoRA (~7.5 GB) — enough to
test whether SDXL fixes the anatomy problem at all before committing to the
IP-Adapter/CLIP-vision/ControlNet download (~4 GB more). This mirrors the
staged verification plan: don't download Tier-2-equivalent SDXL models until
Stage 1 (plain txt2img) actually looks promising on this hardware.

No API token needed — all downloads are unauthenticated Hugging Face / Civitai.
"""
import argparse
import os
import urllib.request

# (subfolder, dest_filename, url, stage) — dest_filename must match the names
# in workflow.py's SDXL_MODELS/SDXL_LORA/SDXL_IPADAPTER/etc constants.
STAGE1_MODELS = [
    ("checkpoints", "sd_xl_base_1.0.safetensors",
     "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"),
    ("vae", "sdxl_vae_fp16fix.safetensors",
     "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl_vae.safetensors"),
    ("loras", "MJMangaSDXL.safetensors",
     "https://civitai.com/api/download/models/351765"),          # Midjourney Manga Art Style SDXL
]

# Tier-2 SDXL equivalents — only needed once Stage 1 validates the base model.
STAGE2_MODELS = [
    ("clip_vision", "CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors",
     "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/image_encoder/model.safetensors"),
    ("ipadapter", "ip-adapter-plus_sdxl_vit-h.safetensors",
     "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors"),
    ("controlnet", "control-lora-openposeXL2-rank256.safetensors",
     "https://huggingface.co/thibaud/controlnet-openpose-sdxl-1.0/resolve/main/control-lora-openposeXL2-rank256.safetensors"),
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
    ap.add_argument("--stage1-only", action="store_true",
                    help="download just checkpoint+VAE+LoRA (~7.5 GB), skip IP-Adapter/ControlNet (~4 GB more)")
    a = ap.parse_args()
    models_root = os.path.join(a.comfy, "models")
    if not os.path.isdir(models_root):
        raise SystemExit(f"no models/ under {a.comfy}")

    entries = STAGE1_MODELS if a.stage1_only else STAGE1_MODELS + STAGE2_MODELS
    for sub, name, url in entries:
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
    print("Done." + (" Run again without --stage1-only once Stage 1 validates." if a.stage1_only else ""))


if __name__ == "__main__":
    main()
