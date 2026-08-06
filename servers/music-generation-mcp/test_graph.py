"""
test_graph.py — offline checks that need no GPU and no ComfyUI.

Validates the two things most likely to be silently wrong in a graph builder:
node wiring, and the duration/seconds coupling that nothing downstream checks.
Run: .venv/Scripts/python.exe test_graph.py
"""

import json
import sys

import ace_workflow as aw
import tracks as tk


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{('  — ' + detail) if detail and not cond else ''}")
    return bool(cond)


def main() -> int:
    ok = True

    # --- 1.5 graph shape ----------------------------------------------------
    g = aw.build_graph(tags="j-pop, female vocal", lyrics="[verse]\nこんにちは",
                       duration=120.0, language="ja", bpm=150, seed=7)
    types = {n: v["class_type"] for n, v in g.items()}
    ok &= check("1.5 uses DualCLIPLoader (not CLIPLoader)",
                "DualCLIPLoader" in types.values(), str(types))
    ok &= check("1.5 DualCLIPLoader type is 'ace'",
                g["2"]["inputs"]["type"] == "ace")
    ok &= check("1.5 loads two DIFFERENT text encoders",
                g["2"]["inputs"]["clip_name1"] != g["2"]["inputs"]["clip_name2"])
    ok &= check("1.5 uses the 1.5 encoder node",
                types["4"] == "TextEncodeAceStepAudio1.5")

    # The coupling this whole module exists to guarantee.
    ok &= check("duration == latent seconds",
                g["4"]["inputs"]["duration"] == g["6"]["inputs"]["seconds"],
                f'{g["4"]["inputs"]["duration"]} vs {g["6"]["inputs"]["seconds"]}')

    ok &= check("negative conditioning does NOT run the audio-code LLM",
                g["5"]["inputs"]["generate_audio_codes"] is False)
    ok &= check("positive DOES run it by default",
                g["4"]["inputs"]["generate_audio_codes"] is True)
    ok &= check("language passed through", g["4"]["inputs"]["language"] == "ja")
    ok &= check("bpm passed through", g["4"]["inputs"]["bpm"] == 150)
    ok &= check("KSampler reads positive/negative from the encoders",
                g["7"]["inputs"]["positive"] == ["4", 0]
                and g["7"]["inputs"]["negative"] == ["5", 0])
    ok &= check("both FLAC and MP3 are saved from one pass",
                {types["9"], types["13"]} == {"SaveAudio", "SaveAudioMP3"})
    ok &= check("both save nodes read the same decode",
                g["9"]["inputs"]["audio"] == g["13"]["inputs"]["audio"] == ["8", 0])

    # --- reference timbre rewires the positive chain ------------------------
    gr = aw.build_graph(tags="x", duration=30.0, reference_audio="ref.mp3")
    ok &= check("reference audio is routed through ReferenceTimbreAudio",
                gr["7"]["inputs"]["positive"] == ["12", 0]
                and gr["12"]["class_type"] == "ReferenceTimbreAudio")
    ok &= check("reference audio disables the audio-code LLM (ComfyUI's advice)",
                gr["4"]["inputs"]["generate_audio_codes"] is False)
    ok &= check("reference is VAE-encoded before conditioning",
                gr["11"]["class_type"] == "VAEEncodeAudio"
                and gr["11"]["inputs"]["audio"] == ["10", 0])

    # --- 1.0 graph ----------------------------------------------------------
    g10 = aw.build_graph(tags="orchestral", duration=60.0, variant="1.0")
    t10 = {n: v["class_type"] for n, v in g10.items()}
    ok &= check("1.0 uses a single checkpoint loader",
                t10["1"] == "CheckpointLoaderSimple")
    ok &= check("1.0 uses the 1.0 encoder node",
                t10["4"] == "TextEncodeAceStepAudio")
    ok &= check("1.0 takes model/clip/vae from the one loader",
                g10["7"]["inputs"]["model"] == ["1", 0]
                and g10["4"]["inputs"]["clip"] == ["1", 1]
                and g10["8"]["inputs"]["vae"] == ["1", 2])
    ok &= check("1.0 latent node is the 1.0 one",
                t10["6"] == "EmptyAceStepLatentAudio")

    # --- validation ---------------------------------------------------------
    for bad, kw in (("duration too long", dict(duration=9999.0)),
                    ("duration too short", dict(duration=1.0)),
                    ("unknown variant", dict(variant="2.0")),
                    ("bad language", dict(language="klingon")),
                    ("bad keyscale", dict(keyscale="H diminished")),
                    ("bad timesignature", dict(timesignature="7")),
                    ("reference audio on 1.0 (rather than ignoring it)",
                     dict(variant="1.0", reference_audio="ref.mp3"))):
        try:
            aw.build_graph(tags="x", **{"duration": 60.0, **kw})
            ok &= check(f"rejects {bad}", False, "no error raised")
        except aw.WorkflowError:
            ok &= check(f"rejects {bad}", True)

    # --- graph is JSON-serialisable (it goes over HTTP) ---------------------
    try:
        json.dumps(g)
        ok &= check("graph serialises to JSON", True)
    except Exception as e:
        ok &= check("graph serialises to JSON", False, str(e))

    # --- track ids -----------------------------------------------------------
    a = tk.new_track_id("rxr", "セカンドチャンス")
    ok &= check("non-ASCII title still yields a usable id", bool(a) and " " not in a, a)
    ok &= check("slugify strips punctuation",
                tk.slugify("Second Chance! (v2)") == "second_chance_v2",
                tk.slugify("Second Chance! (v2)"))

    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
