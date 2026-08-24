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
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python serve_web.py <dir-containing-*-dists> [port]")
    root = find_build(os.path.abspath(sys.argv[1]))
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8124
    print(f"Serving {os.path.basename(root)}")
    print(f"  -> http://127.0.0.1:{port}/")
    print("Leave this window open. Ctrl-C to stop.", flush=True)
    ThreadingHTTPServer(
        ("127.0.0.1", port), functools.partial(Handler, directory=root)
    ).serve_forever()
