"""
ace_workflow.py — ACE-Step graph construction for ComfyUI.

Two variants, both native to ComfyUI core since ~0.25 (no custom nodes needed —
unlike the LTX install, which needed city96's GGUF loaders):

  "1.5"  (default) — split files: acestep_v1.5_turbo + TWO Qwen text encoders
                     + a dedicated VAE. Exposes explicit bpm / key / time
                     signature / duration / LANGUAGE, and a reference-timbre
                     audio slot. The language control is why this is the default:
                     the first real target for this server is a Japanese vocal
                     track, and 1.0 has no way to declare the language.
  "1.0"           — the 3.5B all-in-one checkpoint. Simpler graph (one
                     CheckpointLoaderSimple gives model+clip+vae), fewer knobs:
                     tags and lyrics only. Kept as the fallback if 1.5's
                     Japanese vocals disappoint on a 6 GB card.

## Things that bite

**1.5 needs TWO text encoders, not one.** comfy/text_encoders/ace15.py always
builds a qwen3_06b for the base/lyrics embedding, and the larger Qwen (1.7b or
4b) is a SEPARATE autoregressive LLM that generates audio codes. So it is
DualCLIPLoader(type="ace"), never CLIPLoader — a single-file load silently
lands on the ACE 1.0 T5 path instead (comfy/sd.py:1527 vs :1692).

**`duration` and `seconds` must agree.** TextEncodeAceStepAudio1.5 takes a
`duration` used for conditioning; EmptyAceStep1.5LatentAudio takes `seconds`
which sets the actual latent length. Nothing checks that they match, and a
mismatch conditions the model for one length while sampling another. Both are
derived from a single argument here for exactly that reason.

**The negative prompt must not re-run the LLM.** generate_audio_codes defaults
to True; leaving it on for the negative conditioning pays for a second
autoregressive pass that is then discarded (and at cfg 1.0 the negative is not
even used). It is forced off below.

**Defaults for steps/cfg/sampler are STARTING POINTS, not verified settings.**
They have not been swept on this hardware. tools/ace_run.py exists to sweep
them — the same way ltx_run.py found LTX's real settings.
"""

from __future__ import annotations

# --- model files -------------------------------------------------------------

VARIANTS = {
    "1.5": {
        "unet": "acestep_v1.5_turbo.safetensors",
        "clip1": "qwen_0.6b_ace15.safetensors",   # base + lyrics encoder (always loaded)
        "clip2": "qwen_1.7b_ace15.safetensors",   # audio-code LLM
        "vae": "ace_1.5_vae.safetensors",
        "steps": 12,
        "cfg": 1.0,      # turbo variant — distilled, so a low cfg is expected
        "sampler": "euler",
        "scheduler": "simple",
    },
    "1.0": {
        "checkpoint": "ace_step_v1_3.5b.safetensors",
        "steps": 50,
        "cfg": 5.0,
        "sampler": "euler",
        "scheduler": "simple",
    },
}

LANGUAGES = ['ar', 'az', 'bg', 'bn', 'ca', 'cs', 'da', 'de', 'el', 'en', 'es', 'fa',
             'fi', 'fr', 'he', 'hi', 'hr', 'ht', 'hu', 'id', 'is', 'it', 'ja', 'ko',
             'la', 'lt', 'ms', 'ne', 'nl', 'no', 'pa', 'pl', 'pt', 'ro', 'ru', 'sa',
             'sk', 'sr', 'sv', 'sw', 'ta', 'te', 'th', 'tl', 'tr', 'uk', 'ur', 'vi',
             'yue', 'zh', 'unknown']

KEYSCALES = [f"{root} {quality}"
             for quality in ("major", "minor")
             for root in ("C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb",
                          "G", "G#", "Ab", "A", "A#", "Bb", "B")]

TIMESIGNATURES = ("2", "3", "4", "6")

# ACE 1.5's latent is one frame per 1/25 s (round(seconds * 48000 / 1920)); 1.0's
# is seconds * 44100/512/8. Neither has a divisibility constraint like LTX's
# 8n+1, so duration is free-form — but very short clips give the model no room
# to establish a structure.
MIN_DURATION = 10.0
MAX_DURATION = 240.0


class WorkflowError(ValueError):
    pass


def _check(variant: str, duration: float, language: str, keyscale: str,
           timesignature: str, reference_audio: str | None = None) -> None:
    if variant not in VARIANTS:
        raise WorkflowError(f"variant must be one of {sorted(VARIANTS)}, got {variant!r}")
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise WorkflowError(
            f"duration must be {MIN_DURATION}-{MAX_DURATION}s, got {duration}"
        )
    if variant == "1.0" and reference_audio is not None:
        # Refuse rather than ignore. A silently-dropped reference would look like
        # "the timbre reference does nothing", which is a miserable thing to
        # debug — the same failure mode as mixing LTX connectors across variants.
        raise WorkflowError(
            "reference_audio is a 1.5-only feature (ReferenceTimbreAudio); "
            "variant '1.0' has no identity conditioning for voice."
        )
    if variant == "1.5":
        if language not in LANGUAGES:
            raise WorkflowError(f"language {language!r} not supported; see LANGUAGES")
        if keyscale not in KEYSCALES:
            raise WorkflowError(f"keyscale {keyscale!r} invalid; e.g. 'C major', 'A minor'")
        if str(timesignature) not in TIMESIGNATURES:
            raise WorkflowError(f"timesignature must be one of {TIMESIGNATURES}")


def build_graph(
    *,
    tags: str,
    lyrics: str = "",
    duration: float = 120.0,
    seed: int = 0,
    variant: str = "1.5",
    # 1.5-only musical controls
    bpm: int = 120,
    language: str = "en",
    keyscale: str = "C major",
    timesignature: str = "4",
    generate_audio_codes: bool = True,
    reference_audio: str | None = None,
    # --- lyric adherence (1.5 only) ---------------------------------------
    # These govern the autoregressive LLM that turns the lyric into audio
    # semantic tokens. They were hardcoded to ComfyUI's node defaults for this
    # server's first weeks, which was a mistake: `temperature` 0.85 tells that
    # decoder to sample randomly, and randomly-sampled audio tokens are how a
    # lyric comes back with words quietly swapped. Lower temperature = more
    # literal. Higher lm_cfg_scale = pushed harder toward the conditioning.
    temperature: float = 0.85,
    lm_cfg_scale: float = 2.0,
    top_p: float = 0.9,
    top_k: int = 0,
    min_p: float = 0.0,
    # sampling
    steps: int | None = None,
    cfg: float | None = None,
    sampler: str | None = None,
    scheduler: str | None = None,
    # 1.0-only
    lyrics_strength: float = 1.0,
    # output
    filename_prefix: str = "audio/music_mcp",
    mp3_quality: str = "320k",
) -> dict:
    """Build the ComfyUI API graph for one track.

    Emits BOTH a FLAC and an MP3 off the same sampling pass — the extra encode is
    free next to sampling, and the pipeline wants both (lossless to keep, mp3 for
    Remotion to drop in).

    `reference_audio` is the *ComfyUI-side* name of an already-uploaded file
    (see comfy.upload_audio), not a local path. 1.5 only.
    """
    _check(variant, duration, language, keyscale, str(timesignature), reference_audio)
    v = VARIANTS[variant]
    steps = v["steps"] if steps is None else steps
    cfg = v["cfg"] if cfg is None else cfg
    sampler = v["sampler"] if sampler is None else sampler
    scheduler = v["scheduler"] if scheduler is None else scheduler

    g: dict = {}

    if variant == "1.5":
        g["1"] = {"class_type": "UNETLoader",
                  "inputs": {"unet_name": v["unet"], "weight_dtype": "default"}}
        g["2"] = {"class_type": "DualCLIPLoader",
                  "inputs": {"clip_name1": v["clip1"], "clip_name2": v["clip2"],
                             "type": "ace"}}
        g["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": v["vae"]}}
        model, clip, vae = ["1", 0], ["2", 0], ["3", 0]

        def encode(node_tags: str, node_lyrics: str, codes: bool) -> dict:
            return {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
                "clip": clip,
                "tags": node_tags,
                "lyrics": node_lyrics,
                "seed": seed,
                "bpm": int(bpm),
                # MUST match node 6's `seconds` — see module docstring.
                "duration": float(duration),
                "timesignature": str(timesignature),
                "language": language,
                "keyscale": keyscale,
                "generate_audio_codes": codes,
                "cfg_scale": float(lm_cfg_scale),
                "temperature": float(temperature),
                "top_p": float(top_p),
                "top_k": int(top_k),
                "min_p": float(min_p),
            }}

        # A reference timbre replaces the generated audio codes as the source of
        # "what should this sound like" — ComfyUI's own tooltip says to turn the
        # LLM off when supplying one.
        want_codes = generate_audio_codes and reference_audio is None
        g["4"] = encode(tags, lyrics, want_codes)
        g["5"] = encode("", "", False)          # negative: never pay for the LLM twice
        positive, negative = ["4", 0], ["5", 0]

        if reference_audio is not None:
            g["10"] = {"class_type": "LoadAudio", "inputs": {"audio": reference_audio}}
            g["11"] = {"class_type": "VAEEncodeAudio",
                       "inputs": {"audio": ["10", 0], "vae": vae}}
            g["12"] = {"class_type": "ReferenceTimbreAudio",
                       "inputs": {"conditioning": positive, "latent": ["11", 0]}}
            positive = ["12", 0]

        g["6"] = {"class_type": "EmptyAceStep1.5LatentAudio",
                  "inputs": {"seconds": float(duration), "batch_size": 1}}

    else:  # "1.0"
        g["1"] = {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": v["checkpoint"]}}
        model, clip, vae = ["1", 0], ["1", 1], ["1", 2]
        g["4"] = {"class_type": "TextEncodeAceStepAudio", "inputs": {
            "clip": clip, "tags": tags, "lyrics": lyrics,
            "lyrics_strength": float(lyrics_strength)}}
        g["5"] = {"class_type": "TextEncodeAceStepAudio", "inputs": {
            "clip": clip, "tags": "", "lyrics": "", "lyrics_strength": 1.0}}
        positive, negative = ["4", 0], ["5", 0]
        g["6"] = {"class_type": "EmptyAceStepLatentAudio",
                  "inputs": {"seconds": float(duration), "batch_size": 1}}

    g["7"] = {"class_type": "KSampler", "inputs": {
        "model": model, "seed": int(seed), "steps": int(steps), "cfg": float(cfg),
        "sampler_name": sampler, "scheduler": scheduler,
        "positive": positive, "negative": negative,
        "latent_image": ["6", 0], "denoise": 1.0}}
    g["8"] = {"class_type": "VAEDecodeAudio",
              "inputs": {"samples": ["7", 0], "vae": vae}}
    g["9"] = {"class_type": "SaveAudio",
              "inputs": {"audio": ["8", 0], "filename_prefix": filename_prefix}}
    g["13"] = {"class_type": "SaveAudioMP3", "inputs": {
        "audio": ["8", 0], "filename_prefix": filename_prefix, "quality": mp3_quality}}
    return g


def recipe(**kwargs) -> dict:
    """The reproducible record of one generation, stored beside the audio.

    Same idea as panels.json's layer recipe in character-panel-mcp: a track you
    liked must be re-derivable, and a track you didn't must be diagnosable.
    """
    return {k: v for k, v in kwargs.items() if v is not None}
