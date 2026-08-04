#!/usr/bin/env bash
# fetch-ltx.sh — download LTX-2.3 (22B) + Gemma encoder for local image-to-video.
#
# Repo: unsloth/LTX-2.3-GGUF — a self-consistent set (checkpoint + matching
# embeddings connector + matching VAE per variant). Do NOT mix files across
# generations: Kijai/LTXV2_comfy is the OLDER LTX-2 19B and its connector/VAE
# are not interchangeable with 2.3.
#
# Ordered by priority: if you cancel partway, the essentials are already down.
# Resumable (curl -C -): safe to re-run.
# See docs/ltx-setup.md for placement and the 6GB settings.
set -u
M=/c/AI/ComfyUI_windows_portable/ComfyUI/models
mkdir -p "$M/diffusion_models" "$M/text_encoders" "$M/vae"
HF=https://huggingface.co/unsloth/LTX-2.3-GGUF/resolve/main

get () { # get <url-path> <dest>
  local dest="$2" name; name=$(basename "$dest")
  echo "[get] $name"
  curl -L -C - --retry 5 --retry-delay 10 -o "$dest" "$HF/$1" \
    && echo "[done] $name ($(du -h "$dest" | cut -f1))" \
    || echo "[FAILED] $name"
}

# ---- ESSENTIAL: distilled-1.1 — the fast variant (4–8 steps).
# Use this for the first session: while hunting OOM settings you want quick
# iterations, not 30-step renders. ~13 GB
get "distilled-1.1/ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf" \
    "$M/diffusion_models/ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf"

# Connector + VAE must match the distilled variant.
get "text_encoders/ltx-2.3-22b-distilled_embeddings_connectors.safetensors" \
    "$M/text_encoders/ltx-2.3-22b-distilled_embeddings_connectors.safetensors"
get "vae/ltx-2.3-22b-distilled_video_vae.safetensors" \
    "$M/vae/ltx-2.3-22b-distilled_video_vae.safetensors"

# Text encoder: Gemma 3 12B (LTX-2.3 uses Gemma, NOT T5). Runs once per
# generation and can be offloaded to CPU afterwards. ~6 GB
curl -L -C - --retry 5 --retry-delay 10 \
  -o "$M/text_encoders/gemma-3-12b-it-Q3_K_M.gguf" \
  "https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q3_K_M.gguf" \
  && echo "[done] gemma-3-12b-it-Q3_K_M.gguf"

# ---- OPTIONAL: dev — production quality (20–30 steps), better prompt
# adherence and cleaner fine detail (matters for cel-shaded linework and eyes).
# Get it once distilled is proven to run. Safe to Ctrl-C before this point.
get "ltx-2.3-22b-dev-Q4_K_M.gguf" \
    "$M/diffusion_models/ltx-2.3-22b-dev-Q4_K_M.gguf"
get "text_encoders/ltx-2.3-22b-dev_embeddings_connectors.safetensors" \
    "$M/text_encoders/ltx-2.3-22b-dev_embeddings_connectors.safetensors"
get "vae/ltx-2.3-22b-dev_video_vae.safetensors" \
    "$M/vae/ltx-2.3-22b-dev_video_vae.safetensors"

echo
echo "=== finished ==="
ls -lh "$M/diffusion_models"/ltx-2.3-*.gguf "$M/text_encoders"/*.gguf \
       "$M/text_encoders"/ltx-2.3-*.safetensors "$M/vae"/ltx-2.3-*.safetensors 2>/dev/null
