#!/usr/bin/env python3
"""Is the station playable? The boot-to-playable probe (NFR-3, SYS-01; KP-17).

"Playable" means both halves are up and healthy:

* **page**: ``GET /`` on the page server answers 200 **with our server's own
  Content-Security-Policy** (it names ``ws://127.0.0.1``). An open port alone is not enough: a
  different program squatting on :8080 must never be shown on the glass.
* **engine** (``--check all``): rigd's WebSocket sends ``hello`` and then a ``heartbeat`` with
  ``engine_alive`` and ``audio_ok`` true. That is the state in which the next key sounds.

It polls until both hold or ``--timeout`` runs out, and prints one JSON line::

    {"playable": true, "after_s": 2.4, "uptime_s": 41.0, "budget_s": 90, "within_budget": true}

``uptime_s`` is the time since the machine booted (``/proc/uptime`` on Linux, the boot time on
macOS), so the line written by ``seastones-playable.service`` at every boot is SYS-01's number:
power to playable, minus what the BIOS takes before the kernel starts. ``--log`` appends the
line to a file (``/data/log/boot.jsonl``) so the staff and QA can see every boot's time.

kiosk.sh uses ``--check page --timeout 0`` (one look) to decide when to open the page.

Exit 0 when playable (and, with ``--boot``, within ``--budget``), 1 when not.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

OUR_CSP_MARK = "ws://127.0.0.1"


def uptime_s() -> float | None:
    try:
        return float(open("/proc/uptime").read().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    try:  # macOS: kern.boottime = { sec = 1730000000, usec = 0 } ...
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True,
                             text=True, timeout=2).stdout  # fmt: skip
        sec = int(out.split("sec =")[1].split(",")[0])
        return max(0.0, time.time() - sec)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def page_ok(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            csp = r.headers.get("Content-Security-Policy", "")
            if r.status != 200:
                return False, f"page answered {r.status}"
            if OUR_CSP_MARK not in csp:
                return False, "something answers on the page port, but it is not our page server"
            return True, "page up"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"page not answering ({exc})"


def engine_ok(url: str, wait_s: float) -> tuple[bool, str]:
    try:
        from websockets.sync.client import connect
    except ImportError:
        return False, "python3-websockets is not installed"
    try:
        with connect(url, open_timeout=2, close_timeout=1, max_size=None) as ws:
            end = time.monotonic() + max(wait_s, 1.5)
            hello = False
            while (left := end - time.monotonic()) > 0:
                m = json.loads(ws.recv(timeout=left))
                if m.get("t") == "hello":
                    hello = True
                elif m.get("t") == "heartbeat" and hello:
                    if m.get("engine_alive") and m.get("audio_ok"):
                        return True, "engine up"
                    return False, f"engine not ready (faults: {', '.join(m.get('faults') or [])})"
            return False, "no heartbeat from rigd"
    except (OSError, TimeoutError, ValueError) as exc:
        return False, f"rigd not answering ({exc.__class__.__name__}: {exc})"
    except Exception as exc:  # noqa: BLE001 (websockets' own errors: closed, handshake)
        return False, f"rigd not answering ({exc.__class__.__name__})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="playable.py")
    ap.add_argument("--http", default="http://127.0.0.1:8080/")
    ap.add_argument("--ws", default="ws://127.0.0.1:7690")
    ap.add_argument("--check", choices=("page", "all"), default="all")
    ap.add_argument("--timeout", type=float, default=90.0, help="0: look once")
    ap.add_argument("--budget", type=float, default=90.0, help="SYS-01: power to playable")
    ap.add_argument("--boot", action="store_true", help="fail if uptime is over the budget")
    ap.add_argument("--log", help="append the JSON line here")
    args = ap.parse_args(argv)
    t0 = time.monotonic()
    why = ""
    ok = False
    while True:
        ok, why = page_ok(args.http)
        if ok and args.check == "all":
            ok, why = engine_ok(args.ws, 3.0)
        if ok or time.monotonic() - t0 >= args.timeout:
            break
        time.sleep(0.25)
    up = uptime_s()
    rec = {
        "playable": ok,
        "after_s": round(time.monotonic() - t0, 2),
        "uptime_s": round(up, 1) if up is not None else None,
        "budget_s": args.budget,
        "within_budget": bool(ok and up is not None and up <= args.budget),
        "why": why,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    line = json.dumps(rec)
    print(line, flush=True)
    if args.log:
        with contextlib.suppress(OSError):
            os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
            with open(args.log, "a") as fh:
                fh.write(line + "\n")
    if not ok:
        return 1
    return 1 if args.boot and not rec["within_budget"] else 0


if __name__ == "__main__":
    sys.exit(main())
