"""Serve a Ren'Py web build locally, and keep serving until Ctrl-C.

    python serve_web.py <dir-containing-the-*-dists-folder> [port]

Why this exists:
  * You cannot open index.html by double-clicking. Browsers block WebAssembly
    and service workers over file://.
  * `renpy.exe <project> launcher web_build ... --launch` starts a server and
    then EXITS, killing it. Only the GUI launcher keeps it alive.
  * `python -m http.server` drops Ren'Py's large concurrent fetches
    (renpy.wasm ~21 MB beside renpy.data ~14 MB) with ERR_CONNECTION_RESET,
    because it is single-shot per connection and has no Range support.

This one is threaded, serves byte ranges, and sets the wasm MIME type.

⚠ STOP THIS SERVER BEFORE REBUILDING. It holds the distribution directory open
and the build dies with `PermissionError: [WinError 32]`.

⚠ The browser caches the build in a service worker. After a rebuild the reader
must hard-refresh or they get the previous game.zip.
"""
import functools
import mimetypes
import os
import re
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/octet-stream", ".data")


def find_build(root):
    """Newest *-web directory under any *-dists folder inside `root`."""
    candidates = []
    for entry in os.listdir(root):
        dist = os.path.join(root, entry)
        if not (os.path.isdir(dist) and entry.endswith("-dists")):
            continue
        for sub in os.listdir(dist):
            web = os.path.join(dist, sub)
            if sub.endswith("-web") and os.path.isfile(os.path.join(web, "index.html")):
                candidates.append((os.path.getmtime(web), web))
    if not candidates:
        sys.exit(
            "No web build found under %s\n"
            "Build one first:\n"
            '  "<sdk>/renpy.exe" launcher web_build "<project dir>"' % root
        )
    return max(candidates)[1]


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
    notes_dir = None

    def do_POST(self):
        if self.path.split("?")[0] != "/__notes" or not self.notes_dir:
            return self.send_error(404)
        name = "face_notes.json"
        if "?" in self.path:
            from urllib.parse import parse_qs
            asked = (parse_qs(self.path.split("?", 1)[1]).get("name") or [""])[0]
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,60}\.json", asked or ""):
                name = asked
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self.send_error(400)
        if not 0 < length <= 8 << 20:
            return self.send_error(413)
        body = self.rfile.read(length)
        try:
            import json
            json.loads(body.decode("utf-8"))    # a write is worth one parse
        except Exception as exc:
            return self.send_error(400, "not JSON: %s" % exc)
        dest = os.path.join(self.notes_dir, name)
        with open(dest, "wb") as f:
            f.write(body)
        print("  <- %s (%d bytes)" % (dest, len(body)), flush=True)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().do_GET()
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().do_GET()
        size = os.path.getsize(path)
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if not m:
            return super().do_GET()
        start = int(m.group(1)) if m.group(1) else 0
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        length = max(0, end - start + 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
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
        # A DEVELOPMENT server: never let the browser hold a copy. It does not
        # stop Ren'Py's service worker (which answers before the network is
        # consulted at all), but it removes the other half of the problem --
        # a rebuild that the author cannot see is the most confusing failure
        # this setup produces.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        sys.exit("usage: python serve_web.py <dir-containing-*-dists> [port] "
                 "[--open] [--lan]")
    # The page carries the phone block only if the build's injection ran
    # AFTER the launcher wrote index.html, and the launcher returns before
    # it has (build_web.py, wait_for_build). Adding the block here as well
    # means the served page always has it, whatever the build did, and an
    # edit to the block is served without a rebuild. Idempotent.
    import build_web
    build_web.add_rotate_card(os.path.abspath(args[0]))
    root = find_build(os.path.abspath(args[0]))
    port = int(args[1]) if len(args) > 1 else 8124
    # --lan binds every interface so a phone on the same Wi-Fi can load the
    # game: the only way to test the phone layout on a phone. The printed URL
    # is the machine's own address on that network. Windows may ask once to
    # allow Python through the firewall on private networks; say yes. Note
    # that over plain http on a LAN address the browser treats the page as
    # insecure, so the service worker and storage persistence do not engage;
    # saves still work for the session, and the layout test is unaffected.
    host = "0.0.0.0" if "--lan" in flags else "127.0.0.1"
    shown = "127.0.0.1"
    if host == "0.0.0.0":
        import socket
        try:
            s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s_.connect(("8.8.8.8", 80))
            shown = s_.getsockname()[0]; s_.close()
        except OSError:
            shown = socket.gethostbyname(socket.gethostname())
    url = f"http://{shown}:{port}/"

    # Bind BEFORE opening the browser. A caller that launches the browser
    # first races the server and lands on ERR_CONNECTION_REFUSED, which looks
    # exactly like a failed build -- so the browser is opened from here, after
    # the socket is listening, rather than from whatever script invoked this.
    Handler.notes_dir = os.path.abspath(args[0])
    httpd = ThreadingHTTPServer(
        (host, port), functools.partial(Handler, directory=root)
    )
    print(f"Serving {os.path.basename(root)}")
    print(f"  -> {url}")
    print("Leave this window open. Ctrl-C to stop.", flush=True)
    if "--open" in flags:
        webbrowser.open(url)
    httpd.serve_forever()
