"""
setup_models_controlnet_pro.py — download the Union Pro 2.0 FLUX ControlNet.

Usage:
    python setup_models_controlnet_pro.py --comfy "C:/AI/ComfyUI_windows_portable/ComfyUI"

Why this exists: the server shipped against InstantX's original
`flux_controlnet_union_alpha`, which its own docstrings already describe as
alpha-quality (openpose mode only ~2/3 reliable). Its canny mode turned out to
be worse — across six live tests on a real storyboard sketch (strengths 0.45 /
0.60 / 0.70 / 0.75, preprocessor on and off, noisy and cleaned sketch) it
composited the control image's own edges into the output as visible white
scratch lines and desaturated the whole frame, at every setting that was strong
enough to hold the composition. The control map itself was verified clean, so
the model was the variable.

Shakker-Labs' Union Pro 2.0 is the maintained successor, ungated, 2.14 GB, and
supports canny / depth / pose / soft-edge / grayscale behind the same
ControlNetLoader + SetUnionControlNetType nodes — so it drops straight into
flux_workflow.py by changing WEBCOMIC_CHAR_FLUX_CONTROLNET.

The old alpha file is left in place; delete it once Pro 2.0 is confirmed
better on your own hardware.
"""
import argparse
import os
import urllib.request

MODELS = [
    ("controlnet", "flux_controlnet_union_pro2.safetensors",
     "https://huggingface.co/Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0/"
     "resolve/main/diffusion_pytorch_model.safetensors"),
]


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
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
    print("Done. Set WEBCOMIC_CHAR_FLUX_CONTROLNET=flux_controlnet_union_pro2.safetensors "
          "to use it.")


if __name__ == "__main__":
    main()
