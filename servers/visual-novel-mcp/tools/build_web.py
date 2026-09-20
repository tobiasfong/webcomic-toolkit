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

⚠ THE LAUNCHER RETURNS BEFORE THE BUILD IS DONE. Measured 2026-09-18: it
came back 15 s after starting, the distribution folder was deleted and
recreated 80 s later, and its last file landed 5 s after that. Anything
done to the page in between -- the phone block below -- was done to the
PREVIOUS build's page, which the real build then replaced while the log
said the block had been added; the author saw the page's corner menu still
there. `wait_for_build` waits for the folder itself to settle, so nothing
here touches a page the build has not finished writing. Never run the
injector or the server by hand straight after the launcher.
"""
import argparse
import glob
import io
import os
import subprocess
import sys
import time

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
/* The page's own corner menu duplicates the game: its export and import live on the
   save and load screens, the log is a developer's tool, and the engine credit is on
   the About screen. Only the button is hidden; the file input the game's Load-from-local
   button clicks stays in the page. */
#ContextButton{display:none}
html,body{margin:0;padding:0;overflow:hidden;background:#000}
</style>
<script>
(function(){
  // Hold the frame to the largest 16:9 box that fits, centred.
  //
  // The engine sizes its drawing buffer from the canvas element's own box,
  // and left at 100% x 100% it fills the window's WIDTH, so on any screen
  // wider than 16:9 -- every phone held sideways -- the frame overflows the
  // height and the quick menu falls off the bottom.
  //
  // A PHONE HELD UPRIGHT IS TURNED, NOT ASKED. There used to be a card here
  // saying "turn your phone sideways to play". The author, 2026-09-20:
  // "remove the rotate to landscape instruction when the mobile is
  // portrait. Just go straight to landscape view (even if it's rotated 90
  // degrees). The user will naturally rotate their phone." So in portrait
  // the same 16:9 box is laid out to fit the window's SHORT side and turned
  // a quarter turn. Nothing is asked and nothing is lost -- the game is
  // already playable, sideways, before the phone moves.
  var coarse = window.matchMedia
             ? window.matchMedia("(hover: none) and (pointer: coarse)").matches : false;
  var fit = function(){
    var W = window.innerWidth, H = window.innerHeight;
    var turn = coarse && H > W, w, h;
    if (turn) {
      // Landscape box that fits SIDEWAYS: its height must clear the
      // window's width, its width the window's height.
      w = Math.min(H, Math.round(W * 16 / 9)); h = Math.round(w * 9 / 16);
    } else {
      w = W; h = Math.round(W * 9 / 16);
      if (h > H) { h = H; w = Math.round(H * 16 / 9); }
    }
    var ids = ["canvas", "overlayDiv"];
    for (var i = 0; i < ids.length; i++) {
      var e = document.getElementById(ids[i]);
      if (!e) continue;
      e.style.position = "absolute";
      e.style.width = w + "px"; e.style.height = h + "px";
      e.style.left = Math.round((W - w) / 2) + "px";
      e.style.top = Math.round((H - h) / 2) + "px";
      // Rotating about the centre keeps the turned box centred too: it
      // becomes h wide and w tall, and both were chosen to fit.
      e.style.transformOrigin = "50% 50%";
      e.style.transform = turn ? "rotate(90deg)" : "";
      // A TURNED FRAME DOES NOT TAKE TAPS. Measured 2026-09-20: the engine
      // sizes its drawing buffer from the element's on-screen box, which
      // after a quarter turn is still portrait (749x1333 on a 375x812
      // phone), so it draws the game in PORTRAIT space and the browser
      // rotates the finished pixels. Its input mapping uses that same
      // portrait box, so a tap arrives a quarter turn away from whatever
      // the player is looking at -- they would aim at one button and hit
      // another. Sideways is therefore a PREVIEW: it shows the game is
      // there and which way to turn, and the phone turning is what makes
      // it live. One property, and no wrong tap is possible.
      e.style.pointerEvents = turn ? "none" : "";
    }
  };
  fit();
  window.addEventListener("resize", fit);
  window.addEventListener("orientationchange", function(){ setTimeout(fit, 300); });
  if (window.visualViewport) window.visualViewport.addEventListener("resize", fit);
})();
</script>
""" + ROTATE_END


def wait_for_build(root, started, settle=10, limit=1500):
    """Block until the launcher's build has actually landed on disk.

    The launcher returns long before the build is finished (see the module
    docstring), so the signal is the distribution and not the process: a
    page written after this build started, and nothing under its folder
    touched for `settle` seconds. A launcher that does wait costs `settle`
    seconds here and nothing else. Returns the page.
    """
    pattern = os.path.join(root, "*-dists", "*-web", "index.html")
    deadline = time.time() + limit
    waiting = False
    while time.time() < deadline:
        for page in glob.glob(pattern):
            if os.path.getmtime(page) < started - 1:
                continue                        # the previous build's page
            newest = 0.0
            for dn, _dirs, files in os.walk(os.path.dirname(page)):
                for fn in files:
                    try:
                        newest = max(newest, os.path.getmtime(os.path.join(dn, fn)))
                    except OSError:             # a file mid-write
                        newest = time.time()
            if time.time() - newest >= settle:
                if waiting:
                    print("  the build landed %d s after it started"
                          % int(time.time() - started))
                return page
        if not waiting:
            print("  the launcher has returned; waiting for the build to land ...",
                  flush=True)
            waiting = True
        time.sleep(2)
    sys.exit("The launcher returned, but no new distribution settled under\n"
             "  %s\nwithin %d s. Look for a launcher process still running, or"
             " an error it printed above." % (root, limit))


def add_rotate_card(root):
    """Hold the frame to a centred 16:9 box, and turn it on an upright phone.

    A 16:9 game on a portrait phone renders at about a third of the screen's
    height and the text is unreadable (the author, 2026-09-18: "it looks a
    bit too small"). The manifest the engine writes asks for landscape when
    the game is installed to the home screen, but a page in a browser tab
    cannot force rotation.

    This used to put up a card reading "turn your phone sideways to play".
    The author, 2026-09-20: "remove the rotate to landscape instruction when
    the mobile is portrait. Just go straight to landscape view (even if it's
    rotated 90 degrees). The user will naturally rotate their phone." So the
    same 16:9 box is laid out to fit the window's short side and given a
    quarter turn. The game is playable, sideways, before the phone moves.

    The box also fixes what landscape exposes: the engine's canvas is
    100% x 100% of the window and the frame follows the WIDTH, so on a phone
    held sideways (wider than 16:9) the bottom of the frame, and the quick
    menu with it, falls off the screen. The author saw it: "the menu words
    are cut off." A centred 16:9 box makes fit-to-width the same as
    fit-inside.

    Injected after every build, because the engine regenerates index.html
    each time; an older block is replaced, so the page carries one copy.
    Only after `wait_for_build`: the launcher returns early, and a page
    patched before the build lands is overwritten by it. Re-reads the page
    afterwards and fails if the block is not there. Returns the number of
    pages carrying it.
    """
    done = 0
    for page in glob.glob(os.path.join(root, "*-dists", "*-web", "index.html")):
        html = io.open(page, encoding="utf-8").read()
        if ROTATE_MARK in html:
            a = html.index(ROTATE_MARK)
            b = html.index(ROTATE_END, a) + len(ROTATE_END)
            html = html[:a] + ROTATE_CARD + html[b:]
        else:
            html = html.replace("</body>", ROTATE_CARD + "\n</body>", 1)
        io.open(page, "w", encoding="utf-8", newline="\n").write(html)
        check = io.open(page, encoding="utf-8").read()
        if ROTATE_MARK not in check or ROTATE_END not in check:
            sys.exit("The phone block did not land in %s" % page)
        print("  phone block (portrait turn, 16:9 fit, corner menu hidden) in %s"
              % os.path.relpath(page, root))
        done += 1
    return done


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
    started = time.time()
    code = build(sdk, project)
    if code != 0:
        explain(code)
        return code

    # The launcher writes `<name>-<version>-dists/` beside the project, not
    # inside it, so the server is pointed at the parent.
    root = os.path.dirname(project)
    wait_for_build(root, started)
    print("\nBuilt. Distribution is under %s" % root)
    if not add_rotate_card(root):
        sys.exit("No page found under %s to carry the phone block." % root)

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
