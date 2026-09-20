#!/usr/bin/env python3
"""
iio_browse.py -- browse a capture, pick channels, get block parameters.

The third tool in the set. iio_discover.py enumerates on hardware,
iio_explain.py explains a capture in a terminal, and this explains the
same capture in a browser and hands back the fields the GNU Radio IIO
Device Source block wants.

Like iio_explain.py it never imports libiio and never touches hardware,
so twenty people can run it from one capture with nothing plugged in:

    ./iio_browse.py fixtures/m2k-real.json
    (open http://127.0.0.1:8737)

Nothing here is installed -- the server is Python's own http.server and
the page is plain HTML with no build step. That is deliberate: the
workshop does no software installs on the day.

The browser is kept dumb on purpose. Meaning comes from
iio_explain.annotate(), block parameters come from iio_grc.build(), and
both are tested without a browser in the loop.
"""

import argparse
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import iio_explain
import iio_grc

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browse")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}

MAX_BODY = 1 << 20          # a selection is small; refuse anything silly


def load_snapshot(path):
    with open(path) as handle:
        data = json.load(handle)
    if "devices" not in data:
        raise ValueError("%s does not look like an iio_discover --json "
                         "capture (no 'devices' key)." % path)
    return data


def make_handler(snapshot, annotated, source_path):
    """Build the request handler around one already-loaded capture.

    Annotation runs once at startup rather than per request -- it is the
    same answer every time, and a whole M2K capture takes long enough
    that doing it per click would be felt.
    """

    class Handler(BaseHTTPRequestHandler):
        # The default logger writes a line per request to stderr, which
        # buries the one line that matters (the URL to open).
        def log_message(self, *args):
            pass

        def _send(self, status, body, content_type):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_json(self, status, payload):
            self._send(status, json.dumps(payload),
                       "application/json; charset=utf-8")

        def _send_static(self, name):
            path = os.path.join(STATIC_DIR, name)
            # STATIC_DIR is fixed and names come from the routing table
            # below, but normalise anyway so a future route cannot walk out.
            if not os.path.abspath(path).startswith(STATIC_DIR + os.sep):
                self._send_json(404, {"error": "not found"})
                return
            try:
                with open(path, "rb") as handle:
                    body = handle.read()
            except OSError:
                self._send_json(500, {"error": "missing static file %s" % name})
                return
            extension = os.path.splitext(name)[1]
            self._send(200, body, CONTENT_TYPES.get(extension,
                                                    "application/octet-stream"))

        def do_GET(self):
            route = self.path.split("?", 1)[0]
            if route == "/":
                self._send_static("index.html")
            elif route in ("/app.js", "/style.css"):
                self._send_static(route.lstrip("/"))
            elif route == "/api/block":
                query = urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query)
                wanted = (query.get("device") or [""])[0]
                try:
                    text = iio_grc.generate_block(snapshot, wanted)
                except ValueError as error:
                    self._send_json(404, {"error": str(error)})
                    return
                self._send_json(200, {
                    "filename": "%s.block.yml" % text.split("\n", 1)[0][4:],
                    "yaml": text,
                })
            elif route == "/api/tree":
                self._send_json(200, {
                    "source": os.path.basename(source_path),
                    "capture": annotated,
                    "defaults": {"buffer_size": iio_grc.DEFAULT_BUFFER_SIZE},
                })
            else:
                self._send_json(404, {"error": "no route %s" % route})

        do_HEAD = do_GET

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/api/emit":
                self._send_json(404, {"error": "no route %s" % self.path})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY:
                self._send_json(400, {"error": "bad Content-Length"})
                return
            try:
                selection = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError) as error:
                self._send_json(400, {"error": "bad JSON: %s" % error})
                return
            if not isinstance(selection, dict):
                self._send_json(400, {"error": "selection must be an object"})
                return
            self._send_json(200, iio_grc.build(snapshot, selection))

    return Handler


def serve(path, host="127.0.0.1", port=8737):
    snapshot = load_snapshot(path)
    annotated = iio_explain.annotate(snapshot)
    handler = make_handler(snapshot, annotated, path)
    server = ThreadingHTTPServer((host, port), handler)

    devices = len(snapshot.get("devices", []))
    attrs = sum(len(d.get("device_attrs", [])) + len(d.get("buffer_attrs", []))
                + len(d.get("debug_attrs", []))
                + sum(len(c.get("attrs", [])) for c in d.get("channels", []))
                for d in snapshot.get("devices", []))
    print("%s -- %d devices, %d attributes" % (path, devices, attrs))
    print("http://%s:%d" % (host, server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Browse an IIO capture and build GNU Radio block "
                    "parameters from it. No hardware, no libiio.")
    parser.add_argument("snapshot", nargs="?",
                        default="fixtures/m2k-real.json",
                        help="JSON from iio_discover.py --json")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default 127.0.0.1; use 0.0.0.0 "
                             "to serve a room)")
    parser.add_argument("--port", type=int, default=8737)
    args = parser.parse_args()

    try:
        return serve(args.snapshot, args.host, args.port)
    except (OSError, ValueError) as error:
        sys.exit("%s: %s" % (args.snapshot, error))


if __name__ == "__main__":
    sys.exit(main())
