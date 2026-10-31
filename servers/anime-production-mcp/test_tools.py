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

    print("fitting")

    def fit_preserves_aspect():
        from PIL import Image as _I
        # a tall panel on a wide canvas must letterbox, never squash
        tall = _I.new("RGB", (704, 1216), (200, 30, 30))
        out = assemble.fit(tall, (1920, 1080), "contain")
        assert out.size == (1920, 1080)
        # the art occupies a centered column of the ORIGINAL aspect ratio
        w = round(1080 * 704 / 1216)
        px = out.load()
        assert px[1920 // 2, 540] == (200, 30, 30), "art missing from center"
        assert px[(1920 - w) // 2 - 6, 540] != (200, 30, 30), \
            "art bled past its aspect-correct width — it was stretched"
    check("contain letterboxes instead of stretching", fit_preserves_aspect)

    def fit_cover_crops():
        from PIL import Image as _I
        out = assemble.fit(_I.new("RGB", (704, 1216), (0, 90, 200)), (1920, 1080), "cover")
        assert out.size == (1920, 1080)
        assert out.load()[5, 5] == (0, 90, 200), "cover left background showing"
    check("cover fills the canvas", fit_cover_crops)

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
            """The turnaround must step BACK, not replay the end frame.

            Checked on synthetic indices rather than on real frames: a clip whose
            holds are expressed as durations expands to repeated references to
            the SAME image object, so identity comparison would fail on a
            perfectly correct ping-pong.
            """
            n = 6
            sc = {"kind": "pong", "t0": 0.0, "frames": list(range(n))}
            got = [assemble._pick(sc, k / 12, 12) for k in range(2 * n)]
            assert got[:n] == [0, 1, 2, 3, 4, 5], got
            assert got[n] == 4 and got[n + 1] == 3, f"turnaround replayed: {got}"
            assert got[2 * n - 2] == 0, got          # returns to the start
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

    print("cloud (no network)")
    import cloud_video as cv
    from PIL import Image
    first, last = "https://example.com/a.png", "https://example.com/b.png"

    def payload_fields():
        # Each model spells its frame fields its own way; one wrong name and
        # the end pose is silently dropped while the take is still billed.
        want = {"seedance-2.5": ("image_url", "end_image_url"),
                "seedance-2.0": ("image_url", "end_image_url"),
                "kling-3.0-std": ("image_url", "last_image_url"),
                "kling-3.0-pro": ("image_url", "last_image_url"),
                "kling-4.0": ("image_url", "end_image_url")}
        assert set(want) == set(cv.MODELS), "a model was added without a test row"
        for model, (f, l) in want.items():
            b = cv.payload(model, "The camera holds locked off.", first, last, 5, "720p")
            assert b[f] == first and b[l] == last, (model, b)
            # Sound defaults ON on most of these; the soundtrack comes from elsewhere.
            # (Kling 4.0 documents no sound field, so nothing is sent for it.)
            if cv.MODELS[model]["audio"]:
                assert b.get("generate_audio") is False or b.get("sound") == "off", (model, b)
            assert "seed" not in b, "none of these takes a seed"
            # Kling 3.0 has no resolution field; sending one would be rejected.
            assert ("resolution" in b) == (cv.MODELS[model]["resolutions"] is not None), (model, b)
    check("payload: each model's frame fields, sound off, no seed", payload_fields)

    def payload_refs():
        # A model with no reference field must refuse, not silently drop them
        # (Kling 4.0's image_urls are middle keyframes, not references).
        for model in cv.MODELS:
            if "refs" in cv.MODELS[model]:
                continue
            try:
                cv.payload(model, "x", first, None, 5, "720p", [last])
            except ValueError:
                continue
            raise AssertionError(f"{model} accepted reference images")
    check("payload: character refs refused where there is no field", payload_refs)

    def payload_refuses():
        for model, kw in (("seedance-2.0", {"duration": 3}),        # under 4 s
                          ("seedance-2.0", {"duration": 16}),       # over 15 s
                          ("seedance-2.5", {"resolution": "4k"}),   # not offered on 2.5
                          ("kling-3.0-pro", {"prompt": " "}),       # Kling needs a prompt
                          ("veo", {})):                             # not a curated model
            args = {"prompt": "x", "duration": 5, "resolution": "720p", **kw}
            try:
                cv.payload(model, args["prompt"], first, None, args["duration"], args["resolution"])
            except ValueError:
                continue
            raise AssertionError(f"accepted {model} {kw}")
    check("payload refuses out-of-range values and unknown models", payload_refuses)

    def no_key_no_call():
        saved = {k: os.environ.pop(k, None)
                 for k in (cv.KEY_ID_ENV, cv.KEY_SECRET_ENV, cv.KEY_PAIR_ENV)}
        try:
            assert not cv.has_key()
            try:
                cv._headers()
            except cv.CloudError:
                pass
            else:
                raise AssertionError("headers built with no key")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
    check("no key: refuses before any request", no_key_no_call)

    def edit_fields():
        b = cv.edit_payload("kling-4.0-edit", "Keep the motion.", first, [last], "720p", 3.25)
        # Kling 4.0 does not take the length from the clip: whole seconds, rounded up.
        assert b["video_url"] == first and b["image_urls"] == [last], b
        assert b["duration"] == 4 and b["resolution"] == "720p", b
        b = cv.edit_payload("seedance-2.5-edit", "Keep the motion.", first, None, "1080p")
        assert b["video_url"] == first and b["generate_audio"] is False, b
        assert "image_urls" not in b, "an empty list is below the schema's minimum of 1"
        for model, refs in (("kling-4.0-edit", [last] * 11), ("seedance-2.5", [])):
            try:
                cv.edit_payload(model, "x", first, refs)
            except ValueError:
                continue
            raise AssertionError(f"accepted {model} with {len(refs)} refs")
    check("edit payload: each model's source field, ref limits", edit_fields)

    try:
        ff = assemble.find_ffmpeg()
    except FileNotFoundError:
        skip("cloud to_view", "no ffmpeg; set WEBCOMIC_ANIME_FFMPEG")
    else:
        def mp4_to_view():
            import subprocess
            # 2 s at 24 fps, drawn here: this ffmpeg build has no lavfi
            # test sources. Every frame differs, like a real clip.
            src = os.path.join(tmp, "cloudsrc")
            os.makedirs(src, exist_ok=True)
            for i in range(48):
                Image.new("RGB", (640, 360), (i * 5, 90, 160)).save(
                    os.path.join(src, "f%03d.png" % i))
            mp4 = os.path.join(tmp, "cloud.mp4")
            subprocess.run([ff, "-v", "error", "-framerate", "24", "-i",
                            os.path.join(src, "f%03d.png"), "-pix_fmt", "yuv420p",
                            mp4], check=True)
            last_png = os.path.join(tmp, "cloud_last.png")
            r = cv.to_view(mp4, os.path.join(tmp, "cloud_12fps.webp"), ff, fps=12,
                           last_png=last_png)
            # 2 s at 12 fps; and the webp must keep every frame, not merge any.
            assert r["frames"] == 24, r
            assert len(motion.read_frames(r["path"])) == 24, "frames lost in the webp"
            # The last frame is the clip's FINAL one (red 235), not the first.
            red = Image.open(last_png).getpixel((10, 10))[0]
            assert abs(red - 235) < 12, red
        check("cloud mp4 -> 12 fps webp keeps every frame, saves the last", mp4_to_view)

        def edit_round_trip():
            # A 2 s take, 49 frames at 24 fps like LTX's, sent slowed to clear
            # Seedance's 4 s minimum, must come back as 2 s again.
            take = os.path.join(tmp, "take.webp")
            frames = [Image.new("RGB", (640, 360), (i * 5, 90, 160)) for i in range(49)]
            frames[0].save(take, save_all=True, append_images=frames[1:], duration=41, loop=0)
            for fit in ("slow", "pad"):
                src = cv.edit_source(take, os.path.join(tmp, f"sent_{fit}.mp4"),
                                     "seedance-2.5-edit", fit)
                assert src["sent_seconds"] >= 4.0, src
                assert abs(src["source_seconds"] - 2.01) < 0.05, src
                # Pretend the model returned exactly what it was sent.
                r = cv.to_view(src["mp4"], os.path.join(tmp, f"back_{fit}.webp"), ff, fps=12,
                               last_png=os.path.join(tmp, f"back_{fit}.png"),
                               speed=src["speed"], max_seconds=src["source_seconds"])
                assert abs(r["frames"] - 24) <= 1, (fit, r)
                red = Image.open(os.path.join(tmp, f"back_{fit}.png")).getpixel((10, 10))[0]
                assert abs(red - 240) < 12, (fit, red)
        check("edit: a 2 s take sent long comes back 2 s", edit_round_trip)

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
            # leaves a background-colored line along an edge of every panel.
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
