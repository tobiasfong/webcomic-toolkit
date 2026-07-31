"""Validate a project's Character Bible before anything is generated from it.

Written after a live failure: a character's primary reference was silently
pointed at a one-off render -- hair styled differently, frame cropped above the
ankles so the footwear did not appear at all -- instead of a crop from the
approved sheet. Nothing detected it. Thirteen panels and two sessions later it
surfaced as "why is this costume detail wrong", and by then the wrong art had
been reasoned from repeatedly.

Every check here corresponds to something that actually went wrong:

  * refs listed in the bible that do not exist on disk
  * image files sitting in a character's folder that the bible does not list
    (seen live -- registry and folder disagreed, so which was canon?)
  * a primary reference with no recorded provenance, or provenance that does
    not trace back to an approved *_FINAL sheet
  * an empty description, which forces whoever is prompting to invent one

Exit code is non-zero if anything fails, so this can gate a run.

    python check_bible.py [--project <project>] [--all]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARS = os.path.join(HERE, "characters")


def _resolve(rel: str) -> str:
    return os.path.join(CHARS, rel.replace("/", os.sep))


def check_project(project: str) -> list[str]:
    """Return a list of problems; empty means the bible is trustworthy."""
    problems: list[str] = []
    manifest = os.path.join(CHARS, project, "characters.json")
    if not os.path.isfile(manifest):
        return [f"{project}: no characters.json"]

    data = json.load(open(manifest, encoding="utf-8"))
    for cid, entry in data.items():
        tag = f"{project}/{cid}"
        refs = entry.get("refs", [])
        sources = entry.get("ref_sources", {})

        if not entry.get("description", "").strip():
            problems.append(f"{tag}: empty description — prompts will be invented")
        if not refs:
            problems.append(f"{tag}: no reference images registered")

        listed = set()
        for rel in refs:
            listed.add(os.path.basename(rel))
            if not os.path.isfile(_resolve(rel)):
                problems.append(f"{tag}: ref listed but missing on disk: {rel}")

        # Orphans: files in the character folder the bible does not know about.
        cdir = os.path.join(CHARS, project, cid)
        if os.path.isdir(cdir):
            for fn in sorted(os.listdir(cdir)):
                if fn.lower().endswith((".png", ".jpg", ".jpeg")) and fn not in listed:
                    problems.append(
                        f"{tag}: {fn} is in the folder but not in refs — "
                        "registry and disk disagree about what is canon")

        # Provenance on the PRIMARY ref is what actually prevents a repeat: it
        # is the reference every generation conditions on.
        if refs:
            primary = os.path.basename(refs[0])
            src = sources.get(primary)
            if not src:
                problems.append(
                    f"{tag}: primary ref {primary} has no ref_sources entry — "
                    "cannot tell which approved art it came from")
            else:
                if not os.path.isfile(os.path.join(HERE, src.replace("/", os.sep))):
                    problems.append(f"{tag}: primary ref provenance missing on disk: {src}")
                if "_concepts" not in src:
                    problems.append(
                        f"{tag}: primary ref does not trace to an approved sheet "
                        f"(got {src}) — approved art lives under _concepts/")

        for panel in entry.get("canon_panels", {}):
            if not os.path.isfile(os.path.join(HERE, panel.replace("/", os.sep))):
                problems.append(f"{tag}: canon panel missing on disk: {panel}")

    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=None)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    projects = ([d for d in sorted(os.listdir(CHARS))
                 if os.path.isdir(os.path.join(CHARS, d))]
                if a.all or not a.project else [a.project])

    failed = False
    for proj in projects:
        problems = check_project(proj)
        if problems:
            failed = True
            print(f"FAIL {proj}")
            for p in problems:
                print(f"  - {p}")
        else:
            print(f"ok   {proj}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
