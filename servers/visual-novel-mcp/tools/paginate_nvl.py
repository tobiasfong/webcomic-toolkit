# -*- coding: utf-8 -*-
"""Place NVL page breaks by measured height -- Fate-style pagination, at emit time.

    python paginate_nvl.py <project-dir>

Runs after the emitters (emit_all.py calls it) and rewrites the generated
scene files: wherever the next entry would not fit under the quick menu, an
`nvl clear  # auto-page` goes in before it. The author's own `nvl clear`s are
untouched and always win; this only turns the pages between them.

IDEMPOTENT. Every automatic break carries the marker, every run strips them
all first and places them afresh, so running twice gives the same file and
a change to the prose moves the breaks with it. Never hand-edit a break in:
it is gone on the next emit, like everything else in a generated scene.

See nvlpage.py for the model and the reasoning. verify_all.py measures the
result with the same model on every run.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nvlpage      # noqa: E402
import renpy_sdk    # noqa: E402
import script_diff  # noqa: E402


def strip_auto(path):
    lines = io.open(path, encoding="utf-8").read().split("\n")
    out, i, n = [], 0, 0
    while i < len(lines):
        if lines[i].strip() == "nvl clear  " + nvlpage.MARK:
            n += 1
            i += 1
            if i < len(lines) and not lines[i].strip():
                i += 1                            # the blank we added after it
            continue
        out.append(lines[i])
        i += 1
    if n:
        io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(out))
    return n


def main(project):
    scenes = os.path.join(project, "game", "scenes")
    files = [f for f in script_diff.scene_order(scenes) if os.path.exists(f)]
    if not files:
        raise SystemExit("paginate_nvl: no scene files under %s" % scenes)
    removed = sum(strip_auto(f) for f in files)

    metrics = nvlpage.Metrics(project, renpy_sdk.sdk_dir())
    insertions, tallest, breaks = nvlpage.walk(files, metrics, insert=True)

    by_file = {}
    for f, line, indent in insertions:
        by_file.setdefault(f, []).append((line, indent))
    for f, spots in by_file.items():
        lines = io.open(f, encoding="utf-8").read().split("\n")
        for line, indent in sorted(spots, reverse=True):
            lines[line:line] = [indent + "nvl clear  " + nvlpage.MARK, ""]
        io.open(f, "w", encoding="utf-8", newline="\n").write("\n".join(lines))

    print("paginate_nvl: %d files in story order; measure %d px, limit %d px"
          % (len(files), metrics.measure, metrics.limit))
    print("  automatic page breaks: %d placed (%d removed first)" % (breaks, removed))
    print("  tallest page after: %d px, %s:%d (%d entries)"
          % (tallest[0], os.path.basename(tallest[1] or "?"), tallest[2] + 1, tallest[3]))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python paginate_nvl.py <project-dir>")
    sys.exit(main(os.path.abspath(sys.argv[1])))
