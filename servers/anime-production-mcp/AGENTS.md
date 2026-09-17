# anime-production-mcp — agent notes

Turns finished illustrations into an animated video cut to music, entirely
locally: LTX image-to-video through ComfyUI for motion, drawn effects
(impact, streaks, glow, water, motion lines) for what generation cannot do,
and assembly to the beat grid from the music server.

- **The repo's root `AGENTS.md` governs everything here**, and its video
  section is the manual: distilled for motion, the two levers that actually
  work (image strength and frame rate), render near the source's native
  resolution, ask for small motion and never rotation, animate the
  environment rather than the character, do mouths with the frame player,
  and the table of settings that were tested and failed so nobody retries
  them. Judge frames by eye, not by the motion metric.
- `../anime-production-skill/` ships a vendored copy of this server's
  pipeline, because a skill installs by being copied elsewhere and must be
  self-contained. The server is canonical: after editing its tools run
  `python sync_skill.py --check`, and `python sync_skill.py` to bring the
  copy current. The copy was once found three weeks stale while its docs
  promised parity.
- Effects that are made of light on a surface are drawn; solid objects are
  generated. Bloom needs a white-hot core, several summed blur radii and
  additive accumulation, or it reads as a blurred copy.
- After editing anything under this folder: `python -m pyflakes` over what
  you edited, and read its output after editing, not before.
