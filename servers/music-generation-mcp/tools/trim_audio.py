#!/usr/bin/env python
"""
trim_audio.py — cut a track to an exact duration.

Deliberately NOT an MCP tool: §7a's scope guard keeps this server to generation
and beat analysis, and length-matching for an edit sits at the boundary. It is a
helper the operator runs, not a capability the server advertises.

Why it exists: a video needs an exact length, and the model's own `duration`
input is the thing that re-rolls the whole generation — asking for 31 s instead
of 30 s does not shift a good take by one second, it produces a different take
that may drop lyrics. Generating at a length the model lays out well and then
trimming decouples "what sings correctly" from "what fits the edit".

Safe because these tracks front-load their vocal: the tail is instrumental, so
removing a second costs nothing sung. Applies a short fade so the cut does not
click.

    python tools/trim_audio.py in.flac 31.0 [-o out.flac] [--fade 0.05]
"""

import argparse
import os
import sys

import numpy as np
import soundfile as sf


def trim(src: str, seconds: float, out: str | None = None,
         fade: float = 0.05, start: float = 0.0) -> str:
    """Cut `seconds` of audio beginning at `start`.

    `start` exists because this model handles short generations badly: it needs
    a song-length request to sing a lyric correctly, so the working method is to
    generate long and lift the section you need. A window from the middle needs
    a fade IN as well as out, or the edit clicks at both ends.
    """
    data, sr = sf.read(src, always_2d=True, dtype="float32")
    a = int(round(start * sr))
    b = a + int(round(seconds * sr))
    if a < 0 or b > len(data):
        raise ValueError(
            f"{os.path.basename(src)} is {len(data)/sr:.2f}s — cannot take "
            f"{seconds}s starting at {start}s. This tool cuts; it will not pad."
        )
    cut = data[a:b].copy()

    n = int(fade * sr)
    if n > 0 and 2 * n < len(cut):
        ramp = np.linspace(0.0, 1.0, n, dtype="float32")[:, None]
        if a > 0:                      # only fade in when starting mid-track
            cut[:n] *= ramp
        cut[-n:] *= ramp[::-1]

    if out is None:
        stem, ext = os.path.splitext(src)
        tag = f"_{start:g}-{start + seconds:g}s" if start else f"_{seconds:g}s"
        out = f"{stem}{tag}{ext}"
    sf.write(out, cut, sr)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("seconds", type=float)
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--fade", type=float, default=0.05,
                   help="seconds of fade at the cut edges (0 to disable)")
    p.add_argument("--start", type=float, default=0.0,
                   help="seconds into the source to begin the window")
    a = p.parse_args()
    dest = trim(a.src, a.seconds, a.out, a.fade, a.start)
    info = sf.info(dest)
    print(f"{dest}  {info.duration:.3f}s  {info.samplerate} Hz  {info.channels}ch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
