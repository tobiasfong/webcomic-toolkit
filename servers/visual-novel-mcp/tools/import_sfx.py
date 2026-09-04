"""Import downloaded sound effects into the game, matched to the beats.

    python import_sfx.py <path-to-game-dir> <source-folder>

The source folder for the first batch is vn/<project>/audio_src/, moved there
out of Downloads so the originals survive a cleanup and stay next to the game.
The processed files are lossy relative to them -- trimmed, peak-aligned,
normalized, mono -- so the originals are the only way back to a different trim.

WHY THIS EXISTS RATHER THAN COPYING FILES BY HAND
-------------------------------------------------
Stock audio arrives as whatever the contributor uploaded: different sample
rates, stereo or mono, wildly different loudness, and -- the one that actually
breaks things here -- wildly different ATTACK TIMES. Dropped in raw they sound
like a collage, and half of them miss their own picture.

⚠ THE ATTACK IS THE WHOLE PROBLEM, and it is invisible until you play it.
An impact plate in this game is 50 ms in, 60 ms held, 400 ms out. Measured on
the first batch imported, several stock "spell impact" files take 1.1, 1.8 and
even 3.0 SECONDS to reach their peak -- they are built with a long swell
before the hit, for use in a trailer where the picture waits for them. Played
under a 60 ms flash, the swell is all the player hears while anything is on
screen, and the actual impact lands against an empty street.

So impacts are PEAK-ALIGNED: everything before the peak is cut, leaving a
short pre-roll, and the hit arrives with the flash. Sustained sounds are
exempt, because for those the swell IS the sound -- wind that starts at full
volume is not wind, and a conjuring that begins at its peak is an explosion.

LICENSING
---------
The first batch came from Pixabay: free for commercial use, no attribution.
That is recorded here rather than remembered, because a paid release makes it
matter and the files themselves carry no license metadata. Anything added
from Freesound must be checked per file -- that catalog mixes CC0, CC-BY
(needs credit) and non-commercial (unusable here).
"""
import glob
import os
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vnpaths import game_dir, out_dir  # noqa: E402

# slot -> (filename fragment, treatment)
#
# "impact" is peak-aligned so the hit lands with the plate; "sustain" keeps
# its swell. The fragment is matched against the downloaded filenames, so the
# Pixabay id suffixes do not have to be typed out.
MAPPING = [
    # slot                  fragment                              treatment
    ("sfx_sword_swish",     "sword-slice-393847",                 "impact"),
    ("sfx_sword_ring",      "sword-clashhit",                     "impact"),
    ("sfx_shuriken",        "sword-slice-2-393845",                      "impact"),
    ("sfx_dark_arc",        "violent-sword-slice-393839",          "impact"),
    ("sfx_ice_freeze",      "ice-freezing",                       "sustain"),
    ("sfx_ice_shatter",     "shattering-ice",                     "impact"),
    ("sfx_thunder",         "thunder-clap",                       "impact"),
    ("sfx_breeze",          "soft-wind",                          "sustain"),
    ("sfx_frost_bloom",     "frost-spell-impact",                 "sustain"),
    ("sfx_qi_slash",        "elemental-magic-spell-impact-outgoing", "impact"),
    ("sfx_qi_burst",        "epic-spell-impact",                  "impact"),
    ("sfx_blast_boom",      "fire-spell-impact",                  "impact"),
    ("sfx_ward_hum",        "magic-spell-02",                     "sustain"),
    ("sfx_sword_shimmer",   "soumages-magic-spell",               "sustain"),
    # --- the cave chapter's beasts and ghosts, added 2026-09-05 ---
    # A claw rake gets the SECOND violent slice, so it is audibly its own
    # thing rather than a reuse of sfx_dark_arc, which is the first one.
    ("sfx_claw_rake",       "violent-sword-slice-2-393841",       "impact"),
    # ⚠ CONTRIBUTOR NAME IS "freesound_community", BUT THE FILE CAME FROM
    # PIXABAY, so Pixabay's blanket license applies. Worth stating because the
    # licensing note above singles out Freesound as the catalog that must be
    # checked per file -- a future reader seeing that name on this line would
    # reasonably wonder. If it is ever re-sourced from Freesound directly,
    # check it there.
    ("sfx_bite",            "monster-bite",                       "impact"),
]

# Slots with no good match in the batch keep their synthesized versions.
KEEP_SYNTH = ["sfx_token_ting", "sfx_blizzard_gust"]

PEAK = 0.89
PREROLL = 0.012        # seconds of run-up kept before a peak-aligned hit
FADE = 0.003
MAX_LEN = {"impact": 2.2, "sustain": 4.0}


def mono(d):
    return d.mean(axis=1) if d.ndim > 1 else d


def process(path, treatment):
    d, sr = sf.read(path)
    x = mono(d).astype(np.float64)
    amp = np.abs(x)
    if amp.max() <= 0:
        raise SystemExit("silent file: %s" % path)

    # Trim the leading and trailing silence first, at a low threshold so a
    # quiet run-up is kept rather than clipped into the transient.
    thr = amp.max() * 0.015
    nz = np.nonzero(amp > thr)[0]
    x = x[nz[0]:nz[-1] + 1]

    if treatment == "impact":
        # Cut to just before the peak. This is the step that makes stock
        # trailer-shaped audio usable under a 60 ms flash.
        pk = int(np.argmax(np.abs(x)))
        start = max(0, pk - int(PREROLL * sr))
        x = x[start:]

    cap = int(MAX_LEN[treatment] * sr)
    if len(x) > cap:
        x = x[:cap]
        # A hard cut at the cap would click, so the last 15% is faded.
        tail = int(len(x) * 0.15)
        x[-tail:] *= np.linspace(1, 0, tail)

    x *= PEAK / np.max(np.abs(x))
    f = max(1, int(FADE * sr))
    x[:f] *= np.linspace(0, 1, f)
    x[-f:] *= np.linspace(1, 0, f)
    return x, sr


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: python import_sfx.py <game-dir> <source-folder>")
    out = out_dir(game_dir(), "audio", "sfx")
    src = sys.argv[2]
    files = glob.glob(os.path.join(src, "*.*"))

    for slot, fragment, treatment in MAPPING:
        hits = [f for f in files if fragment in os.path.basename(f)]
        if len(hits) != 1:
            raise SystemExit(
                "%s: expected one file matching %r, found %d.\n%s"
                % (slot, fragment, len(hits),
                   "\n".join("  " + os.path.basename(h) for h in hits)))
        x, sr = process(hits[0], treatment)
        dest = os.path.join(out, slot + ".wav")
        sf.write(dest, x, sr, subtype="PCM_16")
        print("%-20s %-8s %4.2fs  %5.0f KB  <- %s"
              % (slot, treatment, len(x) / float(sr),
                 os.path.getsize(dest) / 1024.0, os.path.basename(hits[0])))

    for slot in KEEP_SYNTH:
        print("%-20s %-8s (kept synthesized -- nothing in the batch matched)"
              % (slot, "synth"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
