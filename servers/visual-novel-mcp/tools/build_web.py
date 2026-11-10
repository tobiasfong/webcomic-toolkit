"""Build the browser version of a Ren'Py project, and optionally serve it.

    python build_web.py <project-dir> [--serve [PORT]] [--open] [--sdk DIR]

    --serve [PORT]   after a successful build, start serve_web.py DETACHED on
                     PORT (default 8140) and return. The port is probed BEFORE
                     the build: if something that is not our own server holds
                     it, the build is not started. A server of ours already
                     running on it keeps serving (publishing is by rename, so
                     it sees the new build without a restart).
    --open           open a browser once the server answers

    python build_web.py "C:/path/to/vn/<project>" --serve 8140

A build is published only when it is COMPLETE: index.html, renpy.js,
renpy-pre.js, at least one .wasm, and a game.zip or game.data, each above a
floor size. Otherwise the live build is left untouched, what is missing is
printed, and the exit code is 1. If nothing at all appears under the
distribution folder a few minutes after the launcher exits, it fails then
rather than waiting out the full limit.

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
import shutil
import io
import os
import re
import subprocess
import sys
import tempfile
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
    """Run the launcher's web_build. Returns (exit code, the process)."""
    cmd = [
        os.path.join(sdk, "renpy.exe" if sys.platform == "win32" else "renpy.sh"),
        os.path.join(sdk, "launcher"),      # absolute -- see the module docstring
        "web_build",
        project,
    ]
    print("Building the web version of %s" % os.path.basename(project))
    print("  %s" % " ".join('"%s"' % c if " " in c else c for c in cmd))
    proc = subprocess.Popen(cmd, cwd=sdk)
    proc.wait()
    return proc.returncode, proc


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
  // ⚠ "(hover: none) and (pointer: coarse)" IS NOT A PHONE TEST. It is the
  // right question everywhere else in this project, but Chrome's "Desktop
  // site" switch makes a phone answer it FALSE: measured on the author's
  // Galaxy, hover/pointer came back desktop while screen.width was 360 and
  // the layout viewport was 720 at 0.57 zoom. The turn never fired and the
  // page looked untouched.
  //
  // The HARDWARE cannot be switched off: a touch digitiser and a physical
  // screen under ~900 CSS px on its short side is a phone, whatever the
  // browser has been told to claim. A desktop touchscreen is far wider, so
  // it stays on the desktop path. This accommodates the device rather than
  // a setting, which is the standing rule -- the old check just trusted a
  // browser that was repeating a preference back to us.
  var touch = (navigator.maxTouchPoints || 0) > 0
           || (window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
  var small = Math.min(screen.width, screen.height) <= 900;
  var coarse = touch && small;
  var fit = function(){
    var W = window.innerWidth, H = window.innerHeight;
    var turn = coarse && !framed && H > W, w, h;
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
  // AND THE FIRST TAP MAKES IT REAL. A turned frame is a picture of the
  // game, not the game: the engine sizes its buffer and maps its input from
  // the element's on-screen box, which a quarter turn leaves portrait. The
  // browser can do the rotation properly instead -- fullscreen, then lock
  // the screen to landscape -- and then the engine sees a genuine landscape
  // window, renders at full size and takes taps where they land. It needs a
  // user gesture, so it rides the first touch anywhere on the page. The
  // listener is on the WINDOW, not the canvas, because a turned canvas
  // takes no pointer events.
  //
  // Android Chrome supports the lock; iOS Safari does not, and there the
  // turned preview stands and the player turns the phone, which reaches the
  // same place through the ordinary landscape path. Nothing is asked for
  // either way.
  // ⚠ A PHONE PLAYS INSIDE AN INNER FRAME, AND THE ROTATION IS APPLIED TO
  // THE FRAME. The author's requirement, 2026-09-20: "I simply want the
  // game to fire up in landscape all the time. Even if the user is holding
  // his phone in portrait. When he sees the landscape version of the game,
  // he will know to rotate it himself, rather than be told to rotate."
  //
  // Rotating the GAME's own canvas cannot do that at full size: the engine
  // decides how big to draw by measuring the canvas's on-screen shape, and
  // a quarter turn makes that shape portrait, so it letterboxes a 16:9 game
  // into a portrait area -- (9/16)^2, a third of the width. Inside an inner
  // frame the measurement is taken against THAT frame's own window, which a
  // rotation outside it never touches. The engine sees an ordinary
  // landscape window, draws full size, and takes taps where they land.
  //
  // ⚠ AND NOTHING ROTATES THE SCREEN. An earlier version asked Android to
  // turn the display itself. That is the opposite of what was asked for --
  // the player is meant to see the landscape picture and turn the phone --
  // and it was the cause of the frame being thrown off-centre and cropped.
  var framed = location.search.indexOf("framed=1") >= 0;
  if (coarse && !framed) { location.replace("phone.html"); return; }
  // A LAYOUT THAT SURVIVES BEING TURNED BACK. Rotating landscape ->
  // portrait -> landscape left the frame wrong: the window reports its old
  // size while the rotation is still settling, and the engine resizes its
  // own surface after we resize ours. A trailing pass a moment later costs
  // nothing and lands on the settled numbers.
  // ⚠ RESIZING OUR ELEMENT DOES NOT TELL THE ENGINE ANYTHING. It listens on
  // WINDOW resize and then measures the canvas. A rotation fires that once,
  // early, while the viewport is still settling, so it measures a box that
  // is about to change and keeps that surface. Our own later passes fix the
  // element and the engine never looks again -- the frame then draws at the
  // wrong size, offset and cropped, which is what turning out to portrait
  // and back produced.
  //
  // ⚠ AND FIXED DELAYS DO NOT WIN A RACE. Passes at 120/400/900 ms fixed it
  // "sometimes" (the author, 2026-09-20: "Sometimes it works, sometimes it
  // goes back"), because how long a rotation takes to settle is not ours to
  // know. So the page checks the thing that actually matters instead of
  // guessing when to check: the drawing buffer must equal the on-screen box
  // times the pixel ratio. While it does not, ask the engine to measure
  // again. A burst of frames after any resize catches it immediately, and a
  // one-second heartbeat afterwards means that however the two get out of
  // step -- an event we never saw, a rotation slower than any timeout -- it
  // corrects itself within a second and stays corrected.
  var syncing = false;
  var synced = function(){
    var c = document.getElementById("canvas");
    if (!c) return true;
    var r = c.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    if (!r.width || !r.height) return true;
    return Math.abs(c.width - Math.round(r.width * d)) <= 2
        && Math.abs(c.height - Math.round(r.height * d)) <= 2;
  };
  var remeasure = function(){
    if (syncing) return;
    syncing = true;
    try { window.dispatchEvent(new Event("resize")); } catch (e) {}
    syncing = false;
  };
  // ⚠ AN UNCHANGED SIZE IS NOT A RESIZE. Measured 2026-09-20: after a fast
  // rotation the canvas buffer AGREES with the on-screen box and the game
  // still draws at the wrong size, offset and cropped -- so the engine's
  // own render size is stale while its canvas is correct, and nothing the
  // page can measure will see that. The author spotted the tell: "it snaps
  // back for portrait, but not landscape", which is the watchdog firing
  // only in the one case where the two DO disagree.
  //
  // Asking it to measure again is useless when the answer has not changed.
  // So give it a change it cannot coalesce away: shrink the box by 2px,
  // let it measure, then restore and let it measure again. The last
  // measurement is the right one, and 2px for one frame is invisible.
  var kick = function(){
    var c = document.getElementById("canvas");
    if (!c) return;
    var w = parseInt(c.style.width, 10), h = parseInt(c.style.height, 10);
    if (!w || !h) return;
    var ids = ["canvas", "overlayDiv"];
    for (var i = 0; i < ids.length; i++) {
      var e = document.getElementById(ids[i]);
      if (e) { e.style.width = (w - 2) + "px"; e.style.height = (h - 2) + "px"; }
    }
    remeasure();
    requestAnimationFrame(function(){ fit(); remeasure(); });
  };
  var until = 0, watching = false;
  var tick = function(){
    fit();
    if (!synced()) remeasure();
    if (Date.now() < until) { requestAnimationFrame(tick); }
    else { watching = false; kick(); }
  };
  var settle = function(){
    until = Date.now() + 2500;
    if (!watching) { watching = true; requestAnimationFrame(tick); }
  };
  setInterval(function(){ if (!synced()) { fit(); remeasure(); } }, 1000);
  document.addEventListener("fullscreenchange", settle);
  if (screen.orientation && screen.orientation.addEventListener) {
    screen.orientation.addEventListener("change", settle);
  }

  fit();
  // TEMPORARY, 2026-09-20: report the geometry once so a layout that looks
  // wrong on a real device can be read as numbers instead of inferred from
  // a screenshot. Posts only to the dev server; anywhere else it 404s and
  // the catch swallows it. DELETE once the phone layout is settled.
  window.addEventListener("resize", function(){ fit(); if (!syncing) settle(); });
  window.addEventListener("orientationchange", function(){ setTimeout(fit, 300); });
  if (window.visualViewport) window.visualViewport.addEventListener("resize", fit);
})();
</script>
""" + ROTATE_END


PHONE_PAGE = """<!doctype html>
<html lang="en-us">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>%s</title>
<style>
  html, body { margin:0; padding:0; height:100%%; overflow:hidden; background:#000; }
  #gameFrame { position:absolute; border:0 none; transform-origin:50%% 50%%; background:#000; }
</style>
</head>
<body>
<!-- The game runs in here. The turn is applied to the FRAME, so the engine
     inside still measures an ordinary landscape window and draws full size.
     Nothing asks the phone to rotate: the player sees the landscape picture
     and turns it themselves. -->
<iframe id="gameFrame" src="index.html?framed=1" allow="autoplay; fullscreen"></iframe>
<script>
(function(){
  var f = document.getElementById("gameFrame");
  var fit = function(){
    var W = window.innerWidth, H = window.innerHeight, turn = H > W, w, h;
    if (turn) { w = Math.min(H, Math.round(W * 16 / 9)); h = Math.round(w * 9 / 16); }
    else { w = W; h = Math.round(W * 9 / 16); if (h > H) { h = H; w = Math.round(H * 16 / 9); } }
    f.style.width = w + "px"; f.style.height = h + "px";
    f.style.left = Math.round((W - w) / 2) + "px";
    f.style.top = Math.round((H - h) / 2) + "px";
    f.style.transform = turn ? "rotate(90deg)" : "";
  };
  fit();
  window.addEventListener("resize", fit);
  window.addEventListener("orientationchange", function(){ setTimeout(fit, 300); });
  if (window.visualViewport) window.visualViewport.addEventListener("resize", fit);
})();
</script>
</body>
</html>
"""

def _new_dist_folders(root, started):
    """Web folders under any *-dists that were touched after the build began."""
    out = []
    for d in glob.glob(os.path.join(root, "*-dists", "*-web")):
        try:
            if os.path.isdir(d) and os.path.getmtime(d) >= started - 1:
                out.append(d)
        except OSError:
            pass
    return out


def wait_for_build(root, started, settle=10, limit=1500, idle_limit=240,
                   launcher_alive=None, log_hint=None):
    """Block until the launcher's build has actually landed on disk.

    The launcher returns long before the build is finished (see the module
    docstring), so the signal is the distribution and not the process: a
    page written after this build started, and nothing under its folder
    touched for `settle` seconds. A launcher that does wait costs `settle`
    seconds here and nothing else. Returns the page.

    If nothing at all has appeared `idle_limit` seconds in and the launcher
    process (`launcher_alive`, a callable; None means it has exited) is gone,
    the build is not coming: fail then instead of sleeping out `limit`.
    `log_hint` names the launcher's log file, if there is one.
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
        gone = launcher_alive is None or not launcher_alive()
        if (gone and time.time() - started > idle_limit
                and not _new_dist_folders(root, started)):
            msg = ("The launcher is gone and nothing has appeared under\n"
                   "  %s\nin %d s, so no build is coming." % (root, idle_limit))
            if log_hint and os.path.isfile(log_hint):
                msg += "\n  The launcher's log: %s" % log_hint
            sys.exit(msg)
        time.sleep(2)
    sys.exit("The launcher returned, but no new distribution settled under\n"
             "  %s\nwithin %d s. Look for a launcher process still running, or"
             " an error it printed above." % (root, limit))


# What a Ren'Py web build always produces, measured on a good build and kept
# loose so a version change does not break it: (label, glob patterns, floor
# in bytes). A file counts when it matches ANY pattern and is at least the
# floor. The floors sit far below a real build (index.html 17 KB, renpy.js
# 396 KB, renpy-pre.js 29 KB, renpy.wasm 21 MB, game.zip 9 MB) and far above
# a truncated or empty file.
REQUIRED = [
    ("index.html", ["index.html"], 2000),
    ("renpy.js", ["renpy.js"], 50000),
    ("renpy-pre.js", ["renpy-pre.js"], 5000),
    ("a .wasm engine file", ["*.wasm"], 1000000),
    ("game.zip or game.data", ["game.zip", "game.data"], 100000),
]


def check_complete(web):
    """Problems that make a `-web` folder an implausible build; [] if it is
    plausible."""
    if not os.path.isdir(web):
        return ["%s is not a folder" % web]
    problems = []
    for label, patterns, floor in REQUIRED:
        best = -1
        for pat in patterns:
            for f in glob.glob(os.path.join(web, pat)):
                try:
                    if os.path.isfile(f):
                        best = max(best, os.path.getsize(f))
                except OSError:
                    pass
        if best < 0:
            problems.append("missing: %s" % label)
        elif best < floor:
            problems.append("too small: %s (%d bytes, expected at least %d)"
                            % (label, best, floor))
    return problems


def publish_live(page):
    """Move the finished build into a STABLE folder the server serves.

    The launcher deletes `<name>-web/` and rewrites it over about a minute,
    and a web build does not pack its images: the page downloads each sprite
    from the server the first time a scene shows it. A rebuild while the
    author was playing therefore pulled a sprite out from under his run --
    "Download error: File not found" at the next new figure (2026-10-11).

    So the launcher's folder is RENAMED to `<name>-web-live/` once it has
    settled: live -> live.old, new -> live, old removed. Two renames, a few
    milliseconds, and serve_web.py waits out a missing file for that long.
    The launcher recreates its own folder from scratch on the next build
    while the live one keeps serving.

    There is always a live folder: if the second rename fails after the first
    succeeded, the old one is moved BACK before retrying or giving up.
    Removing the old copy afterwards never raises. Returns the live page.
    """
    src = os.path.dirname(page)
    live = src + "-live"
    old = live + ".old"
    if os.path.isdir(old):
        shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(old):
            sys.exit("Could not publish the build: the leftover %s cannot be "
                     "removed (something holds it open)." % old)
    last = None
    for attempt in range(20):
        moved = False
        try:
            if os.path.isdir(live):
                os.rename(live, old)
                moved = True
            os.rename(src, live)
            break
        except OSError as exc:
            last = exc
            if moved and not os.path.isdir(live) and os.path.isdir(old):
                try:
                    os.rename(old, live)        # put the old build back
                except OSError as exc2:
                    sys.exit("Could not publish the build, and could not put "
                             "the old one back: it is at %s (%s)" % (old, exc2))
            # the server may hold a file open inside `live` for a moment
            time.sleep(0.25)
    else:
        sys.exit("Could not publish the build: %s is busy (%s). The previous "
                 "live build is still in place." % (live, last))
    if os.path.isdir(old):
        shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(old):
            print("  note: could not remove the previous build at %s; it is "
                  "safe to delete by hand" % old)
    return os.path.join(live, "index.html")


def _write_text_atomic(path, text):
    """Write to a temp file beside `path`, then os.replace() it, so a server
    reading the page never sees half of it."""
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=os.path.dirname(path))
    try:
        with io.open(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


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
    for page in glob.glob(os.path.join(root, "*-dists", "*-web*", "index.html")):
        if ".old" in os.path.basename(os.path.dirname(page)):
            continue                    # a build being replaced by a publish
        html = io.open(page, encoding="utf-8").read()
        if ROTATE_MARK in html:
            a = html.index(ROTATE_MARK)
            b = html.index(ROTATE_END, a) + len(ROTATE_END)
            html = html[:a] + ROTATE_CARD + html[b:]
        else:
            html = html.replace("</body>", ROTATE_CARD + "\n</body>", 1)
        _write_text_atomic(page, html)
        check = io.open(page, encoding="utf-8").read()
        if ROTATE_MARK not in check or ROTATE_END not in check:
            sys.exit("The phone block did not land in %s" % page)
        title = "Loading"
        m = re.search(r"<title>(.*?)</title>", check, re.S)
        if m:
            title = m.group(1).strip()
        phone = os.path.join(os.path.dirname(page), "phone.html")
        _write_text_atomic(phone, PHONE_PAGE % title)
        print("  phone block (inner frame turned in portrait, 16:9 fit, corner"
              " menu hidden) in %s" % os.path.relpath(page, root))
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


def warn_png_art(project):
    """Installed art is WebP (2026-11-09: 253 MB of PNG became 39 MB, and the
    web host caps a browser game at 500 MB). A PNG under game/images means
    something installed art without going through install_image.py or
    register_sprite -- an old one-off script, most likely. Warn, never block:
    the build still works, it is only larger than it needs to be."""
    root = os.path.join(project, "game", "images")
    found = [os.path.join(d, f) for d, _ds, fs in os.walk(root)
             for f in fs if f.lower().endswith(".png")]
    if found:
        mb = sum(os.path.getsize(p) for p in found) / 1048576
        print("\n!! %d PNG file(s) under game/images (%.1f MB) -- installed art "
              "should be WebP:" % (len(found), mb))
        for p in found[:10]:
            print("     " + os.path.relpath(p, project))
        print("   Convert with: python tools/convert_images_webp.py \"%s\" --apply\n"
              % project)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("project", nargs="?",
                    help="the project directory, or its game/ dir")
    ap.add_argument("--sdk", default=None,
                    help="override the recorded SDK path")
    ap.add_argument("--serve", nargs="?", const=str(DEFAULT_PORT), default=None,
                    metavar="PORT",
                    help="serve the build after it succeeds (default port %d)"
                         % DEFAULT_PORT)
    ap.add_argument("--open", action="store_true",
                    help="open a browser once the server is listening")
    a = ap.parse_args()

    # `--serve <project>` must not eat the project as the port: argparse hands
    # --serve whatever follows it, so anything that is not a number goes back
    # to being the project.
    port = None
    if a.serve is not None:
        if a.serve.isdigit():
            port = int(a.serve)
        elif a.project is None:
            a.project, port = a.serve, DEFAULT_PORT
        else:
            ap.error("--serve takes a port number, not %r" % a.serve)
        if not 0 < port < 65536:
            ap.error("not a port: %d" % port)
    if a.project is None:
        ap.error("the project directory is required")

    sdk = renpy_sdk.sdk_dir(a.sdk)
    if not renpy_sdk.has_web_support(sdk):
        sys.exit(
            "This SDK has no web build support.\n"
            "  It ships as a separate archive from the SDK itself, so an\n"
            "  otherwise healthy install can still lack it.\n"
            "  Fix:  python tools/install_renpy.py"
        )

    project = project_dir(a.project)
    # The launcher writes `<name>-<version>-dists/` beside the project, not
    # inside it, so the server is pointed at the parent.
    root = os.path.dirname(project)

    if port is not None:
        # Find out BEFORE a multi-minute build that the server cannot start.
        import serve_web
        if serve_web.recorded_server(root, port):
            pass                    # ours: it keeps serving across the publish
        elif serve_web.port_taken(port):
            sys.exit("port %d is in use by something that is not this "
                     "project's server; free it or pick another port with "
                     "--serve PORT. Nothing was built." % port)

    warn_png_art(project)
    started = time.time()
    code, proc = build(sdk, project)
    if code != 0:
        explain(code)
        return code

    hint = None
    for cand in (os.path.join(sdk, "log.txt"), os.path.join(project, "log.txt")):
        if os.path.isfile(cand):
            hint = cand
            break
    page = wait_for_build(root, started, launcher_alive=lambda: proc.poll() is None,
                          log_hint=hint)
    # A quiet folder is not a finished one: give a slow tail a minute to land
    # before calling the build incomplete.
    problems = check_complete(os.path.dirname(page))
    for _ in range(12):
        if not problems:
            break
        time.sleep(5)
        problems = check_complete(os.path.dirname(page))
    if problems:
        print("\nThe new build is INCOMPLETE and was NOT published; the live "
              "build is untouched.")
        for p_ in problems:
            print("  " + p_)
        print("  in %s" % os.path.dirname(page))
        return 1
    if not add_rotate_card(root):
        sys.exit("No page found under %s to carry the phone block." % root)
    live = publish_live(page)
    print("\nBuilt. Published to %s" % os.path.dirname(live))

    if port is None:
        print("Serve it with:")
        print("  python tools/serve_web.py \"%s\" %d --detach" % (root, DEFAULT_PORT))
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
           root, str(port), "--detach"]
    if a.open:
        cmd.append("--open")
    # Detached, so this command returns and the server outlives the session
    # that ran it (serve_web.py --stop ends it).
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
