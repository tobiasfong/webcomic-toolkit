"""
compose_panel.py — deterministic CPU compositing of a character cutout onto a
background plate. No GPU, no per-image cost, instant to iterate — see
ARCHITECTURE.md §8b.3: "panels are composites, not one-shot generations."

On "free": run as the CLI below, this genuinely costs nothing. But unlike its
CLI-only siblings (clean_crop, compose_strip), this one is ALSO exposed as an
MCP tool in server.py, and reaching it through a harness spends tokens like any
other tool call. The compositing is free; invoking it from a chat is not.

Positioning is feet-anchored (feet_x, feet_y, height_px) rather than a raw
top-left paste box because that is exactly the shape webcomic-background-mcp's
`generate_city_scene(anchor_x=..., anchor_z=...)` already reports back
(`height_px` / `feet_y_px` from `citygen.render_anchor()`) — this tool is designed
to consume that output directly, no conversion needed.

Multi-character panels: call this once per character, passing the previous call's
output back in as `base` (start the first call with `background` instead). Same
"grow it incrementally" shape as this server's `add_city_district` sibling in
webcomic-background-mcp — "redo panel 7 with a sadder expression" is just
re-rendering one character layer and re-compositing, not regenerating the panel.

Usage:
    python compose_panel.py <character_layer.png> --feet-x 512 --feet-y 780
        --height-px 340 --background <plate.png> [--out panel.png]
"""
import os
import argparse


def compose_panel(character_layer_path, feet_x, feet_y, height_px,
                  background=None, base=None, out=None):
    if bool(background) == bool(base):
        raise SystemExit("compose_panel needs exactly one of --background (start a "
                         "new panel) or --base (add a layer to an existing panel).")
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("compose_panel needs Pillow: <venv>/python -m pip install pillow")

    src = base or background
    if not os.path.isfile(src):
        raise SystemExit(f"could not read background/base: {src}")
    if not os.path.isfile(character_layer_path):
        raise SystemExit(f"could not read character layer: {character_layer_path}")

    canvas = Image.open(src).convert("RGBA")
    char = Image.open(character_layer_path).convert("RGBA")

    cw, ch = char.size
    if ch <= 0:
        raise SystemExit(f"character layer has zero height: {character_layer_path}")
    scale = height_px / ch
    new_w, new_h = max(1, round(cw * scale)), max(1, round(height_px))
    char_resized = char.resize((new_w, new_h), Image.LANCZOS)

    # bottom-center of the resized layer lands at (feet_x, feet_y)
    paste_x = round(feet_x - new_w / 2)
    paste_y = round(feet_y - new_h)
    canvas.paste(char_resized, (paste_x, paste_y), char_resized)

    if out is None:
        root = os.path.splitext(src)[0]
        out = f"{root}_panel.png"
        n = 1
        while os.path.exists(out):
            out = f"{root}_panel_{n}.png"
            n += 1
    canvas.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("character_layer")
    ap.add_argument("--feet-x", type=float, required=True)
    ap.add_argument("--feet-y", type=float, required=True)
    ap.add_argument("--height-px", type=float, required=True)
    ap.add_argument("--background", default=None, help="start a new panel from this plate")
    ap.add_argument("--base", default=None, help="add a layer onto this existing panel")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    print(compose_panel(a.character_layer, a.feet_x, a.feet_y, a.height_px,
                        a.background, a.base, a.out))
