# music-generation-mcp

Local BGM and vocal theme-song generation for the webcomic/anime pipeline, via
ComfyUI's native **ACE-Step** support. Hands back a lossless `.flac` and a
Remotion-ready `.mp3` from one generation pass.

This closes the last outsourced step in the video pipeline. The
[anime-production skill](../anime-production-skill/README.md) has always *played*
an mp3 but never made one — the mp3 came from Suno, a paid cloud service, which
is exactly the dependency this ecosystem exists to avoid (same category as Kling
for video and meshy.ai for props). Everything here runs on your own GPU at zero
per-call cost. See `ARCHITECTURE.md` §7a.

**Scope guard:** generation and beat analysis only. Mixing, mastering and stem
separation are a different product.

## Why ACE-Step

It is the only strong open local model that does *songs with vocals*. MusicGen
and Stable Audio Open are instrumental-only — fine for BGM, useless for a theme
song. **No custom ComfyUI nodes are needed**: ACE-Step 1.0 and 1.5 are both in
ComfyUI core as of 0.25. (Contrast the LTX video install, which needed
third-party GGUF loaders.)

## Variants

Two generations of the model, both supported; pick with `variant=`.

| | **1.5** (default) | **1.0** |
|---|---|---|
| Files | 4 split files, **10.0 GB** | one all-in-one checkpoint, **7.7 GB** |
| Controls | tags, lyrics, **language, bpm, key/scale, time signature, duration** | tags, lyrics, `lyrics_strength` |
| Voice steering | `ReferenceTimbreAudio` (experimental) | — |
| Loader | `UNETLoader` + `DualCLIPLoader(type="ace")` + `VAELoader` | `CheckpointLoaderSimple` |
| Speed | turbo — few steps | standard |

**1.5 is the default because of `language`.** The first real target for this
server is a Japanese vocal track, and 1.0 has no way to declare the language —
it infers it from the lyric script. 1.5's explicit `bpm` also matters downstream:
`extract_beats` detects tempo *after the fact*, but the video pipeline wants cuts
pinned to downbeats, and specifying 150 BPM at generation beats measuring it
afterward.

1.5 is the **larger** download, not the smaller one — it needs two text encoders
(a 0.6b base/lyrics encoder that is always loaded, plus a larger Qwen that acts
as a separate audio-code LLM). Keep 1.0 in mind as the fallback if 1.5's
Japanese vocals disappoint on a small card.

> `memory_usage_factor` in ComfyUI's `supported_models.py` reads 4.7 for 1.5
> against 0.5 for 1.0, which looks alarming and is not. The factors multiply
> different latent shapes: for a 120-second track, 1.0's latent is
> `[1,8,16,1292]` → ~207 MB attention working set, and 1.5's is `[1,64,3000]` →
> ~282 MB. Comparable. Weight streaming under `--lowvram`, not attention, is the
> real constraint on 6 GB.

## Models

Download into your ComfyUI tree, then **restart ComfyUI** — it caches some folder
listings at startup, so a freshly-added model can stay invisible until it does.
`check_status` reports what is missing.

**ACE-Step 1.5** — from
[`Comfy-Org/ace_step_1.5_ComfyUI_files`](https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files):

| File | → `ComfyUI/models/` | Size |
|---|---|---|
| `split_files/diffusion_models/acestep_v1.5_turbo.safetensors` | `diffusion_models/` | 4.79 GB |
| `split_files/text_encoders/qwen_0.6b_ace15.safetensors` | `text_encoders/` | 1.19 GB |
| `split_files/text_encoders/qwen_1.7b_ace15.safetensors` | `text_encoders/` | 3.71 GB |
| `split_files/vae/ace_1.5_vae.safetensors` | `vae/` | 0.34 GB |

**ACE-Step 1.0** (optional fallback) — `all_in_one/ace_step_v1_3.5b.safetensors`
from [`Comfy-Org/ACE-Step_ComfyUI_repackaged`](https://huggingface.co/Comfy-Org/ACE-Step_ComfyUI_repackaged)
into `checkpoints/`, 7.7 GB.

## Install

```bash
cd servers/music-generation-mcp
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe test_graph.py     # offline, no GPU needed
```

Register with your harness (stdio):

```json
{
  "mcpServers": {
    "music-generator": {
      "command": "C:/Users/<you>/webcomic-toolkit/servers/music-generation-mcp/.venv/Scripts/python.exe",
      "args": ["C:/Users/<you>/webcomic-toolkit/servers/music-generation-mcp/server.py"]
    }
  }
}
```

## Tools

| Tool | What it does |
|---|---|
| `generate_track` | One track. Blocking, minutes on a 6 GB card. |
| `generate_variations` | Re-run a track's recipe under new seeds — the audition loop. |
| `list_tracks` | Terse listing (id, title, duration, mp3 path). |
| `get_track` | One track's full recipe and file paths. |
| `approve_track` | Lock a take as canon and publish it as `FINAL_<slug>.*`. |
| `forget_track` | Delete a take. Refuses the approved one. |
| `extract_beats` | Beat grid + energy envelope, so video cuts land on downbeats. |
| `check_status` | ComfyUI reachable? VRAM? Which model files are missing? |

### Approving a take

Track ids carry a timestamp, so auditioning cannot overwrite a good take — but
that makes them a poor handle for downstream tools, which should not need to
know that `full_bminor_107s_20260807_004333` is "the theme song".
`approve_track` publishes the winner under a stable name at the project root:

```
output/<project>/FINAL_theme.mp3          <- point Remotion here
output/<project>/FINAL_theme.flac
output/<project>/FINAL_theme_beats.json
```

The `FINAL_` prefix is the same convention the panel pipeline uses, and this
repo's standing rule is that generated attempts under `output/` may be
bulk-deleted freely while an approved `FINAL_` never is — so the existing
protection applies without anyone having to remember. `forget_track` enforces it
in code as well, refusing to delete an approved take.

## Output layout

```
output/
  tracks.json                     the library manifest
  <project>/<track_id>/
    <track_id>.flac               lossless keep
    <track_id>.mp3                Remotion drop-in
    <track_id>.json               the recipe — every parameter, reproducible
    beats.json                    written by extract_beats
```

Track ids carry a timestamp. Auditioning produces many takes of one title, and a
good take being silently overwritten by a worse one is the expensive failure.

## Working notes

- **ComfyUI runs prompts serially.** Submit one generation at a time; a stacked
  job just burns its timeout waiting in the queue.
- **Songs need auditioning — one take is never enough.** Generate, listen, then
  `generate_variations` on whichever came closest. Iteration costs GPU-minutes
  (free, local), not tokens: the reviewer is your ears, and the model never has
  to "listen back".
- **Hunt directions at short durations.** 20-30 s settles whether a `tags` string
  is going anywhere. Commit to 120 s once it is.
- **Sampling defaults are starting points, not verified settings.** `steps`,
  `cfg`, sampler and scheduler in `ace_workflow.VARIANTS` have not been swept on
  this hardware. `tools/ace_run.py` is the sweep harness — the same role
  `ltx_run.py` played when it found LTX's real settings. Write what you learn
  into the repo's `CLAUDE.md`.
- **Judge by ear.** There is no motion-metric equivalent here, and no spectral
  statistic tells you whether you like the vocal — which is the whole reason this
  server exists.

### `extract_beats` — pure Python, no Node and no ffmpeg

`tools/beats.py` is a port of the anime-production skill's `extract-beats.mjs`
onto the same `numpy` + `soundfile` path `analyze_reference.py` uses. Same
algorithm, **same output schema**, so the JSON stays a drop-in for Remotion.

The port exists because the `.mjs` decodes via ffmpeg, which this machine does
not have and which the author declined to install. `soundfile` bundles
libsndfile and reads MP3/FLAC/WAV/OGG directly, so this needs nothing that was
not already required. The skill keeps its own `.mjs` — it finds ffmpeg inside
Remotion's bundled compositor package — so the video pipeline is unaffected.
Two implementations of one algorithm: fix a bug in one, port it to the other.

**Pass `bpm` when you know it.** For tracks this server generated, tempo was an
*input*, so `extract_beats` reads it from the recipe instead of detecting it —
exact by construction. Detection is for reference tracks and outside audio.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI endpoint (shared with the sibling servers by convention). |
| `WEBCOMIC_MUSIC_COMFY_DIR` | `C:\AI\ComfyUI_windows_portable` | For auto-launch. |
| `WEBCOMIC_MUSIC_COMFY_LAUNCH` | `run_nvidia_gpu.bat` | Launcher script. |
| `WEBCOMIC_MUSIC_AUTOLAUNCH` | `1` | Set `0` to require ComfyUI already running. |
| `WEBCOMIC_MUSIC_TIMEOUT` | `1800` | Seconds to wait for one generation. |
| `WEBCOMIC_MUSIC_OUTPUT` | `./output` | Track library root. |

There is no ffmpeg setting. `extract_beats` reads audio through `soundfile`, so
there is no binary to point at.

## Integration

Fills the empty `"video": { "music": "" }` field in a project manifest
(`ARCHITECTURE.md` §6), and pairs with the anime-production skill's beat-sync —
the existing teaser already lands cuts on downbeats at 0.0 ms error against a
150 BPM track.
