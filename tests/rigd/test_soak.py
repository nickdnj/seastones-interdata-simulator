"""Soak (NFR-6, NFR-8, KP-16's software form): a rigd under random visitor, MIDI, patch and staff
traffic, with an engine fault every ~20 s, must stay bounded and fail silent every time.

`make ci` runs 20 s; the 10-minute run is `SX_SOAK_S=600 pytest -s tests/rigd/test_soak.py`
(`make host-soak`). Seeded (SX_SOAK_SEED). Asserted:
* every injected fault (three NaNs: dsp_fault) is silent from 100 ms after it until rigd's
  recovery HOME, and the rig plays again afterwards (FLT-11, FLT-12);
* resident memory grows by under 25 MB and open file descriptors by under 8 between the first
  quarter and the end; the engine-internal key-to-write p95 stays at or under 1.0 ms; the
  audio thread never stalls (audio_ok throughout);
* no stuck note: once every key is let go and the machine is HOMEd, no voice holds a note and
  the output falls silent (NFR-8);
* every server message validates against the schema.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from conftest import Keys, sounding

DURATION = float(os.environ.get("SX_SOAK_S", "20"))
SEED = int(os.environ.get("SX_SOAK_SEED", "20261102"))
RATE = 48000
FLOOR = ["stadium-drone", "two-voice-duet", "bell", "sweep", "four-voices", "computer-rhythm",
         "slow-steps", "big-steps", "arpeggio"]  # fmt: skip
SPEEDS = ["run", "run", "run", "div30", "div300", "crawl", "step"]


def rss_kb(pid: int) -> int:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


def fds(pid: int) -> int:
    proc = Path(f"/proc/{pid}/fd")
    if proc.exists():
        return len(list(proc.iterdir()))
    out = subprocess.run(["lsof", "-p", str(pid)], capture_output=True, text=True)
    return max(0, len(out.stdout.splitlines()) - 1)


def test_soak(rigd_factory, client_factory, tmp_path):
    (tmp_path / "pin").write_text("4826\n")
    lat_log = tmp_path / "presses.jsonl"
    r = rigd_factory("--test-hooks", "--staff-pin-file", str(tmp_path / "pin"),
                     "--latency-log", str(lat_log), capture=True)  # fmt: skip
    keys = None
    try:
        keys = Keys()
        keys.do("plug", "plug")
    except Exception:  # noqa: BLE001 (no MIDI system here: touch traffic only)
        keys = None
    c = client_factory(r.url)
    c.until(lambda m: m["t"] == "state")
    rng = random.Random(SEED)
    print(f"\nsoak: {DURATION:.0f} s, seed {SEED}, MIDI {'on' if keys else 'off'}")
    t0 = time.monotonic()
    baseline = None
    faults = []
    held_midi: set[int] = set()
    next_fault = t0 + 8.0
    actions = 0
    while time.monotonic() - t0 < DURATION:
        now = time.monotonic()
        if baseline is None and now - t0 > DURATION / 4:
            baseline = (rss_kb(r.proc.pid), fds(r.proc.pid))
        if now >= next_fault:
            # a quiet moment, then three NaNs: dsp_fault; it must be silent and recover
            c.command({"t": "machine.speed", "position": "run"})
            c.touch(1 << rng.randrange(37))
            c.until(sounding, 3.0)
            c.pump(0.3)
            mark = c.mark()
            for _ in range(2):
                c.command({"t": "test.inject", "what": "nan"})
                c.pump(0.02)
            f_ref = c.last("state")["frames"]
            c.command({"t": "test.inject", "what": "nan"})
            c.until(lambda m: m["t"] == "fault" and m["code"] == "dsp_fault"
                    and not m.get("cleared"), 3.0, mark)  # fmt: skip
            c.until(lambda m: m["t"] == "fault" and m["code"] == "dsp_fault"
                    and m.get("cleared"), 5.0, mark)  # fmt: skip
            c.pump(0.2)
            f_clear = c.last("state")["frames"]
            faults.append((f_ref, f_clear))
            c.touch(0)
            next_fault = time.monotonic() + 20.0
            continue
        k = rng.random()
        if k < 0.35:
            c.touch(sum(1 << rng.randrange(37) for _ in range(rng.randint(0, 4))))
        elif k < 0.55 and keys:
            note = 48 + rng.randrange(37)
            if note in held_midi:
                keys.do(f"off {note}")
                held_midi.discard(note)
            else:
                keys.do(f"on {note}")
                held_midi.add(note)
        elif k < 0.62:
            c.command({"t": "patch.load", "slug": rng.choice(FLOOR)})
        elif k < 0.72:
            p = c.last("patch")
            if p and p["cables"]:
                x = rng.choice(p["cables"])
                if (
                    c.command({"t": "patch.disconnect", "from": x["from"], "to": x["to"]})["t"]
                    == "ack"
                ):
                    c.command({"t": "patch.connect", "from": x["from"], "to": x["to"]})
        elif k < 0.78:
            c.command({"t": "machine.speed", "position": rng.choice(SPEEDS)})
            if rng.random() < 0.5:
                c.command({"t": "machine.step"})
        elif k < 0.82:
            c.command({"t": "machine.home"})
        elif k < 0.86:
            c.command({"t": "staff.auth", "pin": rng.choice(["4826", "4826", "0000"])})
            c.command({"t": "staff.ceiling", "dba": rng.randint(60, 78)})
            c.command({"t": "staff.close"})
        else:
            c.pump(rng.uniform(0.01, 0.08))
        actions += 1
        hb = c.last("heartbeat")
        if hb:
            assert hb["audio_ok"], "the audio thread never stalls"
    end_rss, end_fds = rss_kb(r.proc.pid), fds(r.proc.pid)
    # let everything go, HOME, and listen for a stuck note
    if keys:
        for note in held_midi:
            keys.do(f"off {note}")
        keys.do("cc 123 0")
    c.touch(0)
    c.command({"t": "staff.auth", "pin": "4826"})
    c.command({"t": "staff.mute", "on": False})
    c.command({"t": "machine.speed", "position": "run"})
    c.command({"t": "patch.load", "slug": "four-voices"})
    c.command({"t": "machine.home"})
    c.pump(2.0)
    st = c.last("state")
    assert not sounding(st) and not any(st["keys_raw"]), "no stuck note"
    tail = r.at_frames(st["frames"] - RATE // 2, st["frames"])
    assert len(tail) and np.max(np.abs(tail)) < 1e-3, "the output is silent with no key held"
    # latency after the soak, at RUN: 20 single presses, each written within L1 (1.0 ms, ADR-009)
    probe_from = len(lat_log.read_text().splitlines()) if lat_log.exists() else 0
    for _ in range(20):
        c.touch(1 << rng.randrange(37))
        c.pump(0.08)
        c.touch(0)
        c.pump(0.12)
    probe = [json.loads(x) for x in lat_log.read_text().splitlines()[probe_from:]]
    lat = [(x["first_write"] - x["latch"]) / x["rate"] * 1000 for x in probe]
    worst_lat = max(lat) if lat else float("inf")
    # fail-silent, every time (a fault cycle takes about a second beyond its 20 s gap)
    loudest = []
    for f_ref, f_clear in faults:
        quiet = r.at_frames(f_ref + RATE // 10, f_clear - RATE // 10)
        loudest.append(float(np.max(np.abs(quiet))) if len(quiet) else float("nan"))
    assert baseline is not None
    grew_mb = (end_rss - baseline[0]) / 1024
    print(f"soak: {actions} actions, {len(faults)} faults (loudest after a fault "
          f"{max(loudest):.1e}), RSS {baseline[0] / 1024:.0f} -> {end_rss / 1024:.0f} MB, fds "
          f"{baseline[1]} -> {end_fds}, worst key-to-write {worst_lat:.2f} ms ({len(lat)} presses)")  # fmt: skip
    assert len(faults) >= max(1, int((DURATION - 8) // 21))
    assert all(x < 1e-4 for x in loudest), ("not silent after a fault", loudest)
    assert grew_mb < 25, f"memory grew {grew_mb:.1f} MB"
    assert end_fds - baseline[1] < 8, "file descriptors leak"
    assert len(lat) >= 15 and worst_lat <= 1.0, "key latched to first write, at RUN (L1)"
    assert r.proc.poll() is None
    assert not c.invalid
    if keys:
        keys.close()
    print(sys.version.split()[0])
