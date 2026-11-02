#!/usr/bin/env python3
"""The station's static server (CT-01; ARCHITECTURE 4.1 `seastones-web`).

Ported in spirit from the Model 4 kiosk's ``src/webserve/serve.py``: the process that must
never die. It serves the page (``src/web/``), the content index and the program listing, and
two small ``POST`` routes. It imports nothing from ``rigd`` and knows nothing about the
engine, so an engine crash cannot take the page down (the page then shows its own error
state, KIOSK-4).

Routes:

    /                         src/web/index.html, and the page's own files under src/web/
    /content/index.json       the content index (built at start from --content, CT-01)
    /content/images/<name>    an image the index names (our own drawings only)
    /program/rig.lst.json     the assembler's listing, for the code view (CODE-1)
    POST /heartbeat           touch the page-heartbeat file the watchdog reads
    POST /counters            append one anonymous counters line (KIOSK-7), size-bounded

Only files with a known extension are served from src/web/ (never this file, never a
``.py``). Every response carries a Content-Security-Policy that allows nothing off the
machine and no media at all (KIOSK-6; the page makes no sound, AUDIO-1).

If the content index cannot be built, ``/content/index.json`` answers 503 and the page
shows its content-down state. There is no fallback content here (no demo fallback).

    python3 src/web/serve.py --port 8080 [--content content] [--program build/program]

Note for the architecture owner: ARCHITECTURE 12 puts this file at
``src/webserve/serve.py``. The UI lane may only write under ``src/web/``, so it lives here.
"""

from __future__ import annotations

import argparse
import http.server
import ipaddress
import json
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_CONTENT = os.path.join(ROOT, "content")
DEFAULT_INDEX_DIR = os.path.join(ROOT, "build", "content")
DEFAULT_PROGRAM = os.path.join(ROOT, "build", "program")
DEFAULT_RUN = os.path.join(ROOT, "build", "run")

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; media-src 'none'; object-src 'none'; "
    "connect-src 'self' ws://127.0.0.1:* ws://localhost:*; base-uri 'none'; frame-ancestors 'none'"
)

MAX_BODY_BYTES = 64 * 1024
MAX_COUNTERS_BYTES = 2 * 1024 * 1024
COUNTER_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def build_index(content_dir: str, out_dir: str) -> str | None:
    """Index the content folder with the ported tool. Returns the error text, or None."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    try:
        from content.tool.index import build  # noqa: PLC0415 (import after path set)

        build(content_dir, out_dir, source="dev" if content_dir == DEFAULT_CONTENT else "usb")
        return None
    except Exception as exc:  # the server never dies for content; the page shows it
        return f"{type(exc).__name__}: {exc}"


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "seastones-web"
    sys_version = ""
    cfg: dict = {}
    lock = threading.Lock()

    def log_message(self, fmt, *args):  # one quiet line per request, no client address
        if self.cfg.get("verbose"):
            sys.stderr.write("serve: " + (fmt % args) + "\n")

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _file(self, path: str) -> None:
        ext = os.path.splitext(path)[1].lower()
        if ext not in TYPES or not os.path.isfile(path):
            self._send(404, b"not found\n", "text/plain")
            return
        with open(path, "rb") as fh:
            self._send(200, fh.read(), TYPES[ext])

    def _under(self, base: str, rel: str) -> str | None:
        rel = rel.lstrip("/")
        if not rel or ".." in rel.split("/") or rel.startswith("."):
            return None
        full = os.path.realpath(os.path.join(base, rel))
        return full if full.startswith(os.path.realpath(base) + os.sep) else None

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path in ("/", "/index.html"):
            return self._file(os.path.join(HERE, "index.html"))
        if path == "/content/index.json":
            index = os.path.join(self.cfg["index_dir"], "index.json")
            if self.cfg.get("index_error") or not os.path.exists(index):
                msg = self.cfg.get("index_error") or "index.json was not built"
                return self._send(503, json.dumps({"error": msg}).encode(), "application/json")
            return self._file(index)
        if path.startswith("/content/images/"):
            full = self._under(
                os.path.join(self.cfg["content"], "images"), path[len("/content/images/") :]
            )
            return self._file(full) if full else self._send(404, b"not found\n", "text/plain")
        if path == "/program/rig.lst.json":
            return self._file(os.path.join(self.cfg["program"], "rig.lst.json"))
        if path.endswith(".py"):
            return self._send(404, b"not found\n", "text/plain")
        full = self._under(HERE, path)
        return self._file(full) if full else self._send(404, b"not found\n", "text/plain")

    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            return self._send(413, b"too large\n", "text/plain")
        body = self.rfile.read(length) if length else b""
        if self.path == "/heartbeat":
            try:
                os.makedirs(self.cfg["run"], exist_ok=True)
                with open(os.path.join(self.cfg["run"], "page-heartbeat"), "w") as fh:
                    fh.write(str(int(time.time())))
            except OSError:
                pass  # the watchdog notices a stale file by itself
            return self._send(204, b"", "text/plain")
        if self.path == "/counters":
            try:
                rec = json.loads(body or b"{}")
                name, count = rec.get("name"), rec.get("count", 1)
                if not (
                    isinstance(name, str) and COUNTER_NAME.match(name) and isinstance(count, int)
                ):
                    return self._send(400, b"bad counter\n", "text/plain")
                line = json.dumps({"name": name, "count": count, "t": int(time.time())}) + "\n"
                path = os.path.join(self.cfg["run"], "counters.jsonl")
                with self.lock:
                    os.makedirs(self.cfg["run"], exist_ok=True)
                    if os.path.exists(path) and os.path.getsize(path) > MAX_COUNTERS_BYTES:
                        os.replace(path, path + ".1")
                    with open(path, "a") as fh:
                        fh.write(line)
                        fh.flush()
                        os.fsync(fh.fileno())
                return self._send(204, b"", "text/plain")
            except (ValueError, OSError):
                return self._send(400, b"bad counter\n", "text/plain")
        return self._send(404, b"not found\n", "text/plain")


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="serve.py")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--content", default=DEFAULT_CONTENT, help="content folder to index at start")
    ap.add_argument("--index-dir", default=DEFAULT_INDEX_DIR, help="where index.json is written")
    ap.add_argument("--no-build", action="store_true", help="serve an index already in --index-dir")
    ap.add_argument("--program", default=DEFAULT_PROGRAM, help="folder holding rig.lst.json")
    ap.add_argument("--run", default=DEFAULT_RUN, help="heartbeat and counters folder")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    if not _loopback(args.host):
        print(
            "serve.py: refusing to listen beyond loopback (the station is offline)", file=sys.stderr
        )
        return 2
    error = None if args.no_build else build_index(args.content, args.index_dir)
    if error:
        print(f"serve.py: content index not built: {error}", file=sys.stderr)
    Handler.cfg = {
        "content": os.path.abspath(args.content),
        "index_dir": os.path.abspath(args.index_dir),
        "index_error": error,
        "program": os.path.abspath(args.program),
        "run": os.path.abspath(args.run),
        "verbose": args.verbose,
    }
    httpd = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    print(f"serve.py: http://{args.host}:{httpd.server_address[1]}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
