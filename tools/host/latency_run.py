#!/usr/bin/env python3
"""Key-to-sound latency through the live host, frame-timestamp method (LAT-02 "Mode B"; VS-13).

Drives a real rigd on a real audio device with a virtual MIDI keyboard (tools/host/sxkeys) and
pairs, for every press:

  t_send      sxkeys: the host time it handed the note-on to the MIDI system
  t_arrive    rigd's MIDI thread: the host time the note-on arrived (same clock)
  frames      the engine's Method B stamps: key set, period latch, first D/A or gate write,
              onset (output above -50 dBFS after the gate rise, the 47-frame limiter included)
  t_onset     the host time the callback that rendered the onset frame started, plus the
              onset's offset in that buffer (src/host callback clock ring)
  t_out       t_onset + the device's REPORTED output latency (CoreAudio: device + safety +
              stream + IO buffer)

Key to sound = t_out - t_send. Nothing is recorded from a microphone and no audio is written:
the device can be given zeros (--silent-device) because the timing is the device's own either
way. This is Mode B, not the loopback rig (Mode A, LAT-03): on a Mac its output-latency term
is the HAL's report, not a measurement, so the result is indicative only. The station number is
S-1b/S-9 on the station hardware.

    tools/host/latency_run.py --presses 500 --out docs/qa/results/host/latency-mac.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summary(xs: list[float]) -> dict:
    return {
        "n": len(xs),
        "p50": round(pct(xs, 50), 3),
        "p95": round(pct(xs, 95), 3),
        "p99": round(pct(xs, 99), 3),
        "max": round(max(xs), 3) if xs else None,
        "min": round(min(xs), 3) if xs else None,
    }


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="latency_run.py")
    ap.add_argument("--presses", type=int, default=500)
    ap.add_argument("--note", type=int, default=60)
    ap.add_argument("--hold-ms", type=int, default=60)
    ap.add_argument("--gap-min-ms", type=int, default=120)
    ap.add_argument("--gap-max-ms", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261102)
    ap.add_argument("--audio", default="auto", help="auto (the real device) or null")
    ap.add_argument("--device", default="")
    ap.add_argument("--period", type=int, default=128)
    ap.add_argument("--audible", action="store_true", help="play it (default: silent device)")
    ap.add_argument("--preset", help="the patch to measure with (default: rigd's default preset)")
    ap.add_argument("--out", type=Path, help="write the JSON record here")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT / "tests" / "rigd"))
    from conftest import MIDI_PREFIX, Client, Keys  # noqa: PLC0415 (the tests' own drivers)

    tmp = Path(tempfile.mkdtemp(prefix="sx-latency-"))
    lat_log = tmp / "presses.jsonl"
    port = free_port()
    cmd = [sys.executable, "-m", "rigd", "--audio", args.audio, "--port", str(port),
           "--period", str(args.period), "--latency-log", str(lat_log), "--no-ui-mute",
           "--midi-source", MIDI_PREFIX]  # fmt: skip
    if args.preset:
        cmd += ["--preset", args.preset]
    if args.device:
        cmd += ["--device", args.device]
    if not args.audible:
        cmd.append("--silent-device")
    log = open(tmp / "rigd.log", "w")  # noqa: SIM115
    rigd = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            env=dict(os.environ, PYTHONPATH=str(ROOT / "src")))  # fmt: skip
    keys = None
    sends: list[int] = []
    try:
        deadline = time.monotonic() + 10
        while "listening on" not in (tmp / "rigd.log").read_text():
            if time.monotonic() > deadline or rigd.poll() is not None:
                raise SystemExit("rigd did not start:\n" + (tmp / "rigd.log").read_text())
            time.sleep(0.05)
        c = Client(f"ws://127.0.0.1:{port}")
        keys = Keys()
        keys.do("plug", "plug")
        c.until(lambda m: m["t"] == "heartbeat" and m["midi_present"], 10.0)
        lines: queue.Queue = keys.lines
        stop = threading.Event()

        def pump():  # keep the WebSocket drained while the presses run
            while not stop.is_set():
                c.pump(0.2)

        th = threading.Thread(target=pump, daemon=True)
        th.start()
        keys.do(f"presses {args.presses} {args.note} {args.hold_ms} {args.gap_min_ms} "
                f"{args.gap_max_ms} {args.seed}", "presses")  # fmt: skip
        expected_s = args.presses * (args.hold_ms + (args.gap_min_ms + args.gap_max_ms) / 2) / 1e3
        end = time.monotonic() + expected_s * 1.5 + 5
        while len(sends) < args.presses and time.monotonic() < end:
            try:
                m = lines.get(timeout=1.0)
            except queue.Empty:
                continue
            if m.get("t") == "sent" and m.get("kind") == "on":
                sends.append(int(m["host_ns"]))
        time.sleep(0.5)
        stop.set()
        th.join()
        c.close()
    finally:
        if keys:
            keys.close()
        rigd.send_signal(signal.SIGTERM)
        rigd.wait(10)
        log.close()

    rigd_log = (tmp / "rigd.log").read_text()
    presses = [json.loads(x) for x in lat_log.read_text().splitlines()] if lat_log.exists() else []
    rows = []
    for p in presses:
        t_arr = p["midi_on_ns"]
        cands = [s for s in sends if s <= t_arr]
        if not cands or not p["out_host_ns"] or p["midi_note"] != args.note:
            continue
        t_send = max(cands)
        rate = p["rate"]
        rows.append({
            "midi_ms": (t_arr - t_send) / 1e6,
            "arrival_to_latch_ms": (p["latch"] - p["arrival"]) / rate * 1e3,
            "latch_to_write_ms": (p["first_write"] - p["latch"]) / rate * 1e3,
            "write_to_onset_ms": (p["onset"] - p["first_write"]) / rate * 1e3,
            "send_to_onset_handed_ms": (p["onset_host_ns"] - t_send) / 1e6,
            "reported_output_ms": p["output_latency_frames"] / rate * 1e3,
            "key_to_sound_ms": (p["out_host_ns"] - t_send) / 1e6,
        })  # fmt: skip
    if not rows:
        print(rigd_log)
        raise SystemExit("no paired presses")
    first_line = next((ln for ln in rigd_log.splitlines() if "profile" in ln), "")
    record = {
        "what": "key to sound through the live host, LAT-02 Mode B (frame timestamps); "
        "INDICATIVE ONLY on a Mac: the output term is the HAL's reported latency",
        "machine": f"{platform.node().split('.')[0]} {platform.machine()} macOS "
        f"{platform.mac_ver()[0]}"
        if sys.platform == "darwin"
        else platform.platform(),
        "rigd": first_line.removeprefix("rigd: "),
        "silent_device": not args.audible,
        "presses_sent": len(sends),
        "presses_paired": len(rows),
        "settings": {
            k: getattr(args, k)
            for k in ("note", "hold_ms", "gap_min_ms", "gap_max_ms", "seed", "period", "preset")
        },  # fmt: skip
        "key_to_sound_ms": summary([r["key_to_sound_ms"] for r in rows]),
        "components_ms": {
            k: summary([r[k] for r in rows])
            for k in (
                "midi_ms",
                "arrival_to_latch_ms",
                "latch_to_write_ms",
                "write_to_onset_ms",
                "send_to_onset_handed_ms",
                "reported_output_ms",
            )
        },  # fmt: skip
    }
    text = json.dumps(record, indent=1)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
