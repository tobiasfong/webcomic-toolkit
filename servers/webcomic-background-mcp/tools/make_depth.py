"""
make_depth.py — estimate a depth map from a finished illustration or background
plate, via the Depth-Anything V2 preprocessor in the local ComfyUI install
(no extra Python dependencies; the model auto-downloads on first use).

The depth map (white = near, black = far) feeds tools/parallax.py, which turns
a still illustration into a subtle 2.5D camera-drift clip for promo videos.

Usage:
    python make_depth.py <image> [output] [--model vitb|vitl|vits|vitg] [--res 1024]
"""
import sys
import os
import uuid
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import workflow


def make_depth(inp, out=None, model="vitl", resolution=1024, timeout=600):
    if out is None:
        base = os.path.splitext(os.path.basename(inp))[0]
        out = os.path.join(os.path.dirname(inp) or ".", f"depth_{base}.png")
    workflow.ensure_comfy_running()
    img = workflow._upload_image(inp)
    g = {
        "10": {"class_type": "LoadImage", "inputs": {"image": img}},
        "11": {"class_type": "DepthAnythingV2Preprocessor",
               "inputs": {"image": ["10", 0],
                          "ckpt_name": f"depth_anything_v2_{model}.pth",
                          "resolution": resolution}},
        # unique prefix per call — an identical resubmitted graph is otherwise
        # served entirely from ComfyUI's cache, recording no outputs in history
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["11", 0],
                         "filename_prefix": f"depth_{uuid.uuid4().hex[:8]}"}},
    }
    # first run downloads the model — allow a generous timeout
    data = workflow._submit_and_wait(g, timeout)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output", nargs="?", default=None)
    ap.add_argument("--model", default="vitl",
                    choices=["vits", "vitb", "vitl", "vitg"],
                    help="Depth-Anything V2 size (vitl = best quality, default)")
    ap.add_argument("--res", type=int, default=1024)
    a = ap.parse_args()
    print(make_depth(a.input, a.output, a.model, a.res))
