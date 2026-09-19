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

## Expressions

The registry supports two kinds. Face PATCHES (`register_expression`) are
small deltas over the neutral body, for art where a face can be repainted
in place. FULL BODIES (`register_body`, added 2026-09-19) are a second
matted render under the same tag, scaled to the neutral's height and
centered on its canvas, emitted as a body group so `show <tag> anger` swaps
the figure in place. Use full bodies for flat cel art: a repainted face
redraws its own contour and the seam against the old one sits inside the
face. The measured recipe for a full body is in the repo's AGENTS.md under
the visual novel rules: the turnaround path with the expression as an
extra clause, a tall canvas, the sprite's own render as the reference, the
state named simply.

Which line gets which face is `expressions.json` in the project, read by
`emitlib.py` for every emitter and anchored on the opening of a paragraph,
so a face is staging like a `show` and never typed into a scene file. A
face persists until the next entry for that tag, and `scene` resets
everyone to neutral.

### Making an expression body: what a day of it taught

Measured over ~60 renders on twelve characters, 2026-09-19.

**The prompt carries the WHOLE costume description**, expression clauses
stripped. The turnaround prompt names no costume of its own, so without it a
skirt came back as trousers and a robe lost its trim. It also fixes
expressions that were failing: the same word and seed that gave one character
no smile gave a good one once her costume was in the prompt.

**The state word is a ladder, and each character sits on a different rung.**
For a smile: smiling, grinning, laughing, widest last. For anger: angry,
glaring, shouting. Plain "smiling" and plain "angry" move most faces not at
all; "grinning" and "shouting" are the reliable middle. A word only reads as
a change when it moves something the neutral is not already doing, so a
character whose resting face is stern needs an open mouth and one who already
half-smiles needs a grin or a laugh. No adverbs: they overshoot.

**For a detail-heavy character, ask for a FRONT view, not three-quarter.**
Nine three-quarter draws of one character lost his topknot, his shoes or his
robe in turn; a front view held all three first time. The rotation is what
gives every fiddly element a reason to be redrawn, so when a figure carries
glasses, a complicated hairstyle, layers and a prop, buy fewer of them.

**A squeeze fixes width, never length.** Scaling a body horizontally to match
the neutral's width-to-height is the standard finish and was used on half the
set. It cannot fix short legs: "stumpy" means reroll.

**Conditioning on an existing CG works when words fail.** One character's face
did not move for five different words; his own CG already carried the look,
and conditioning on it (padded first, since it fills its frame) produced the
body. Several characters have a CG with an expression already in it.

⚠ **Masked repair is a no-op on this path.** Three seeds of a masked foot
repair measured 7.05 inside the mask against 4.58 outside, and all three
landed within 0.01 of each other -- the seed changed nothing. Masked face
edits come back off-style even with the style LoRA loaded. Repair by hand or
reroll; do not spend seeds on a mask.

**A detail that is in the art but not in the description will be lost.** One
character's shoulder emblem arrived by accident in his original render, was
kept because the author liked it, and was never written down -- so every
expression render dropped or reinvented it. When a render loses a detail,
check the description before blaming the seed.

**Sweep only after every character's set is confirmed.** A render that was
sent but never ruled on is not in the manifest, and the sweep deletes it.

### A playtest overlay hands its decisions back over HTTP

A dev build running in a browser has no filesystem, so an in-play tool that
RECORDS the author's decisions could only offer a download -- and then he has
to find the file and say where it landed. `serve_web.py` takes `POST
/__notes` and writes the body beside the build, so the page sends its own
notes and the converter reads them with no argument. The body must parse as
JSON, the filename may come from `?name=`, and the DIRECTORY never does.

⚠ Send after every decision, not only on a button. A web build served over
plain http on a LAN address gets no persistent storage (`serve_web.py` says
so in its own header), so a closed tab takes the session's decisions with it.
The button stays, sending synchronously so it can report the status, and
falls back to a browser download when the POST fails -- that is the case of a
build opened from somewhere other than this server.

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
- **The launcher returns before the build is done.** Measured 2026-09-18:
  `renpy.exe launcher web_build` came back 15 s after it started, the
  distribution folder was deleted and recreated 80 s later, and its last
  file landed 5 s after that. A script that patches the page or starts a
  server as soon as the launcher returns is working on the PREVIOUS build,
  which the real one then replaces without a word -- the page block below
  went missing that way while the build log said it had been added.
  `build_web.py` waits for a page newer than the build's start and for the
  folder to go quiet, then injects and re-reads the page to prove it;
  `serve_web.py` injects again before serving, so the served page always
  carries the block and an edit to it needs no rebuild.
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

# Working rules for the game itself

Moved here from the repository's root `AGENTS.md` on 2026-09-19. The root
file loads in EVERY session in this repository, including the ones that
never open the game, and at 120 KB it was charging every one of them for
this. It now carries a pointer and the few rules a session must have
without reading anything; the rest is below, where a session working on
the game reads it.

## Visual novel — working rules

Added 2026-09-02 after a full debugging pass. The game lives under a
gitignored `vn/<project>/`; its private supplement — story state, the
speaker-to-sprite map, which sprite gaps are deliberate — is
`vn/<project>/HANDOVER.md`. THIS section is the procedure, and it is here
because this file is the one every session loads regardless of model.

### The verification sequence — all of it, in order, on every change

Each step caught a real bug in one week. None substitutes for another.

**⚠ RUN THEM AS ONE COMMAND, not by hand:**

```bash
servers/visual-novel-mcp/.venv/Scripts/python.exe servers/visual-novel-mcp/tools/verify_all.py vn/<project> "<master.docx>"
```

`verify_all.py` (added 2026-09-08) runs every step below in order -- the
numbering here follows the tool's order exactly -- and stops at the first
failure with that step's output. It exists because the steps,
run by hand, get skipped, reordered, or filtered wrong — the lint step in
particular was grepped for `game/x.rpy:42` and reported a clean sheet while
the game would not compile, since a parse error prints in a different
shape. The script never greps lint: it deletes `errors.txt` and fails if
Ren'Py writes it back. It also adds a measured check that no NVL page runs
under the quick menu, and calls `check_story` directly. A green run is the
whole sequence with nothing skipped; that is the only green worth reporting.
The steps are listed individually below so each one's REASON survives.

1. **Re-emit every scene** from the master docx:
   `python vn/<project>/tools/emit_all.py`. **As of 2026-09-05 EVERY scene
   file is generated** — there is no hand-written scene left, so never
   hand-edit one; the next re-emit wipes it. Staging lives in the emitter:
   change it there. (The prologue and early Act 1 were converted with
   `servers/visual-novel-mcp/tools/convert_scene.py`, each verified line-
   for-line identical against its hand-written original before the original
   was replaced. Convert any future hand-written scene the same way, with
   `--check`, and do not replace a file until the check says IDENTICAL.)
2. **`script_diff`** — and READ THE TOP of its output. Its warning prints
   first and its total prints last; read through `tail` it shows a
   reassuring count while the first line says the comparison is
   meaningless. Expected result: `in sync`.
3. **Lint** with `renpy.exe <project> lint` — project path FIRST.

   ⚠ **DELETE `errors.txt` FIRST AND CHECK WHETHER IT COMES BACK.** That is
   the reliable signal, because it appears only when the script failed to
   COMPILE, and no filter can hide it:

   ```bash
   rm -f vn/<project>/errors.txt   # then lint; if it reappears, read it
   ```

   Filtering the output is where this goes wrong, twice now. Ren'Py prints
   FINDINGS as `game/x.rpy:42: ...` but PARSE ERRORS as
   `File "game/x.rpy", line 42:` — a different shape entirely. A filter on
   the first shape reports a clean sheet while the game will not start. It
   swallowed a broken `if` once and `has vbox` not being allowed inside an
   `if` on 2026-09-07, which then crashed a live playtest. If you must
   filter, use `^(game/.*\.rpy:[0-9]+|File "game)` — and never filter on the
   word "error", which discards the only line that matters.

   Expected: no findings AND no `errors.txt`.
4. **Sprite audit** — see below. Expected: only the documented deliberate
   gaps, AND no stale ones. Since 2026-09-14 an exemption on the deliberate
   list that no line hits any more is a FAILURE, because it is not clutter:
   it silently forgives the regression if someone later removes the `show`
   that made it obsolete. Three were found by hand that day, exempted one
   afternoon and staged the next. Delete the exemption in the same edit
   that stages the character.
4b. **Slot audit** — `python servers/visual-novel-mcp/tools/slot_audit.py
   vn/<project>`. Expected: `no two sprites share a slot`. Showing a
   second sprite at an occupied slot is NOT an error in Ren'Py; the
   first figure is silently covered, and lint and `script_diff` both
   pass because the text is right. Slots are INHERITED across a jump,
   so the occupant may be someone the file never mentions — which is
   how a character came to stand on the protagonist. Only playing it,
   or this, will find it.
4c. **Spec check** — `python servers/visual-novel-mcp/tools/spec_check.py
   "<master.docx>" vn/<project>`. Expected: `DISAGREE : 0`. The combat spec
   is fenced and never emitted, so `script_diff` cannot see it and the
   author's numbers can drift from the engine in silence — a figure retyped,
   an editor's stray undo, a value tuned in `combat.rpy` and never written
   back. Two things it must keep doing: enemies SCALE (one move name, several
   statlines) and a technique has TWO TIERS, so each name holds the SET of
   values the engine uses and a claim passes if it matches one. Keying either
   globally produced confident, wrong findings against correct code. It also
   PRINTS the numeric spec lines it could not parse, so its coverage is
   visible rather than assumed.

   ⚠ **THERE IS A THIRD COPY, and since 2026-09-11 this checks it too.** The
   tier-II inventory entries restate the same upgrade figures in English,
   because those items describe MECHANICS rather than carrying the author's
   shelf copy. So a number lives in the docx, in `combat.rpy`, AND in
   `inventory.rpy`. Two of those were compared and the third was not: the
   author swapped a single-target and an area attack's damage, the docx and
   the engine were updated together and passed clean, and the bag went on
   telling the player the old figure. The inventory is now checked against
   the DOCX -- like against like, two pieces of prose making one claim -- and
   the docx-vs-engine comparison closes the loop transitively.

4d. **Combat reachability** -- `python servers/visual-novel-mcp/tools/
   combat_calls.py "<master.docx>" vn/<project>`. Expected: `0 unreached, 0
   unanchored`. Added 2026-09-13 after a fully specified three-enemy fight
   turned out never to have been wired: the scene cut from the enemies
   lunging straight to one of them asking how his technique had been broken,
   so the player won a battle they never fought and every step above was
   green while it happened.

   ⚠ **EACH OTHER CHECK MISSES THIS FOR ITS OWN REASON, and together they
   describe the class.** The combat spec is FENCED, so `script_diff` drops it
   from the docx side AND the emitter side and the two agree about nothing --
   the same hole 4c and the fence bug already record. `spec_check` proves the
   NUMBERS in the fence match the engine, and a fight nobody enters has
   numbers that agree perfectly. Lint does not consider a missing `call` a
   syntax error. The sprite audit was satisfied because the enemies had
   sprites; nobody showed them. **Agreement is not execution, and no amount
   of cross-checking two descriptions of a thing proves the thing runs.**

   It counts PER SCENE FILE -- how many fights the document specifies there
   against how many that file calls -- rather than matching each spec to a
   line window. A window has to know how far a `call` may sit from the prose
   around it, and the honest answer is "however much staging the emitter put
   between them": in one scene the call is seven lines and five `show`
   statements clear of the next spoken line, which reported three correctly
   wired fights as unreached. Counting needs no such constant and still
   catches the original, where one file specified TWO fights and called ONE.

   It finds the markers with a RAW REGEX over the raw paragraphs, not through
   `prose_mask`. That is deliberate and it is the point: the fence patterns
   are what was wrong the last two times, so a checker for fence-shaped bugs
   must not ask the fence what it thinks. The mask picks only the prose
   ANCHOR naming the file, where being wrong prints `UNANCHORED` instead of
   passing silently.

4e. **Static audit** -- `python servers/visual-novel-mcp/tools/static_audit.py
   vn/<project>`. Expected: `0 finding(s)`. Six file-level checks that were
   being run BY HAND on every audit and therefore skipped, mistyped, or --
   the case that prompted it, 2026-09-14 -- written with a regex the shell
   mangled and trusted anyway: every literal image path resolves (Ren'Py
   only complains when the image is DRAWN, so a broken path in a screen
   nobody opened in testing ships -- eight such lines were found in the
   small-screen variant that day); every `show`/`scene` name resolves;
   sprites.json, sprites_generated.rpy, the sprite folders on disk and the
   speakers in characters.rpy agree; no name is `define`d twice; every plate
   that is not screen-sized is declared through a fitting Transform rather
   than a bare path (the two-thirds-screen failure, caught at declaration
   instead of in play); and every backticked `file.ext` in HANDOVER.md,
   ROUTES.md and this file exists. The last is the stale-note guard -- a
   note naming a file that is gone is how finished work gets handed back as
   unfinished.

4f. **Sprite overlap** -- `python servers/visual-novel-mcp/tools/
   sprite_overlap.py vn/<project>/game 30`. **A REPORT, never a gate.**
   Coverage is measured on WIDTH alone and a crowd is meant to overlap, so no
   threshold separates staging the author has approved from staging he has
   rejected: both of one week's rejections (a father covering his daughter
   in the reunion, four figures reading as friends instead of two sides)
   scored 30-43%, while approved crowd scenes score 57-100% and a wide,
   low beast beside a standing figure scores 89% without hiding her face.
   What the number is good for is BEING SEEN -- the reunion was fixed the
   day someone looked -- so `verify_all` prints the top pair on every green
   run. Read it. Do not make it fail.

5. **Sound coverage** — every `show fx X` has a `play sound` on the line
   before it, except ambient effects. Since 2026-09-11 the same step also
   checks that every plate a scene or a fight names is DECLARED in a .rpy.
   Ren'Py defines an image for every file under `images/` on its own, so an
   undeclared plate still resolves and every other checker stays green --
   and it is drawn at its native 1280x720 in the middle of the 1080p frame,
   which is the two-thirds-screen failure presentation.rpy warns about. Two
   assassin plates ran that way for a month.
6. **`check_story`** via the MCP — after RESTARTING the server if anything
   under `servers/visual-novel-mcp/` was edited. The running process keeps
   the old module; a parser fix was invisible for an hour.
6b. **NVL page height** -- measured by `verify_all` with `nvlpage.py` as a
   FLOOR: a page it calls tall is tall; one it passes is not proven to fit.
   See "NVL pages turn on the entry cap" under the emitter rules for why the
   model is not trusted to pack pages.

7. **Web build** (`build_web.py`) when assets or the launcher changed.
   Run `optimize_png.py <project>` first whenever images were added: the
   web build ships every PNG byte-for-byte under progressive download, so
   their size IS the browser download. Lossless, and it hashes every
   file's pixels before and after so a change fails the run (10.9% off
   201 files in 85 s, 2026-09-16). ⚠ Run the build from the REPO ROOT: a
   shell whose working directory is inside the distribution folder holds
   it open, and the launcher's error blames a server that is not running.
   ⚠ And THE LAUNCHER RETURNS BEFORE THE BUILD IS DONE: measured
   2026-09-18, it came back in 15 s and the distribution folder was
   deleted and rewritten 80 s later. Anything done to the page in between
   is done to the previous build's page, which the real build then
   replaces -- that is how the phone block went missing from a page whose
   build log said it had been added. `build_web.py` now waits for the
   folder to settle and re-reads the page after injecting; `serve_web.py`
   injects too. Never patch the page or start the server by hand straight
   after the launcher.

Repo-wide, on any change under `servers/`:

8. **`python -m pyflakes`** over the edited server — and READ ITS OUTPUT
   AFTER EDITING, not just before. An "unused import" finding names ONE
   name on a possibly multi-name line; deleting the line removed `Image`
   from two files, `py_compile` passed them (syntax only), and only the
   pyflakes re-run caught 88 undefined names.
9. **`python servers/anime-production-mcp/sync_skill.py --check`**. The
   anime-production skill ships a vendored copy of that server's pipeline
   because it installs by being copied elsewhere and must be self-contained.
   The server is canonical; the copy was once found three weeks stale and
   missing a function while its docs promised "same code either way". Run
   without `--check` to bring it current after editing the server's tools.

### Emitters — where they bite

- **The unbounded tail has fired THREE TIMES.** An emitter that runs to the
  end of the document is correct until the author writes the next chapter;
  the next run then swallows that chapter into the previous scene with a
  normal success summary. Every emitter gets an END ANCHOR. Where the next
  beat is unwritten and no anchor exists, CAP the tail at a paragraph count
  and refuse to run past it — failing loudly costs one rerun.
- The docx has a blank paragraph between every line, so `i + 1` after a
  marker is the blank. Use a next-non-empty helper. This once emitted `""`
  as an entire conditional branch, and lint passed it.
- Anchor on prose CONTENT, never paragraph numbers. The document moves.
- **A SPEC FENCE THAT DOES NOT OPEN IS INVISIBLE TO `script_diff`.** Fired
  2026-09-07. The boss battle's header read `(Combat sequence - as this is a
  boss battle, use main theme instead of battle theme)`, while `fence_start`
  demanded the paren close immediately. The fence never opened, and **32
  paragraphs of stat block — the boss's HP and PP, every move, both
  assassins — were emitted as spoken dialogue** and read aloud to the player.

  The reason the diff stayed green is worth generalizing: **the docx side and
  the emitter share `prose_mask`, so a bad mask makes them agree WITH EACH
  OTHER while both are wrong.** `script_diff` proves the two sides match; it
  cannot prove the mask is right. Any checker that shares a definition with
  the thing it checks has this hole.

  So write fence and spec patterns to tolerate a NOTE in the header — anchor
  with ``, not with a closing paren — and when spec text turns up as
  dialogue, suspect the fence regex before the emitter. The one check that
  catches it is reading the emitted scene, which is why the sequence ends by
  looking at the file rather than at a count.
- The outgoing `jump` is EMITTED, never appended by hand — a hand-added one
  was silently deleted by the next re-emit.
- **The five emitter helpers live in `tools/emitlib.py`, bound once per
  emitter with `find, split_speaker, esc, say, block = emitlib.bind(SPEAKERS)`.**
  Never paste them into an emitter. Settled 2026-09-08 after an audit found
  `esc` copied into 26 files and `say`/`split_speaker` into 25, in SEVEN
  variants that disagreed about where quotes were stripped and whether the
  annotation filter ran; changing `esc` earlier that week had meant patching
  25 files with a regex. A copy is a fork. The consolidation was verified by
  a byte-diff of every generated scene — re-run that diff whenever emitlib
  changes. `convert_scene.py` emits the bind line, not a copy. The
  scene-local pair a hand-written emitter needs — `find` over its own
  paragraphs and `block` with staging — comes from
  `find, block = emitlib.bind_scene(paras, prose, say, name=..., floor=start)`
  for the same reason: seven emitters had grown seven `find`s and six
  `block`s, one of them under a different name.
- **A fight starts with `$ battle_setup([...enemies...], music=...)`**, never
  with the six assignments spelled out. Seven labels once repeated them and
  only three reset the stun flag.
- **NVL pages turn on the entry cap (`gui.nvl_list_length`, four). Height
  pagination was tried and REVERTED, 2026-09-09.** `paginate_nvl.py` packed
  pages to the exact measured budget for one evening and they overflowed in
  play: the font model (`nvlpage.py`) had been checked against its own
  numbers, never against a rendered frame, and packing to the limit left no
  margin for the few percent it was off. The count is blunter, but its slack
  is what makes it safe. `verify_all.py` still measures pages with that
  model as a FLOOR -- a page it calls tall is tall; one it passes is not
  proven to fit. Do not re-wire the paginator without first calibrating the
  model against a screenshot and then packing to no more than ~85%.
- Every speaker gets a `show` before speaking, re-issued after every
  `scene`. Speaking from an empty frame is the most-reported bug here.
- Conditional paragraphs: emit the DEFAULT branch first (negate the
  condition) to match document order, or `script_diff` reports a phantom
  NEW+DROPPED pair.
- Choice cards, spec notes and scenario headers must be listed in
  `patterns.json` or they report as unconverted prose. Write those regexes
  as RAW strings: a `\b` typed with one backslash became a literal
  backspace character and could never match, while printing as if correct.

### The sprite audit must carry state across scenes

Sprites survive a `jump`; only `scene` clears them. An audit that resets
per file produced fifteen false positives. Walk files in story order
(`script_diff.scene_order()`, which follows branches topologically), carry
the shown set across, reset on every `scene`, treat `scene cg` as a
no-sprite state. The speaker VARIABLE is not always the sprite TAG — look
it up. What remains is a short hand-checked list, and an off-screen voice
is sometimes the point; confirm intent in the file's comments before
"fixing" it.

### Expressions are FULL BODIES, drawn on the turnaround path -- settled 2026-09-19

The registry was built for one body plus face patches. On this art the
patch route FAILED, in three ways that are worth knowing because each one
looked like the fix for the last:

| attempt | what came back |
|---|---|
| masked Kontext edit of the face, bare model | a Western-comic mouth and nose on a manhwa face: "two different styles meshed together" |
| the same with the style LoRA on the editor | the right style, and a fuller cheek whose new contour the OLD jaw line cut through: "as if someone bit off part of his face" |
| the whole head from the edit, with its own matte | the same, plus white fringe in the hair |

A face redrawn in place redraws its own contour, and the seam between the
new contour and the old one is inside the face, where no feather hides it.
So an expression is a SECOND BODY under the same tag, a pose change
allowed, the way a Fate/stay night sprite crosses its arms when it shouts.
`register_body` in the sprite registry scales it to the neutral's height,
centers it on the neutral canvas, and emits a body group so
`show <tag> anger` swaps the figure in place.

**The recipe that produced an approved body**, after nine renders, one
lever at a time:

1. **The turnaround path, not the plain edit.** `single_view` (the
   turnaround LoRA stacked on the style LoRA, "create a front three-quarter
   view of this exact character") with the expression as an extra clause.
   The plain unmasked edit drew a big head on short legs on every seed and
   canvas, because it builds a new body from the description with the
   reference steering only the surface; the turnaround LoRA rotates a body
   it can see and keeps its proportions.
2. **A TALL canvas, 832x1408.** The edit inherits the reference's framing,
   the turnaround panel is cut tight, and a three-quarter stance made to
   fill the same height loses it from the torso and legs. The author read
   that off the render and was right; the taller canvas fixed the
   proportions where seed and padding had not.
3. **The sprite's OWN render as the reference**, not the bible's concept
   crop: the sprite came off a later turnaround and its costume differs.
   The plain edit also obeyed a "gold piping" clause in the bible text that
   the approved sprite does not carry -- check the description against the
   installed sprite before trusting it in a prompt.
4. **Name the state, and nothing else.** "Shouting angrily" read; "jaw
   clenched, lips pressed, corners down" read as a grimace.

5. **No adverbs.** The author, after three soft smiles: "keep the prompt
   simple and use smile, no need for adverbs like happily or small or
   gently." "Smiling happily" gave one character a smile too wide to read
   as natural and gave two others no smile at all. The limb total and the
   clearance clause stay -- those are framing guards, not description.

**What varies and what does not, measured over a dozen bodies in one
afternoon:** ANGER hit on the first draw for every character. SMILES are
the flaky one and should be budgeted two or three draws. The SEED decides
BUILD as well as expression -- one reroll came back "thinner and younger",
another "like a dwarf" -- so show the author the matted figure's
width-to-height beside the neutral's with every comparison; it catches the
slim draws, though only his eye catches a bad face.

⚠ A narrow, low-resolution reference is the other suspect when a body comes
back deformed (a three-legged figure with a fused hand, in one case). The
references that worked were 832x1216; the one that failed was 420 wide.
Check the reference's size before spending seeds.

Not every character needs both faces, and that is the author's call, not a
gap: one stays neutral when angry by design, and one whose neutral art
already smiles has that art registered under the smile name so a line
anchored to smile still resolves. `register_body` widens the body canvas
when a wider stance needs it, but only for a character with no face
patches -- patches carry pixel offsets that widening would move.

⚠ The TURNAROUND SHEET is not a way to get expressions: asked for eight
figures shouting it returned a different character in the same clothes,
the style LoRA overwritten by an American cartoon style. And the editor's
default is the BARE model: any repaint of a sprite must carry the style
LoRA that drew it, or it comes back in another style.

⚠ Two process failures the same afternoon, so they are rules: when a rerun
comes back IDENTICAL to the last one, the inputs did not change -- a
reference override had silently failed to land in the script -- so diff
the two renders numerically before believing a lever did nothing; and a
one-line patch written through a heredoc turned a `\n` escape into a real
newline and broke the file, which pyflakes caught. Assert every replace.

Which lines get a face is data too: `expressions.json` in the project,
anchors on the opening of a paragraph, read by `emitlib.py` for every
emitter, so a face change is staging in the same sense a `show` is. The
list is proposed by scanning the author's own narration for cues
("laughed", "snarled", "eyes widened") and reviewed by him; his line
count decides who gets faces at all.

### Engine traps confirmed here

- **The image TAG is the first word of the name.** `fx snowfall` and
  `fx ice burst` share tag `fx`: the ambient effect claims the tag below
  the sprites, every later plate inherits that z-position and renders
  BEHIND the cast, and the `hide` after a flash kills the ambient effect for
  the rest of the scene. Show persistent effects `as <own tag>`.
- **Two `show`s at one slot stack silently.** One figure vanishes behind
  the other for a whole scene. No error, no warning.
- **`define` at different init phases.** `gui.rpy` runs at
  `init offset = -2`; a stock-template `define` in `options.rpy` at init 0
  silently WINS over the deliberate value. Lint reports it only as "already
  defined", which reads as ignorable. One place, one value.
- **CGs are declared without a transform** on the assumption they are
  screen-sized. Anything else renders small in the middle. Cover-crop on
  disk first.
- Impact plates: 50 ms in, 60 held, 400 out. The sound goes BEFORE the
  `show`. Stock "impact" audio can take 1–3 s to reach its peak —
  `import_sfx.py` peak-aligns impacts and leaves sustained sounds alone.
- Draw GEOMETRY (`fx_plates.py`); GENERATE volumetric objects. Three drawn
  attempts at a translucent bloom all failed before it was generated.

### Web build: saves, and how to verify anything in it

Settled 2026-09-05, after four wasted rebuild cycles.

- **Saves in the web build live in browser storage** (an IDBFS mount at
  `/home/web_user/.renpy`, flushed to IndexedDB by `emscripten.syncfs()`).
  Saving and loading are AUTOMATIC and survive closing the tab. What loses
  them: the player clearing site data, a private window, or the browser
  evicting storage under disk pressure. Only the last is preventable, and
  `game/web_storage.rpy` does it — `navigator.storage.persist()`, once per
  session, gated on `import emscripten`. Chrome grants it from engagement
  heuristics (returning visitor, bookmarked, or INSTALLED as a PWA — the web
  build ships a `display: standalone` manifest and service worker, so it is
  installable when self-hosted; itch.io's iframe blocks install). A fresh
  origin is denied, which is expected, not a bug.
- **Ren'Py Sync is a one-hour device-to-device transfer, not a backup**
  (`00sync.rpy:507`: "This sync will expire in an hour"), and it runs on
  sponsor-funded infrastructure. Never automate it.
- **Ren'Py ALREADY SHIPS Export Saves / Import Saves** — `onSavegamesExport()`
  and `onSavegamesImport()` in `web/renpy-pre.js`, behind the `≡` button in
  the page corner where no player looks. One zip, every save, and import
  rescans the slots live. `screens.rpy` calls the same functions from
  web-only "Back up saves" / "Restore saves" buttons on the save/load screen
  via the built-in `ExecJS(code)` action — which RAISES off the web, so gate
  it on `renpy.variant("web")`.
- **Do not auto-download on every save.** Chrome blocks repeated automatic
  downloads behind a permission prompt, and each save would drop another
  file in Downloads. One button, one file.
- ⚠ **The browser tool's `javascript_tool` runs in an ISOLATED WORLD** and
  cannot see globals the page sets on `window`. Verify page-side code through
  the DOM, DOM events, or the network — `fetch('/DIAG/marker')` shows up as a
  404 line in `serve_web.py`'s log. And before any rebuild loop, find the
  5-second probe: `lint` executes every `init python` block, so a file-write
  there answers "did init run" without a build.
- Each web cycle costs ~4 minutes (120 MB build, ~3 min WASM unpack). Say so
  before the second cycle, not after the fourth.
- **Phones play it sideways.** A 16:9 game on a portrait phone is a third
  of the screen tall; every phone VN asks for landscape instead. The
  engine's manifest already requests it for an installed app, and
  `build_web.py` injects a "turn your phone sideways" card into the page
  after every build, shown only on a touch device held upright (settled
  2026-09-18). To test on a real phone, `serve_web.py ... --lan` binds the
  Wi-Fi address and prints it. Do NOT trust the in-app browser's phone
  emulation for this: it drew the frame at double size after Start while
  the author's phone and Chrome's device toolbar drew it correctly.
  The full how-to is the **Phones** chapter of
  `servers/visual-novel-mcp/WORKFLOW.md`, with the reusable code in
  `servers/visual-novel-mcp/snippets/` and the mark in `draw_ctc.py`. The
  four rules a session must carry even without reading it:
  1. The engine's canvas follows the window WIDTH; the injected page block
     holds it to a centered 16:9 box, or a phone held sideways loses the
     quick menu off the bottom.
  2. Text size is three states, and the factor scales TEXT, NOT BOXES:
     every screen with a size in pixels must read `_preferences.font_size`
     (rows too), the NVL page scrolls by drag rather than overflowing, and
     every new screen gets one look at the biggest state -- the sequence
     does not test scaling.
  3. A command menu needs two taps on a phone (arm and show stats, then
     use), keyed on the browser's own `(hover: none)` -- the engine's touch
     and mobile variants missed on a real phone -- with hover doing NOTHING
     on touch, because a tap arrives as hover then click.
  4. **Accommodate the device; never make it a setting.** A tap-twice
     preference was rejected: desktop would inherit it, and a phone reader
     who cannot see the stats will not guess a setting exists.
