"""src/web/serve.py, the static server (CT-01, KIOSK-6, KIOSK-7).

Starts the real server on a free loopback port with the real content set and checks what it
serves and what it refuses: only the page's own files, the content index, the listing; never
a .py file or a path outside src/web; a Content-Security-Policy that allows nothing off the
machine and no media; bounded counters; a heartbeat file; loopback only.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVE = os.path.join(ROOT, "src", "web", "serve.py")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _free_port()
    run = tmp_path_factory.mktemp("run")
    idx = tmp_path_factory.mktemp("index")
    proc = subprocess.Popen(
        [sys.executable, SERVE, "--port", str(port), "--index-dir", str(idx), "--run", str(run)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/", timeout=0.5)
            break
        except OSError:
            time.sleep(0.05)
    yield base, run
    proc.terminate()
    proc.wait(timeout=5)


def _get(url):
    try:
        r = urllib.request.urlopen(url, timeout=3)
        return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _post(url, body: bytes):
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=3)
        return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_serves_the_page_with_a_strict_csp(server):
    base, _ = server
    status, headers, body = _get(base + "/")
    assert status == 200
    assert b'<script type="module" src="app/app.js">' in body
    csp = headers["Content-Security-Policy"]
    assert "media-src 'none'" in csp
    assert "default-src 'self'" in csp
    assert "https:" not in csp


def test_serves_the_content_index_and_the_listing(server):
    base, _ = server
    status, _, body = _get(base + "/content/index.json")
    assert status == 200
    index = json.loads(body)
    assert index["schema"] == "seastones.content-index/1"
    assert "staff_pin" not in json.dumps(index["conf"])
    if os.path.exists(os.path.join(ROOT, "build", "program", "rig.lst.json")):
        status, _, body = _get(base + "/program/rig.lst.json")
        assert status == 200 and json.loads(body)["format"] == "seastones.listing/1"


@pytest.mark.parametrize(
    "path",
    [
        "/serve.py",
        "/app/../serve.py",
        "/../content/slots.md",
        "/%2e%2e/content/kiosk.conf",
        "/app/nope.js",
    ],
)
def test_refuses_anything_else(server, path):
    base, _ = server
    status, _, _ = _get(base + path)
    assert status == 404


def test_counters_are_bounded_and_named(server):
    base, run = server
    assert _post(base + "/counters", json.dumps({"name": "home", "count": 1}).encode()) == 204
    assert _post(base + "/counters", json.dumps({"name": "Bad Name!", "count": 1}).encode()) == 400
    assert _post(base + "/counters", b"x" * (70 * 1024)) == 413
    lines = (run / "counters.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["name"] == "home"


def test_heartbeat_touches_the_watchdog_file(server):
    base, run = server
    assert _post(base + "/heartbeat", b"") == 204
    assert (run / "page-heartbeat").exists()


def test_refuses_to_listen_beyond_loopback():
    out = subprocess.run(
        [sys.executable, SERVE, "--host", "0.0.0.0", "--port", "0"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert out.returncode == 2
    assert "loopback" in out.stderr
