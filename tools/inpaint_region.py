"""
inpaint_region.py — paint a rectangular region of an existing background image
back into scenery. Use it to remove a stray figure that a character-trained model
(e.g. Solstice) dropped in, so you keep a clean background layer.

Usage:
    python inpaint_region.py <image> <x0> <y0> <x1> <y1>
        [--out PATH] [--model counterfeit] [--prompt "stone cathedral stairs, no people"]

The region (x0,y0,x1,y1) is the figure's bounding box in pixels. Fills with
Counterfeit by default (no character bias), guided by --prompt. The character-plate
mode already returns a figure-free plate; this is for cleaning unexpected extras.
"""
import sys, os, time, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import workflow
from PIL import Image, ImageDraw
import requests


def inpaint(image, box, out=None, model="counterfeit", prompt=None):
    out = out or os.path.splitext(image)[0] + "_clean.png"
    prompt = prompt or "background scenery, architecture, empty, deserted, no people"
    if model not in workflow.MODELS:
        raise SystemExit(f"unknown model '{model}'; options: {', '.join(workflow.MODELS)}")
    ckpt = workflow.MODELS[model]["ckpt"]
    vae = workflow.MODELS[model]["vae"]

    im = Image.open(image).convert("RGB")
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    mask_path = os.path.join(os.path.dirname(out), "_inpaint_mask.png")
    mask.save(mask_path)

    workflow.ensure_comfy_running()
    img_name = workflow._upload_image(image)
    mask_name = workflow._upload_image(mask_path)

    vae_node, vae_ref = {}, ["4", 2]
    if vae:
        vae_node = {"41": {"class_type": "VAELoader", "inputs": {"vae_name": vae}}}
        vae_ref = ["41", 0]
    neg = workflow.DEFAULT_NEGATIVE + ", 1girl, woman, man, person, dress, standing figure, human"
    g = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        **vae_node,
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["4", 1]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": img_name}},
        "11": {"class_type": "LoadImageMask", "inputs": {"image": mask_name, "channel": "red"}},
        "12": {"class_type": "VAEEncodeForInpaint", "inputs": {"pixels": ["10", 0], "vae": vae_ref, "mask": ["11", 0], "grow_mask_by": 20}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 88, "steps": 30, "cfg": 7.0, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["12", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": vae_ref}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "inpaint"}},
    }
    pid = requests.post(f"{workflow.COMFY_URL}/prompt", json={"prompt": g}, timeout=30).json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 300:
        time.sleep(1.5)
        hist = requests.get(f"{workflow.COMFY_URL}/history/{pid}", timeout=30).json()
        if pid in hist:
            o = hist[pid]["outputs"]["9"]["images"][0]
            data = requests.get(f"{workflow.COMFY_URL}/view", params={"filename": o["filename"], "subfolder": o["subfolder"], "type": o["type"]}, timeout=30).content
            with open(out, "wb") as f:
                f.write(data)
            print("saved", out)
            return out
    raise SystemExit("timed out")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("x0", type=int); ap.add_argument("y0", type=int)
    ap.add_argument("x1", type=int); ap.add_argument("y1", type=int)
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default="counterfeit")
    ap.add_argument("--prompt", default=None)
    a = ap.parse_args()
    inpaint(a.image, (a.x0, a.y0, a.x1, a.y1), a.out, a.model, a.prompt)
