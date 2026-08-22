"""
graph.py — build the branch graph from parsed scripts and run story checks.

The graph is always derived fresh from the .rpy files (rpy_parse.py). Nothing
here is cached to disk; a check is cheap (text parsing) and a stale graph is
worse than a slow one.
"""

import os
import rpy_parse

# labels the engine itself calls — never "unreachable"
ENGINE_ENTRY_LABELS = {
    "start", "quit", "after_load", "splashscreen", "before_main_menu",
    "main_menu", "after_warp", "hide_windows",
}

AUDIO_EXTS = (".ogg", ".opus", ".mp3", ".wav", ".flac")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".avif")


class Analysis:
    def __init__(self, game_dir: str):
        self.game_dir = game_dir
        self.scans = rpy_parse.scan_game(game_dir)
        self.labels: dict[str, dict] = {}      # name -> {file, line}
        self.edges: dict[str, list] = {}       # label -> [{target, kind, file, line}]
        self.flags_set: dict[str, list] = {}
        self.flags_read: dict[str, list] = {}
        self.defines: set[str] = set()
        self.image_names: list[tuple] = []
        self.duplicate_labels: list[dict] = []
        self._build()

    def _rel(self, path: str) -> str:
        return os.path.relpath(path, self.game_dir).replace("\\", "/")

    def _build(self):
        for scan in self.scans:
            rel = self._rel(scan.path)
            for lab in scan.labels:
                if lab["name"] in self.labels:
                    self.duplicate_labels.append(
                        {"label": lab["name"], "file": rel, "line": lab["line"],
                         "first": self.labels[lab["name"]]}
                    )
                else:
                    self.labels[lab["name"]] = {"file": rel, "line": lab["line"]}
            self.defines.update(scan.defines)
            for img in scan.images:
                self.image_names.append(img["name"])

        # auto-defined images: files under images/ define a name from the stem
        images_dir = os.path.join(self.game_dir, "images")
        if os.path.isdir(images_dir):
            for root, _dirs, files in os.walk(images_dir):
                for fname in files:
                    stem, ext = os.path.splitext(fname)
                    if ext.lower() in IMAGE_EXTS:
                        self.image_names.append(tuple(stem.lower().split()))

        for scan in self.scans:
            rel = self._rel(scan.path)
            for j in scan.jumps:
                src = j["from_label"] or "__module__"
                self.edges.setdefault(src, []).append(
                    {"target": j["target"], "kind": j["kind"],
                     "dynamic": j["dynamic"], "file": rel, "line": j["line"]}
                )
            for fs in scan.flags_set:
                self.flags_set.setdefault(fs["name"], []).append(
                    {"file": rel, "line": fs["line"], "label": fs["from_label"], "via": fs["via"]}
                )
            for fr in scan.flags_read:
                self.flags_read.setdefault(fr["name"], []).append(
                    {"file": rel, "line": fr["line"], "label": fr["from_label"]}
                )

        # fallthrough edges: label ends without return/jump and the next label
        # in the same file continues execution
        for scan in self.scans:
            order = [lab["name"] for lab in scan.labels]
            fall = set(scan.fallthrough)
            for i, name in enumerate(order[:-1]):
                if name in fall:
                    self.edges.setdefault(name, []).append(
                        {"target": order[i + 1], "kind": "fallthrough",
                         "dynamic": False, "file": self._rel(scan.path), "line": None}
                    )

    def reachable(self, roots: set[str] | None = None) -> set[str]:
        roots = set(roots or ENGINE_ENTRY_LABELS) & set(self.labels)
        seen = set(roots)
        stack = list(roots)
        while stack:
            node = stack.pop()
            for e in self.edges.get(node, []):
                t = e["target"]
                if t and t in self.labels and t not in seen:
                    seen.add(t)
                    stack.append(t)
        return seen

    def check(self, sprite_tags: set[str] | None = None,
              documented_flags: set[str] | None = None) -> dict:
        report = {}

        dangling = []
        for src, edges in self.edges.items():
            for e in edges:
                if e["target"] and not e["dynamic"] and e["target"] not in self.labels:
                    dangling.append({"from": src, **e})
        report["dangling_targets"] = dangling

        reach = self.reachable()
        unreachable = sorted(
            name for name in self.labels
            if name not in reach and not name.startswith("_")
        )
        report["unreachable_labels"] = [
            {"label": n, **self.labels[n]} for n in unreachable
        ]
        report["duplicate_labels"] = self.duplicate_labels

        read_never_set = []
        for name, reads in sorted(self.flags_read.items()):
            if name in self.flags_set or name in self.defines:
                continue
            read_never_set.append({"flag": name, "first_read": reads[0], "reads": len(reads)})
        report["flags_read_never_set"] = read_never_set

        set_never_read = sorted(
            name for name in self.flags_set
            if name not in self.flags_read
        )
        report["flags_set_never_read"] = set_never_read

        if documented_flags is not None:
            report["flags_undocumented"] = sorted(
                (set(self.flags_set) | set(self.flags_read)) - documented_flags - self.defines
            )

        # every `show`/`scene` should resolve to a defined image (image/
        # layeredimage statement, images/ auto-define, or a registered sprite)
        defined = set(self.image_names)
        tags = {n[0] for n in defined} | (sprite_tags or set())
        unresolved = []
        for scan in self.scans:
            rel = self._rel(scan.path)
            for s in scan.shows:
                words = s["words"]
                if not words:
                    continue
                if words[0] in tags:
                    continue
                if any(set(words) <= set(n) or set(n) <= set(words) for n in defined):
                    continue
                unresolved.append({"file": rel, **s, "words": list(words)})
        report["unresolved_displayables"] = unresolved

        missing_audio = []
        for scan in self.scans:
            rel = self._rel(scan.path)
            for a in scan.audio:
                f = a["file"]
                if f.startswith("<"):  # e.g. "<loop 6.333>track.ogg" audio spec
                    f = f.split(">", 1)[-1]
                if not os.path.isfile(os.path.join(self.game_dir, f)):
                    missing_audio.append({"file_ref": a["file"], "in": rel, "line": a["line"]})
        report["missing_audio_files"] = missing_audio

        report["counts"] = {
            "files": len(self.scans),
            "labels": len(self.labels),
            "edges": sum(len(v) for v in self.edges.values()),
            "menus": sum(len(s.menus) for s in self.scans),
            "choices": sum(len(m["choices"]) for s in self.scans for m in s.menus),
            "flags": len(set(self.flags_set) | set(self.flags_read)),
            "problems": (len(dangling) + len(unreachable) + len(self.duplicate_labels)
                         + len(read_never_set) + len(unresolved) + len(missing_audio)),
        }
        return report

    def trace_paths(self, to_label: str, start: str = "start",
                    max_paths: int = 12, max_depth: int = 120) -> dict:
        """Enumerate simple paths start -> to_label with the flags set along
        each. Bounded — with heavy branching this is a sample, not a census.

        ⚠ Flags are attributed at LABEL granularity, not per branch: the
        scanner is line-based and does not build a block tree, so a flag set
        inside one menu choice is credited to every path through that label.
        Read the result as "flags this route COULD have set", never as a
        definitive state. Duplicates within a label are collapsed."""
        if to_label not in self.labels:
            raise ValueError(f"Unknown label {to_label!r}.")
        if start not in self.labels:
            raise ValueError(f"Start label {start!r} not found.")

        label_sets: dict[str, list] = {}
        for name, sets in self.flags_set.items():
            for s in sets:
                if s["label"] and s["via"] == "$":
                    bucket = label_sets.setdefault(s["label"], [])
                    if name not in bucket:
                        bucket.append(name)

        paths = []
        truncated = False

        def dfs(node, path, flags):
            nonlocal truncated
            if len(paths) >= max_paths or len(path) > max_depth:
                truncated = True
                return
            flags = flags + label_sets.get(node, [])
            path = path + [node]
            if node == to_label:
                paths.append({"labels": path, "flags_set_in_order": flags})
                return
            for e in self.edges.get(node, []):
                t = e["target"]
                if t and t in self.labels and t not in path:
                    dfs(t, path, flags)

        dfs(start, [], [])
        return {"from": start, "to": to_label, "paths": paths,
                "path_count": len(paths), "truncated": truncated,
                "caveat": "flags are label-granular, not per-branch: a flag set "
                          "inside one menu choice is credited to every path "
                          "through that label"}
