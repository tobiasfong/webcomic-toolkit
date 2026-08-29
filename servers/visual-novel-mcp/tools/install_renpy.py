"""Download and install the Ren'Py SDK, so the harness does the setup.

    python install_renpy.py [--dest DIR] [--force] [--version X.Y.Z]

WHY THIS EXISTS
---------------
Every other server in this toolkit lets the AI harness install what it needs.
This one used to tell the reader to go and fetch Ren'Py themselves, which broke
the promise the rest of the ecosystem makes -- and hid a real bug, because the
browser preview named an SDK path on the author's own machine. One person could
run it. This installs the engine and records where it went, so tools resolve
the path through renpy_sdk.py instead of containing one.

TWO ARCHIVES, NOT ONE
---------------------
The web build support is a SEPARATE download from the SDK (~13 MB against
~163 MB), and a normal-looking install without it simply cannot produce a
browser build. Both are fetched here.

THE VERSION IS PINNED ON PURPOSE
--------------------------------
WORKFLOW.md documents engine behavior measured against this exact release --
traps that `renpy lint` does not catch. Installing whatever is newest would
move that ground silently. `--version` overrides it for anyone who needs to,
and says what it is giving up.

INTEGRITY
---------
The SHA-256 of each pinned archive is recorded below and checked after
download. That catches a truncated or corrupted transfer, which is the
realistic failure for a 163 MB file over a home connection. It is NOT a
signature check: the hashes came from the same site as the archives, so it
proves the bytes arrived intact, not that the site was honest. Upstream signs
its checksums with PGP; verifying that would need a key and a trust decision
this script has no business making on someone's behalf.
"""
import argparse
import hashlib
import os
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import renpy_sdk                                            # noqa: E402

VERSION = "8.5.3"
BASE = "https://www.renpy.org/dl/%s/%s"

# sha256, for the pinned version only. A --version override falls back to the
# published checksums file, and says so.
HASHES = {
    "renpy-8.5.3-sdk.zip":
        "ff57648f9c04f27e381c48af6d8e3ee3cdec296bed4d3831f47f09b0a71b505e",
    "renpy-8.5.3-sdk.tar.bz2":
        "eb0a9be7f0fb13632fe25ceade9a8bed5a1b4d6b6e83bd19eeeb29e1a1bb4a45",
    "renpy-8.5.3-web.zip":
        "954db897e65f51ea63cb2fb7b203d02be0447f4e22069514020bbe6c6691fdfc",
}

DEFAULT_DEST = os.path.join(os.path.expanduser("~"), ".webcomic-toolkit",
                            "engines")


def sdk_archive(version):
    """Windows ships a zip; the other two ship a bzip2 tarball."""
    return ("renpy-%s-sdk.zip" if sys.platform == "win32"
            else "renpy-%s-sdk.tar.bz2") % version


def published_hashes(version):
    """Parse upstream's checksums file -- only needed for a --version override.

    The file is one section per algorithm, each headed by a `# name` line, so
    read until the sha256 heading and take the lines after it.
    """
    url = BASE % (version, "checksums.txt")
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
    except OSError as e:
        sys.exit("Could not fetch %s: %s" % (url, e))
    out, section = {}, None
    for line in text.splitlines():
        if line.startswith("# "):
            section = line[2:].strip()
        elif section == "sha256" and " " in line.strip():
            digest, _, name = line.strip().partition(" ")
            out[name.strip()] = digest
    return out


def download(url, dest, expect):
    """Fetch to a .part file, verify, then rename.

    Downloading straight onto the final name means an interrupted transfer
    leaves a file that looks installed, and the next run skips it.
    """
    part = dest + ".part"
    total = 0
    sha = hashlib.sha256()
    # A carriage return redraws one line on a terminal and appends 150+ times
    # to a log file. An unattended harness run is the normal case here, so
    # report milestones when nobody is watching a tty.
    live = sys.stdout.isatty()
    milestone = 0
    with urllib.request.urlopen(url, timeout=120) as r:
        size = int(r.headers.get("Content-Length") or 0)
        with open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
                total += len(chunk)
                if not size:
                    continue
                pct = 100.0 * total / size
                if live:
                    sys.stdout.write("\r    %5.1f%%  %d/%d MB"
                                     % (pct, total >> 20, size >> 20))
                    sys.stdout.flush()
                elif pct >= milestone + 25:
                    milestone = 25 * int(pct // 25)
                    print("    %d%%  %d/%d MB" % (milestone, total >> 20,
                                                  size >> 20), flush=True)
    if live:
        print("")
    got = sha.hexdigest()
    if expect and got != expect:
        os.remove(part)
        sys.exit("  Checksum mismatch for %s\n    expected %s\n    got      %s\n"
                 "  The download was corrupted or the file has changed."
                 % (os.path.basename(dest), expect, got))
    os.replace(part, dest)
    return dest


def _safe_members(names, root):
    """Refuse absolute paths and anything climbing out of the target."""
    root = os.path.abspath(root)
    for n in names:
        p = os.path.normpath(os.path.join(root, n))
        if p != root and not p.startswith(root + os.sep):
            sys.exit("Refusing to extract outside the target: %s" % n)


def extract(archive, into):
    """Unpack, and return the single top-level directory it created."""
    os.makedirs(into, exist_ok=True)
    before = set(os.listdir(into))
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            _safe_members(z.namelist(), into)
            z.extractall(into)
    else:
        with tarfile.open(archive, "r:bz2") as t:
            _safe_members(t.getnames(), into)
            # filter="data" is the supported way to block device nodes and
            # traversal on 3.12+; older interpreters fall back to the manual
            # check above.
            try:
                t.extractall(into, filter="data")
            except TypeError:
                t.extractall(into)
    made = sorted(set(os.listdir(into)) - before)
    return os.path.join(into, made[0]) if len(made) == 1 else into


def mark_executable(sdk):
    """Restore the +x bits a zip cannot carry (no-op on Windows)."""
    if sys.platform == "win32":
        return
    for name in ("renpy.sh",
                 os.path.join("lib", "py3-linux-x86_64", "renpy"),
                 os.path.join("lib", "py3-mac-universal", "renpy")):
        p = os.path.join(sdk, name)
        if os.path.exists(p):
            os.chmod(p, os.stat(p).st_mode | 0o111)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dest", default=DEFAULT_DEST,
                    help="where to put the SDK (default: %s)" % DEFAULT_DEST)
    ap.add_argument("--version", default=VERSION,
                    help="override the pinned version (see the docstring)")
    ap.add_argument("--force", action="store_true",
                    help="reinstall even if one is already recorded")
    a = ap.parse_args()

    if a.version != VERSION:
        print("WARNING: installing %s instead of the pinned %s. The engine "
              "notes in WORKFLOW.md were measured against %s."
              % (a.version, VERSION, VERSION))
        hashes = published_hashes(a.version)
    else:
        hashes = HASHES

    existing = renpy_sdk.sdk_dir(required=False)
    if existing and not a.force:
        print("Already installed: %s" % existing)
        if renpy_sdk.has_web_support(existing):
            print("Web build support present. Nothing to do (--force to redo).")
            return 0
        print("Web build support MISSING -- fetching just that.")

    dest = os.path.abspath(a.dest)
    os.makedirs(dest, exist_ok=True)
    sdk = existing if (existing and not a.force) else None

    with tempfile.TemporaryDirectory(prefix="renpy-dl-") as tmp:
        if sdk is None:
            name = sdk_archive(a.version)
            print("Downloading %s" % name)
            arc = download(BASE % (a.version, name), os.path.join(tmp, name),
                           hashes.get(name))
            print("  extracting to %s" % dest)
            sdk = extract(arc, dest)
            mark_executable(sdk)

        name = "renpy-%s-web.zip" % a.version
        print("Downloading %s (browser build support)" % name)
        arc = download(BASE % (a.version, name), os.path.join(tmp, name),
                       hashes.get(name))
        # This archive's single top-level entry IS `web/`, so it unpacks
        # straight into the SDK root where the launcher looks for it.
        with zipfile.ZipFile(arc) as z:
            _safe_members(z.namelist(), sdk)
            z.extractall(sdk)

    if not renpy_sdk.looks_like_sdk(sdk):
        sys.exit("Extraction finished but %s does not look like an SDK." % sdk)
    if not renpy_sdk.has_web_support(sdk):
        sys.exit("Installed, but the web component is not where it belongs.")

    reported = renpy_sdk.version(sdk)
    if not reported:
        print("WARNING: installed, but the engine would not report a version. "
              "The files are in place; running it may need a display or extra "
              "system libraries.")
    else:
        print("Engine reports: %s" % reported)

    path = renpy_sdk.write_config(sdk, a.version)
    print("\nInstalled: %s" % sdk)
    print("Recorded in %s -- tools resolve it through renpy_sdk.py." % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
