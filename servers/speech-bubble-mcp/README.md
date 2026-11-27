# speech-bubble-mcp

Lettering for comics and manga videos, as an MCP server: speech bubbles,
thought bubbles, caption boxes, shouts and whispers, drawn onto a still page or
animated over a video shot. Runs on the CPU, with no model, no network and no
API key.

The connected AI harness does the thinking -- which line goes in which shot,
where the speaker stands, any translation -- and this server does the
mechanical part: fitting the type, drawing the balloon, aiming the tail and
timing the fades.

| | |
|---|---|
| GPU | none |
| Python | 3.10+ |
| Video | any ffmpeg (decode and encode only, no filters needed) |
| Languages | English, Japanese (vertical or horizontal), Chinese, Korean |

## Install

```bash
git clone https://github.com/tobiasfong/webcomic-toolkit
cd webcomic-toolkit/servers/speech-bubble-mcp
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt         # macOS / Linux
```

Register it with your harness, for example Claude Code:

```bash
claude mcp add -s user speech-bubble -e SPEECH_BUBBLE_FFMPEG=/path/to/ffmpeg -- \
  /path/to/speech-bubble-mcp/.venv/Scripts/python.exe /path/to/speech-bubble-mcp/server.py
```

Check it with `check_status`: it reports the ffmpeg it found, a font for each
language, and where it writes.

## Tools

| tool | what it does |
|---|---|
| `set_project_style` | one project's fonts, type size, colors, uppercase, vertical Japanese, reading order |
| `get_project_style` | the saved and the effective style |
| `parse_script` | `NAME: line`, `NAME (thought): line`, `CAPTION: line` script -> bubble entries, words untouched |
| `fit_text` | the line breaks and size a line would get, without drawing -- checks a translation fits |
| `letter_image` | letters a still: the lettered PNG, the bubbles alone on a transparent layer, and a saved spec |
| `letter_video` | animates bubbles over a clip or a still; `preview_at` renders single frames first |
| `list_lettering`, `get_lettering` | saved specs; re-render one in another language by name |
| `check_status` | ffmpeg, fonts, output folders |

## A bubble

```json
{"id": "l3",
 "kind": "speech",
 "text": {"en": "Wait. You think I came here for the money?", "zh": "等等。你以为我是为了钱来的？"},
 "at": [0.30, 0.25],
 "tail": [0.42, 0.55],
 "start": 1.2, "in": "fade"}
```

- `kind`: `speech`, `thought`, `caption`, `shout`, `whisper`.
- `at`: the bubble's center as fractions of the frame, or a name (`top-left`,
  `top`, `top-right`, `left`, `center`, `right`, `bottom-left`, `bottom`,
  `bottom-right`). Omit it to auto-place on calm art near the speaker.
- `tail`: the speaker's mouth or head, as fractions, or `left`, `right`,
  `center`, `far-left`, `far-right`. Omit it for no tail.
- Video only: `start`, `end` (seconds; default is one after another by reading
  time, staying to the end of the shot), `in` (`fade`, `slide-up`,
  `slide-down`, `slide-left`, `slide-right`, `pop`, `none`), `out` (`none` or
  `fade`).
- Optional: `scale` (a shout uses 1.15), `font`, `max_width`, `vertical` /
  `horizontal` to force Japanese one way.

An explicit newline in `text` is always kept: that is how a line is broken at
the phrase the writer wants.

## Where things go

- Lettered images: `../character-panel-mcp/output/<project>/lettered/`
- Lettered videos: `../anime-production-mcp/output/<project>/lettered/`, with
  each bubble as a transparent PNG in `<name>_<lang>_bubbles/`
- Specs and styles: `state/` (gitignored -- dialogue carries character names)

Installed on its own, without those sibling servers, it writes to `output/`.
`SPEECH_BUBBLE_STATE`, `SPEECH_BUBBLE_IMAGE_OUT` and `SPEECH_BUBBLE_VIDEO_OUT`
override each location.

## How it works

- **The bubble follows the text.** One type size for a whole project; the
  balloon is fitted around the words, never the words squeezed into a balloon.
  Line breaks are chosen by trying every line count and keeping the tightest
  ellipse, which gives the short-long-short shape of hand lettering.
- **Drawn twice, outlined once.** Each shape is a set of primitives drawn grown
  by the stroke in the outline color, then at size in the fill color, so a
  tail, a cloud's bumps or a burst's spikes share one clean outline. Drawn at
  3x and downsampled.
- **Video frames are composited here, in Pillow.** ffmpeg only decodes and
  encodes, so a reduced ffmpeg build works. The preview and the encode call the
  same function, so an approved preview is what renders.

## Troubleshooting

- **`No ffmpeg found`** -- only video needs it. Set `SPEECH_BUBBLE_FFMPEG`.
- **Tofu boxes instead of characters** -- the font lacks that script. Set one
  per language with `set_project_style(fonts={"zh": "..."})`.
- **`Bubble has no 'ja' text`** -- the spec has no line in that language yet;
  translations are added to `text` as a per-language map.
- **A bubble runs off the frame** -- allowed, and reported as `off_frame`.
  Pin it with `at` if it should not.

## Tests

```bash
.venv/Scripts/python.exe test_tools.py
```

Synthetic art in a temporary folder; video checks need ffmpeg. They compare
rendered frames against the source and against a still lettered by the other
code path, so they check what was encoded, not what was planned.
