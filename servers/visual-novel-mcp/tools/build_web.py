"""Build the browser version of a Ren'Py project, and optionally serve it.

    python build_web.py <project-dir> [--serve [PORT]] [--open]

This is the last link in the chain: install_renpy.py puts the engine on the
machine, renpy_sdk.py finds it again, and this uses it. Nothing here contains
a path -- the project comes in as an argument and the SDK is resolved.

⚠ THE LAUNCHER ARGUMENT MUST BE ABSOLUTE, AND THE ERROR DOES NOT SAY SO.
`renpy.exe launcher web_build <project>` resolves `launcher` against the
CURRENT DIRECTORY rather than against the SDK. Run it from anywhere but the
SDK root and it fails with:

    Base directory '...\\launcher' does not exist. Giving up.

which reads as a missing or broken SDK. It is neither; only the argument was
relative. Both paths below are made absolute for exactly this reason, and
this is the single most confusing failure in the whole setup.

⚠ NOT `--launch`. That flag starts a server and then EXITS, killing it, so
the page never loads. Serving is done here instead, by the toolkit's own
threaded server -- `python -m http.server` drops Ren'Py's large concurrent
fetches (renpy.wasm ~21 MB beside renpy.data ~14 MB) because it has no Range
support.

⚠ STOP A RUNNING SERVER BEFORE REBUILDING. It holds the distribution
directory open and the build dies with `PermissionError: [WinError 32]`.
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import renpy_sdk                                            # noqa: E402
import vnpaths                                              # noqa: E402

DEFAULT_PORT = 8140


def project_dir(raw):
    """The directory CONTAINING game/, which is what the launcher wants.

    vnpaths resolves either spelling to the game/ directory, so accepting
    both here costs nothing and removes a class of mistake.
    """
    return os.path.dirname(vnpaths.game_dir([raw]))


def build(sdk, project):
    """Run the launcher's web_build. Returns the process exit code."""
    cmd = [
        os.path.join(sdk, "renpy.exe" if sys.platform == "win32" else "renpy.sh"),
        os.path.join(sdk, "launcher"),      # absolute -- see the module docstring
        "web_build",
        project,
    ]
    print("Building the web version of %s" % os.path.basename(project))
    print("  %s" % " ".join('"%s"' % c if " " in c else c for c in cmd))
    proc = subprocess.run(cmd, cwd=sdk)
    return proc.returncode


def explain(code):
    """Turn the two failures that actually happen into readable advice."""
    print("\nBuild FAILED (exit %d) -- the engine's message above names the "
          "cause." % code)
    print("  'Base directory ... does not exist'")
    print("      a path was relative. This script passes absolute ones, so if")
    print("      you see it, the SDK record points somewhere wrong:")
    print("      rerun  python tools/install_renpy.py --force")
    print("  'WinError 32' / 'being used by another process'")
    print("      a server still holds the distribution directory open.")
    print("      Stop it and build again.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("project", help="the project directory, or its game/ dir")
    ap.add_argument("--sdk", default=None,
                    help="override the recorded SDK path")
    ap.add_argument("--serve", nargs="?", const=DEFAULT_PORT, type=int,
                    default=None, metavar="PORT",
                    help="serve the build after it succeeds (default port %d)"
                         % DEFAULT_PORT)
    ap.add_argument("--open", action="store_true",
                    help="open a browser once the server is listening")
    a = ap.parse_args()

    sdk = renpy_sdk.sdk_dir(a.sdk)
    if not renpy_sdk.has_web_support(sdk):
        sys.exit(
            "This SDK has no web build support.\n"
            "  It ships as a separate archive from the SDK itself, so an\n"
            "  otherwise healthy install can still lack it.\n"
            "  Fix:  python tools/install_renpy.py"
        )

    project = project_dir(a.project)
    code = build(sdk, project)
    if code != 0:
        explain(code)
        return code

    # The launcher writes `<name>-<version>-dists/` beside the project, not
    # inside it, so the server is pointed at the parent.
    root = os.path.dirname(project)
    print("\nBuilt. Distribution is under %s" % root)

    if a.serve is None:
        print("Serve it with:")
        print("  python tools/serve_web.py \"%s\" %d --open" % (root, DEFAULT_PORT))
        return 0

    # ASCII ONLY in anything printed. Under an unattended harness run stdout
    # is redirected, Windows encodes that as cp1252, and a non-ASCII character
    # raises UnicodeEncodeError. That happened here: it fired AFTER a
    # successful build, so the build was finished and then thrown away, and
    # the server never started. The traceback names an encoding, which makes
    # it look like a file problem rather than a print.
    print("\nNOTE: if the page looks stale, hard-refresh. Ren'Py's service "
          "worker answers before the network is consulted, so a rebuild you "
          "cannot see is the most confusing failure this setup produces.")
    cmd = [sys.executable,
           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "serve_web.py"),
           root, str(a.serve)]
    if a.open:
        cmd.append("--open")
    # Handed to a child rather than run here so Ctrl-C stops the server the
    # way it does when serve_web.py is run directly.
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
