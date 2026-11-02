#!/usr/bin/env python3
"""A launchd-free stand-in for systemd's supervision of rigd, for the Mac and for tests (VS-17).

It does for one child what ``deploy/systemd/seastones-rigd.service`` asks systemd to do:

* ``Restart=always`` with ``RestartSec`` (1 s): any exit, for any reason, starts it again.
* ``Type=notify`` and ``WatchdogSec`` (5 s): the child gets ``NOTIFY_SOCKET``; after its
  ``READY=1``, a gap of more than WatchdogSec between ``WATCHDOG=1`` datagrams sends it
  SIGABRT (systemd's default WatchdogSignal) and, if it is still there 1 s later, SIGKILL.

Each line it prints is one JSON event (``start`` with the child's PID, ``ready``,
``watchdog_timeout``, ``exit``), stamped with ``time.monotonic()``, so tests can measure
recovery. ``{n}`` in the child's arguments becomes the start count (1, 2, ...), so each run
can write its own capture. SIGTERM or SIGINT stops the child and the stub.

    scripts/supervise-stub.py [--restart-sec 1] [--watchdog-sec 5] -- python3 -m rigd ...
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time


def emit(event: str, **kw) -> None:
    print(json.dumps({"event": event, "t": time.monotonic(), **kw}), flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="supervise-stub.py")
    ap.add_argument("--restart-sec", type=float, default=1.0)
    ap.add_argument("--watchdog-sec", type=float, default=5.0)
    ap.add_argument("--max-starts", type=int, default=0, help="0: no limit")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        ap.error("no command")

    tmp = tempfile.mkdtemp(prefix="sx-notify-")
    path = os.path.join(tmp, "notify")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(path)
    sock.settimeout(0.05)
    stopping = False

    def stop(_sig, _frm):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    starts = 0
    child = None
    try:
        while not stopping and (not args.max_starts or starts < args.max_starts):
            starts += 1
            argv_n = [a.replace("{n}", str(starts)) for a in cmd]
            child = subprocess.Popen(argv_n, env=dict(os.environ, NOTIFY_SOCKET=path))
            emit("start", n=starts, pid=child.pid)
            ready = False
            last_ping = time.monotonic()
            abort_at = None
            while child.poll() is None and not stopping:
                try:
                    data = sock.recv(4096).decode(errors="replace")
                except TimeoutError:
                    data = ""
                now = time.monotonic()
                for line in data.splitlines():
                    if line == "READY=1" and not ready:
                        ready = True
                        last_ping = now
                        emit("ready", n=starts, pid=child.pid)
                    elif line == "WATCHDOG=1":
                        last_ping = now
                if ready and abort_at is None and now - last_ping > args.watchdog_sec:
                    emit("watchdog_timeout", n=starts, pid=child.pid, silent_s=now - last_ping)
                    # as systemd does: the signal, then SIGCONT so a stopped process takes it;
                    # the pending SIGABRT is delivered before any of its code runs again
                    child.send_signal(signal.SIGABRT)
                    os.kill(child.pid, signal.SIGCONT)
                    abort_at = now + 1.0
                if abort_at is not None and now > abort_at and child.poll() is None:
                    child.kill()
            if child.poll() is None:  # stopping
                child.send_signal(signal.SIGTERM)
                try:
                    child.wait(5)
                except subprocess.TimeoutExpired:
                    child.kill()
            emit("exit", n=starts, pid=child.pid, code=child.wait())
            if not stopping:
                time.sleep(args.restart_sec)
    finally:
        if child is not None and child.poll() is None:
            child.kill()
        sock.close()
        os.unlink(path)
        os.rmdir(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
