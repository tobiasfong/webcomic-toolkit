"""
compose_sheet.py — deterministic PIL layout tools that arrange separately-
generated reference views into ONE composite sheet image. Zero GPU, zero tokens.

Two layouts:
  compose_sheet()          — plain grid of labeled crops, no design opinion.
  compose_concept_sheet()  — a poster layout modeled on Tobias's friend Avery's
                              hand-composed God/Speed character sheets: title,
                              a large front-view hero pose, a back-view panel,
                              a column of labeled expression close-ups, and
                              short text blocks (role/status/abilities/
                              personality) pulled straight from the Character
                              Bible. Deliberately far less text than Avery's
                              sheets (no bio paragraphs, no quotes, no lore
                              boxes) — this server generates panels, it doesn't
                              write your story's text for you.

(ARCHITECTURE.md §8b.6 originally called the "designed sheet" a non-goal —
correct at the time; ripped out once there was an actual template to build
toward and someone asked for it.)

Usage:
    python compose_sheet.py view1.png view2.png view3.png --label "front" \
        --label "back" --label "side" --out sheet.png
"""
import os
import math
import argparse


def compose_sheet(image_paths, labels=None, out=None, columns=None,
                  cell_width=320, padding=16, label_height=28,
                  background_color=(255, 255, 255)):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise SystemExit("compose_sheet needs Pillow: <venv>/python -m pip install pillow")
    if not image_paths:
        raise SystemExit("compose_sheet needs at least one image.")
    if labels is not None and len(labels) != len(image_paths):
        raise SystemExit(f"got {len(labels)} labels for {len(image_paths)} images — "
                         f"pass one label per image, or none at all.")

    n = len(image_paths)
    if columns is None:
        columns = max(1, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / columns) if columns else 1

    imgs = []
    for p in image_paths:
        if not os.path.isfile(p):
            raise SystemExit(f"could not read image: {p}")
        im = Image.open(p).convert("RGB")
        scale = cell_width / im.width
        cell_h = max(1, round(im.height * scale))
        imgs.append(im.resize((cell_width, cell_h), Image.LANCZOS))

    row_heights = []
    for r in range(rows):
        row_imgs = imgs[r * columns:(r + 1) * columns]
        row_heights.append(max((im.height for im in row_imgs), default=0))

    label_block = label_height if labels else 0
    canvas_w = columns * cell_width + (columns + 1) * padding
    canvas_h = sum(h + label_block for h in row_heights) + (rows + 1) * padding
    canvas = Image.new("RGB", (canvas_w, canvas_h), background_color)
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    y = padding
    for r in range(rows):
        x = padding
        row_h = row_heights[r]
        for c in range(columns):
            i = r * columns + c
            if i >= n:
                break
            im = imgs[i]
            # vertically center within the row's tallest cell
            y_off = (row_h - im.height) // 2
            canvas.paste(im, (x, y + y_off))
            if labels:
                label = labels[i]
                text_y = y + row_h + 4
                if font is not None:
                    bbox = draw.textbbox((0, 0), label, font=font)
                    tw = bbox[2] - bbox[0]
                else:
                    tw = len(label) * 6
                draw.text((x + (cell_width - tw) // 2, text_y), label,
                         fill=(0, 0, 0), font=font)
            x += cell_width + padding
        y += row_h + label_block + padding

    if out is None:
        root = os.path.splitext(image_paths[0])[0]
        out = f"{root}_sheet.png"
        n2 = 1
        while os.path.exists(out):
            out = f"{root}_sheet_{n2}.png"
            n2 += 1
    canvas.save(out)
    return out


# Noto Sans JP covers both Latin and Japanese glyphs in one file — needed
# because `personality` text may legitimately contain Japanese speech-pattern
# notes (敬語/普通語, 俺/私/etc.) mixed with English. Falls back to a
# Latin-only font (or PIL's bitmap default) on machines without it — Japanese
# text will show as tofu boxes there, which is an honest degrade, not silent
# corruption.
def _font(size, bold=False):
    from PIL import ImageFont
    noto = "C:/Windows/Fonts/NotoSansJP-VF.ttf"
    if os.path.isfile(noto):
        try:
            f = ImageFont.truetype(noto, size)
            if bold:
                f.set_variation_by_name("Bold")
            return f
        except Exception:
            pass
    candidates = []
    if os.name == "nt":
        windir = os.environ.get("WINDIR", "C:/Windows")
        candidates.append(os.path.join(windir, "Fonts", "arialbd.ttf" if bold else "arial.ttf"))
    else:
        candidates += [
            f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
            f"/System/Library/Fonts/Supplemental/Arial{' Bold' if bold else ''}.ttf",
        ]
    for c in candidates:
        if os.path.isfile(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _wrap_pixels(draw, text, font, max_width):
    """Word-wrap text to max_width pixels, measured with the actual font (not a
    char-count estimate) — needed because Japanese/Latin glyphs have very
    different widths in the same font. Preserves existing newlines."""
    lines = []
    for para in text.splitlines() or [""]:
        words = para.split(" ")
        if not words or words == [""]:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = f"{cur} {w}"
            if draw.textlength(trial, font=font) <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def compose_concept_sheet(
    front_path,
    back_path=None,
    expression_paths=None,
    expression_labels=None,
    name="Character",
    profile="",
    abilities="",
    appearance="",
    accent_color=None,
    out=None,
):
    """Lay out one character's generated views + Character Bible text into ONE
    poster-style reference sheet — see the module docstring for the Avery-style
    template this follows. `front_path` is the only required image; everything
    else is optional so a partial call still produces something reasonable.

    Args:
        front_path: The full-body front view — the large hero image, center of
            the sheet.
        back_path: The full-body back view, shown in its own labeled panel.
        expression_paths / expression_labels: Parallel lists — face close-ups
            and their captions (e.g. the view text minus the "face close-up, "
            prefix). Rendered as a labeled column, Avery-sheet "EXPRESSIONS"-row
            style.
        name: Character name, rendered as the title.
        profile: Who they are — role in the story, standing, personality, speech
            patterns. Bible's `profile` field.
        abilities: Powers/skills/equipment. Bible's `abilities` field.
        appearance: Hair/eye color, build, costume — bible's `description`
            field, passed through under this heading rather than a separate
            field, so it's typed once and does double duty (generation prompt
            input AND sheet text).
        Each of the three gets its own labeled block, wrapped to the left
        column's width; empty ones are skipped entirely (no empty box).
        accent_color: (r, g, b) for the title/section-heading color. Defaults to
            a neutral gold if omitted — pass the character's extracted palette's
            first color for a per-character accent.
        out: Output path. Auto-derived next to front_path if omitted.

    Returns:
        The filesystem path to the saved sheet PNG.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("compose_concept_sheet needs Pillow: <venv>/python -m pip install pillow")
    if not os.path.isfile(front_path):
        raise SystemExit(f"could not read front image: {front_path}")

    expression_paths = expression_paths or []
    expression_labels = expression_labels or [f"view {i + 1}" for i in range(len(expression_paths))]

    BG = (17, 15, 19)
    FG = (228, 224, 216)
    MUTED = (150, 145, 140)
    ACCENT = tuple(accent_color) if accent_color else (212, 175, 110)
    RULE = (58, 54, 50)

    PAD = 36
    LEFT_W = 420
    CENTER_W = 660
    RIGHT_W = 380
    HEADER_H = 130

    f_title = _font(56, bold=True)
    f_h2 = _font(23, bold=True)
    f_body = _font(20)
    f_label = _font(16, bold=True)
    f_caption = _font(17)

    scratch = Image.new("RGB", (10, 10))
    sdraw = ImageDraw.Draw(scratch)

    def text_h(text, font):
        bbox = sdraw.textbbox((0, 0), text or " ", font=font)
        return bbox[3] - bbox[1]

    # --- load + scale images ---
    front = Image.open(front_path).convert("RGB")
    front = front.resize((CENTER_W, round(CENTER_W * front.height / front.width)), Image.LANCZOS)

    back = None
    if back_path and os.path.isfile(back_path):
        back = Image.open(back_path).convert("RGB")
        back = back.resize((RIGHT_W, round(RIGHT_W * back.height / back.width)), Image.LANCZOS)

    # Expression images are "face close-up" renders on the same full-body
    # portrait canvas as everything else — most of the frame is empty backdrop
    # around a small face. Avery's sheets show expressions as a compact
    # horizontal row of small square headshots, not a tall stack — matching
    # that (rather than stacking full-width thumbnails) is what keeps this
    # column from towering over the front hero image. Crop a top-anchored
    # square per thumbnail (cheap headshot-crop heuristic, no face-detection
    # dependency — matches how this server's close-up prompts frame the
    # subject), sized to fit N across RIGHT_W.
    n_expr = len(expression_paths)
    EXPR_GAP = 10
    expr_side = (RIGHT_W - EXPR_GAP * max(0, n_expr - 1)) // max(1, n_expr) if n_expr else 0
    f_expr_caption = _font(14)

    exprs = []
    for p in expression_paths:
        if not os.path.isfile(p):
            continue
        im = Image.open(p).convert("RGB")
        side = min(im.width, im.height)
        left = (im.width - side) // 2
        im = im.crop((left, 0, left + side, side))
        exprs.append(im.resize((expr_side, expr_side), Image.LANCZOS))
    expression_labels = expression_labels[:len(exprs)]

    # --- build the left text column as a flat list of draw ops ---
    left_ops = []  # (text, font, color, height)

    def heading(text):
        left_ops.append((text, f_h2, ACCENT, text_h(text, f_h2) + 10))

    def body(text):
        for ln in _wrap_pixels(sdraw, text, f_body, LEFT_W):
            left_ops.append((ln, f_body, FG, text_h(ln, f_body) + 6))
        left_ops.append(("", f_body, FG, 22))

    if profile:
        heading("PROFILE")
        body(profile)
    if abilities:
        heading("ABILITIES")
        body(abilities)
    if appearance:
        heading("APPEARANCE")
        body(appearance)

    left_content_h = sum(h for _, _, _, h in left_ops)

    right_content_h = 0
    if exprs:
        right_content_h += (text_h("EXPRESSIONS", f_h2) + 14 + expr_side + 6
                            + text_h("Ag", f_expr_caption) + 20)
    if back is not None:
        right_content_h += text_h("BACK VIEW", f_h2) + 14 + back.height

    body_h = max(front.height, left_content_h, right_content_h, 1)
    canvas_w = PAD * 4 + LEFT_W + CENTER_W + RIGHT_W
    canvas_h = HEADER_H + body_h + PAD * 2

    canvas = Image.new("RGB", (canvas_w, canvas_h), BG)
    draw = ImageDraw.Draw(canvas)

    # header
    draw.text((PAD, PAD), name.upper(), font=f_title, fill=ACCENT)
    draw.line([(PAD, HEADER_H - 14), (canvas_w - PAD, HEADER_H - 14)], fill=RULE, width=2)

    y0 = HEADER_H + PAD

    # left column
    x, y = PAD, y0
    for text, font, color, h in left_ops:
        if text:
            draw.text((x, y), text, font=font, fill=color)
        y += h

    # center column: front hero image
    cx = PAD * 2 + LEFT_W
    canvas.paste(front, (cx, y0))
    draw.text((cx, y0 + front.height + 8), "FRONT VIEW", font=f_label, fill=MUTED)

    # right column: expressions (horizontal row), then back view
    rx, ry = PAD * 3 + LEFT_W + CENTER_W, y0
    if exprs:
        draw.text((rx, ry), "EXPRESSIONS", font=f_h2, fill=ACCENT)
        ry += text_h("EXPRESSIONS", f_h2) + 14
        ex = rx
        for im, lbl in zip(exprs, expression_labels):
            canvas.paste(im, (ex, ry))
            label_y = ry + im.height + 6
            tw = draw.textlength(lbl.upper(), font=f_expr_caption)
            draw.text((ex + (expr_side - tw) / 2, label_y), lbl.upper(),
                     font=f_expr_caption, fill=MUTED)
            ex += expr_side + EXPR_GAP
        ry += expr_side + 6 + text_h("Ag", f_expr_caption) + 20
    if back is not None:
        draw.text((rx, ry), "BACK VIEW", font=f_h2, fill=ACCENT)
        ry += text_h("BACK VIEW", f_h2) + 14
        canvas.paste(back, (rx, ry))

    if out is None:
        root = os.path.splitext(front_path)[0]
        out = f"{root}_concept_sheet.png"
        n2 = 1
        while os.path.exists(out):
            out = f"{root}_concept_sheet_{n2}.png"
            n2 += 1
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    canvas.save(out)
    return out


def compose_full_reference_sheet(
    front_path,
    back_path=None,
    expression_paths=None,
    expression_labels=None,
    name="Character",
    subtitle="",
    profile="",
    abilities="",
    appearance="",
    functions=None,
    notes=None,
    prop_path=None,
    prop_label="",
    prop_caption="",
    diagram_path=None,
    action_paths=None,
    action_labels=None,
    accent_color=None,
    out=None,
):
    """A denser Avery-template-style poster: bordered boxes scattered around
    a hero pose (left/center/right columns + an action-pose row), instead of
    compose_concept_sheet()'s single stacked-left-column layout. Everything
    besides front_path is optional, so a partial call still produces something
    reasonable — skip a section entirely rather than draw an empty box.

    Deliberately does NOT model a stat box (age/height/likes/dislikes), a
    personal quote, or a mission-statement box — those need real per-character
    facts this server has no field for, and guessing at them was explicitly
    rejected once already (don't invent bio details). Add explicit params for
    those if a real, user-supplied need shows up later.

    Args:
        front_path / back_path: full-body views.
        expression_paths / expression_labels: face/angle close-ups shown as a
            row of square headshot crops (top-anchored), Avery "EXPRESSIONS"
            style.
        name / subtitle: title block.
        profile / abilities / appearance: Character Bible text, one bordered
            box each.
        functions: bullet list under a "FUNCTIONS" box — e.g. abilities broken
            into short bullet phrases (caller's job to derive from real text,
            not invent).
        notes: bullet list under a "FILE NOTES" box — same idea, sourced from
            real profile text.
        prop_path / prop_label / prop_caption: one boxed illustration (a
            signature item/artifact), Avery "JADE MAGATAMA"-style.
        diagram_path: one boxed illustration explaining how the character's
            ability works (caller renders this separately, e.g. via PIL boxes
            + arrows — this function just embeds whatever image it's given).
        action_paths / action_labels: a labeled row of action/combat poses,
            Avery "IN ACTION" style. Shown at full aspect ratio (not
            square-cropped) since the prop/effect can be anywhere in frame.
        accent_color: (r, g, b) heading/border color. Defaults to a neutral
            gold.
        out: output path, auto-derived next to front_path if omitted.

    Returns:
        The filesystem path to the saved sheet PNG.
    """
    from PIL import Image, ImageDraw

    if not os.path.isfile(front_path):
        raise SystemExit(f"could not read front image: {front_path}")

    expression_paths = expression_paths or []
    expression_labels = expression_labels or [f"view {i + 1}" for i in range(len(expression_paths))]
    functions = functions or []
    notes = notes or []
    action_paths = action_paths or []
    action_labels = action_labels or [f"action {i + 1}" for i in range(len(action_paths))]

    BG = (17, 15, 19)
    BOX_BG = (23, 20, 24)
    FG = (228, 224, 216)
    MUTED = (150, 145, 140)
    ACCENT = tuple(accent_color) if accent_color else (212, 175, 110)
    BORDER = (70, 60, 58)

    PAD = 36
    LEFT_W = 380
    CENTER_W = 620
    RIGHT_W = 420
    BOX_GAP = 28
    BOX_PAD = 20
    HERO_MAX_H = 820
    SIDE_IMG_MAX_H = 460

    f_title = _font(52, bold=True)
    f_subtitle = _font(17)
    f_body = _font(19)
    f_bullet = _font(18)
    f_label = _font(15, bold=True)
    f_caption = _font(15)

    scratch0 = Image.new("RGB", (10, 10))
    sdraw0 = ImageDraw.Draw(scratch0)

    def text_h(text, font):
        bbox = sdraw0.textbbox((0, 0), text or " ", font=font)
        return bbox[3] - bbox[1]

    def wrapped(text, font, max_w):
        return _wrap_pixels(sdraw0, text, font, max_w)

    def measure_lines(lines, font, line_gap=9):
        return sum(text_h(ln, font) + line_gap for ln in lines) if lines else 0

    # ---------- crest (decorative only — no invented lore, just a mark) ----------
    def make_crest(size=72):
        crest_im = Image.new("RGB", (size, size), BG)
        cdraw = ImageDraw.Draw(crest_im)
        m = 4
        cdraw.ellipse([m, m, size - m, size - m], outline=ACCENT, width=3)
        bw, bh = size * 0.5, size * 0.26
        bx, by = (size - bw) / 2, (size - bh) / 2 + 2
        cdraw.line([(bx, by), (bx + bw / 2, by + 6), (bx + bw, by)], fill=ACCENT, width=2)
        cdraw.line([(bx, by), (bx, by + bh)], fill=ACCENT, width=2)
        cdraw.line([(bx + bw, by), (bx + bw, by + bh)], fill=ACCENT, width=2)
        cdraw.line([(bx, by + bh), (bx + bw / 2, by + bh - 6), (bx + bw, by + bh)], fill=ACCENT, width=2)
        cdraw.line([(bx + bw / 2, by + 6), (bx + bw / 2, by + bh - 6)], fill=ACCENT, width=1)
        return crest_im

    crest = make_crest(72)

    # ---------- box primitives ----------
    def draw_box(d, x, y, w, title, body_h, accent=ACCENT):
        """Border + header for a box whose body height is already known.
        Returns (content_y, box_bottom_y)."""
        title_h = (text_h(title, f_label) + 18) if title else 12
        total_h = title_h + body_h + BOX_PAD * 2
        d.rectangle([x, y, x + w, y + total_h], fill=BOX_BG, outline=accent, width=2)
        if title:
            d.text((x + BOX_PAD, y + 11), title.upper(), font=f_label, fill=accent)
        return y + title_h + BOX_PAD, y + total_h

    def text_box(d, x, y, w, title, text, accent=ACCENT):
        lines = wrapped(text, f_body, w - BOX_PAD * 2)
        body_h = measure_lines(lines, f_body)
        cy, bottom = draw_box(d, x, y, w, title, body_h, accent)
        for ln in lines:
            d.text((x + BOX_PAD, cy), ln, font=f_body, fill=FG)
            cy += text_h(ln, f_body) + 9
        return bottom

    def bullet_box(d, x, y, w, title, items, accent=ACCENT):
        all_lines = []
        for item in items:
            all_lines.extend(wrapped(f"•  {item}", f_bullet, w - BOX_PAD * 2))
        body_h = measure_lines(all_lines, f_bullet)
        cy, bottom = draw_box(d, x, y, w, title, body_h, accent)
        for ln in all_lines:
            d.text((x + BOX_PAD, cy), ln, font=f_bullet, fill=FG)
            cy += text_h(ln, f_bullet) + 9
        return bottom

    def image_box(d, cv, x, y, w, title, im, caption=None, accent=ACCENT, max_h=None):
        im2 = im.copy()
        target_w = w - BOX_PAD * 2
        scale = target_w / im2.width
        if max_h and round(im2.height * scale) > max_h:
            scale = max_h / im2.height
        new_w, new_h = round(im2.width * scale), round(im2.height * scale)
        im2 = im2.resize((new_w, new_h), Image.LANCZOS)
        cap_h = (text_h(caption, f_caption) + 10) if caption else 0
        body_h = new_h + cap_h
        cy, bottom = draw_box(d, x, y, w, title, body_h, accent)
        paste_x = x + (w - new_w) // 2
        cv.paste(im2, (paste_x, cy))
        if caption:
            d.text((x + BOX_PAD, cy + new_h + 8), caption, font=f_caption, fill=MUTED)
        return bottom

    def row_box(d, cv, x, y, w, title, ims, labels, accent=ACCENT, gap=12, square=True):
        n = len(ims)
        if n == 0:
            return y
        cells = []
        if square:
            cell_w = (w - BOX_PAD * 2 - gap * (n - 1)) // n
            for im in ims:
                side = min(im.width, im.height)
                left = (im.width - side) // 2
                cells.append(im.crop((left, 0, left + side, side)).resize((cell_w, cell_w), Image.LANCZOS))
        else:
            # uniform HEIGHT (not width) — full aspect preserved, no cropping,
            # so mismatched source aspects (e.g. a 3/4-view crop vs a profile
            # crop of different width) still line up evenly in the row.
            aspects = [im.width / im.height for im in ims]
            target_h = (w - BOX_PAD * 2 - gap * (n - 1)) / sum(aspects)
            for im, aspect in zip(ims, aspects):
                cells.append(im.resize((round(target_h * aspect), round(target_h)), Image.LANCZOS))
        max_h = max(c.height for c in cells)
        label_h = text_h("Ag", f_caption) + 10
        body_h = max_h + label_h
        cy, bottom = draw_box(d, x, y, w, title, body_h, accent)
        cx = x + BOX_PAD
        for cell, lbl in zip(cells, labels):
            cv.paste(cell, (cx, cy + (max_h - cell.height)))
            lw = d.textlength(lbl.upper(), font=f_caption)
            d.text((cx + (cell.width - lw) / 2, cy + max_h + 6), lbl.upper(), font=f_caption, fill=MUTED)
            cx += cell.width + gap
        return bottom

    # ---------- preload images ----------
    front = Image.open(front_path).convert("RGB")
    back = Image.open(back_path).convert("RGB") if back_path and os.path.isfile(back_path) else None
    exprs = [Image.open(p).convert("RGB") for p in expression_paths if os.path.isfile(p)]
    actions = [Image.open(p).convert("RGB") for p in action_paths if os.path.isfile(p)]
    prop_im = Image.open(prop_path).convert("RGB") if prop_path and os.path.isfile(prop_path) else None
    diagram_im = Image.open(diagram_path).convert("RGB") if diagram_path and os.path.isfile(diagram_path) else None

    # front + back shown side by side in one box, scaled to a shared height —
    # no per-image caption needed, front/back is obvious from position.
    FB_GAP = 18
    if back is not None:
        fb_scale = HERO_MAX_H / max(front.height, back.height)
        front_scaled = front.resize((round(front.width * fb_scale), round(front.height * fb_scale)), Image.LANCZOS)
        back_scaled = back.resize((round(back.width * fb_scale), round(back.height * fb_scale)), Image.LANCZOS)
        fb_w = front_scaled.width + FB_GAP + back_scaled.width
        fb_h = max(front_scaled.height, back_scaled.height)
    else:
        fb_scale = HERO_MAX_H / front.height
        front_scaled = front.resize((round(front.width * fb_scale), HERO_MAX_H), Image.LANCZOS)
        back_scaled = None
        fb_w, fb_h = front_scaled.width, front_scaled.height

    canvas_w = PAD * 2 + LEFT_W + BOX_GAP + CENTER_W + BOX_GAP + RIGHT_W

    def layout(d, cv):
        cv.paste(crest, (PAD, PAD))
        title_x = PAD + crest.width + 18
        d.text((title_x, PAD - 8), name.upper(), font=f_title, fill=ACCENT)
        title_bottom = PAD - 8 + text_h(name.upper(), f_title)
        sub_h = 0
        if subtitle:
            d.text((title_x, title_bottom + 6), subtitle.upper(), font=f_subtitle, fill=MUTED)
            sub_h = text_h(subtitle, f_subtitle) + 6
        header_bottom = max(PAD + crest.height, title_bottom + sub_h) + 20
        d.line([(PAD, header_bottom), (canvas_w - PAD, header_bottom)], fill=BORDER, width=2)
        y0 = header_bottom + BOX_GAP

        # left column
        lx, ly = PAD, y0
        if profile:
            ly = text_box(d, lx, ly, LEFT_W, "PROFILE", profile) + BOX_GAP
        if appearance:
            ly = text_box(d, lx, ly, LEFT_W, "APPEARANCE", appearance) + BOX_GAP
        if notes:
            ly = bullet_box(d, lx, ly, LEFT_W, "FILE NOTES", notes) + BOX_GAP
        if prop_im is not None:
            ly = image_box(d, cv, lx, ly, LEFT_W, prop_label or "ARTIFACT", prop_im,
                           prop_caption, max_h=SIDE_IMG_MAX_H) + BOX_GAP

        # center column: front + back side by side, then action row
        cx0 = PAD + LEFT_W + BOX_GAP
        cy0 = y0
        fb_box_h = fb_h + BOX_PAD * 2
        d.rectangle([cx0, cy0, cx0 + CENTER_W, cy0 + fb_box_h], fill=BOX_BG, outline=ACCENT, width=2)
        paste_x = cx0 + (CENTER_W - fb_w) // 2
        cv.paste(front_scaled, (paste_x, cy0 + BOX_PAD + (fb_h - front_scaled.height)))
        if back_scaled is not None:
            cv.paste(back_scaled, (paste_x + front_scaled.width + FB_GAP,
                                   cy0 + BOX_PAD + (fb_h - back_scaled.height)))
        cy = cy0 + fb_box_h + BOX_GAP
        if actions:
            cy = row_box(d, cv, cx0, cy, CENTER_W, "IN ACTION", actions, action_labels,
                        square=False) + BOX_GAP

        # right column
        rx0 = PAD + LEFT_W + BOX_GAP + CENTER_W + BOX_GAP
        ry = y0
        if exprs:
            ry = row_box(d, cv, rx0, ry, RIGHT_W, "EXPRESSIONS", exprs, expression_labels,
                        square=False) + BOX_GAP
        if abilities:
            ry = text_box(d, rx0, ry, RIGHT_W, "ABILITIES", abilities) + BOX_GAP
        if functions:
            ry = bullet_box(d, rx0, ry, RIGHT_W, "FUNCTIONS", functions) + BOX_GAP
        if diagram_im is not None:
            ry = image_box(d, cv, rx0, ry, RIGHT_W, "MECHANISM", diagram_im) + BOX_GAP

        return max(ly, cy, ry)

    # pass 1: measure on a tall scratch canvas (cheap — no GPU work, just PIL)
    scratch_canvas = Image.new("RGB", (canvas_w, 8000), BG)
    total_h = layout(ImageDraw.Draw(scratch_canvas), scratch_canvas)

    # pass 2: real canvas, exact height
    canvas = Image.new("RGB", (canvas_w, total_h + PAD), BG)
    layout(ImageDraw.Draw(canvas), canvas)

    if out is None:
        root = os.path.splitext(front_path)[0]
        out = f"{root}_full_sheet.png"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    canvas.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--label", action="append", default=None,
                    help="one per image, in order — repeat for multiple")
    ap.add_argument("--columns", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    print(compose_sheet(a.images, a.label, a.out, a.columns))
