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

## Ren'Py engine traps

Every one of these was hit in practice and cost real debugging. They are
grouped by what they break, and none of them are caught by `renpy lint`.

### A bare string in a `label` is a SAY STATEMENT, not a docstring

A label is Ren'Py SCRIPT, not a Python function. A triple-quoted string at
the top of one is not documentation — it is narration, and it is read to the
player every time the label runs.

Written out of Python habit on a helper label called by every attack in a
fight, this narrated three paragraphs about millisecond timing to the player
on each swing, mid-combat. It reached a screenshot before anyone caught it.

Nothing warns you. It is valid script, so `lint` passes and the word count
rises by an amount nobody is watching. What makes the habit feel safe is that
functions inside an `init python:` block in the same file DO take real
docstrings — so the convention is correct four lines away from where it
speaks.

    label battle_fx(plate):
        """Play one attack's impact."""     # <- SPOKEN ALOUD
        $ ...

Use `#` comments above the label instead. To audit: for every line matching
`^label\s`, the next non-blank line must not start with `"""` or `'''`.

### `scene` clears the figures, so a speaker after one has no sprite

`scene` replaces the background AND empties the master layer. Every plate
change therefore needs the sprites re-shown behind it, including the ones that
were standing there a line ago.

Hit three times in one session, each with a plausible-sounding excuse:
characters spoke from an empty courtyard after arriving, again after a fight
whose label hides every figure before drawing its own stage, and again through
an illusion on the reasoning that "the plate is the subject of this beat". It
never is. If somebody speaks, they are present.

Nothing catches it — the script is valid, `lint` passes, and the only symptom
is a voice with no body. To audit, walk the scenes IN JUMP ORDER tracking
`show` / `hide` / `scene` / `call battle_*`, and flag any speaker whose tag is
not currently shown. Two things that audit must get right, or it reports noise:

* **Carry the shown set ACROSS files.** The master layer survives a jump, so
  auditing each file from an empty stage flags everyone who walked in during
  the previous scene. Done wrong this reported 19 problems; done right, 4.
* **A CG depicts its characters.** Suppress the check while a `scene cg` is up,
  and remember that a prop reveal on a black field (`scene bg black` plus
  `show prop ...`) is the same thing. All four survivors above were that.

### A BRANCHING jump breaks script_diff's file ordering

`script_diff` derives its scene order by following the jump chain, and it
resolves a jump target to a file BY NAME. Three labels living in one file are
unreachable that way, so the chain comes up short and the tool falls back to
sorting the scenes alphabetically — which is silent, and catastrophic for the
comparison: the lesson sorted before the summons, the whole prologue landed
last, and 235 blocks were reported unconverted when nothing was missing.

Every choice before this one was a `call screen` that set a variable and
carried straight on, so a linear chain had always been enough.

**Keep a branch inside a single file whose label matches its name.** Jump to
that file, branch within it, and let all arms converge on one jump out.

### Text substitution EVALUATES what is inside the brackets

`[name]` is not a format key — Ren'Py evaluates the expression. So a menu
caption containing `[pp[fire]]` looks for a **variable** called `fire` and
raises `NameError: name 'fire' is not defined`. It raises while BUILDING the
menu, so the symptom is a menu that renders no options at all, and the next
click surfaces the traceback. Quoting inside the brackets does not fix it.

Pull values into plain names first, or hang them off an object — `[s.pp]`
(attribute access) is safe, `[d[key]]` (subscript by bare word) is not. Grep
for the shape before shipping:

```
rg '\[[A-Za-z_][A-Za-z0-9_]*\[[A-Za-z_]' --glob '*.rpy'
```

### Screens draw ABOVE the master layer, always

A screen cannot appear behind a sprite that a scene left showing. A battle
screen built over a scene that had already run `show <mob>` rendered on top of
full-height dialogue-scale figures, plus a second copy of the protagonist.

Take the figures down on entry and leave the background alone:

```
python:
    for _tag in list(renpy.get_showing_tags()):
        if not _tag.startswith(("bg", "cg", "fx")):
            renpy.hide(_tag)
```

Within the screens layer, zorder still decides order, and the say window sits
at **0**. A stage of sprites therefore needs a NEGATIVE zorder or it covers its
own dialogue. Status boxes and command menus go above 0.

### `centered` is the time-card style, not a message style

`centered` is its own character with its own style (`centered_text`) and
inherits nothing from the NVL styles. Sized for title cards (84 px here), it
writes a combat telegraph across the whole screen in letters the height of a
character sprite. In-engine messages need their own `Character(None, ...)`
with a `window_style` that puts them in a box.

### NVL positions the name and the dialogue ABSOLUTELY, in one `fixed`

See `screen nvl_dialogue` in the stock `screens.rpy`: nothing separates the two
automatically. Identical `xpos` and `ypos` means they are drawn on top of each
other — a two-word speaker name wrapped inside its box and the dialogue printed
straight through it. Separate them by COLUMN (stock does this with
`nvl_name_xalign = 1.0`, so `nvl_name_xpos` is the name's right edge) or by
ROW (give the name the full text width and push the dialogue's `ypos` past it).

### Auto-forward is calibrated for ADV line lengths

```
delay = (config.afm_bonus + characters) / config.afm_characters * afm_time
```

`config.afm_characters` defaults to 250 — about one line of a bottom textbox.
Against paragraph-length NVL blocks (108 characters average, 409 longest, in
one real script) the stock value gave **8 seconds typical and 26 seconds
worst**, which reads as a dead button. Worse, clicking to check whether it is
working turns it back off (`renpy/display/behavior.py:798`), so it never
appears to work.

Raise `config.afm_characters` rather than lowering the `afm_time` default:
`afm_time` is a stored preference, so a new default does nothing for a profile
that has already played. 900 gave ~1.7 s median, ~7 s worst.

### The bundled font has NO CJK glyphs

DejaVuSans renders every kanji as an empty box. Verify coverage per script
rather than assuming — render a character and compare its ink against a script
the font certainly lacks (Devanagari, Thai); a `.notdef` box is byte-identical
across all of them. Noto Sans JP covers kana and kanji; **Hangul is tofu in it**
and needs Noto Sans KR as a separate file.

Wire it as a `FontGroup` mapping codepoint ranges, so Latin keeps rendering in
the original face and only CJK switches. Apply it to the STYLES, not to
`gui.text_font`: the gui7 generator in `guisupport.rpy` re-renders the
interface images at startup from the `gui.*` font values and expects a path
string, not a font object.

### Leading underscores are reserved

Store variables named `_x` are excluded from saves and rollback. They appear to
work inside one interaction and are a latent bug. Use plain names.

### `vpgrid` requires uniform cell size

Both axes. It is the right container for a command list that grows past one
screen — it scrolls with the mouse wheel, drags, and follows keyboard focus —
but every child needs an explicit `xsize` AND `ysize`.

### Stock GUI values are 720p-era

`gui.scale()` in `guisupport.rpy` is the identity function, so every number in
`gui.rpy` is raw pixels. A project that called `gui.init(1920, 1080)` still
carries the template's 720p constants: text columns that reach halfway across
the frame, and a 14 px quick-menu bar. Check them against the real canvas
before concluding a layout is "just how Ren'Py looks".

### A full-screen scrim is the wrong way to make text readable

At the opacity text needs (~85 %), a translucent panel over the whole frame
erases the art behind it. Legibility travels better ON the glyphs: outlines (a
dropped shadow plus a crisp dark edge) cost nothing where they are not needed.
If a scrim helps, gradient it so it darkens only the band the text occupies.

## Tools

`tools/` holds the standalone scripts. **None of them may hardcode a path into
a game tree** — the project slug is private and this directory is public, so
they take the path as an argument (`vnpaths.game_dir`, or `VN_GAME_DIR`).

| tool | what it does |
|---|---|
| `script_diff.py` | diffs the author's docx master against the converted scenes |
| `fx_plates.py` | draws impact plates — convergence bursts, slash beams, an ice crescent |
| `make_nvl_scrim.py` | draws the NVL scrim gradient |
| `make_battle_ui.py` | draws the battle panel and selection cursor as 9-patch frames |
| `serve_web.py` | serves a web build with threading and Range support |
| `install_renpy.py` | downloads the pinned SDK and its separate web component |
| `renpy_sdk.py` | resolves where that SDK is — nothing else may hold a path |
| `build_web.py` | builds the browser version, and can serve it |

The drawing tools exist because their output is GEOMETRY — lines meeting at a
vanishing point, an arc of exact curvature, a rounded panel that stretches
without distorting its corners. Diffusion cannot place geometry where you ask
for it, and it turns fine repeated marks into texture. Drawn, they are exact,
instant, recolorable, and reusable. Regenerate from the script; never edit the
PNGs.

`script_diff.py` needs the project's own spec vocabulary to tell an author's
inline notes from prose, and that vocabulary IS story content — so it lives in
a `patterns.json` beside the game tree, not here. Without one the tool falls
back to generic defaults and will report spec blocks as unconverted story.

## Verifying

`renpy lint` parses; it does not execute. It passed on the menu that crashed
the moment it drew. Two checks that do catch things:

- **Simulate the logic.** Extract an `init python` block, `exec` it, and drive
  the label's control flow in plain Python — 120 simulated playthroughs
  confirmed a fight terminated, never soft-locked on spent PP, and stayed
  unlosable.
- **Composite the screen before shipping it.** Paste the sprites at their real
  scale onto the real background and draw every UI box at its real size. This
  caught heads cropped above the frame, a status box overlapping a panel, and a
  sprite picked from a turnaround sheet that was a three-quarter view rather
  than the back view it looked like at thumbnail size.

## Web builds

- The command is `launcher web_build`. `distribute --package web` produces a
  zip of game files with no runtime, and `--launch` starts a server and exits.
- **Pass the launcher as an ABSOLUTE path.** `renpy.exe launcher web_build
  <project>` resolves `launcher` against the CURRENT DIRECTORY, not against the
  SDK, so it works when run from the SDK folder and fails everywhere else:

      Base directory 'C:/.../launcher' does not exist. Giving up.

  That message names the caller's directory, so it reads as a missing or
  corrupted SDK. The SDK is fine; only the argument was relative. Write
  `renpy.exe "<sdk>\launcher" web_build "<project>"` and the cwd stops
  mattering. A double-clicked launch script is exactly the case that exposes
  this, because its cwd is its own folder rather than the SDK's.
- **Bind the port before opening the browser.** A script that opens the browser
  and then starts the server races it, and the reader gets
  `ERR_CONNECTION_REFUSED` — indistinguishable from a build that failed.
  `serve_web.py --open` opens it after the socket is listening.
- **The port is part of the save file's address.** Browser saves are per
  origin, so serving on a different port hides every existing save without
  deleting anything. Pick one port and keep it.
- Serve over HTTP; browsers block WebAssembly and service workers on `file://`.
  `python -m http.server` drops Ren'Py's large concurrent fetches — the server
  needs threading and Range support.
- **Stop that server before rebuilding.** It holds the distribution directory
  open and the build dies with `PermissionError: [WinError 32]`.
- Tell the author to hard-refresh: the service worker will otherwise serve the
  previous `game.zip`.
- Large images are deferred to progressive download with placeholders left in
  `game.zip`; fonts are not. A CJK font lands entirely in the initial download.

## Privacy

Game content (scripts, names, world detail) must never reach the public
repo. The game tree and state live under gitignored paths — verify with
`git check-ignore` before creating files anywhere new.

**This file is tracked.** Keep character names, project names, and story
detail out of it — describe mechanisms, not the work they were found on.

## Fresh-chat economics

State lives on disk. Prefer a new session per scene over one mega-chat;
`get_scene_context` restores everything needed. Same philosophy as the
novel-translation server.
