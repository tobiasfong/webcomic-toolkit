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
import glob
import io
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


ROTATE_MARK = "<!-- rotate-card -->"
ROTATE_END = "<!-- /rotate-card -->"
ROTATE_CARD = ROTATE_MARK + """
<style>
#rotateCard{display:none;position:fixed;inset:0;z-index:99999;background:#000;color:#eee;
  font:20px/1.4 sans-serif;text-align:center;align-items:center;justify-content:center;
  flex-direction:column;padding:24px}
#rotateCard .phone{width:34px;height:60px;border:3px solid #eee;border-radius:7px;
  margin:0 auto 18px;animation:rotateHint 2.4s ease-in-out infinite}
@keyframes rotateHint{0%,35%{transform:rotate(0)}65%,100%{transform:rotate(-90deg)}}
@media (orientation: portrait) and (hover: none) and (pointer: coarse){#rotateCard{display:flex}}
/* The page's own corner menu duplicates the game: its export and import live on the
   save and load screens, the log is a developer's tool, and the engine credit is on
   the About screen. Only the button is hidden; the file input the game's Load-from-local
   button clicks stays in the page. */
#ContextButton{display:none}
</style>
<div id="rotateCard"><div class="phone"></div><div>Turn your phone sideways to play.</div></div>
<script>
(function(){
  // Hold the canvas to the largest 16:9 box centered in the window. The
  // engine sizes its drawing buffer from the canvas element's own box, and
  // left at 100% x 100% it fills the window's width, so on any screen wider
  // than 16:9 -- every phone held sideways -- the frame overflows the height
  // and the quick menu falls off the bottom.
  var fit = function(){
    var W = window.innerWidth, H = window.innerHeight;
    var w = W, h = Math.round(W * 9 / 16);
    if (h > H) { h = H; w = Math.round(H * 16 / 9); }
    var ids = ["canvas", "overlayDiv"];
    for (var i = 0; i < ids.length; i++) {
      var e = document.getElementById(ids[i]);
      if (!e) continue;
      e.style.width = w + "px"; e.style.height = h + "px";
      e.style.left = Math.round((W - w) / 2) + "px"; e.style.top = Math.round((H - h) / 2) + "px";
    }
  };
  fit();
  window.addEventListener("resize", fit);
  window.addEventListener("orientationchange", function(){ setTimeout(fit, 300); });
  if (window.visualViewport) window.visualViewport.addEventListener("resize", fit);
})();
</script>
""" + ROTATE_END


def add_rotate_card(root):
    """Ask a phone held upright to turn sideways, and keep the frame inside
    the window once it has.

    A 16:9 game on a portrait phone renders at about a third of the screen's
    height and the text is unreadable (the author, 2026-09-18: "it looks a
    bit too small"). The manifest the engine writes already asks for
    landscape when the game is installed to the home screen, but a page in
    a browser tab cannot force rotation, so it asks instead -- the way phone
    VNs have always done it. The card shows only on a touch device held in
    portrait, so a desktop browser never sees it.

    The script beside it fixes what rotation then exposes: the engine's
    canvas is 100% x 100% of the window and the frame follows the WIDTH, so
    on a phone held sideways (wider than 16:9) the bottom of the frame, and
    the quick menu with it, falls off the screen. The author saw it: "the
    menu words are cut off." Holding the canvas to a centered 16:9 box makes
    fit-to-width the same as fit-inside.

    Injected after every build, because the engine regenerates index.html
    each time; an older block is replaced, so the page carries one copy.
    """
    for page in glob.glob(os.path.join(root, "*-dists", "*-web", "index.html")):
        html = io.open(page, encoding="utf-8").read()
        if ROTATE_MARK in html:
            a = html.index(ROTATE_MARK)
            b = html.index(ROTATE_END, a) + len(ROTATE_END) if ROTATE_END in html[a:] else html.index("</div>", html.index('id="rotateCard"', a)) + len("</div>")
            html = html[:a] + ROTATE_CARD + html[b:]
        else:
            html = html.replace("</body>", ROTATE_CARD + "\n</body>", 1)
        io.open(page, "w", encoding="utf-8", newline="\n").write(html)
        print("  rotate card and 16:9 fit added to %s" % os.path.relpath(page, root))


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
    add_rotate_card(root)

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
