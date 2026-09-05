#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_arc.py — assemble a dynamic arc from generated material.

Deliberately NOT an MCP tool, for the same reason as trim_audio.py: §7a's scope
guard keeps that server to generation and beat analysis, and this is editing.
It is a helper the operator runs, not a capability the server advertises.

WHY IT EXISTS. ACE-Step writes texture and groove; across roughly thirty takes
it never produced a long-form build. Asking for one in tags did nothing
(measured), and section markers in the lyrics field made things worse -- they
inserted up to 30% silence, because those markers exist to structure a song
around a VOICE and there is no voice in an instrumental to fill them. The model
was tried fairly and it does not do this, so the arc gets CONSTRUCTED instead.
Same principle as drawing a magic circle rather than prompting for one.

WHAT IT CAN AND CANNOT DO. There is no stem separation here, so instruments
cannot be added or removed. What actually creates the feeling of a build is
available anyway:

  * a LOWPASS that opens over time -- the standard "held back, then released"
  * a GAIN envelope underneath it
  * CONTRAST -- a quiet passage immediately before the loudest, so the climax
    has something to be loud against
  * a DROP -- a short gap before the peak, so the impact lands

Sections are specified in BARS against the source's own grid, so everything
stays rhythmically aligned and the result can still be looped or trimmed.

    python tools/build_arc.py src.flac --bpm 112 --start 76.1 \\
        --section 0:8:lp=400-2500:gain=0.45-0.85 \\
        --section 8:16:full \\
        --section 0:4:lp=700:gain=0.55 \\
        --section 8:16:full:gain=1.0 \\
        -o arc.flac
"""

import argparse
import os
import sys

import numpy as np
import soundfile as sf

FFT = 4096
HOP = 1024


def _stft_filter(x: np.ndarray, sr: int, fc_start: float, fc_end: float,
                 order: int = 4) -> np.ndarray:
    """Lowpass with a cutoff that glides from fc_start to fc_end.

    Overlap-add STFT with a Butterworth-shaped magnitude mask per block. scipy
    is not installed in this venv and is not worth a dependency for one filter,
    so this is numpy only. A brick wall would ring audibly; the Butterworth
    rolloff does not.
    """
    n, ch = x.shape
    win = np.hanning(FFT).astype("float32")
    out = np.zeros((n + FFT, ch), dtype="float32")
    norm = np.zeros(n + FFT, dtype="float32")
    freqs = np.fft.rfftfreq(FFT, 1.0 / sr)
    nblocks = max(1, (n - 1) // HOP + 1)

    for bi, i in enumerate(range(0, n, HOP)):
        blk = np.zeros((FFT, ch), dtype="float32")
        seg = x[i:i + FFT]
        blk[:len(seg)] = seg
        blk *= win[:, None]
        frac = bi / max(1, nblocks - 1)
        fc = fc_start + (fc_end - fc_start) * frac
        mask = 1.0 / np.sqrt(1.0 + (freqs / max(fc, 1.0)) ** (2 * order))
        spec = np.fft.rfft(blk, axis=0) * mask[:, None]
        out[i:i + FFT] += np.fft.irfft(spec, n=FFT, axis=0).astype("float32")
        norm[i:i + FFT] += win
    norm[norm < 1e-6] = 1.0
    return (out[:n] / norm[:n, None]).astype("float32")


def _parse_section(spec: str):
    """'0:8:lp=400-2500:gain=0.45-0.85' -> (0, 8, (400,2500), (0.45,0.85))"""
    parts = spec.split(":")
    if len(parts) < 2:
        raise ValueError("section needs at least start:end in bars, got %r" % spec)
    b0, b1 = int(parts[0]), int(parts[1])
    lp = gain = None
    for p in parts[2:]:
        if p == "full":
            continue
        k, _, v = p.partition("=")
        rng = [float(t) for t in v.split("-")] if v else []
        if k == "lp":
            lp = (rng[0], rng[-1])
        elif k == "gain":
            gain = (rng[0], rng[-1])
    return b0, b1, lp, gain


def build(src, bpm, start, sections, out=None, xfade=0.02, drop_before=None):
    data, sr = sf.read(src, always_2d=True, dtype="float32")
    bar = 4 * 60.0 / bpm
    nx = int(xfade * sr)
    pieces = []

    for idx, spec in enumerate(sections):
        b0, b1, lp, gain = _parse_section(spec)
        i0 = int(round((start + b0 * bar) * sr))
        i1 = int(round((start + b1 * bar) * sr))
        if i0 < 0 or i1 > len(data):
            raise ValueError("section %r runs past the source (%.2fs)"
                             % (spec, len(data) / sr))
        seg = data[i0:i1].copy()
        if lp:
            seg = _stft_filter(seg, sr, lp[0], lp[1])
        if gain:
            g = np.linspace(gain[0], gain[1], len(seg), dtype="float32")[:, None]
            seg *= g
        pieces.append(seg)

    if drop_before is not None and 0 <= drop_before < len(pieces):
        gap = np.zeros((int(0.18 * sr), data.shape[1]), dtype="float32")
        pieces.insert(drop_before, gap)

    # Equal-power crossfades at the joins, so a section change does not click.
    arc = pieces[0]
    for seg in pieces[1:]:
        k = min(nx, len(arc), len(seg))
        if k > 0:
            t = np.linspace(0, np.pi / 2, k, dtype="float32")[:, None]
            head = arc[-k:] * np.cos(t) + seg[:k] * np.sin(t)
            arc = np.concatenate([arc[:-k], head, seg[k:]])
        else:
            arc = np.concatenate([arc, seg])

    peak = float(np.abs(arc).max())
    if peak > 0.999:
        arc /= peak / 0.999
    if out is None:
        out = os.path.splitext(src)[0] + "_arc.flac"
    sf.write(out, arc, sr)
    return out, len(arc) / sr, len(arc) / sr / bar


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("--bpm", type=float, required=True)
    p.add_argument("--start", type=float, default=0.0,
                   help="seconds into the source where bar 0 begins (a downbeat)")
    p.add_argument("--section", action="append", required=True,
                   help="startbar:endbar[:full][:lp=A[-B]][:gain=A[-B]]")
    p.add_argument("--drop-before", type=int, default=None,
                   help="insert a 180ms gap before this section index")
    p.add_argument("-o", "--out", default=None)
    a = p.parse_args()
    out, dur, bars = build(a.src, a.bpm, a.start, a.section, a.out,
                           drop_before=a.drop_before)
    print("%s  %.3fs  %.2f bars" % (out, dur, bars))
    return 0


if __name__ == "__main__":
    sys.exit(main())
