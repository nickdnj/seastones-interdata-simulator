#!/usr/bin/env python3
"""Watchdog layer 2: the page is running but has stopped painting (ARCHITECTURE 10; SYS-06).

The page POSTs ``/heartbeat`` every 10 s and the page server rewrites ``<run>/page-heartbeat``.
A wedged page looks alive from outside (the browser process is still there), so this checks
that the heartbeat keeps CHANGING. Run every 30 s (seastones-watchdog.timer on Linux, the
local.seastones.watchdog launchd job on macOS); when the heartbeat has not changed for
``HEARTBEAT_STALE_S`` it runs ``restart-browser.sh`` and the browser's loop opens a fresh page.

Ported from the Model 4 kiosk's ``watchdog.sh``, with one change found by the clock-jump check
(SOK-08): staleness is measured on the **monotonic** clock (``time.monotonic()``, the same
clock in every process since boot), never as ``now - mtime`` on the wall clock. A wall-clock
jump forward (a dead RTC corrected by staff, a DST change done by hand) would otherwise look
like a stale page and black out the screen for nothing; a jump back would hide a real hang.

State lives in ``<run>/watchdog.state`` (JSON): the last heartbeat seen, when it was first
seen (monotonic), and the last restart (for the cooldown, so a slow first paint never becomes
a kill loop). Values from a previous boot (larger than now) are discarded.

    deploy/watchdog.py --run /run/seastones --conf /opt/seastones/deploy/station.conf \\
        --restart /opt/seastones/deploy/restart-browser.sh [--log /data/log/kiosk.log]

Exit 0 always unless the arguments are wrong (a timer job that fails would only add noise).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time


def read_conf(path: str | None) -> dict[str, str]:
    """NAME=value lines of station.conf, read without a shell."""
    out: dict[str, str] = {}
    if not path:
        return out
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def token(path: str) -> str | None:
    """What the heartbeat file says right now; None if it is not there."""
    try:
        st = os.stat(path)
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return None
    return f"{st.st_mtime_ns}:{st.st_size}:{head.hex()}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="watchdog.py")
    ap.add_argument("--run", required=True, help="the page server's --run folder")
    ap.add_argument("--conf", help="station.conf (HEARTBEAT_STALE_S, WATCHDOG_*)")
    ap.add_argument("--restart", required=True, help="the command that restarts the browser")
    ap.add_argument("--log", help="append one line per action")
    ap.add_argument("--now", type=float, help="tests: the monotonic time to act at")
    args = ap.parse_args(argv)
    conf = read_conf(args.conf)
    stale_s = float(conf.get("HEARTBEAT_STALE_S", 60))
    cooldown_s = float(conf.get("WATCHDOG_COOLDOWN_S", 120))
    grace_s = float(conf.get("WATCHDOG_BOOT_GRACE_S", 180))
    now = time.monotonic() if args.now is None else args.now
    hb = os.path.join(args.run, "page-heartbeat")
    state_path = os.path.join(args.run, "watchdog.state")

    def log(text: str) -> None:
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} watchdog: {text}\n"
        if args.log:
            with contextlib.suppress(OSError), open(args.log, "a") as fh:
                fh.write(line)
        else:
            sys.stdout.write(line)

    try:
        state = json.load(open(state_path))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    for k in ("seen", "kill"):  # from a previous boot: monotonic time started again
        if not isinstance(state.get(k), (int, float)) or state[k] > now:
            state.pop(k, None)

    def save(action: str) -> int:
        state["action"] = action
        with contextlib.suppress(OSError):
            os.makedirs(args.run, exist_ok=True)
            tmp = state_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(state, fh)
            os.replace(tmp, state_path)
        return 0

    tok = token(hb)
    if tok != state.get("token") or "seen" not in state:
        state["token"], state["seen"] = tok, now
        return save("fresh" if tok else "waiting")
    if "kill" in state and now - state["kill"] < cooldown_s:
        return save("cooldown")
    if tok is None and now < grace_s:
        return save("boot-grace")  # monotonic time is time since boot
    age = now - state["seen"]
    if age <= stale_s:
        return save("ok")
    what = "has not changed" if tok else "has never appeared"
    log(
        f"the page heartbeat {what} for {age:.0f} s (limit {stale_s:.0f} s): restarting the browser"
    )
    state["kill"] = now
    state["seen"] = now  # judge the new page from now on
    save("restart")
    try:
        subprocess.run([args.restart], timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"could not run {args.restart}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
