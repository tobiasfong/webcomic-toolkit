# music-generation-mcp — agent notes

Local BGM and vocal theme generation through ComfyUI's native ACE-Step
support. One generation pass hands back a lossless track and a video-ready
one, plus the beat grid the animation pipeline cuts to.

- **The repo's root `AGENTS.md` governs everything here**, and its music
  section is the manual: feed the model song-length lines, count lyric
  density in morae per bar, describe the SCENE rather than the arrangement,
  set the key deliberately, sweep seeds on a fixed tag string because
  rewording re-rolls the composition, and cut a loop to whole bars delivered
  as OGG. Each of those was measured, and the failed alternatives are listed
  so they are not retried.
- `tools/analyze_reference.py` measures bpm and key from any track and flags
  relative major/minor pairs; reconcile a measured tempo against the
  requested one by their ratio before trusting either. `tools/build_arc.py`
  shapes a take deterministically when it repeats instead of building;
  `tools/trim_audio.py` cuts on a downbeat.
- Judge by ear. The compression ratio catches silence and noise; no
  statistic says whether a vocal is any good, which is why this server
  exists.
- After editing anything under this folder: `python -m pyflakes` over what
  you edited, and read its output after editing, not before.
