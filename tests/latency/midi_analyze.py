#!/usr/bin/env python3
"""Key contact to MIDI event latency, and unplug notice time (SP-S2A, for S-2b on the bench).

Two clocks meet here. Key contacts are sample times on the QA measurement interface (seconds,
from ``analyze.py``'s contact detection or ``--trials-csv``). MIDI events are host monotonic
times in ns from ``sxmidi listen``. ``sxmidi listen --sync`` writes a byte to the rig's Pico at
logged host times, and the Pico pulses a spare capture channel; those pulses are the sync
points. A least-squares line maps host ns onto capture seconds (offset plus drift), and the
fit residual is reported so a bad sync is visible.

Then each contact is paired with the first note-on after it within ``--window-ms``. Unpaired
contacts (missed notes) and unpaired note-ons (extra or doubled notes) are counted, not
dropped quietly.

Unplug: the capture time at which the hub cut power (``--unplug-capture-s``, from the hub's
logged switch time or a capture channel) against the host time of the ``source_removed`` line.

Usage:
    midi_analyze.py --contacts contacts.txt --sync-capture sync.txt --events listen.jsonl
                    [--window-ms 50] [--unplug-capture-s 12.345]
``contacts.txt`` and ``sync.txt`` are one time in seconds per line. ``--same-clock`` skips the
fit when both are already on one clock (unit tests, or a host-side contact sensor).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import summarize  # noqa: E402


def fit_clock(host_ns: np.ndarray, capture_s: np.ndarray) -> tuple[float, float, float]:
    """capture_s ~= a + b * host_s. Returns (a, b, max residual in ms)."""
    if len(host_ns) != len(capture_s) or len(host_ns) < 2:
        raise ValueError(
            f"need >= 2 paired sync points, got {len(host_ns)} host and {len(capture_s)} capture"
        )
    h = host_ns.astype(np.float64) / 1e9
    h0 = h[0]
    b, a = np.polyfit(h - h0, capture_s, 1)
    resid = capture_s - (a + b * (h - h0))
    return float(a - b * h0), float(b), float(np.max(np.abs(resid)) * 1000.0)


def pair(
    contacts_s: np.ndarray, events_s: np.ndarray, window_ms: float
) -> tuple[np.ndarray, int, int]:
    """Return (latencies ms, unpaired contacts, unpaired events)."""
    ev = np.sort(events_s)
    used = np.zeros(len(ev), dtype=bool)
    lat: list[float] = []
    missed = 0
    for c in np.sort(contacts_s):
        i = int(np.searchsorted(ev, c, side="left"))
        while i < len(ev) and used[i]:
            i += 1
        if i < len(ev) and (ev[i] - c) * 1000.0 <= window_ms:
            used[i] = True
            lat.append((ev[i] - c) * 1000.0)
        else:
            missed += 1
    return np.asarray(lat), missed, int((~used).sum())


def load_events(path: Path) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """(note-on host ns, sync host ns, source_removed host ns) from sxmidi listen output."""
    on, sync, removed = [], [], []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("type") == "note_on":
            on.append(e["host_ns"])
        elif e.get("type") == "sync":
            sync.append(e["host_ns"])
        elif e.get("type") == "source_removed":
            removed.append(e["host_ns"])
    return np.asarray(on, dtype=np.int64), np.asarray(sync, dtype=np.int64), removed


def analyze_midi(
    contacts_s: np.ndarray,
    note_on_ns: np.ndarray,
    sync_host_ns: np.ndarray | None,
    sync_capture_s: np.ndarray | None,
    window_ms: float = 50.0,
    removed_ns: list[int] | None = None,
    unplug_capture_s: float | None = None,
    seed: int = 1974,
) -> dict[str, object]:
    rec: dict[str, object] = {"method": "key contact (capture clock) to MIDI note-on (host clock)"}
    if sync_host_ns is None:
        a, b, resid = 0.0, 1.0, 0.0
        rec["clock"] = "same clock (no fit)"
    else:
        assert sync_capture_s is not None
        a, b, resid = fit_clock(sync_host_ns, sync_capture_s)
        rec["clock"] = {
            "offset_s": a,
            "rate": b,
            "drift_ppm": (b - 1.0) * 1e6,
            "max_residual_ms": resid,
        }
    ev_s = a + b * (note_on_ns.astype(np.float64) / 1e9)
    lat, missed, extra = pair(contacts_s, ev_s, window_ms)
    rec["contacts"] = int(len(contacts_s))
    rec["note_ons"] = int(len(note_on_ns))
    rec["unpaired_contacts"] = missed
    rec["unpaired_note_ons"] = extra
    rec["latency"] = summarize(lat, seed=seed)
    if unplug_capture_s is not None:
        if removed_ns:
            t = a + b * (removed_ns[0] / 1e9)
            rec["unplug_notice_ms"] = round((t - unplug_capture_s) * 1000.0, 3)
        else:
            rec["unplug_notice_ms"] = None
            rec["unplug_error"] = "no source_removed event in the log"
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--contacts", type=Path, required=True)
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--sync-capture", type=Path)
    ap.add_argument("--same-clock", action="store_true")
    ap.add_argument("--window-ms", type=float, default=50.0)
    ap.add_argument("--unplug-capture-s", type=float)
    ap.add_argument("--p95-max", type=float, help="S-2 line: 4 ms")
    ap.add_argument("--unplug-max-ms", type=float, help="S-2 line: 20 ms")
    args = ap.parse_args(argv)
    contacts = np.loadtxt(args.contacts, ndmin=1)
    on, sync, removed = load_events(args.events)
    if args.same_clock:
        sh, sc = None, None
    else:
        if args.sync_capture is None:
            ap.error("--sync-capture is required unless --same-clock")
        sh, sc = sync, np.loadtxt(args.sync_capture, ndmin=1)
    rec = analyze_midi(contacts, on, sh, sc, args.window_ms, removed, args.unplug_capture_s)
    ok = True
    lat = rec["latency"]
    if args.p95_max is not None and isinstance(lat, dict):
        ok = ok and bool(lat.get("n")) and lat["p95_ms"] <= args.p95_max
    if args.unplug_max_ms is not None:
        u = rec.get("unplug_notice_ms")
        ok = ok and u is not None and u <= args.unplug_max_ms
    if args.p95_max is not None or args.unplug_max_ms is not None:
        rec["verdict"] = "pass" if ok else "fail"
    json.dump(rec, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
