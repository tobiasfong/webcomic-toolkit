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

### The image TAG is the first word, so `fx snow` and `fx slash` are one image

Ren'Py takes the first word of an image name as its tag, and one tag holds one
displayable. So `fx snowfall`, `fx ice burst`, `fx slash thunder` and every
other plate named `fx something` are all the SAME tag -- `fx`.

Two failures came out of that in one scene, and neither raises anything:

1. **Z-ORDER IS FIXED WHEN THE TAG FIRST APPEARS.** Ambient snow was shown
   right after the `scene`, before the sprites, which put the `fx` tag below
   them. Every impact plate afterwards replaced that same tag and inherited
   its position, so the flashes played BEHIND the characters.
2. **THE AMBIENT EFFECT DIES AT THE FIRST IMPACT.** Showing a plate replaces
   the tag, and the `hide` after the flash removes it -- so the snow stopped
   for the rest of the scene the first time anything was cast.

Give a persistent effect its own tag: `show fx snowfall as snow`. Then the
weather keeps its low position and impact plates stack on top as a fresh tag.

Lint cannot see any of this; both states are valid. It is caught by watching
the scene, or by asking why an effect that clearly rendered is not in front.

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

## Generating scenes from the master document

Where an author writes prose in a word processor and the game is Ren'Py, the
cheapest arrangement is a small per-chapter script that reads the document and
writes the scene files: the STRUCTURE is chosen in the script (which paragraph
gets which speaker, where the plate changes, where a fight is called) and the
WORDS come out of the document untouched. Rerun it after the author edits and
the prose follows.

The reason to bother is not tidiness. Retyping a chapter of somebody's prose
is how a wrong word gets into the game and stays there, and a session that has
just spent a round fixing the author's typos should not be adding its own.

Four things this has to get right, each learned by getting it wrong.

**An emitter must own a BOUNDED span — a start anchor AND an end anchor.**
The obvious shape is "everything after the line where my chapter begins", and
it works perfectly until the author writes the next chapter. Then that emitter
silently swallows the new material too and rewrites another emitter's scene
with it. Nothing fails: the files are written, the script prints its usual
summary, and the only symptom is `script_diff` reporting differing regions and
a DROPPED line — which reads like the author cut something. One emitter here
reported 371 paragraphs where it owned 86.

**Chain links belong IN the emitter, not appended to its output.** A
`jump` added to a generated file by hand survives exactly until the next
regeneration, which rewrites the whole file. The chapters then become
unreachable and `script_diff` falls back to alphabetical ordering, producing a
diff full of blocks that are not actually missing. If a scene jumps onward,
the script that writes that scene writes the jump.

**Resolve positions BY CONTENT, never by paragraph number.** Indices shift
the moment the author inserts a line, and an index that has quietly moved
points at the wrong prose without complaining. Search for a distinctive
phrase instead, and search FORWARD from the previous anchor so the same
phrase occurring twice cannot capture the wrong one.

**Escape first, then substitute.** Any escaping pass that protects the
author's own brackets from being read as interpolation will also mangle a tag
the emitter inserted beforehand — `[_limb]` came out as `[[_limb]` and
rendered literally on screen. Build the escaped string, then substitute into
it.

Two smaller notes. Author-to-implementer asides ("Scenario 1:", "(Timeskip,
so bigger font)") are structure, not narration, and belong in patterns.json's
spec markers so they never reach a player. And a sentence's full stop can sit
AFTER a closing bracket — `...I lower my hand (sword if ..., hand if ...).` —
so a pattern anchored at end-of-string silently matches nothing and the note
ships in the game text.

## Tools

`tools/` holds the standalone scripts. **None of them may hardcode a path into
a game tree** — the project slug is private and this directory is public, so
they take the path as an argument (`vnpaths.game_dir`, or `VN_GAME_DIR`).

| tool | what it does |
|---|---|
| `blood_overlay.py` | Draw a dried-blood layer for a matted character sprite |
| `build_web.py` | Build the browser version of a Ren'Py project, and optionally serve it |
| `choice_glyphs.py` | Draw pictogram choice cards: flat symbols, not illustrations |
| `choice_squad.py` | Build a choice card from registered sprites: a group, on a dark field |
| `combat_calls.py` | Every combat the document SPECIFIES must be one the player actually fights |
| `convert_scene.py` | Turn a hand-written Ren'Py scene into an emitter that regenerates it from |
| `decay_overlay.py` | Draw an ADDITIVE decay layer for a background plate: mold, rust, stains, |
| `draw_ctc.py` | Draw the click-to-continue mark: a right-pointing triangle centered on a line-tall canvas |
| `emitlib.py` | The helpers every scene emitter needs, defined ONCE |
| `fx_plates.py` | Draw the fight-scene impact plates: convergence bursts, slash beams, and |
| `import_sfx.py` | Import downloaded sound effects into the game, matched to the beats |
| `install_renpy.py` | Download and install the Ren'Py SDK, so the harness does the setup |
| `make_battle_ui.py` | Draw the battle UI panels: the box frame and the selection cursor |
| `make_nvl_scrim.py` | Draw the NVL scrim: a vertical fade that darkens ONLY the band the text |
| `menu_fx.py` | Draw the ambient pieces a static title screen needs to stop feeling dead |
| `night_sky.py` | Replace a daytime sky with a drawn night sky, and grade the rest to match |
| `nvlpage.py` | The NVL page model: which entries share a screen, and how tall it is |
| `optimize_png.py` | Losslessly shrink every PNG under a Ren'Py project's game folder |
| `paginate_nvl.py` | Place NVL page breaks by measured height -- Fate-style pagination, at emit time |
| `promo_video.py` | Render a promo video from a title screen: the cover, its ambience, a track |
| `renpy_sdk.py` | Locate the Ren'Py SDK that install_renpy.py put on this machine |
| `script_diff.py` | Diff an author's docx master against the converted Ren'Py scenes |
| `serve_web.py` | Serve a Ren'Py web build locally, and keep serving until Ctrl-C |
| `sfx_plates.py` | Synthesize the battle sound effects, the way fx_plates.py draws the visuals |
| `slot_audit.py` | Two sprites standing in one slot -- found by walking, not by playing |
| `spec_check.py` | The author's numbers in the docx against the numbers the game actually uses |
| `sprite_audit.py` | Report speakers who talk with no sprite on screen |
| `sprite_overlap.py` | Report sprites that stand on top of each other, and say who is buried |
| `static_audit.py` | Cheap static checks over a project that nothing else in the sequence runs |
| `subset_font.py` | Subset a CJK font down to the glyphs a game actually displays |
| `sync_cards.py` | Generate a choice screen's option data from the author's docx |
| `verify_all.py` | The whole verification sequence, in one command, stopping at the first failure |
| `vnpaths.py` | Locate the visual novel's game tree without naming the project |
| `vnrich.py` | Paragraph text WITH the author's emphasis kept |

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

**Run `tools/verify_all.py <project> "<master.docx>"`.** It runs the whole
sequence -- emit, diff, lint, sprites, slots, spec, combat, static, overlap,
sound, story, nvl, pyflakes, skill -- in order and stops at the first failure.
The repo's AGENTS.md documents each step and the bug that put it there. The
table above is generated from each tool's own docstring (2026-09-14), after a
hand-kept version listed eight tools of thirty and none of the audits.

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

### Read the tools' output the way the tools write it

Three verification tools each gave a wrong all-clear in one week, and in
every case the tool had said so and the reading discarded it.

- **`script_diff` prints its warning at the TOP and its total at the
  bottom.** Read through `tail`, it shows "1 region differs" while the
  first line says the scenes are being compared in alphabetical order and
  every count below is meaningless. Never pipe it through `tail`; read the
  first lines first. It now follows branches (topological order, so a
  convergence waits for all the branches into it), and still warns when a
  file has more than one label, the graph has no single head, or there is
  a cycle.
- **Lint's findings are lines of the form `game/<file>.rpy:<line>`.**
  Grepping for the word "error" once threw away the one line that mattered.
  Filter on that shape. And a "define already defined" line is not noise:
  `gui.rpy` runs at `init offset = -2`, so a stock-template `define` in
  `options.rpy` at init 0 silently WINS over a deliberate value set earlier.
- **`check_story`'s parser read `call screen NAME` as a call to a label
  named `screen`** and reported two permanent dangling jumps — which trains
  people to ignore the dangling list, the one list that must never be
  ignored. Fixed in `rpy_parse.py`.
- **Editing anything under this server's directory changes nothing until
  the MCP server is restarted.** The running process keeps the old module.
  Verify a parser fix in a fresh interpreter before trusting `check_story`.

### The sprite audit must carry state across scenes

A speaker with no sprite on screen is the most-reported bug in this project,
and the obvious audit — reset the shown set at each file — produced fifteen
false positives. Sprites survive a `jump`; only `scene` clears them. Walk
the files in story order (use `script_diff.scene_order()`), carry the shown
set across, reset it on every `scene`, and treat a `scene cg` as a
no-sprite state. The speaker VARIABLE is not always the sprite TAG, so the
mapping has to be looked up, not assumed.

What remains after that is a short list to check by hand, and a voice from
off-screen is sometimes the point — an ambush shout before the figure lands,
a line during a blackout, dialogue over an insert shot. Confirm intent in
the file's own comments before "fixing" it.

### Cap an emitter's tail when it cannot be anchored

A generator that copies prose from the master document to the END of the
document is correct until the author writes the next chapter; the next run
then swallows that chapter into the previous scene and prints a normal
success summary. This has fired three times. When there is no end anchor
yet because the next beat is unwritten, CAP the tail at a paragraph count
and refuse to run past it. Failing loudly costs one rerun; failing silently
cost an evening.

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

## Phones

Settled 2026-09-18 on a real phone, on a 16:9 game. Everything in this
chapter is engine-level and project-agnostic; the reusable parts are
`snippets/touch_input.rpy`, `snippets/text_size.rpy`, `tools/draw_ctc.py`,
and what `tools/build_web.py` and `tools/serve_web.py` already do.

### Landscape, and how to get a phone into it

A 16:9 game on a portrait phone renders at about a third of the screen's
height and the text is unreadable. The answer is landscape, not a 9:16
build: a portrait build would re-author every plate, every full-screen
illustration and the sprite staging for a frame that keeps a third of each
picture, and no visual novel does it. Four things carry landscape:

- The manifest the engine writes already requests landscape when the game
  is installed to a home screen. A page in a browser tab cannot force
  rotation, so `build_web.py` injects a "turn your phone sideways" card
  into the page after every build, shown only on a touch device held
  upright (the CSS query `(orientation: portrait) and (hover: none)`).
- **The engine's canvas fills the window's WIDTH and the frame follows it,**
  so on any screen wider than 16:9 -- every phone held sideways -- the
  bottom of the frame and the quick menu fall off the screen. The same
  injected block holds the canvas to the largest 16:9 box centered in the
  window, on load, resize and rotation. The engine sizes its drawing buffer
  from the canvas element's own box, so fit-to-width becomes fit-inside.
- Test on a real phone: `serve_web.py <dir> <port> --lan` binds the Wi-Fi
  address and prints it. Chrome's device toolbar, rotated then reloaded, is
  the desktop stand-in (the engine picks its layout once, at load).
- ⚠ Do NOT trust an in-app browser's phone emulation for this: one drew the
  frame at double size after Start while the phone and Chrome drew it
  correctly. The splash image is HTML, sized by CSS, and letterboxes
  perfectly whatever the engine does after it -- it proves nothing.

### Reading on a phone

- A tap anywhere advances. No tap button, no mouse icon, no console glyph:
  a mouse icon is wrong on a phone and a console button is wrong everywhere
  but that console.
- **The click-to-continue mark** is the cue every platform shows: a small
  right-pointing triangle blinking at the end of the current line.
  `tools/draw_ctc.py` draws it centered on a canvas as tall as the line,
  because the engine aligns an inline image to the top of the line and a
  short glyph floats there. Wire it as `ctc="ctc_blink",
  ctc_position="nestled"` on every speaker AND the narrator; the docstring
  shows both lines.
- Pinch zoom is not a reading mode: it scales the page like a photo and
  taps land where the engine thinks they land at the unscaled size. Text
  size is the reading control.

### Text size

Phones differ in physical size, so the reader picks. Three fixed states
(the default, a big and a biggest, as ratios of the body size) beat a
slider: each is a state every screen can be checked at, and a reader picks
in one tap. The engine's own factor, `_preferences.font_size`, scales every
piece of text; `snippets/text_size.rpy` has the Preferences block.

⚠ **The factor scales text, not boxes.** Every screen with a size in pixels
breaks at the larger states unless it reads the factor: names wrap past a
card's bottom, descriptions run off the screen, fixed-height rows overlap,
a long button label wraps into the row below it, and a highlight frame
wraps half of a two-row label. All of it was found at the biggest state on
one project and none at the default. The snippet has the rules: boxes and
rows multiply by the factor (capped where the box would leave the screen),
a grid that must keep its footprint switches to one wide column above
~1.15x and scrolls, images inside a box give back what the text takes, and
a name-to-dialogue offset fixed in a style must scale too.

⚠ **NVL pages are nearly full at the default.** Measure with the page model
before offering larger text: on one project the tallest four-entry page
stood at 925 of the 1010 px above the quick menu, so a 5% increase already
ran into the menu. The fix is not fewer entries but a drag-scrolled
viewport opened at the bottom (in the snippet): the newest line is always
in view and a taller page is read by dragging up; the wheel keeps rollback.
The quick menu gets `box_wrap True`, or its last button falls off the right
edge at large text and leaves History as the only door into the game menu.

**Check every new screen once at the biggest state.** The verification
sequence does not test text scaling or the phone layout; this is the one
manual glance that remains, thirty seconds per screen.

### Commands that need hover

A command menu shows a move's stats on hover and uses it on click. A phone
has no hover, so the stats cannot appear and the first tap uses the move.
Two taps: the first arms and highlights a move and shows its stats, the
second on the highlighted move uses it. `snippets/touch_input.rpy` has the
detection and the pattern, and its header carries the three traps:

- **Detect the device; never make it a setting.** A "tap twice / click
  once" preference was tried and rejected: desktop would inherit a choice
  that means nothing there, and a phone reader who cannot see the stats
  will not guess that a setting exists to fix it. The game accommodates the
  device from the start.
- **The engine's `touch` and `mobile` variants are not reliable** -- both
  were unset on a real phone while every other phone feature worked. Ask
  the browser the actual question: `(hover: none)` over the emscripten
  bridge, once, cached.
- **On touch a tap arrives as hover, then click.** A `hovered` action that
  arms the move makes the click of the same tap land on an armed button.
  On touch, hover must do nothing.
- Give the button style a `selected_background`: the mouse's hover frame
  is what an armed move must show, or arming is invisible.

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
