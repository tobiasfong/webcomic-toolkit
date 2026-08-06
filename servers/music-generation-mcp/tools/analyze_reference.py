#!/usr/bin/env python
"""
analyze_reference.py — measure a reference track's tempo and key.

Why this exists: the model's `bpm` and `keyscale` inputs were being set from
guesswork. The first RxR takes were generated in D major because "uplifting
anime OP" sounded right before anyone understood the song — and it took two
rounds of listening to discover the song wanted a minor key. Measuring a
reference the author already likes replaces that guess with a number.

This does NOT judge music, and it is not a substitute for listening. It reports
three things a human would otherwise have to supply by ear:

    bpm        — for the `bpm` input, and for beat-synced cuts downstream
    keyscale   — for the `keyscale` input, in the exact form ACE-Step expects
    duration   — for sanity against the lyric-density arithmetic

Reads MP3/FLAC/WAV/OGG directly through libsndfile — no ffmpeg, which this
machine does not have.

Method, and its limits:
  * Tempo: spectral-flux onset envelope, then autocorrelation over a 60-180 BPM
    search range. Octave errors (half/double time) are the classic failure —
    both candidates are reported so a human can pick.
  * Key: chroma folded from an FFT magnitude spectrum, correlated against the
    Krumhansl-Schmuckler major and minor profiles. Reports the best match plus
    the runner-up, because relative major/minor pairs (D major vs B minor —
    exactly the pair in play here) share a key signature and are genuinely
    ambiguous to this method. If the top two are a relative pair, that is
    information, not a bug.

Usage:
    python tools/analyze_reference.py reference.mp3
"""

import sys

import numpy as np
import soundfile as sf

SR = 22050
HOP = 512
WIN = 2048

# Krumhansl-Schmuckler key profiles.
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
# Spelling matches ace_workflow.KEYSCALES so output can be pasted straight in.
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def load_mono(path: str) -> tuple[np.ndarray, float]:
    data, sr = sf.read(path, always_2d=True, dtype="float32")
    mono = data.mean(axis=1)
    if sr != SR:  # cheap linear resample; adequate for tempo/chroma
        n = int(len(mono) * SR / sr)
        mono = np.interp(np.linspace(0, len(mono) - 1, n),
                         np.arange(len(mono)), mono).astype(np.float32)
    return mono, len(data) / sr


def spectrogram(x: np.ndarray) -> np.ndarray:
    n = 1 + (len(x) - WIN) // HOP
    if n < 2:
        raise ValueError("clip too short to analyse")
    window = np.hanning(WIN).astype(np.float32)
    frames = np.lib.stride_tricks.as_strided(
        x, shape=(n, WIN), strides=(x.strides[0] * HOP, x.strides[0])) * window
    return np.abs(np.fft.rfft(frames, axis=1))


def tempo(mag: np.ndarray) -> tuple[float, float]:
    flux = np.diff(mag, axis=0)
    onset = np.maximum(flux, 0).sum(axis=1)
    onset -= onset.mean()
    if not np.any(onset):
        return 0.0, 0.0
    ac = np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    fps = SR / HOP
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)      # 180 down to 60 BPM
    hi = min(hi, len(ac) - 1)
    if hi <= lo:
        return 0.0, 0.0
    band = ac[lo:hi]
    best = lo + int(np.argmax(band))
    bpm = 60.0 * fps / best
    # Report the octave alternative too — half/double time is the classic error.
    alt = bpm * 2 if bpm < 100 else bpm / 2
    return bpm, alt


def key(mag: np.ndarray) -> list[tuple[str, float]]:
    freqs = np.fft.rfftfreq(WIN, 1.0 / SR)
    chroma = np.zeros(12)
    usable = (freqs > 55) & (freqs < 2000)          # A1..~B6
    pitches = 12 * np.log2(freqs[usable] / 440.0) + 69
    bins = np.rint(pitches).astype(int) % 12
    energy = mag[:, usable].sum(axis=0)
    for b in range(12):
        chroma[b] = energy[bins == b].sum()
    if chroma.sum() == 0:
        return []
    chroma /= chroma.sum()

    scored = []
    for i in range(12):
        for name, profile in (("major", MAJOR), ("minor", MINOR)):
            rotated = np.roll(profile, i)
            r = np.corrcoef(chroma, rotated / rotated.sum())[0, 1]
            scored.append((f"{NOTES[i]} {name}", float(r)))
    return sorted(scored, key=lambda t: -t[1])


def relative_pair(a: str, b: str) -> bool:
    """True if a and b are a relative major/minor pair (same key signature)."""
    try:
        (ra, qa), (rb, qb) = a.split(), b.split()
    except ValueError:
        return False
    if qa == qb:
        return False
    maj, minr = (ra, rb) if qa == "major" else (rb, ra)
    return (NOTES.index(minr) - NOTES.index(maj)) % 12 == 9


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: analyze_reference.py <audio file>")
        return 2
    path = sys.argv[1]
    x, dur = load_mono(path)
    mag = spectrogram(x)

    bpm, alt = tempo(mag)
    ranked = key(mag)

    print(f"{path}")
    print(f"  duration   {dur:.1f} s")
    print(f"  bpm        {bpm:.1f}   (octave alternative: {alt:.1f} — pick by ear)")
    if ranked:
        top, second = ranked[0], ranked[1]
        print(f"  keyscale   '{top[0]}'   (r={top[1]:.3f})")
        print(f"  runner-up  '{second[0]}'   (r={second[1]:.3f})")
        if relative_pair(top[0], second[0]):
            print("  NOTE: those two are a relative major/minor pair — same key "
                  "signature, so this method cannot separate them. Choose by "
                  "whether the track feels bright or heavy.")
        bar = 4 * 60 / bpm if bpm else 0
        if bar:
            print(f"\n  at {bpm:.0f} BPM in 4/4, one bar = {bar:.2f} s")
            print(f"  a {dur:.0f} s track is {dur/bar:.0f} bars; "
                  f"at ~2.3 bars/sung line that supports "
                  f"~{int(dur/bar/2.3)} sung lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
