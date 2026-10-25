"""
ACE-Step 1.5 extend / repaint for ComfyUI — the model's own "keep this stretch, write that one" mode.

ACE-Step 1.5 was trained with two extra inputs beside the noisy latent: `src_latents` (the source song, with
the stretch to write replaced by the stored silence latent) and `chunk_masks` (1 where the model writes, 0 where
it keeps). That is how the reference pipeline repaints and extends (acestep/core/generation/handler/
conditioning_masks.py): the new section is composed WITH the old one in view instead of as a separate song.

ComfyUI's port has both inputs in `AceStepConditionGenerationModel.prepare_condition`, but `forward()` hard-sets
`src_latents = x` and `chunk_masks = ones`, and `model_base.ACEStep15.extra_conds` never passes either, so plain
ComfyUI can only write whole songs. This package adds them back without editing ComfyUI's files:

  * `forward` is replaced with a copy that accepts `src_latents` / `chunk_masks` keyword inputs and otherwise
    behaves exactly like the original (a guard refuses to patch if ComfyUI's forward has changed shape).
  * `extra_conds` is wrapped to forward the `ace15_src_latents` / `ace15_chunk_masks` entries that the node below
    puts on the conditioning. `is_covers` is set to "repaint": prepare_condition only REPLACES src_latents when
    is_covers is None/True (audio-code hints) or False (the timbre reference), so any other value leaves the
    source in place.
  * `AceStep15ExtendSetup` builds both from a VAE-encoded source track, and also returns the latent with a noise
    mask over the kept stretch, so the sampler holds those frames to the original (the reference pipeline does
    the same with its repaint mask) — the old part comes back as recorded, not re-sung.

Installed into ComfyUI/custom_nodes by tools/install_comfy_nodes.py; ComfyUI must be restarted to load it.
"""

import inspect

import torch

import comfy.conds
import comfy.model_base
import comfy.ldm.ace.ace_step15 as ace15

FPS = 25.0                       # ACE 1.5 latent frames per second (48 kHz / 1920)

# ---------------------------------------------------------------------------------------------- the patch
_Model = ace15.AceStepConditionGenerationModel
_ORIG_FORWARD = _Model.forward
_src = inspect.getsource(_ORIG_FORWARD)
if "chunk_masks = torch.ones_like(x)" not in _src or "src_latents = x" not in _src:
    raise RuntimeError("ace_extend: ComfyUI's AceStepConditionGenerationModel.forward no longer matches the version "
                       "this patch copies; refusing to patch. Update comfy_nodes/ace_extend.")


def _forward(self, x, timestep, context, lyric_embed=None, refer_audio=None, audio_codes=None, is_covers=None,
             replace_with_null_embeds=False, src_latents=None, chunk_masks=None, **kwargs):
    # A copy of ComfyUI's forward, except src_latents / chunk_masks may be passed in ([B, C, T], like x).
    refer_audio_order_mask = None
    attention_mask = None
    precomputed_lm_hints_25Hz = None
    refer_audio_acoustic_hidden_states_packed = refer_audio.movedim(-1, -2)

    x = x.movedim(-1, -2)
    if refer_audio_order_mask is None:
        refer_audio_order_mask = torch.zeros((x.shape[0],), device=x.device, dtype=torch.long)
    src_latents = x if src_latents is None else src_latents.movedim(-1, -2).to(x)
    chunk_masks = torch.ones_like(x) if chunk_masks is None else chunk_masks.movedim(-1, -2).to(x)

    enc_hidden, enc_mask, context_latents = self.prepare_condition(
        context, None, lyric_embed, None,
        refer_audio_acoustic_hidden_states_packed, refer_audio_order_mask,
        src_latents, chunk_masks, is_covers, precomputed_lm_hints_25Hz=precomputed_lm_hints_25Hz,
        audio_codes=audio_codes)
    if replace_with_null_embeds:
        enc_hidden[:] = self.null_condition_emb.to(enc_hidden)
    out = self.decoder(hidden_states=x, timestep=timestep, timestep_r=timestep, attention_mask=attention_mask,
                       encoder_hidden_states=enc_hidden, encoder_attention_mask=enc_mask,
                       context_latents=context_latents)
    return out.movedim(-1, -2)


_Model.forward = _forward

_ORIG_EXTRA = comfy.model_base.ACEStep15.extra_conds


def _extra_conds(self, **kwargs):
    out = _ORIG_EXTRA(self, **kwargs)
    src = kwargs.get("ace15_src_latents", None)
    if src is not None:
        out["src_latents"] = comfy.conds.CONDRegular(src)
        out["chunk_masks"] = comfy.conds.CONDRegular(kwargs["ace15_chunk_masks"])
        out["is_covers"] = comfy.conds.CONDConstant("repaint")
        out.pop("audio_codes", None)       # the source, not LLM hints, guides an extension
    return out


comfy.model_base.ACEStep15.extra_conds = _extra_conds


# ---------------------------------------------------------------------------------------------- the node
def _tag(conditioning, src, mask):
    out = []
    for c in conditioning:
        d = c[1].copy()
        d["ace15_src_latents"] = src
        d["ace15_chunk_masks"] = mask
        out.append([c[0], d])
    return out


class AceStep15ExtendSetup:
    """Keep a source track's first `keep_seconds`, and let the model write on to `total_seconds`.

    `keep_seconds` can be shorter than the source: cutting before the old ending lets the extension carry on
    from the body of the song instead of after a fade-out."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "source": ("LATENT", {"tooltip": "the source track through VAEEncodeAudio (ACE 1.5 VAE)"}),
            "keep_seconds": ("FLOAT", {"default": 90.0, "min": 1.0, "max": 600.0, "step": 0.04}),
            "total_seconds": ("FLOAT", {"default": 240.0, "min": 2.0, "max": 600.0, "step": 0.04}),
            "blend_seconds": ("FLOAT", {"default": 0.4, "min": 0.0, "max": 4.0, "step": 0.04,
                                        "tooltip": "soft edge on the kept stretch, so the seam is not a hard cut"}),
        }}

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "setup"
    CATEGORY = "audio/ace"

    def setup(self, positive, negative, source, keep_seconds, total_seconds, blend_seconds):
        s = source["samples"]                                   # [1, C, T]
        total = int(round(total_seconds * FPS))
        keep = min(int(round(keep_seconds * FPS)), s.shape[2], total)
        if keep >= total:
            raise ValueError("ace_extend: total_seconds must be longer than keep_seconds")
        silence = ace15.get_silence_latent(total, s.device).to(s)[:, :, :total]
        if silence.shape[1] != s.shape[1]:
            raise ValueError(f"ace_extend: source has {s.shape[1]} latent channels, the ACE 1.5 silence latent has "
                             f"{silence.shape[1]}; encode the source with the ACE 1.5 VAE")
        src = silence.clone()
        src[:, :, :keep] = s[:, :, :keep]                       # the source, silence where the model writes
        write = torch.zeros((1, 1, total), device=s.device, dtype=s.dtype)
        write[:, :, keep:] = 1.0                                # 1 = write, 0 = keep (the model's chunk mask)
        chunk = write.expand(1, s.shape[1], total).contiguous()

        noise_mask = write.clone()                              # the sampler holds the kept frames to the source
        ramp = int(round(blend_seconds * FPS))
        if ramp > 0:
            a = max(0, keep - ramp)
            noise_mask[:, :, a:keep] = torch.linspace(0.0, 1.0, keep - a + 2, device=s.device)[1:-1].to(s)
        latent = {"samples": src.clone(), "noise_mask": noise_mask, "type": source.get("type", "audio")}
        return (_tag(positive, src, chunk), _tag(negative, src, chunk), latent)


NODE_CLASS_MAPPINGS = {"AceStep15ExtendSetup": AceStep15ExtendSetup}
NODE_DISPLAY_NAME_MAPPINGS = {"AceStep15ExtendSetup": "ACE-Step 1.5 Extend (keep + write on)"}
