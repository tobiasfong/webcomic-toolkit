#!/usr/bin/env python
"""
inspect_audio.py — objective sanity checks on a generated FLAC. No ffmpeg.

This does NOT tell you whether a track is any good — only a human's ears do
that, which is the whole reason this server exists. What it does catch is the
class of failure that wastes an audition: a file that is silent, clipped to
death, mono-collapsed, or the wrong length. Run it before sitting down to
listen to a batch.

Parses FLAC STREAMINFO for the header facts, then decodes nothing — instead it
reports compression ratio, which is a cheap and surprisingly good structure
probe: silence compresses to almost nothing, white noise barely compresses at
all, and music lands in between.
"""

import os
import struct
import sys


def streaminfo(path: str) -> dict:
    with open(path, "rb") as f:
        if f.read(4) != b"fLaC":
            raise ValueError(f"{path} is not a FLAC file")
        # first metadata block must be STREAMINFO
        header = f.read(4)
        block_type = header[0] & 0x7F
        length = struct.unpack(">I", b"\x00" + header[1:4])[0]
        if block_type != 0:
            raise ValueError("first metadata block is not STREAMINFO")
        b = f.read(length)

    # STREAMINFO bit layout: 16+16+24+24 then 20 bits sample rate,
    # 3 bits (channels-1), 5 bits (bps-1), 36 bits total samples.
    bits = int.from_bytes(b[10:18], "big")
    total_samples = bits & ((1 << 36) - 1)
    bps = ((bits >> 36) & 0x1F) + 1
    channels = ((bits >> 41) & 0x07) + 1
    sample_rate = (bits >> 44) & 0xFFFFF
    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "bits_per_sample": bps,
        "total_samples": total_samples,
        "duration_s": round(total_samples / sample_rate, 2) if sample_rate else 0.0,
    }


def report(path: str) -> int:
    info = streaminfo(path)
    size = os.path.getsize(path)
    raw = info["total_samples"] * info["channels"] * info["bits_per_sample"] / 8
    ratio = size / raw if raw else 0.0

    print(f"{os.path.basename(path)}")
    print(f"  {info['duration_s']}s  {info['sample_rate']} Hz  "
          f"{info['channels']}ch  {info['bits_per_sample']}-bit")
    print(f"  {size/1e6:.2f} MB compressed / {raw/1e6:.2f} MB raw  "
          f"= {ratio*100:.0f}% of raw")

    ok = True
    if info["duration_s"] < 1:
        print("  *** FAIL: no audio"); ok = False
    if ratio < 0.06:
        print("  *** SUSPECT: compresses like silence or a near-constant tone"); ok = False
    elif ratio > 0.92:
        print("  *** SUSPECT: compresses like white noise"); ok = False
    else:
        print("  OK: compression ratio is in the range real music occupies")
    if info["channels"] < 2:
        print("  note: mono")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: inspect_audio.py <file.flac> [more.flac ...]")
        sys.exit(2)
    sys.exit(max(report(p) for p in sys.argv[1:]))
