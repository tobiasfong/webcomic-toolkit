"""
test_tools.py — exercise every path that does NOT need the GPU.

Deliberately scoped that way: the ComfyUI paths cost ~65 s a take and need model
files, so they are checked by `check_status` and by actually generating. What
this covers is the half where a silent regression is plausible — frame maths,
timing, masking, encoding.

Run:  .venv\\Scripts\\python.exe test_tools.py [path\\to\\clip.webp] [path\\to\\frame.png]

Both arguments are optional. Without them the frame and slot assertions are
skipped, since they need real artwork — the repo ships no art on purpose.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools import assemble, effects, framing, motion, subs

CUES = [(1.0, 5.0, "これは僕の人生", "This is my life."),
        (6.0, 11.0, "今度こそ", "This time, for sure.")]

_ok = _fail = _skip = 0


def check(label, fn):
    global _ok, _fail
    try:
        fn()
    except Exception as e:
        _fail += 1
        print(f"  FAIL  {label}: {type(e).__name__}: {e}")
    else:
        _ok += 1
        print(f"  PASS  {label}")


def skip(label, why):
    global _skip
    _skip += 1
    print(f"  SKIP  {label} ({why})")


def main() -> int:
    clip = sys.argv[1] if len(sys.argv) > 1 else None
    frame = sys.argv[2] if len(sys.argv) > 2 else None
    tmp = tempfile.mkdtemp(prefix="anime_test_")

    print("subtitles")

    def srt_roundtrip():
        r = subs.write_srt(CUES, os.path.join(tmp, "x.srt"))
        assert r["cues"] == 2, r
        body = open(os.path.join(tmp, "x.srt"), encoding="utf-8").read()
        assert "00:00:01,000 --> 00:00:05,000" in body, body[:200]
    check("srt timestamps", srt_roundtrip)

    def rasterise():
        s = subs.Subtitles(CUES)
        assert len(s.cues) == 2
        assert s.cues[0][2].width == 1920
        # bottom clearance: the block must not run under a player's control bar
        assert s.cues[0][3] + s.cues[0][2].height < 1080, "caption sits too low"
    check("caption rasterise + bottom clearance", rasterise)

    def overlap():
        try:
            subs.Subtitles([(0, 5, "a", ""), (3, 8, "b", "")])
        except ValueError:
            return
        raise AssertionError("overlapping cues were accepted")
    check("overlapping cues rejected", overlap)

    def backwards():
        try:
            subs.Subtitles([(5, 1, "a", "")])
        except ValueError:
            return
        raise AssertionError("a cue ending before it starts was accepted")
    check("backwards cue rejected", backwards)

    print("masking")
    check("region_mask polygon", lambda: effects.region_mask(
        (100, 100), polygons=[[[0, 0], [99, 0], [99, 99]]]).size == (100, 100) or
        (_ for _ in ()).throw(AssertionError("wrong size")))

    def exclusion_punches_a_hole():
        m = effects.region_mask((100, 100), polygons=[[[0, 0], [99, 0], [99, 99], [0, 99]]],
                                exclude=[[[20, 20], [80, 20], [80, 80], [20, 80]]], blur=0)
        assert m.getpixel((50, 50)) == 0, "exclude did not punch through"
        assert m.getpixel((5, 95)) == 255, "exclude removed too much"
    check("exclude punches a hole", exclusion_punches_a_hole)

    print("timing")

    if not clip:
        skip("plan / encode / motion", "no clip argument")
    else:
        def plan_kinds():
            w, _ = assemble.plan([{"clip": clip, "kind": "once", "name": "a"},
                                  {"clip": clip, "kind": "hold", "name": "b"},
                                  {"clip": clip, "kind": "loop", "name": "c"}],
                                 beats=None, hold_seconds=4.0, default_panel=6.0)
            clen = w[0]["clip_seconds"]
            # `once` lasts EXACTLY its clip — no static hold, by design
            assert abs((w[0]["t1"] - w[0]["t0"]) - clen) < 0.05, w[0]
            # `hold` is clip + hold_seconds
            assert abs((w[1]["t1"] - w[1]["t0"]) - (clen + 4.0)) < 0.05, w[1]
            # `loop` fills the panel regardless of clip length
            assert abs((w[2]["t1"] - w[2]["t0"]) - 6.0) < 0.05, w[2]
        check("once/hold/loop durations", plan_kinds)

        def pong_has_no_seam():
            w, _ = assemble.plan([{"clip": clip, "kind": "pong"}], beats=None)
            n = len(w[0]["frames"])
            a = assemble._pick(w[0], w[0]["t0"] + (n - 1) / 12, 12)
            b = assemble._pick(w[0], w[0]["t0"] + n / 12, 12)
            assert a is not b, "ping-pong repeated the turnaround frame"
        check("ping-pong turnaround", pong_has_no_seam)

        check("measure", lambda: motion.measure(clip)["frames"] > 1 or
              (_ for _ in ()).throw(AssertionError("no frames")))
        check("retime", lambda: motion.retime(clip, os.path.join(tmp, "r.webp"),
                                              fps=12)["fps"] == 12 or
              (_ for _ in ()).throw(AssertionError("wrong fps")))
        check("impact", lambda: effects.impact(clip, os.path.join(tmp, "i.webp"),
                                               at=1, decay=4)["frames"] > 0 or
              (_ for _ in ()).throw(AssertionError("no frames")))

        try:
            assemble.find_ffmpeg()
        except FileNotFoundError:
            skip("encode", "no ffmpeg; set WEBCOMIC_ANIME_FFMPEG")
        else:
            def encode():
                r = assemble.assemble([{"clip": clip, "kind": "loop", "name": "s"}],
                                      os.path.join(tmp, "v.mp4"),
                                      cues=[(0.2, 2.5, "test", "caption")],
                                      duration=3.0)
                assert r["frames"] == 72, r
                assert os.path.getsize(r["path"]) > 10_000, "suspiciously small mp4"
            check("encode 3s with burned-in caption", encode)

    print("framing")
    if not frame:
        skip("measure_slot", "no frame argument")
    else:
        def slot_is_not_the_bbox():
            r = framing.measure_slot(frame)
            x0, y0, x1, y1 = r["slot"]
            assert x1 > x0 and y1 > y0, r
            # The failure this guards: taking the ALPHA BOUNDING BOX instead of
            # the full-height columns gives a slot wider than the real one, and
            # leaves a background-coloured line along an edge of every panel.
            from PIL import Image
            bbox = Image.open(frame).convert("RGBA").getchannel("A").point(
                lambda v: 255 if v < 8 else 0).getbbox()
            assert (x1 - x0) <= (bbox[2] - bbox[0]), (
                f"slot {x1-x0}px is wider than the alpha bbox {bbox[2]-bbox[0]}px — "
                f"measurement is wrong")
        check("slot is narrower than the alpha bbox", slot_is_not_the_bbox)

    print(f"\n{_ok} passed, {_fail} failed, {_skip} skipped   (artifacts in {tmp})")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
