#!/usr/bin/env python
"""
ace_run.py — standalone ACE-Step driver, no MCP in the way.

The sibling of anime-production-skill/assets/tools/ltx_run.py, and it exists for
the same reason: LTX's real settings (strength 0.8, fps 48, near-native
resolution) were found by sweeping a plain CLI, not through an MCP tool. The
defaults in ace_workflow.VARIANTS are starting points that have NOT been swept
on this hardware — use this to fix that, then write what you learn into
CLAUDE.md the way the LTX findings were.

Examples
--------
Instrumental smoke test (short — prove the plumbing before spending 2 minutes):
    python tools/ace_run.py --tags "lo-fi hip hop, warm rhodes, vinyl crackle" \\
        --duration 20 --prefix smoke

Japanese vocal take:
    python tools/ace_run.py --tags "j-pop, anime opening, female vocal, strings" \\
        --lyrics-file lyrics.txt --language ja --bpm 150 --duration 120

Sweep steps:
    for s in 8 12 20; do python tools/ace_run.py ... --steps $s --prefix st$s; done

Judge by EAR. There is no motion-metric equivalent here, and a track that scores
well on any spectral statistic can still have a vocal you hate — which is the
whole reason this server exists.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ace_workflow as aw          # noqa: E402
import comfy                        # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tags", default="cinematic orchestral, strings, piano, emotional")
    p.add_argument("--lyrics", default="")
    p.add_argument("--lyrics-file", dest="lyrics_file", default=None,
                   help="read lyrics from a UTF-8 text file (avoids shell quoting pain)")
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--variant", default="1.5", choices=sorted(aw.VARIANTS))
    p.add_argument("--bpm", type=int, default=120)
    p.add_argument("--language", default="en", choices=aw.LANGUAGES)
    p.add_argument("--keyscale", default="C major")
    p.add_argument("--timesignature", default="4", choices=aw.TIMESIGNATURES)
    p.add_argument("--no-audio-codes", dest="codes", action="store_false",
                   help="skip the audio-code LLM (faster, lower quality; 1.5 only)")
    p.add_argument("--reference", default=None, help="local audio path for timbre reference")
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--cfg", type=float, default=None)
    p.add_argument("--sampler", default=None)
    p.add_argument("--scheduler", default=None)
    p.add_argument("--prefix", default="ace_test")
    p.add_argument("--out", default=None, help="directory for the returned files")
    a = p.parse_args()

    lyrics = a.lyrics
    if a.lyrics_file:
        with open(a.lyrics_file, encoding="utf-8") as f:
            lyrics = f.read()

    ref = comfy.upload_audio(a.reference) if a.reference else None

    graph = aw.build_graph(
        tags=a.tags, lyrics=lyrics, duration=a.duration, seed=a.seed,
        variant=a.variant, bpm=a.bpm, language=a.language, keyscale=a.keyscale,
        timesignature=a.timesignature, generate_audio_codes=a.codes,
        reference_audio=ref, steps=a.steps, cfg=a.cfg, sampler=a.sampler,
        scheduler=a.scheduler, filename_prefix=f"audio/{a.prefix}",
    )

    out_dir = a.out or os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "output", "_scratch")
    os.makedirs(out_dir, exist_ok=True)

    v = aw.VARIANTS[a.variant]
    print(f"variant {a.variant}  steps {a.steps or v['steps']}  cfg {a.cfg or v['cfg']}  "
          f"{a.duration}s  seed {a.seed}  lang {a.language}  bpm {a.bpm}")
    t0 = time.time()
    outs = comfy.submit_and_wait(graph)
    elapsed = time.time() - t0

    written = []
    for refs in outs.values():
        for r in refs:
            dest = os.path.join(out_dir, f"{a.prefix}_{r['filename']}")
            comfy.fetch(r, dest)
            written.append(dest)
    print(f"done in {elapsed:.0f}s")
    for w in written:
        print(f"  {w}  ({os.path.getsize(w) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
