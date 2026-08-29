"""Locate the Ren'Py SDK that install_renpy.py put on this machine.

This is the engine-side twin of vnpaths.game_dir(): one place that answers
"where is it?", so no tool has to hardcode an answer.

⚠ THAT IS THE WHOLE POINT. The preview used to name a path on the author's own
machine, which meant it worked for exactly one person and failed on the first
line for anybody who cloned the repository. A recorded path is what makes the
setup portable, so resolve through here rather than writing a path anywhere.

Resolution order:
  1. an explicit path passed by the caller
  2. the RENPY_SDK environment variable
  3. the path recorded by install_renpy.py
  4. give up with instructions -- never guess, and never search the disk

Nothing here downloads anything; install_renpy.py does that.
"""
import json
import os
import subprocess
import sys

CONFIG = os.path.join(
    os.path.expanduser("~"), ".webcomic-toolkit", "renpy.json"
)


def _launcher_name():
    """The executable to run, which is not the same file on every platform."""
    return "renpy.exe" if sys.platform == "win32" else "renpy.sh"


def read_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_config(sdk, version):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump({"sdk": sdk, "version": version}, f, indent=2)
        f.write("\n")
    return CONFIG


def looks_like_sdk(path):
    """A directory is an SDK if it has both the launcher and the project it runs.

    Checking the launcher alone is not enough: an interrupted extraction can
    leave the executable in place with the launcher project still missing, and
    the failure then surfaces much later as an unhelpful Ren'Py traceback.
    """
    return bool(path) and os.path.isfile(os.path.join(path, _launcher_name())) \
        and os.path.isdir(os.path.join(path, "launcher"))


def sdk_dir(explicit=None, required=True):
    """Return the SDK directory, or exit with instructions."""
    for candidate in (explicit, os.environ.get("RENPY_SDK"),
                      read_config().get("sdk")):
        if candidate and looks_like_sdk(os.path.abspath(candidate)):
            return os.path.abspath(candidate)

    if not required:
        return None
    sys.exit(
        "No Ren'Py SDK found.\n"
        "  Install one:  python tools/install_renpy.py\n"
        "  Or point at an existing install:  set RENPY_SDK=<path to the sdk>\n"
        "The SDK is not part of this repository; it is downloaded on demand."
    )


def launcher(sdk=None):
    """Full path to the executable that runs Ren'Py."""
    return os.path.join(sdk or sdk_dir(), _launcher_name())


def has_web_support(sdk=None):
    """Whether the web build component is present.

    It ships as a SEPARATE archive from the SDK, so a perfectly good install
    can still be unable to produce a browser build. Report that as its own
    condition rather than letting the build fail with something obscure.
    """
    return os.path.isfile(os.path.join(sdk or sdk_dir(), "web", "index.html"))


def version(sdk=None):
    """Ask the engine what it is, or None if it will not run."""
    try:
        out = subprocess.run([launcher(sdk), "--version"],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or "").strip()
    return text or (out.stderr or "").strip() or None


if __name__ == "__main__":
    found = sdk_dir(sys.argv[1] if len(sys.argv) > 1 else None)
    print("sdk:     %s" % found)
    print("version: %s" % (version(found) or "would not run"))
    print("web:     %s" % ("yes" if has_web_support(found) else
                           "MISSING -- rerun install_renpy.py"))
