"""
subs.py — bilingual burned-in captions, and the matching .srt.

ONE SOURCE OF TRUTH. The cue list drives both the burned-in captions and the
sidecar, so the two can never drift apart. Timings come from the author calling
lines against the vocal by ear; beat detection cannot supply them, because a
downbeat says where the bar is, not where a sung line starts.

LEGIBILITY. Panels are full-bleed, so a caption sits over artwork whose
brightness is unknown and changes shot to shot. Dark text vanishes on a night
sky, light text on a white mat. Each line therefore gets three layers — a
blurred dark glow, a dark stroke, then near-white fill — which reads on
anything.

COST. A line's pixels never change while it is on screen, so each is rasterised
ONCE into a sprite and composited per frame. Rendering text for every frame of a
two-minute video costs more than the artwork does.

BURNED IN *OR* SIDECAR, RARELY BOTH. If the captions are in the picture and an
.srt is also uploaded, players that default subtitles on will draw a second copy
over the first. Upload the video alone, or render with captions off and ship the
.srt.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# The caption block's bottom edge, as a fraction of frame height. 0.937 of 1080
# leaves 68px — YouTube's control bar rides over roughly the last 60px whenever
# the viewer moves the mouse, and a caption under it is simply gone.
BOTTOM_FRAC = 0.937
FADE = 0.15


class Subtitles:
    """Rasterised cues, ready to composite.

    cues: [(start, end, primary, secondary)] in seconds. `primary` is drawn full
    size, `secondary` beneath it at `secondary_scale`. Pass an empty secondary
    for a monolingual caption.
    """

    def __init__(self, cues, size=(1920, 1080),
                 primary_font=r"C:\Windows\Fonts\meiryob.ttc",
                 secondary_font=r"C:\Windows\Fonts\segoeuib.ttf",
                 primary_size=52, secondary_scale=0.7, gap=10,
                 fill=(252, 250, 248), stroke=(24, 20, 28), glow=(10, 8, 14),
                 bottom_frac=BOTTOM_FRAC):
        self.size = size
        self.fade = FADE
        W, H = size
        sec_size = max(8, int(round(primary_size * secondary_scale)))
        self.pf = ImageFont.truetype(primary_font, primary_size)
        self.sf = ImageFont.truetype(secondary_font, sec_size)
        self.p_stroke = max(2, round(primary_size * 0.096))
        self.s_stroke = max(2, round(sec_size * 0.11))
        self.gap = gap
        self.fill = (*fill, 255)
        self.stroke = (*stroke, 255)
        self.glow = (*glow, 255)
        self.bottom = int(H * bottom_frac)
        self.cues = [self._sprite(*c) for c in self._validate(cues)]

    @staticmethod
    def _validate(cues):
        out = []
        for c in cues:
            if len(c) == 3:
                c = (c[0], c[1], c[2], "")
            t0, t1, a, b = c[0], c[1], c[2], c[3]
            if t1 <= t0:
                raise ValueError(f"Cue ends before it starts: {c}")
            out.append((float(t0), float(t1), a, b or ""))
        out.sort(key=lambda c: c[0])
        for i in range(1, len(out)):
            if out[i][0] < out[i - 1][1]:
                raise ValueError(
                    f"Cues overlap: {out[i-1][2]!r} ends {out[i-1][1]}s but "
                    f"{out[i][2]!r} starts {out[i][0]}s. Two captions on screen at "
                    f"once is almost never intended."
                )
        return out

    def _sprite(self, t0, t1, primary, secondary):
        W, _ = self.size
        probe = ImageDraw.Draw(Image.new("L", (8, 8)))
        pb = probe.textbbox((0, 0), primary, font=self.pf, stroke_width=self.p_stroke)
        ph = pb[3] - pb[1]
        if secondary:
            sb = probe.textbbox((0, 0), secondary, font=self.sf, stroke_width=self.s_stroke)
            sh = sb[3] - sb[1]
        else:
            sb, sh = (0, 0, 0, 0), 0

        pad = 22                                  # room for the glow to fall off
        hgt = pad + ph + (self.gap + sh if secondary else 0) + pad
        py = pad - pb[1]
        sy = pad + ph + self.gap - sb[1]
        px = (W - (pb[2] - pb[0])) // 2 - pb[0]
        sx = (W - (sb[2] - sb[0])) // 2 - sb[0]

        def draw_on(d, ink_p, ink_s, stroke_p, stroke_s):
            d.text((px, py), primary, font=self.pf, fill=ink_p,
                   stroke_width=self.p_stroke, stroke_fill=stroke_p)
            if secondary:
                d.text((sx, sy), secondary, font=self.sf, fill=ink_s,
                       stroke_width=self.s_stroke, stroke_fill=stroke_s)

        m = Image.new("L", (W, hgt), 0)
        draw_on(ImageDraw.Draw(m), 255, 255, 255, 255)
        m = m.filter(ImageFilter.GaussianBlur(8)).point(lambda v: min(255, int(v * 1.6)))

        sp = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
        sp.paste(Image.new("RGBA", (W, hgt), self.glow), (0, 0), m)
        draw_on(ImageDraw.Draw(sp), self.fill, self.fill, self.stroke, self.stroke)
        return (t0, t1, sp, self.bottom - (hgt - pad))

    def draw(self, canvas: Image.Image, t: float) -> Image.Image:
        """Return canvas with whichever caption is live at t composited on.

        COPIES before pasting. Scene frames come straight out of a cached clip
        list that loops, so drawing into one in place would burn the caption
        permanently into every later pass over that frame.
        """
        for t0, t1, sp, y in self.cues:
            if not (t0 - self.fade <= t <= t1 + self.fade):
                continue
            a = min((t - (t0 - self.fade)) / self.fade,
                    ((t1 + self.fade) - t) / self.fade, 1.0)
            if a <= 0.01:
                continue
            if a < 0.999:
                sp = sp.copy()
                sp.putalpha(sp.getchannel("A").point(lambda v: int(v * a)))
            canvas = canvas.copy()
            canvas.paste(sp, (0, y), sp)
        return canvas


def _ts(s: float) -> str:
    h, r = divmod(s, 3600)
    m, r = divmod(r, 60)
    ms = int(round(r % 1 * 1000))
    sec = int(r)
    if ms == 1000:                                # 4.9999 must not become "04,1000"
        sec, ms = sec + 1, 0
    return f"{int(h):02d}:{int(m):02d}:{sec:02d},{ms:03d}"


def write_srt(cues, path: str) -> dict:
    """Standard SubRip. Two text lines per cue when bilingual."""
    cues = Subtitles._validate(cues)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for i, (t0, t1, a, b) in enumerate(cues, 1):
            body = f"{a}\n{b}" if b else a
            f.write(f"{i}\n{_ts(t0)} --> {_ts(t1)}\n{body}\n\n")
    return {"path": path, "cues": len(cues),
            "last_ends": cues[-1][1] if cues else 0.0}
