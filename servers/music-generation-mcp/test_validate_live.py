"""
test_validate_live.py — push the graph at a running ComfyUI and read its
validation verdict, WITHOUT trusting a successful run to prove correctness.

Why this exists: ComfyUI validates every node's inputs against its real schema
before executing, so a POST /prompt catches wrong enum values, bad node ids and
broken links that a hand-written unit test cannot. This is the technique that
caught character-panel-mcp's invalid IP-Adapter `weight_type` during its Tier-2
build (see that server's CHANGELOG).

Duration is pinned to the 10 s minimum so that if validation DOES pass and the
graph executes, it costs seconds rather than minutes.

Missing-model errors are reported separately from wiring errors: before the
model files finish downloading, "value not in list" on clip_name/unet_name is
EXPECTED and tells us nothing is wrong with the graph — while any other error
class is a real bug.
"""

import json
import sys

import requests

import ace_workflow as aw
import comfy

MISSING_MODEL_TYPES = {"value_not_in_list"}
MODEL_FIELDS = {"unet_name", "clip_name1", "clip_name2", "vae_name", "ckpt_name"}


def probe(label: str, **kwargs) -> bool:
    graph = aw.build_graph(duration=10.0, filename_prefix="audio/_validate", **kwargs)
    r = requests.post(f"{comfy.COMFY_URL}/prompt", json={"prompt": graph}, timeout=60)
    if r.status_code == 200:
        print(f"  {label}: VALIDATED CLEAN (queued {r.json().get('prompt_id')})")
        return True

    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    node_errors = body.get("node_errors") or {}
    top = body.get("error") or {}

    missing, real = [], []
    for nid, err in node_errors.items():
        for e in err.get("errors", []):
            field = (e.get("extra_info") or {}).get("input_name")
            where = f'node {nid} ({graph[nid]["class_type"]}).{field}'
            if e.get("type") in MISSING_MODEL_TYPES and field in MODEL_FIELDS:
                missing.append(f"{where}: {e.get('message')}")
            else:
                real.append(f"{where}: {e.get('type')} — {e.get('message')} {e.get('details','')}")
    if not node_errors and top:
        real.append(f"top-level: {top.get('type')} — {top.get('message')} {top.get('details','')}")

    for m in missing:
        print(f"  {label}: [model not downloaded yet] {m}")
    for m in real:
        print(f"  {label}: *** WIRING ERROR *** {m}")
    if not real:
        print(f"  {label}: no wiring errors — only missing model files")
    return not real


def main() -> int:
    if not comfy.comfy_is_up():
        print("ComfyUI is not running; nothing to validate against.")
        return 2

    print("Validating graphs against live ComfyUI schema:")
    ok = True
    ok &= probe("1.5 instrumental", tags="cinematic orchestral, strings")
    # Placeholder lyric, deliberately not from a real song — this repo is public
    # and test fixtures are a silly place to publish someone's unreleased words.
    ok &= probe("1.5 japanese vocal", tags="j-pop, anime opening, female vocal",
                lyrics="[verse]\n春の風が吹く\n遠い空を見上げて", language="ja", bpm=150)
    ok &= probe("1.0 fallback", tags="cinematic orchestral", variant="1.0")

    print("\nNo wiring errors found." if ok else "\nWIRING ERRORS ABOVE — fix before generating.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
