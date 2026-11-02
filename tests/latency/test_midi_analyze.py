"""Unit tests for tests/latency/midi_analyze.py on synthetic data (SP-S2A acceptance 3).

Synthetic contacts and note-ons are generated from seeds: a host clock with an offset and a
50 ppm drift against the capture clock, a known 3 ms latency with jitter, a dropped note, a
doubled note, and an unplug.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import midi_analyze as ma  # noqa: E402

SEED = 1974
OFFSET_S = 123456.789  # host clock reads this much more than the capture clock
DRIFT = 50e-6


def host_ns(capture_s: np.ndarray) -> np.ndarray:
    """Capture-clock seconds to host-clock ns, with offset and drift."""
    return np.round((capture_s * (1.0 + DRIFT) + OFFSET_S) * 1e9).astype(np.int64)


def make(n: int = 400, lat_ms: float = 3.0, jitter_ms: float = 0.8, seed: int = SEED):
    rng = np.random.default_rng(seed)
    contacts = 1.0 + np.cumsum(rng.uniform(0.15, 0.2, n))
    lat = lat_ms + rng.uniform(0, jitter_ms, n)
    on_capture = contacts + lat / 1000.0
    sync_capture = np.arange(0.5, contacts[-1] + 1.0, 1.0)
    return contacts, lat, host_ns(on_capture), host_ns(sync_capture), sync_capture


def test_clock_fit_recovers_drift_and_latency() -> None:
    contacts, lat, on_ns, sync_ns, sync_cap = make()
    rec = ma.analyze_midi(contacts, on_ns, sync_ns, sync_cap, seed=SEED)
    assert abs(rec["clock"]["drift_ppm"] + 50.0) < 1.0  # host runs fast, so the map's rate is < 1
    assert rec["clock"]["max_residual_ms"] < 0.01
    s = rec["latency"]
    assert s["n"] == 400 and rec["unpaired_contacts"] == 0 and rec["unpaired_note_ons"] == 0
    for q in (50, 95, 99):
        assert abs(s[f"p{q}_ms"] - np.percentile(lat, q)) < 0.01


def test_missed_and_doubled_notes_are_counted() -> None:
    contacts, _, on_ns, sync_ns, sync_cap = make(n=100)
    on_ns = np.delete(on_ns, 10)  # a press with no note-on
    on_ns = np.append(on_ns, on_ns[20] + 1_000_000)  # a doubled note-on 1 ms later
    rec = ma.analyze_midi(contacts, on_ns, sync_ns, sync_cap)
    assert rec["unpaired_contacts"] == 1
    assert rec["unpaired_note_ons"] == 1
    assert rec["latency"]["n"] == 99


def test_event_outside_window_is_not_paired() -> None:
    contacts = np.array([1.0, 2.0])
    on = np.array([int(1.0e9 + 60e6), int(2.0e9 + 3e6)])  # 60 ms late, then 3 ms
    rec = ma.analyze_midi(contacts, on, None, None, window_ms=50.0)
    assert rec["unpaired_contacts"] == 1 and rec["latency"]["n"] == 1
    assert abs(rec["latency"]["p50_ms"] - 3.0) < 1e-6


def test_unplug_notice_time() -> None:
    contacts, _, on_ns, sync_ns, sync_cap = make(n=50)
    unplug_at = 20.0
    removed = [int(host_ns(np.array([unplug_at + 0.0123]))[0])]
    rec = ma.analyze_midi(
        contacts, on_ns, sync_ns, sync_cap, removed_ns=removed, unplug_capture_s=unplug_at
    )
    assert abs(rec["unplug_notice_ms"] - 12.3) < 0.01


def test_unplug_without_notice_is_an_error_not_a_zero() -> None:
    rec = ma.analyze_midi(
        np.array([1.0]), np.array([1_003_000_000]), None, None, removed_ns=[], unplug_capture_s=5.0
    )
    assert rec["unplug_notice_ms"] is None and "unplug_error" in rec


def test_fit_needs_paired_sync_points() -> None:
    with pytest.raises(ValueError):
        ma.fit_clock(np.array([1, 2, 3]), np.array([0.1, 0.2]))


def test_cli_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    contacts, _, on_ns, sync_ns, sync_cap = make(n=200)
    removed = int(host_ns(np.array([40.008]))[0])
    lines = [json.dumps({"type": "sync", "host_ns": int(t)}) for t in sync_ns]
    lines += [
        json.dumps(
            {"type": "note_on", "note": 60, "velocity": 90, "host_ns": int(t), "driver_ns": 0}
        )
        for t in on_ns
    ]
    lines.append(json.dumps({"type": "source_removed", "host_ns": removed}))
    (tmp_path / "listen.jsonl").write_text("\n".join(lines) + "\n")
    np.savetxt(tmp_path / "contacts.txt", contacts)
    np.savetxt(tmp_path / "sync.txt", sync_cap)
    rc = ma.main(
        [
            "--contacts",
            str(tmp_path / "contacts.txt"),
            "--events",
            str(tmp_path / "listen.jsonl"),
            "--sync-capture",
            str(tmp_path / "sync.txt"),
            "--unplug-capture-s",
            "40.0",
            "--p95-max",
            "4",
            "--unplug-max-ms",
            "20",
        ]
    )
    rec = json.loads(capsys.readouterr().out)
    assert rc == 0 and rec["verdict"] == "pass"
    assert abs(rec["unplug_notice_ms"] - 8.0) < 0.01
