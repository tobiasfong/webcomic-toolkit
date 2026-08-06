# Changelog — music-generation-mcp

## v0.1.0 — 2026-08-06

First cut. Implements `ARCHITECTURE.md` §7a, which had been sitting as
"planned, not built" with three questions marked *undecided — resolve before
building*. All three are now resolved:

### §7a's open questions, answered

**"Model. ACE-Step is the obvious candidate."** Confirmed, and better than
expected: ComfyUI has shipped ACE-Step natively since ~0.25, so **no custom
nodes are needed at all**. `comfy_extras/nodes_ace.py` provides both
generations. This is a materially easier install than the LTX video path, which
needed city96's third-party GGUF loaders.

**"Whether 6 GB is enough. Untested. Assume quantisation will be needed, as
with LTX-2.3 and FLUX Kontext."** No quantisation is available or needed —
Comfy-Org publishes bf16 split files and ComfyUI streams weights. **Verified
later the same day: yes, comfortably** — ~5.9 GB peak for a 120 s track, no
OOM, and faster than real time. `--lowvram` turned out to make no measurable
difference. See "Verified live" below.

**"Language. Vocal quality in Japanese specifically must be auditioned."**
It drove the variant choice: **1.5 is the default because it has an explicit
`language` input including `ja`**; 1.0 has no way to declare a language and
infers it from the lyric script. **Auditioned the same day** across six rounds
of author feedback — see v0.2.0.

### Built

- `ace_workflow.py` — graph construction for both variants behind one
  `variant=` switch, the same shape `ltx_run.py` uses. Ships a fallback path,
  not a rewrite, if 1.5 disappoints.
- `comfy.py` — ComfyUI plumbing. A near-copy of `character-panel-mcp`'s, kept
  duplicated so this folder stays independently installable. Diverges where
  audio does: outputs arrive as an `audio` list rather than `images`, one graph
  emits several files, and the default timeout is 1800 s rather than 300 —
  sampling two minutes of audio on a small card is nothing like an image.
- `tracks.py` — per-project track library. Namespaced from day one; the
  background server had to retrofit that at v1.2.0 and §8b.1 says explicitly not
  to repeat it. Track ids carry a timestamp so auditioning cannot silently
  overwrite a good take with a worse one.
- `server.py` — six tools: `generate_track`, `generate_variations`,
  `list_tracks`, `get_track`, `extract_beats`, `check_status`.
- `tools/ace_run.py` — standalone CLI driver for sweeping settings without MCP
  in the way, mirroring `ltx_run.py`.
- `tools/extract-beats.mjs` — duplicated from the anime-production skill at the
  author's direction, so both pipelines own a copy. Analysis code identical; the
  one divergence is a `--ffmpeg` flag, since the skill's copy resolves ffmpeg
  inside Remotion's bundled compositor package and this server has no Remotion.
- `test_graph.py` — 28 offline checks, no GPU required. All pass.

### Decisions worth keeping

- **1.5 is the bigger download, not the smaller one** — 10.0 GB against 1.0's
  7.7 GB. It needs *two* text encoders: `comfy/text_encoders/ace15.py` always
  builds a qwen3_06b for the base/lyrics embedding, and the larger Qwen is a
  separate autoregressive audio-code LLM. So it is `DualCLIPLoader(type="ace")`,
  never `CLIPLoader` — a single-file load silently lands on 1.0's T5 path
  instead (`comfy/sd.py:1527` vs `:1692`). Chosen anyway, for `language`/`bpm`.
- **`memory_usage_factor` 4.7 vs 0.5 is not an OOM signal.** The factors
  multiply different latent shapes. For 120 seconds: 1.0 is `[1,8,16,1292]` →
  ~207 MB attention working set, 1.5 is `[1,64,3000]` → ~282 MB. Comparable.
- **`duration` and `seconds` must agree.** `TextEncodeAceStepAudio1.5` takes a
  `duration` used for conditioning while `EmptyAceStep1.5LatentAudio` takes a
  `seconds` that sets the real latent length. Nothing checks that they match, and
  a mismatch conditions the model for one length while sampling another. Both are
  derived from one argument, and `test_graph.py` asserts it.
- **The negative conditioning must not re-run the audio-code LLM.**
  `generate_audio_codes` defaults to True; leaving it on for the negative pays
  for a second autoregressive pass that is then discarded — and at cfg 1.0 the
  negative is not even used. Forced off.
- **FLAC and MP3 come out of one sampling pass.** The extra encode is free next
  to sampling, and the pipeline wants both: lossless to keep, mp3 for Remotion.

### Verified live, same day

Four real generations ran end to end, through both the CLI driver and the MCP
`generate_track` path:

| run | duration | wall time | peak VRAM |
|---|---|---|---|
| lo-fi instrumental smoke test | 20 s | 21 s | ~5.65 GB |
| セカンドチャンス, male vocal, ja | 120 s | 105 s | — |
| セカンドチャンス, female vocal, ja | 120 s | 93 s | — |
| A/B re-run, male, `--lowvram` | 120 s | 87 s | 5972 MiB |
| A/B re-run, male, plain launcher | 120 s | 91 s | 5904 MiB |

- **6 GB is enough.** No OOM at any point, no quantisation available or needed.
- **It runs faster than real time**, which inverts §7a's assumption that
  auditioning would be costly. `generate_variations` at n=5 is ~9 minutes.
- **`--lowvram` is not needed.** 87 s/5972 MiB with it vs 91 s/5904 MiB without,
  same graph and seed — inside run-to-run noise, and neither OOMs. Use the plain
  `run_nvidia_gpu.bat`, which is what `comfy.py` already defaults to. The flag was
  inherited from an already-running ComfyUI process and assumed deliberate; it
  was not.
- **Output is structurally sound**: exactly 120.00 s at 48 kHz stereo 16-bit,
  confirming the `duration`/`seconds` coupling holds live. Compression ratios of
  27% (sparse lo-fi) and ~60% (full band with vocals) sit where real music sits —
  a silence/noise sanity check, not a quality judgement.
- `tools/inspect_audio.py` added for that check: parses FLAC STREAMINFO, needs no
  ffmpeg.

### Fixed during the build

- **`mcp` pinned to `<2`.** mcp 2.0.0 removed `mcp.server.fastmcp`, which every
  Python server in this repo imports; the unbounded `mcp>=1.2.0` here resolved
  straight to it and died at import. The same latent break existed in all three
  sibling servers' requirements (their venvs predate 2.0, so only fresh installs
  were affected) — bounded in all four at the author's direction and verified:
  bounded resolves to 1.29.0, unbounded to 2.0.0.

### Open at v0.1.0 — see v0.2.0 below for what has since been resolved

- Sampling defaults (`steps=12`, `cfg=1.0`, `euler`/`simple`) were never swept.
  Still true.
- Whether the Japanese vocals are any good — **resolved by audition**: six
  rounds of author feedback converged on a settled recipe. See v0.2.0.
- `ReferenceTimbreAudio` wired but never run. Still true.

### v0.2.0 — same session

- **`extract_beats` ported to pure Python and RUN.** `tools/beats.py` reimplements
  the skill's `extract-beats.mjs` on the `numpy`/`soundfile` path, dropping both
  Node and ffmpeg — the author declined to install ffmpeg, and `soundfile`
  bundles libsndfile so nothing new was needed. Same output schema, so it stays
  a Remotion drop-in. The `.mjs` duplicate added earlier this session is removed
  here; the skill keeps its own copy, which finds ffmpeg inside Remotion.
  Verified on the winning track: 268 beats, 67 downbeats, bar 1.600 s — and
  **67 bars is exactly the budget predicted for a 107 s track**, an independent
  confirmation of the density arithmetic in CLAUDE.md.
- When a track was generated here, `extract_beats` now takes bpm from the recipe
  instead of detecting it. Tempo was an input; detection can only be worse.
- `tools/analyze_reference.py` added: measures bpm and key of any mp3/flac/wav so
  those parameters come from measurement, not guesswork. Validated against known
  inputs (152.0 measured vs 150 requested). It cannot separate relative
  major/minor pairs — nothing chroma-based can — and says so when it sees one.
  That limitation is itself what proved requesting `B minor` returns D major's
  pitch collection.
- **`generate_variations` run live**: 5 takes in 380 s. Combined with the
  original, a 6-seed sweep at one config showed 4 half-time / 2 full-tempo,
  the only distribution-backed claim in this work.
- **Near-miss fixed before the first push:** `.gitignore` had `!output/tracks.json`
  to preserve the library manifest — but recipes embed lyrics, and this repo is
  public, so that would have published the author's unreleased song text. `output/`
  is now ignored wholesale and the reason is recorded in the file. A real lyric
  line used as a test fixture in `test_validate_live.py` was replaced too.

- **`approve_track` / `forget_track` added.** Track ids carry a timestamp so
  auditioning cannot clobber a good take, which makes them a bad handle for
  downstream tools. `approve_track` publishes the winner as
  `FINAL_<slug>.{mp3,flac}` + `_beats.json` at the project root — the same
  `FINAL_` convention the panel pipeline uses, so the repo's "never delete an
  approved FINAL_" rule covers it automatically. `forget_track` enforces that in
  code too, refusing an approved take; the guard was tested before being relied
  on, which matters because 22 tracks were script-deleted in this same session.
- **RxR's theme song is settled**: seed 9242, published as
  `FINAL_second_chance.*`. 107 s, 150 BPM, B minor, 4/4, `ja`, sectioned lyrics
  with a blank line between every sung line. Beat grid: bar 1.600 s, 67
  downbeats, offset 0.355 s.

### Open — still not verified

- **Sampling defaults are starting points, not swept settings.** `steps=12`,
  `cfg=1.0`, `euler`/`simple` produce usable audio, but nothing has been compared
  against them. The LTX experience says defaults are often the trap
  (`strength=1.0` froze every clip for six experiments). Sweep with
  `tools/ace_run.py`.
- `ReferenceTimbreAudio` is marked `is_experimental=True` in ComfyUI. Wired and
  unit-tested; never run. It is the next lever if a vocal is close but wrong —
  vocal register turned out not to be controllable by tag wording.
