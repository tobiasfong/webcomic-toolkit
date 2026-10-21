#!/usr/bin/env bash
# fetch-ltx.sh — download LTX-2.5 (22B, INT8) for local image-to-video.
#
# Repo: Lightricks/LTX-2.5 — Lightricks' own files. It is GATED: open
# https://huggingface.co/Lightricks/LTX-2.5, accept the license, create a read
# token at https://huggingface.co/settings/tokens, then:
#     HF_TOKEN=hf_... bash fetch-ltx.sh
#
# INT8 ("int8-convrot") is the build for RTX 30/40-series cards; NVFP4 needs
# Blackwell. ~40 GB in all. Needs ComfyUI v0.32+ (this project uses a v0.41
# install shared with FLUX 3 Klein); set COMFY_MODELS to its models folder.
# Resumable (curl -C -): safe to re-run. See ltx-setup.md.
set -u
M=${COMFY_MODELS:-/c/AI/ComfyUI_flux3/ComfyUI/models}
HF=https://huggingface.co/Lightricks/LTX-2.5/resolve/main
if [ -z "${HF_TOKEN:-}" ]; then
  echo "HF_TOKEN is not set — the repo is gated, so every download would fail."
  exit 1
fi
mkdir -p "$M/diffusion_models" "$M/text_encoders" "$M/vae" "$M/latent_upscale_models"

get () { # get <repo path>  -> same subfolder under $M
  local dest="$M/$1"
  echo "[get] $1"
  curl -L -C - --retry 5 --retry-delay 10 -H "Authorization: Bearer $HF_TOKEN" \
       -o "$dest" "$HF/$1" \
    && echo "[done] $(basename "$1") ($(du -h "$dest" | cut -f1))" \
    || echo "[FAILED] $1"
}

# Small files first, so a cancelled run still leaves something usable to test.
get "vae/ltx-2.5-audio-vae-bf16.safetensors"                              # 0.4 GB
get "vae/ltx-2.5-video-vae-bf16.safetensors"                              # 1.5 GB
get "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"  # 1.0 GB
get "text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"      # 15.4 GB
get "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"  # 21.5 GB

echo
echo "=== finished ==="
# A gated-repo failure saves an HTML error page under the model's name; a real
# .safetensors file starts with an 8-byte length and then '{'.
for f in "$M"/vae/ltx-2.5-*.safetensors "$M"/latent_upscale_models/ltx-2.5-*.safetensors \
         "$M"/text_encoders/gemma4-*ltx-2.5*.safetensors "$M"/diffusion_models/ltx-2.5-*.safetensors; do
  [ -f "$f" ] || continue
  if [ "$(dd if="$f" bs=1 skip=8 count=1 2>/dev/null)" = "{" ]; then
    echo "  ok   $(du -h "$f" | cut -f1)  $(basename "$f")"
  else
    echo "  BAD  $(basename "$f") — not a safetensors file (license not accepted, or bad token?)"
  fi
done
