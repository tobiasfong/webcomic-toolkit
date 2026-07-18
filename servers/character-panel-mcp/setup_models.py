"""
setup_models.py — download the Tier-2 models this server needs into a ComfyUI
install (IP-Adapter identity + OpenPose ControlNet). Not needed for Tier 1.

Usage:
    python setup_models.py --comfy "C:/AI/ComfyUI_windows_portable/ComfyUI"

Downloads (skips anything already present):
  - CLIP-ViT-H-14 vision encoder -> models/clip_vision  (IP-Adapter's image encoder)
  - IP-Adapter Plus (SD1.5)      -> models/ipadapter    (identity, "PLUS (high strength)")
  - IP-Adapter Plus Face (SD1.5) -> models/ipadapter    (portraits, "PLUS FACE (portraits)")
  - ControlNet OpenPose          -> models/controlnet   (pose control)

No API token needed — all four are unauthenticated Hugging Face downloads.
Also needs the ComfyUI_IPAdapter_plus custom node (see README.md Step 3) — this
script only fetches model weights, not custom nodes.

True FaceID (InsightFace-based) is NOT covered here — deliberately not built,
see README.md's "Consistency tiers" section for why.
"""
import argparse
import os
import urllib.request

# (subfolder, dest_filename, url) — dest_filename must match what
# IPAdapterUnifiedLoader's presets and workflow.py's CONTROLNET_OPENPOSE expect.
MODELS = [
    ("clip_vision", "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
     "https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors"),
    ("ipadapter", "ip-adapter-plus_sd15.safetensors",
     "https://huggingface.co/h94/IP-Adapter/resolve/main/models/ip-adapter-plus_sd15.safetensors"),
    ("ipadapter", "ip-adapter-plus-face_sd15.safetensors",
     "https://huggingface.co/h94/IP-Adapter/resolve/main/models/ip-adapter-plus-face_sd15.safetensors"),
    ("controlnet", "control_v11p_sd15_openpose_fp16.safetensors",
     "https://huggingface.co/comfyanonymous/ControlNet-v1-1_fp16_safetensors/resolve/main/control_v11p_sd15_openpose_fp16.safetensors"),
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
    print("Done. Still needed: the ComfyUI_IPAdapter_plus custom node (README.md Step 3).")


if __name__ == "__main__":
    main()
