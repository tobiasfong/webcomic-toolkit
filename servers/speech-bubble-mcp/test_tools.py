"""
test_tools.py — offline checks for the speech-bubble server.

    .venv/Scripts/python.exe test_tools.py

Everything runs on synthetic art in a temporary folder: nothing touches the
real state or output folders. Video checks need ffmpeg (SPEECH_BUBBLE_FFMPEG,
WEBCOMIC_ANIME_FFMPEG or PATH) and are skipped without it.

The video checks compare the RENDERED frames against the source and against a
still lettered by the other code path. A check that only re-ran the planner
would agree with itself whatever the encode did.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sb_test_")
os.environ["SPEECH_BUBBLE_STATE"] = os.path.join(TMP, "state")
os.environ["SPEECH_BUBBLE_IMAGE_OUT"] = os.path.join(TMP, "img")
os.environ["SPEECH_BUBBLE_VIDEO_OUT"] = os.path.join(TMP, "vid")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import server  # noqa: E402
import video as vd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILS.append(name)


def art(path, size=(1280, 720)):
    im = Image.new("RGB", size, (90, 110, 140))
    d = ImageDraw.Draw(im)
    for x in range(0, size[0], 40):
        d.line([(x, 0), (x + 200, size[1])], fill=(70, 90, 120), width=5)
    d.ellipse([300, 380, 460, 560], fill=(220, 180, 150))
    im.save(path)
    return path


SCRIPT = """INT. HOTEL BALLROOM - NIGHT
He sets the glass down.
CAPTION: Three years later.
LIN: Wait. You think I came
    here for the money?
LIN (thought): She still doesn't recognize me.
MEI (shout): Get out!
MEI (quietly): Is that really him?
[hold on her face]
"""


def test_script():
    r = server.parse_script(SCRIPT)
    bub = [e for e in r["entries"] if e["type"] == "bubble"]
    check("script: five bubbles", r["bubbles"] == 5, r["bubbles"])
    check("script: caption kind", bub[0]["kind"] == "caption")
    check("script: continuation joined", bub[1]["text"] ==
          "Wait. You think I came here for the money?", bub[1]["text"])
    check("script: thought and shout kinds", (bub[2]["kind"], bub[3]["kind"]) == ("thought", "shout"))
    check("script: direction kept, not turned into a kind",
          bub[4]["kind"] == "speech" and bub[4].get("direction") == "quietly")
    check("script: note and heading kept",
          any(e["type"] == "note" for e in r["entries"])
          and r["entries"][0]["type"] == "heading")
    check("script: speakers", r["speakers"] == ["LIN", "MEI"], r["speakers"])


BUBBLES = [
    {"id": "c1", "kind": "caption", "text": {"en": "Three years later.", "zh": "三年后。"},
     "at": "top-left"},
    {"id": "l1", "kind": "speech", "tail": [0.3, 0.55],
     "text": {"en": "Wait. You think I came here for the money?", "zh": "等等。你以为我是为了钱来的？"}},
    {"id": "l2", "kind": "thought", "tail": [0.3, 0.55],
     "text": {"en": "She still doesn't recognize me.", "zh": "她还是没认出我。"}},
]


def test_still():
    img = art(os.path.join(TMP, "page.png"))
    r = server.letter_image("demo", img, BUBBLES, lang="en", name="page")
    check("still: lettered image written", os.path.isfile(r["image"]))
    lay = Image.open(r["layer"])
    a = np.asarray(lay)[..., 3]
    check("still: layer is transparent outside bubbles", lay.mode == "RGBA"
          and (a == 0).mean() > 0.6, f"{(a == 0).mean():.2f} clear")
    check("still: three bubbles described", len(r["bubbles"]) == 3)
    l1 = r["bubbles"][1]
    check("still: auto-placed speech sits above its speaker", l1["at"][1] < 0.55, l1["at"])
    check("still: no warnings on a clean layout", not r["warnings"], r["warnings"])
    import bubbles as bb
    crowd = [{"kind": "caption", "text": "Sample caption box. Narration goes here.", "at": "top-left"},
             {"kind": "speech", "text": "This is a sample speech bubble, pointing at its speaker.",
              "tail": [0.5, 0.2]},
             {"kind": "thought", "text": "A thought bubble slides up after it.", "tail": [0.09, 0.22]},
             {"kind": "shout", "text": "And a shout pops in!", "tail": [0.88, 0.25]}]
    ps = bb.plan(crowd, "en", (1920, 1080), bb.Style(), image=Image.open(img).resize((1920, 1080)))
    crossings = [(p.id, q.id) for p in ps for q in ps if p is not q and p.tail
                 and bb._tail_hits((p.cx, p.cy), p.tail, (q.cx, q.cy, *q.extents()))]
    check("still: auto-placed tails cross no other bubble", not crossings, crossings)
    z = server.letter_image("demo", img, lang="zh", name="page")
    check("still: re-letter saved spec in Chinese", os.path.isfile(z["image"]))
    spec = server.get_lettering("demo", "page")
    check("still: spec keeps both languages", sorted(spec["outputs"]) == ["en", "zh"])
    try:
        server.letter_image("demo", img, lang="ja", name="page")
        check("still: missing language is an error", False)
    except KeyError:
        check("still: missing language is an error", True)


def test_fit():
    h = server.fit_text("demo", "Is that really him?")
    check("fit: short line on two lines", h["lines"] == ["Is that", "really him?"], h["lines"])
    v = server.fit_text("demo", "お前、本当にそれでいいのか？", lang="ja")
    check("fit: Japanese is vertical and tall", v["direction"] == "vertical"
          and v["size_px"][1] > v["size_px"][0], v["size_px"])
    n = server.fit_text("demo", "お前、\n本当にそれで\nいいのか？", lang="ja")
    check("fit: author's line breaks win", n["lines"] == ["お前、", "本当にそれで", "いいのか？"], n["lines"])
    k = server.fit_text("demo", "Okay「fine」、then。", lang="zh")
    check("fit: kinsoku keeps punctuation off line starts",
          all(not ln[:1] in "、。」" for ln in k["lines"]), k["lines"])
    server.set_project_style("demo2", text_size=0.05)
    big = server.fit_text("demo2", "Is that really him?")
    check("fit: project type size applies", big["font_px"] > h["font_px"],
          (big["font_px"], h["font_px"]))


def make_clip(ff, path, seconds=2.0, size=(640, 360), fps=24):
    """A moving test clip, made from Pillow frames because the reduced ffmpeg
    build this toolkit runs on has no test-pattern sources."""
    p = subprocess.Popen([ff, "-y", "-v", "error", "-f", "image2pipe", "-vcodec", "png",
                          "-framerate", str(fps), "-i", "-", "-c:v", "libx264",
                          "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
    for i in range(int(seconds * fps)):
        im = Image.new("RGB", size, (60 + i * 3 % 120, 90, 130))
        ImageDraw.Draw(im).rectangle([i * 8, 200, i * 8 + 80, 300], fill=(240, 200, 40))
        im.save(p.stdin, format="PNG", compress_level=1)
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("could not make the test clip")
    return path


def test_video():
    try:
        ff = vd.find_ffmpeg()
    except FileNotFoundError:
        print("SKIP video: no ffmpeg")
        return
    clip = make_clip(ff, os.path.join(TMP, "shot.mp4"))
    bubbles = [{"id": "l1", "kind": "speech", "text": "Wait. You think I came here for the money?",
                "at": [0.3, 0.3], "tail": [0.35, 0.8]},
               {"id": "l2", "kind": "thought", "text": "She still doesn't recognize me.",
                "at": [0.72, 0.65], "tail": [0.6, 0.9], "in": "slide-up"}]
    r = server.letter_video("demo", clip, bubbles, name="shot",
                            preview_at=[0.0, 3.0])
    t = r["timeline"]
    check("video: second bubble waits for the first to be read",
          t[1]["start"] >= t[0]["start"] + 1.5, t)
    check("video: last frame held to fit reading time", r["held"] > 0, r["held"])
    pre, post = (np.asarray(Image.open(p).convert("RGB"), np.float32) for p in r["previews"])
    x0, y0, x1, y1 = r["bubbles"][0]["box_px"]
    src = Image.open(vd.grab_frame(clip, os.path.join(TMP, "f0.png"), at_end=False))
    base = np.asarray(src.convert("RGB"), np.float32)
    d_pre = np.abs(pre[y0:y1, x0:x1] - base[y0:y1, x0:x1]).mean()
    check("video: nothing drawn before a bubble starts", d_pre < 6, f"{d_pre:.1f}")
    white = (post[y0:y1, x0:x1].min(axis=2) > 235).mean()
    check("video: bubble drawn after it appears", white > 0.3, f"{white:.2f} of its box is white fill")

    enc = server.letter_video("demo", clip, bubbles, name="shot")
    info = vd.probe(enc["path"])
    check("video: encoded length matches the schedule",
          abs(info["duration"] - enc["seconds"]) < 0.15, (info["duration"], enc["seconds"]))

    # Same drawing both ways: letter the held last frame as a still and compare
    # the bubble pixels with the video's last frame.
    last = vd.grab_frame(enc["path"], os.path.join(TMP, "last.png"))
    src_last = vd.grab_frame(clip, os.path.join(TMP, "src_last.png"))
    still = server.letter_image("demo", src_last, bubbles, name="shot_still")
    a = np.asarray(Image.open(last).convert("RGB"), np.float32)
    b = np.asarray(Image.open(still["image"]).convert("RGB"), np.float32)
    x0, y0, x1, y1 = still["bubbles"][0]["box_px"]
    diff = np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean()
    check("video: bubble matches the still lettering", diff < 6, f"{diff:.2f}")

    img = art(os.path.join(TMP, "still_shot.png"), (1536, 864))
    s = server.letter_video("demo", img, bubbles[:1] + [dict(bubbles[1], **{"in": "pop"})],
                            name="still_shot", width=1920, height=1080, duration=2.0,
                            preview_at=[2.5])
    check("video: still source upscaled and previewed",
          Image.open(s["previews"][0]).size == (1920, 1080))
    try:
        server.letter_video("demo", clip, [dict(bubbles[0], **{"in": "spin"})],
                            name="bad", preview_at=[1])
        check("video: unknown animation rejected", False)
    except ValueError:
        check("video: unknown animation rejected", True)


if __name__ == "__main__":
    try:
        test_script()
        test_fit()
        test_still()
        test_video()
        st = server.check_status()
        check("status: fonts for all four languages",
              not any(str(v).startswith("MISSING") for v in st["fonts"].values()), st["fonts"])
    finally:
        keep = "--keep" in sys.argv
        if not keep:
            shutil.rmtree(TMP, ignore_errors=True)
        else:
            print("kept", TMP)
    print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)
