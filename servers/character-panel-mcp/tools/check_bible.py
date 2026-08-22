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

Provenance that was searched for and genuinely could not be found is recorded as
"irrecoverable: <why>" and reported as a NOTE rather than a failure. That is a
different thing from provenance nobody ever looked for, and the distinction is
worth keeping: a gate that can never go green is a gate people stop running.

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


def check_project(project: str) -> tuple[list[str], list[str]]:
    """Return (problems, notices). No problems means the bible is trustworthy;
    notices are things a human already adjudicated and should still see."""
    problems: list[str] = []
    notices: list[str] = []
    manifest = os.path.join(CHARS, project, "characters.json")
    if not os.path.isfile(manifest):
        return [f"{project}: no characters.json"], notices

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
            elif src.split(":", 1)[0].strip().lower() == "irrecoverable":
                # Somebody went looking and the source render was not on disk.
                # That is not the failure this check exists to catch -- that one
                # is provenance nobody ever checked. Keep it loud on every run,
                # but do not let it hold the gate shut for the whole project.
                why = src.split(":", 1)[1].strip() if ":" in src else ""
                notices.append(
                    f"{tag}: primary ref {primary} provenance marked irrecoverable"
                    + (f" — {why}" if why else ""))
            else:
                # Two accepted shapes: a bare path, or a path followed by a
                # parenthetical explaining how the provenance was established.
                # The narrative form exists because re-verifying a source by
                # CONTENT (dimensions, grading) is worth recording -- silently
                # dropping it to satisfy the checker would lose exactly the
                # evidence that makes the path trustworthy. Resolve the whole
                # string first, so a filename that genuinely contains " (" is
                # not broken by the split.
                path = src
                note = ""
                if not os.path.isfile(os.path.join(HERE, path.replace("/", os.sep))):
                    head, sep, tail = src.partition(" (")
                    if sep:
                        path, note = head.strip(), tail.rstrip().rstrip(")").strip()

                if not os.path.isfile(os.path.join(HERE, path.replace("/", os.sep))):
                    problems.append(f"{tag}: primary ref provenance missing on disk: {path}")
                if "_concepts" not in path:
                    problems.append(
                        f"{tag}: primary ref does not trace to an approved sheet "
                        f"(got {path}) — approved art lives under _concepts/")
                if note:
                    # Loud on every run: the path resolves, but somebody had a
                    # reason to annotate where it came from.
                    notices.append(f"{tag}: primary ref {primary} provenance note — {note}")

        for panel in entry.get("canon_panels", {}):
            if not os.path.isfile(os.path.join(HERE, panel.replace("/", os.sep))):
                problems.append(f"{tag}: canon panel missing on disk: {panel}")

    return problems, notices


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
        problems, notices = check_project(proj)
        if problems:
            failed = True
            print(f"FAIL {proj}")
        else:
            print(f"ok   {proj}")
        for p in problems:
            print(f"  - {p}")
        for n in notices:
            print(f"  NOTE {n}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
