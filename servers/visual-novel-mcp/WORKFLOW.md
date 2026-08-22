# Visual novel workflow

Branching VN production on top of the webcomic-toolkit asset pipeline.
Engine: Ren'Py. The human author owns every story decision and every
approval; this server owns bookkeeping, validation, and derived structure.

## The one rule

**The .rpy scripts are the single source of truth for the branch graph.**
Labels, jumps, menus, and flags are derived by parsing the scripts — never
retype or summarize graph structure into prose or state. What the state file
holds is only what a script cannot express: synopses, flag meanings,
continuity notes, approval status, the sprite manifest.

## Loop (per scene, designed for a fresh chat per scene)

1. `get_scene_context(scene_id)` once — synopsis, neighbors, flags in scope,
   characters with their registered expressions, relevant notes.
2. Write or revise the scene IN CHAT first when the author is present; use
   `save_scene` to commit. It parses the script immediately and reports
   dangling jumps, unknown flags, and unresolved sprites while the context
   is still warm.
3. Record judgment calls with `record_note`, new flags with `define_flag`
   (meaning included — a flag without documented semantics is a future bug).
4. `check_story()` before ending a session. Non-zero problems means the
   graph cannot be trusted yet.
5. The author approves scenes; status moves to "approved" only on his
   explicit say-so. An approved scene whose file changes is flagged.

## Sprites

One matted body + hand-drawn face patches (deltas over the approved face).
Bodies are never re-rendered per expression — pixel-identical bodies are what
keep sprites from jittering mid-conversation.

- `register_sprite` copies the matted body into the game tree.
- The author draws patches; `register_expression` places one at a pixel
  offset; `preview_expression` renders the alignment check over magenta.
- `emit_sprites` regenerates `sprites_generated.rpy` — never hand-edit it.
- Mirroring: check `mirror_ok` before flipping a sprite; asymmetric costume
  details (one-sided blossoms) make mirroring a redraw, not a flip.

Character appearance still resolves from the character bible, never from
memory (repo rule). Event CGs use the normal panel pipeline and its rules.

## Privacy

Game content (scripts, names, world detail) must never reach the public
repo. The game tree and state live under gitignored paths — verify with
`git check-ignore` before creating files anywhere new.

## Fresh-chat economics

State lives on disk. Prefer a new session per scene over one mega-chat;
`get_scene_context` restores everything needed. Same philosophy as the
novel-translation server.
