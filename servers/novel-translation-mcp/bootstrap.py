"""
bootstrap.py — one-time-per-project setup utility, NOT an MCP tool.

For a novel that already has a real master docx in more than one language
(e.g. an EN draft plus a JA master with existing translated chapters), this
registers both in one step and optionally seeds the approved glossary from a
JSON file. For a brand-new novel with no prior translation, skip this script
— just call the `register_project` MCP tool.

Usage:
  python bootstrap.py --project-name "My Novel" --project-slug my_novel \
      --en-manuscript "C:\\path\\to\\English.docx" \
      --ja-master "C:\\path\\to\\Japanese master.docx" \
      [--glossary-file glossary.json] [--state-dir DIR]

--glossary-file: a JSON array of {"term": ..., "translation": ..., "note": ...}
objects, imported as ALREADY-APPROVED glossary entries. Use this only for
terms a human has already decided — new proposals should go through the
propose_glossary_term tool's staged/approved flow instead.

Safe to re-run: registration is idempotent, and glossary seeding skips terms
already present (matched by "term") instead of duplicating them.
"""

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manuscript
import state
import projects


def seed_glossary(state_dir: str, glossary_file: str) -> int:
    with open(glossary_file, "r", encoding="utf-8") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        raise SystemExit(f"{glossary_file} must be a JSON array of {{term, translation, note}} objects.")
    data = state.load(state_dir)
    existing_terms = {t["term"] for t in data["glossary"]["approved"]}
    added = 0
    for e in entries:
        if e["term"] in existing_terms:
            continue
        data["glossary"]["approved"].append(
            {"term": e["term"], "translation": e["translation"], "note": e.get("note", "")}
        )
        added += 1
    state.save(state_dir, data)
    return added


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-name", required=True)
    ap.add_argument("--project-slug", default=None, help="defaults to a slug of --project-name")
    ap.add_argument("--en-manuscript", required=True, help="source-language master docx")
    ap.add_argument("--ja-master", default=None, help="target-language master docx, if one already exists")
    ap.add_argument("--source-lang", default="en")
    ap.add_argument("--target-lang", default="ja")
    ap.add_argument("--state-dir", default=None, help="defaults to the source manuscript's folder")
    ap.add_argument("--glossary-file", default=None, help="JSON array of already-approved {term, translation, note}")
    args = ap.parse_args()

    manuscripts = {args.source_lang: args.en_manuscript}
    if args.ja_master:
        manuscripts[args.target_lang] = args.ja_master

    state_dir = args.state_dir or os.path.dirname(args.en_manuscript)

    slug, entry = projects.register(
        name=args.project_name,
        manuscripts=manuscripts,
        source_lang=args.source_lang,
        state_dir=state_dir,
        slug=args.project_slug,
    )
    print(f"Registered project '{slug}':")
    for lang, vol_map in entry["manuscripts"].items():
        for vol, path in sorted(vol_map.items()):
            chapters = manuscript.parse_chapters(path, lang)
            print(f"  {lang} v{vol}: {len(chapters)} chapters -> {path}")

    if args.glossary_file:
        added = seed_glossary(state_dir, args.glossary_file)
        print(f"\nSeeded {added} new approved glossary term(s) from {args.glossary_file} (already-present terms skipped).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
