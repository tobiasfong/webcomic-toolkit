"""
Speech Bubble — MCP Server
==========================
Letters finished art: speech bubbles, thought bubbles, caption boxes, shouts
and whispers, on a still page or animated over a video shot. CPU only; no
model, no network, no API key.

THE DIVISION OF LABOR, same as every server in this toolkit: the connected
harness does the thinking (which line goes in which shot, translation, where
the speaker stands) and this server does the mechanical part (fitting type,
drawing the balloon, aiming the tail, timing the fades). Translation is never
done here -- a bubble's `text` can carry one string per language, written by
the harness or the author, and the same spec renders in any of them.

A bubble spec:

    {"id": "l3",                       optional; script ids carry through
     "kind": "speech",                 speech | thought | caption | shout | whisper
     "text": "Words." or {"en": "...", "zh": "..."},
     "at": [0.3, 0.25] or "top-left",  bubble center, 0-1 of the frame; omit to auto-place
     "tail": [0.42, 0.55] or "left",   the speaker's mouth or head; omit for no tail
     -- video only --
     "start": 1.2, "end": 6.0,         seconds; omit for the reading-time default
     "in": "fade", "out": "none"}      fade | slide-up/down/left/right | pop | none

Positions are fractions of the frame, so one spec fits the 1536x864 render and
the 1920x1080 delivery. Bubbles may overlap the art or run off the frame edge;
that is allowed, and `off_frame` in the result says when it happens.

Usage discipline:
  * ONE TYPE SIZE PER PROJECT. Set it once with set_project_style; never
    shrink one bubble's text to fit a space. Uneven type sizes are what make
    lettering look amateur.
  * DO NOT LOOK AT THE OUTPUT TO JUDGE IT. Send the file to the author. The
    result lists every bubble's box, line breaks and an off_frame flag, which
    answers most layout questions for free.
  * PREVIEW BEFORE ENCODING. letter_video(preview_at=[...]) renders single
    frames through the same filter graph in seconds; encode once he approves.
  * NEVER REWRITE HIS WORDS. Line breaks are chosen automatically, but an
    explicit newline in the text always wins; that is how a line is broken at
    the phrase the author wants.
"""

from __future__ import annotations

import os
import tempfile

from PIL import Image
from mcp.server.fastmcp import FastMCP

import bubbles as bb
import lettering as lt
import script as sc
import store
import video as vd

mcp = FastMCP("speech-bubble")

STYLE_KEYS = ("language", "fonts", "font_scale", "uppercase", "vertical_ja", "reading",
              "max_width", "fill", "stroke", "text", "caption_fill", "caption_text",
              "line_spacing", "pad_scale", "stroke_scale")


def _style(project: str) -> tuple[bb.Style, str]:
    p = store.get_project(project)
    return bb.Style.from_dict(p), p.get("language", "en")


def _bubbles_from(project, name, bubbles):
    if bubbles:
        return bubbles, None
    if not name:
        raise ValueError("Pass bubbles, or the name of saved lettering to re-render.")
    spec = store.load_spec(project, name)
    return spec["bubbles"], spec


def _warnings(placed, frame):
    w = []
    for p in placed:
        d = bb.describe(p, frame)
        if d["off_frame"]:
            w.append(f"{p.id} runs off the frame edge")
    for i, p in enumerate(placed):
        for q in placed[i + 1:]:
            a, b = bb.describe(p, frame)["box_px"], bb.describe(q, frame)["box_px"]
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox > 0 and oy > 0 and ox * oy > 0.15 * min(
                    (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])):
                w.append(f"{p.id} and {q.id} overlap")
    return w


def _merge_spec(project, name, mode, source, bubbles, lang, output):
    try:
        old = store.load_spec(project, name)
    except FileNotFoundError:
        old = {}
    outputs = dict(old.get("outputs", {}))
    outputs[lang] = output
    return store.save_spec(project, name, {"mode": mode, "source": source,
                                           "bubbles": bubbles, "outputs": outputs})


# --- tools ----------------------------------------------------------------------

@mcp.tool()
def set_project_style(project: str, language: str | None = None,
                      fonts: dict | None = None, text_size: float | None = None,
                      uppercase: bool | None = None, vertical_ja: bool | None = None,
                      reading: str | None = None, max_width: float | None = None,
                      colors: dict | None = None) -> dict:
    """Set a project's lettering style. Every argument is optional; only what
    you pass changes.

    language    default language for this project's bubbles ("en", "ja", "zh", "ko")
    fonts       {"en": "C:/path/font.ttf", "ja": "YuGothB.ttc", ...} per language
    text_size   type size as a fraction of the frame's short side (default 0.034,
                ~37 px on 1080p). ONE size for the whole project.
    uppercase   all-caps English, the comic convention (default off: his text
                is lettered as written)
    vertical_ja Japanese in vertical columns (default on)
    reading     "ltr" (English) or "rtl" (manga order) -- used by auto-placement
    max_width   widest a bubble may be, fraction of frame width (default 0.42)
    colors      {"fill": [r,g,b], "stroke": ..., "text": ..., "caption_fill": ...,
                 "caption_text": ...}
    """
    changes = {"language": language, "fonts": fonts, "font_scale": text_size,
               "uppercase": uppercase, "vertical_ja": vertical_ja, "reading": reading,
               "max_width": max_width}
    for k, v in (colors or {}).items():
        if k in ("fill", "stroke", "text", "caption_fill", "caption_text"):
            changes[k] = list(v)
    for lang, f in (fonts or {}).items():
        lt.resolve_font_path(lang, f)  # fail now, not at render time
    return {"project": project, "style": store.update_project(project, changes)}


@mcp.tool()
def get_project_style(project: str = "") -> dict:
    """A project's lettering style, or every project's when none is named.
    Unset values use the defaults in set_project_style."""
    if project:
        st, lang = _style(project)
        return {"project": project, "saved": store.get_project(project),
                "effective": {**st.__dict__, "language": lang,
                              "fonts_resolved": {l: lt.resolve_font_path(l, st.fonts.get(l))
                                                 for l in ("en", "ja", "zh", "ko")}}}
    return {"projects": store.projects()}


@mcp.tool()
def parse_script(text: str) -> dict:
    """Read a script (the text itself, or a path to a .txt/.md file) into
    bubble entries: `NAME: words` is speech, `NAME (thought): words` a thought,
    `NAME (shout|whisper): words` those kinds, `CAPTION: words` a caption box,
    `[notes]`, headings and action lines are kept but never lettered.
    Words are returned exactly as written. Assigning lines to shots is a
    shot-table decision for the author, not something this tool guesses."""
    if len(text) < 260 and os.path.isfile(text):
        with open(text, encoding="utf-8") as f:
            text = f.read()
    return sc.parse(text)


@mcp.tool()
def fit_text(project: str, text: str, kind: str = "speech", lang: str = "",
             frame_width: int = 1920, frame_height: int = 1080) -> dict:
    """How big a bubble this text makes, without drawing anything: its line
    breaks and its size as pixels and as a fraction of the frame. Use it to
    check a translation fits the space the original had."""
    st, dlang = _style(project)
    lang = lang or dlang
    body = bb.measure({"kind": kind, "text": text}, lang, (frame_width, frame_height), st)
    p = bb.Placed("fit", body, frame_width / 2, frame_height / 2, None)
    ex, ey = p.extents()
    return {"lines": body.layout.lines,
            "direction": "vertical" if body.layout.direction == "v" else "horizontal",
            "font_px": body.font_px, "size_px": [round(2 * ex), round(2 * ey)],
            "size_frac": [round(2 * ex / frame_width, 3), round(2 * ey / frame_height, 3)]}


@mcp.tool()
def letter_image(project: str, image: str, bubbles: list[dict] | None = None,
                 lang: str = "", name: str = "") -> dict:
    """Letter a still: draws every bubble onto the image and saves three files
    -- the lettered PNG, the bubbles alone on a transparent layer (for the
    author's own editor, or to swap art underneath), and the spec, so the page
    can be re-lettered in another language or after a change.

    Omit `bubbles` and pass `name` to re-render saved lettering, e.g. in a
    second language. Omitted positions are auto-placed on calm parts of the
    art, near the speaker, in reading order; the result reports where each
    went, so a position can be pinned by copying it into `at`."""
    st, dlang = _style(project)
    lang = lang or dlang
    name = store.safe(name or os.path.splitext(os.path.basename(image))[0])
    bubbles, _ = _bubbles_from(project, name, bubbles)
    with Image.open(image) as im:
        base = im.convert("RGBA")
    frame = base.size
    placed = bb.plan(bubbles, lang, frame, st, image=base)
    layer = bb.layer(frame, placed)
    out_dir = store.image_out(project)
    out = os.path.join(out_dir, f"{name}_{lang}.png")
    layer_path = os.path.join(out_dir, f"{name}_{lang}_layer.png")
    Image.alpha_composite(base, layer).convert("RGB").save(out)
    layer.save(layer_path)
    result = {"image": out, "layer": layer_path,
              "bubbles": [bb.describe(p, frame) for p in placed]}
    result["spec"] = _merge_spec(project, name, "image", image, bubbles, lang,
                                 {"image": out, "layer": layer_path})
    result["warnings"] = _warnings(placed, frame)
    return result


@mcp.tool()
def letter_video(project: str, source: str, bubbles: list[dict] | None = None,
                 lang: str = "", name: str = "", width: int = 0, height: int = 0,
                 fps: float = 0, duration: float = 0, hold: str = "auto",
                 fade: float = 0.45, wait_for_motion: bool = False,
                 preview_at: list[float] | None = None) -> dict:
    """Animate bubbles over a video shot or a still. Each bubble fades (or
    slides, or pops) in after the previous one has had time to be read, and
    stays until the shot ends. If the lines need more time than the clip has,
    the last frame is held (hold="auto"); pass a number of seconds instead to
    set the hold, or "0" for none.

    source          an .mp4/.webm clip, or a still image (then `duration` is
                    its minimum length; it stretches to fit the reading time)
    width, height   output size (default: the source's own; 1920x1080 for delivery)
    wait_for_motion start the first bubble only when the clip's motion ends
    preview_at      seconds -> renders only those frames, with the same
                    function the encode uses. Do this first and show the author.

    Per-bubble `start`/`end`/`in`/`out` override the defaults. Output goes to
    the anime-production server's output folder, with each bubble saved as a
    transparent PNG beside it in <name>_<lang>_bubbles/, for hand editing."""
    st, dlang = _style(project)
    lang = lang or dlang
    name = store.safe(name or os.path.splitext(os.path.basename(source))[0])
    bubbles, _ = _bubbles_from(project, name, bubbles)
    for b in bubbles:
        for k in ("in", "out"):
            if b.get(k) and b[k] not in vd.ANIMS:
                raise ValueError(f"Bubble {b.get('id', '?')}: unknown {k} animation "
                                 f"'{b[k]}'. Use one of {vd.ANIMS}.")
    info = vd.probe(source)
    W = int(width or info["width"]) // 2 * 2
    H = int(height or info["height"]) // 2 * 2
    fps = float(fps or info["fps"] or 24)

    # Auto-placement reads the frame the bubbles mostly land on: the last one.
    if info["still"]:
        with Image.open(source) as im:
            ref = im.convert("RGB").resize((W, H), Image.LANCZOS)
    else:
        tmp = os.path.join(tempfile.gettempdir(), f"sb_{os.getpid()}_last.png")
        vd.grab_frame(source, tmp)
        with Image.open(tmp) as im:
            ref = im.convert("RGB").resize((W, H), Image.LANCZOS)
        os.remove(tmp)

    placed = bb.plan(bubbles, lang, (W, H), st, image=ref)
    base_len = info["duration"] if not info["still"] else (duration or None)
    hold_v = "auto" if str(hold) == "auto" else float(hold)
    times, total, held = vd.schedule(bubbles, [p.body.text for p in placed], lang,
                                     base_len, fade=fade, hold=hold_v,
                                     wait_for_motion=wait_for_motion)
    out = os.path.join(store.video_out(project), f"{name}_{lang}.mp4")
    work = os.path.splitext(out)[0] + "_bubbles"
    os.makedirs(work, exist_ok=True)
    sprites = []
    for p, tm, b in zip(placed, times, bubbles):
        path = os.path.join(work, f"{store.safe(p.id)}.png")
        p.sprite.save(path)
        sprites.append({"image": p.sprite, "path": path, "x0": p.x0, "y0": p.y0,
                        "ax": (p.cx - p.x0) / p.sprite.width,
                        "ay": (p.cy - p.y0) / p.sprite.height,
                        "start": tm["start"], "end": tm["end"],
                        "in": b.get("in", "fade"), "out": b.get("out", "none")})
    res = vd.render(source, info, (W, H), fps, total, held, sprites, out,
                    fade=fade, preview_at=preview_at)
    res["timeline"] = [{"id": p.id, "kind": p.body.kind, **tm}
                       for p, tm in zip(placed, times)]
    res["bubbles"] = [bb.describe(p, (W, H)) for p in placed]
    res["warnings"] = _warnings(placed, (W, H))
    if not preview_at:
        res["spec"] = _merge_spec(project, name, "video", source, bubbles, lang,
                                  {"video": out, "seconds": total})
    return res


@mcp.tool()
def list_lettering(project: str) -> dict:
    """Every saved lettered page or shot in a project, with its languages."""
    return {"project": project, "lettering": store.list_specs(project)}


@mcp.tool()
def get_lettering(project: str, name: str) -> dict:
    """One saved lettering spec: its bubbles exactly as written, and its outputs."""
    return store.load_spec(project, name)


@mcp.tool()
def check_status() -> dict:
    """What this server can find: ffmpeg (needed only for video), a font for
    each language, and where it writes."""
    fonts = {}
    for lang in ("en", "ja", "zh", "ko"):
        try:
            fonts[lang] = lt.resolve_font_path(lang)
        except FileNotFoundError as e:
            fonts[lang] = f"MISSING: {e}"
    try:
        ff = vd.find_ffmpeg()
    except FileNotFoundError as e:
        ff = f"MISSING: {e}"
    return {"ffmpeg": ff, "fonts": fonts, "state": store.state_dir(),
            "image_output": os.path.join(store.image_root(), "<project>", "lettered"),
            "video_output": os.path.join(store.video_root(), "<project>", "lettered")}


if __name__ == "__main__":
    mcp.run()
