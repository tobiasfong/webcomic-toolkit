"""Serve a Ren'Py web build locally, and keep serving until Ctrl-C.

    python serve_web.py <dir-containing-the-*-dists-folder> [port] [flags]

    flags:  --open     open a browser once the server is listening
            --lan      bind every interface (a phone on the same Wi-Fi); POSTs
                       are still accepted from this machine only
            --detach   start as a fully detached background process, print the
                       URL and return at once (survives the launching session)
            --status   say whether the recorded server is alive and answering
            --stop     stop the recorded server and remove its pid file

    python serve_web.py "C:/path/to/vn" 8140 --detach     # start in the background
    python serve_web.py "C:/path/to/vn" --status
    python serve_web.py "C:/path/to/vn" --stop

Detached mode appends the server's output to `<dir>/serve_web.log` and keeps
`<dir>/serve_web.pid` (`<pid> <port>`, written by the server itself once it is
bound, so the pid is the real interpreter's and not a launcher shim's). Asking
for a server while a recorded one is alive and answering starts nothing: the
URL is printed and the exit code is 0. A port held by anything else prints
`port N is in use: ...` and exits 2.

Why this exists:
  * You cannot open index.html by double-clicking. Browsers block WebAssembly
    and service workers over file://.
  * `renpy.exe <project> launcher web_build ... --launch` starts a server and
    then EXITS, killing it. Only the GUI launcher keeps it alive.
  * `python -m http.server` drops Ren'Py's large concurrent fetches
    (renpy.wasm ~21 MB beside renpy.data ~14 MB) with ERR_CONNECTION_RESET,
    because it is single-shot per connection and has no Range support.

This one is threaded, serves byte ranges, and sets the wasm MIME type.

⚠ A SERVER STARTED FROM AN AGENT SESSION DIES WITH THAT SESSION. Observed with
exit code 4, which nothing in this script produces: the host cleans up the
session's process tree. Start it with --detach.

⚠ STOP THIS SERVER BEFORE REBUILDING? No longer needed for the build to land:
build_web.py publishes by renaming to `-web-live`. It still holds files open
for a moment, which publish_live retries around.

⚠ The browser caches the build in a service worker. After a rebuild the reader
must hard-refresh or they get the previous game.zip.
"""
import argparse
import atexit
import functools
import http.client
import ipaddress
import json
import mimetypes
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/octet-stream", ".data")

DEFAULT_PORT = 8124
PID_NAME = "serve_web.pid"
LOG_NAME = "serve_web.log"
PID_HEADER = "X-Serve-Web-Pid"
_notes_lock = threading.Lock()


def say(text="", stream=None):
    """Print that can never raise: a closed or broken pipe (the launching
    session went away) must not take a request or the server down with it."""
    try:
        (stream or sys.stdout).write(text + "\n")
        (stream or sys.stdout).flush()
    except (OSError, ValueError, AttributeError):
        pass


def find_build(root):
    """The *-web-live directory build_web.py publishes to, under any *-dists
    folder inside `root`; failing that, the newest *-web directory. The live
    folder is preferred because it is STABLE across rebuilds -- the launcher's
    own folder vanishes for a minute every build (see build_web.publish_live).
    """
    candidates, live = [], []
    for entry in os.listdir(root):
        dist = os.path.join(root, entry)
        if not (os.path.isdir(dist) and entry.endswith("-dists")):
            continue
        for sub in os.listdir(dist):
            web = os.path.join(dist, sub)
            if not os.path.isfile(os.path.join(web, "index.html")):
                continue
            if sub.endswith("-web-live"):
                live.append((os.path.getmtime(web), web))
            elif sub.endswith("-web"):
                candidates.append((os.path.getmtime(web), web))
    if live:
        return max(live)[1]
    if not candidates:
        sys.exit(
            "No web build found under %s\n"
            "Build one first:\n"
            '  "<sdk>/renpy.exe" launcher web_build "<project dir>"' % root
        )
    return max(candidates)[1]


def _row_key(row):
    """What makes two note rows the same decision: the line, the sprite and
    the opening of the line before (a short line alone is ambiguous)."""
    if not isinstance(row, dict):
        return ("<raw>", repr(row))
    return ((row.get("text") or "").strip(), row.get("tag"),
            (row.get("prev") or "").strip()[:40].strip())


def _merge_rows(held, incoming):
    """The file's rows, with the sender's replacing same-key rows in place
    and its new rows appended in the order sent."""
    out = list(held)
    at = {_row_key(r): i for i, r in enumerate(out)}
    for r in incoming:
        k = _row_key(r)
        if k in at:
            out[at[k]] = r
        else:
            at[k] = len(out)
            out.append(r)
    return out


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # ⚠ On Windows SO_REUSEADDR lets a second socket bind a port that is
    # already listening, so a "taken" port is silently shared and requests go
    # to either server. The stdlib sets it for every HTTPServer.
    allow_reuse_address = os.name != "nt"


def _is_loopback(addr):
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        return (mapped or ip).is_loopback
    except ValueError:
        return False


def _write_atomic(dest, data):
    """Write `data` to a temp file in dest's folder, then os.replace() it."""
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".part",
                               dir=os.path.dirname(dest))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # keep-alive; avoids reset storms

    ## A DEV BUILD IN A BROWSER HAS NO WAY TO HAND A FILE BACK. Added
    ## 2026-09-20: a playtest overlay that records decisions (which sprite
    ## face goes on which line) could only offer a browser download, which
    ## means the author fishes a file out of Downloads and says where it
    ## landed. The page POSTs it here instead and it lands beside the build,
    ## so the tooling reads it directly. Anything the game wants to write
    ## back can use this -- the name comes from the query string, the
    ## DIRECTORY never does.
    ##
    ## ⚠ NO DOUBLE UNDERSCORE IN THIS PATH. It was "/__notes" for an hour
    ## and every request arrived as "/_m1_<file>__notes": Ren'Py mangles a
    ## leading double underscore per script file, and it does it to the
    ## string, so a URL written in a .rpy is not the URL that is sent.
    notes_dir = None
    loopback_posts_only = False            # set when bound to every interface

    def _refuse(self, code, msg=None):
        # The body was not read, so a kept-alive connection would parse it as
        # the next request.
        self.close_connection = True
        return self.send_error(code, msg)

    def do_POST(self):
        if self.loopback_posts_only and not _is_loopback(self.client_address[0]):
            return self._refuse(403, "notes are accepted from this machine only")
        if self.path.split("?")[0] != "/dev-notes" or not self.notes_dir:
            # Name what was refused. A bare 404 here sent one debugging
            # session chasing the endpoint when the caller was asking for
            # something else entirely.
            return self._refuse(404, "no POST handler for %s (notes_dir=%r)"
                                     % (self.path, self.notes_dir))
        name = "face_notes.json"
        if "?" in self.path:
            from urllib.parse import parse_qs
            asked = (parse_qs(self.path.split("?", 1)[1]).get("name") or [""])[0]
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,60}\.json", asked or ""):
                name = asked
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._refuse(400)
        if not 0 < length <= 8 << 20:
            return self._refuse(413)
        body = self.rfile.read(length)
        try:
            incoming = json.loads(body.decode("utf-8"))
        except Exception as exc:
            return self.send_error(400, "not JSON: %s" % exc)
        dest = os.path.join(self.notes_dir, name)
        # ⚠ A LIST OF NOTES IS MERGED INTO THE FILE, NEVER WRITTEN OVER IT.
        # The page sends its whole copy, and that copy lives in the browser's
        # persistent data, which is only flushed now and then. Reload the
        # page before a flush and its copy is BEHIND the file; the next send
        # then erased 21 of the author's latest notes (2026-10-19). Merging
        # makes a stale sender harmless: rows are keyed on what identifies a
        # decision (the line, the sprite, the line before), a row the page
        # sends replaces the file's row for the same key, and rows only the
        # file has are kept. The overlay never deletes a note, so a union
        # loses nothing it meant to keep.
        #
        # The read-merge-write is one critical section (requests are handled
        # concurrently) and the write is a temp file renamed into place, so a
        # reader or a crash never sees half a file.
        try:
            with _notes_lock:
                if isinstance(incoming, list) and os.path.isfile(dest):
                    try:
                        with open(dest, encoding="utf-8") as f:
                            held = json.load(f)
                    except Exception:
                        held = None
                    if isinstance(held, list):
                        incoming = _merge_rows(held, incoming)
                        body = json.dumps(incoming, indent=1,
                                          ensure_ascii=False).encode("utf-8")
                _write_atomic(dest, body)
        except OSError as exc:
            return self.send_error(500, "could not write notes: %s" % exc)
        say("  <- %s (%d bytes)" % (dest, len(body)), sys.stderr)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _range_not_satisfiable(self, size):
        self.send_response(416)
        self.send_header("Content-Range", "bytes */%d" % size)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        # A publish renames the served folder twice (build_web.publish_live);
        # a file asked for in that gap would 404 and the engine treats that
        # as fatal. Wait it out: a few checks over half a second.
        path = self.translate_path(self.path)
        for _ in range(5):
            if os.path.exists(path):
                break
            time.sleep(0.1)
        rng = self.headers.get("Range")
        if not rng:
            return super().do_GET()
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().do_GET()
        # One range only; a list of ranges or anything unparseable is served
        # whole, which RFC 9110 allows.
        m = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", rng)
        if not m or not (m.group(1) or m.group(2)):
            return super().do_GET()
        try:
            size = os.path.getsize(path)
        except OSError:
            return super().do_GET()
        first, last = m.group(1), m.group(2)
        if not first:                           # suffix: the LAST N bytes
            n = int(last)
            if n == 0 or size == 0:
                return self._range_not_satisfiable(size)
            start, end = max(0, size - n), size - 1
        else:
            start = int(first)
            if start >= size:
                return self._range_not_satisfiable(size)
            end = min(int(last), size - 1) if last else size - 1
            if end < start:                     # malformed: serve it whole
                return super().do_GET()
        length = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Content-Length", str(length))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        # Lets --status and --stop confirm that what answers on the port is
        # the recorded process and not a stranger that took its pid or port.
        self.send_header(PID_HEADER, str(os.getpid()))
        # A DEVELOPMENT server: never let the browser hold a copy. It does not
        # stop Ren'Py's service worker (which answers before the network is
        # consulted at all), but it removes the other half of the problem --
        # a rebuild that the author cannot see is the most confusing failure
        # this setup produces.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        # ⚠ NEVER LET A LOG LINE FAIL A REQUEST. The launching session's pipe
        # can close under a running server, and then every write to stderr
        # raises. In detached mode stderr is the log file.
        try:
            say(fmt % args, sys.stderr)
        except Exception:
            pass


# ---------------------------------------------------------------- process control

def _pid_path(root):
    return os.path.join(root, PID_NAME)


def read_pidfile(root):
    """(pid, port) from the pid file, or None."""
    try:
        with open(_pid_path(root), encoding="utf-8") as f:
            pid, port = f.read().split()[:2]
        return int(pid), int(port)
    except (OSError, ValueError):
        return None


def pid_alive(pid):
    """Whether a process exists. Never os.kill(pid, 0): on Windows that
    TERMINATES the process."""
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)    # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def probe(port, timeout=3.0):
    """GET / on this machine. Returns (http status, pid the server reports)
    or None when nothing answers HTTP there."""
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            c.request("GET", "/")
            r = c.getresponse()
            r.read()
            hdr = r.getheader(PID_HEADER)
            return r.status, (int(hdr) if hdr and hdr.isdigit() else None)
        finally:
            c.close()
    except (OSError, http.client.HTTPException):
        return None


def port_taken(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def recorded_server(root, port=None):
    """(pid, port) of the recorded server when it is alive AND answering as
    that pid (and on `port`, if one is asked for); otherwise None."""
    rec = read_pidfile(root)
    if not rec or (port is not None and rec[1] != port):
        return None
    pid, p = rec
    if not pid_alive(pid):
        return None
    got = probe(p)
    if got and got[0] == 200 and got[1] == pid:
        return pid, p
    return None


def lan_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def tail_log(root, n=12):
    try:
        with open(os.path.join(root, LOG_NAME), encoding="utf-8",
                  errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""


def cmd_status(root, port):
    rec = read_pidfile(root)
    if not rec:
        say("no server recorded under %s" % root)
        return 1
    srv = recorded_server(root, port)
    if srv:
        say("running: pid %d, http://127.0.0.1:%d/ answering" % srv)
        return 0
    pid, p = rec
    if pid_alive(pid):
        say("pid %d is alive but nothing answers as it on port %d" % (pid, p))
    else:
        say("not running (pid %d from the pid file is gone; stale file %s)"
            % (pid, _pid_path(root)))
    return 1


def cmd_stop(root, port):
    rec = read_pidfile(root)
    if not rec:
        say("no server recorded under %s" % root)
        return 0
    pid, p = rec
    if not pid_alive(pid):
        say("pid %d is already gone; removing the stale pid file" % pid)
        _drop_pidfile(root)
        return 0
    if not recorded_server(root, port):
        say("pid %d is alive but does not answer as this server on port %d; "
            "not stopping a process that may not be ours (pid file left in "
            "place)" % (pid, p))
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        say("could not stop pid %d: %s" % (pid, exc))
        return 1
    for _ in range(50):
        if not pid_alive(pid):
            break
        time.sleep(0.1)
    else:
        say("pid %d did not exit" % pid)
        return 1
    _drop_pidfile(root)
    say("stopped pid %d (port %d)" % (pid, p))
    return 0


def _drop_pidfile(root, only_pid=None):
    rec = read_pidfile(root)
    if only_pid is not None and rec and rec[0] != only_pid:
        return
    try:
        os.remove(_pid_path(root))
    except OSError:
        pass


def _open_if_asked(port, flags):
    """--open with a server ALREADY running still opens the page. A launcher
    script that starts the server and opens the browser in one command used
    to print "already running" and show nothing, which reads as a failure."""
    if "--open" in flags:
        try:
            webbrowser.open("http://127.0.0.1:%d/" % port)
        except Exception:
            pass


def cmd_detach(root, port, flags):
    srv = recorded_server(root, port)
    if srv:
        say("already running (pid %d): http://127.0.0.1:%d/" % srv)
        _open_if_asked(srv[1], flags)
        return 0
    if port_taken(port):
        say("port %d is in use: something other than a recorded server of "
            "this folder is listening there" % port)
        return 2
    _drop_pidfile(root)
    cmd = [sys.executable, os.path.abspath(__file__), root, str(port),
           "--_detached"] + [f for f in ("--lan",) if f in flags]
    log = open(os.path.join(root, LOG_NAME), "ab")
    kw = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=root,
              close_fds=True)
    if os.name == "nt":
        # CREATE_NO_WINDOW, never DETACHED_PROCESS. A venv's python.exe is a
        # launcher that starts the real interpreter as its child; started
        # with DETACHED_PROCESS the launcher has no console, so Windows gave
        # that child a NEW, VISIBLE console window titled with the python
        # path. Closing that stray window killed the server, which the
        # browser reported as a download "network error" in the middle of a
        # page load (twice, the evening this mode was added). With
        # CREATE_NO_WINDOW the launcher owns a windowless console and the
        # interpreter inherits it: nothing appears on the desktop.
        base = (getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
        brk = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
        try:
            proc = subprocess.Popen(cmd, creationflags=base | brk, **kw)
        except OSError:
            # the enclosing job object does not allow breakaway
            proc = subprocess.Popen(cmd, creationflags=base, **kw)
    else:
        proc = subprocess.Popen(cmd, start_new_session=True, **kw)
    log.close()
    deadline = time.time() + 25
    while time.time() < deadline:
        srv = recorded_server(root, port)
        if srv:
            url = "http://127.0.0.1:%d/" % port
            say("started (pid %d, log %s)" % (srv[0], os.path.join(root, LOG_NAME)))
            if "--lan" in flags:
                say("  LAN: http://%s:%d/" % (lan_address(), port))
            say("  -> " + url)
            if "--open" in flags:
                webbrowser.open(url)
            return 0
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    say("the server did not come up on port %d" % port)
    t = tail_log(root)
    if t:
        say("--- end of %s ---\n%s" % (LOG_NAME, t.rstrip()))
    return 1


# ---------------------------------------------------------------- foreground

def run_server(root, port, flags):
    detached = "--_detached" in flags
    # The page carries the phone block only if the build's injection ran
    # AFTER the launcher wrote index.html, and the launcher returns before
    # it has (build_web.py, wait_for_build). Adding the block here as well
    # means the served page always has it, whatever the build did, and an
    # edit to the block is served without a rebuild. Idempotent, atomic, and
    # never allowed to stop the server from starting.
    try:
        import build_web
        build_web.add_rotate_card(root)
    except BaseException as exc:                   # sys.exit counts too
        say("note: the phone block was not refreshed: %s" % exc, sys.stderr)
    build = find_build(root)
    # --lan binds every interface so a phone on the same Wi-Fi can load the
    # game: the only way to test the phone layout on a phone. The printed URL
    # is the machine's own address on that network. Windows may ask once to
    # allow Python through the firewall on private networks; say yes. Note
    # that over plain http on a LAN address the browser treats the page as
    # insecure, so the service worker and storage persistence do not engage;
    # saves still work for the session, and the layout test is unaffected.
    lan = "--lan" in flags
    host = "0.0.0.0" if lan else "127.0.0.1"
    shown = lan_address() if lan else "127.0.0.1"
    url = "http://%s:%d/" % (shown, port)

    # Bind BEFORE opening the browser. A caller that launches the browser
    # first races the server and lands on ERR_CONNECTION_REFUSED, which looks
    # exactly like a failed build -- so the browser is opened from here, after
    # the socket is listening, rather than from whatever script invoked this.
    Handler.notes_dir = root
    Handler.loopback_posts_only = lan
    try:
        httpd = Server((host, port), functools.partial(Handler, directory=build))
    except OSError as exc:
        say("port %d is in use: %s" % (port, exc.strerror or exc), sys.stderr)
        return 2
    pidfile = _pid_path(root)
    try:
        _write_atomic(pidfile, ("%d %d\n" % (os.getpid(), port)).encode())
        atexit.register(_drop_pidfile, root, os.getpid())
    except OSError as exc:
        say("note: could not write %s: %s" % (pidfile, exc), sys.stderr)
    say("Serving %s" % os.path.basename(build))
    say("  -> " + url)
    if not detached:
        say("Leave this window open. Ctrl-C to stop.")
    if "--open" in flags and not detached:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Serve a Ren'Py web build (see the module docstring).")
    ap.add_argument("dir", help="the folder containing the *-dists folder")
    ap.add_argument("port", nargs="?", type=int, default=None)
    for f in ("--open", "--lan", "--detach", "--status", "--stop", "--_detached"):
        ap.add_argument(f, action="store_true", help=argparse.SUPPRESS
                        if f == "--_detached" else None)
    a = ap.parse_args()
    root = os.path.abspath(a.dir)
    if not os.path.isdir(root):
        say("not a folder: %s" % root, sys.stderr)
        return 2
    flags = {f for f in ("--open", "--lan", "--detach", "--status", "--stop",
                         "--_detached") if getattr(a, f.lstrip("-"))}
    if a.status:
        return cmd_status(root, a.port)
    if a.stop:
        return cmd_stop(root, a.port)
    port = a.port if a.port is not None else DEFAULT_PORT
    if not 0 < port < 65536:
        say("not a port: %d" % port, sys.stderr)
        return 2
    srv = recorded_server(root, port)
    if srv:
        say("already running (pid %d): http://127.0.0.1:%d/" % srv)
        _open_if_asked(srv[1], flags)
        return 0
    if a.detach:
        return cmd_detach(root, port, flags)
    return run_server(root, port, flags)


if __name__ == "__main__":
    sys.exit(main())
