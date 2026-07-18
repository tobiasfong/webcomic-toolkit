# Changelog

All notable changes to the Character & Panel Generator MCP server are documented
here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This server lives in the [`webcomic-toolkit`](https://github.com/tobiasfong/webcomic-toolkit)
monorepo (`servers/character-panel-mcp`) alongside its sibling servers from day one;
releases are tagged `character-panel-mcp@vX.Y.Z`.

## [1.0.0] — 2026-07-18

### Added
- **Character Bible** (`register_character`, `list_characters`, `forget_character`,
  `list_projects`) — the character-domain sibling of `webcomic-background-mcp`'s
  World Builder. Unlike a location's single canonical image, a character has a
  *set* of reference images (turnarounds, expression sheets); re-registering an
  existing character appends to the set instead of replacing it.
- **`generate_character_pose`** — Tier 1 of the three-tier consistency design
  (img2img seeded from the character's primary reference, onto a clean backdrop),
  auto-matted to RGBA via `rembg`.
- **`compose_panel`** — deterministic CPU compositing of a matted character onto a
  background plate, feet-anchored (`feet_x`/`feet_y`/`height_px`) to match the
  exact shape `webcomic-background-mcp`'s `generate_city_scene` anchor tool already
  reports, so the two servers' outputs chain directly. Supports multi-character
  panels by chaining calls (`base=<previous output>`).
- **`check_status`** — ComfyUI reachability check, same as the background server.
- Tier 2 (IP-Adapter + OpenPose ControlNet) and Tier 3 (per-character LoRA baking)
  are designed but deliberately not built this release — see README.md's
  "Consistency tiers" section.
