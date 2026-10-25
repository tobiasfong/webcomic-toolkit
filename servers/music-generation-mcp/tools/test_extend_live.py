"""Live check of extend_track on a real track (needs ComfyUI + the ace_extend add-on).

    python tools/test_extend_live.py <track_id> [keep_seconds] [duration]

Extends the track with its own lyrics (a mechanics test, not a song), then measures what can be measured
without ears: the kept stretch must match the source sample for sample (after the codec), and the new stretch
must be sound, not silence. Prints both numbers and the new track's id; judge the music by listening.
"""
import os
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402
import tracks as tk  # noqa: E402


def mono(path):
    a, sr = sf.read(path, always_2d=True)
    return a.mean(axis=1), sr


if __name__ == "__main__":
    tid = sys.argv[1]
    keep = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 130.0
    src = tk.get(tid)
    rec = server.extend_track(tid, lyrics=src["recipe"].get("lyrics", ""), duration=dur, keep_seconds=keep,
                              title=f"{src['title']} (extend test)")
    a, sra = mono(src["files"]["flac"])
    b, srb = mono(rec["files"]["flac"])
    assert sra == srb, (sra, srb)
    n = int((keep - 1.0) * sra)
    corr = float(np.corrcoef(a[:n], b[:n])[0, 1])
    new = b[int((keep + 1.0) * srb):]
    rms_new = float(np.sqrt(np.mean(new ** 2)))
    rms_old = float(np.sqrt(np.mean(b[:n] ** 2)))
    print(f"new track: {rec['id']}  length {len(b) / srb:.1f}s")
    print(f"kept stretch vs source, correlation: {corr:.4f}  (expect ~1.0)")
    print(f"loudness of the new stretch / the kept one: {rms_new / rms_old:.2f}  (expect well above 0)")
