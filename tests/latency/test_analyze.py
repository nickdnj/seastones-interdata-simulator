"""Tests for tests/latency/analyze.py (SP-S1A acceptance: recover 17.0 ms within 0.1 ms).

All captures are generated at run time from seeds (synth.py); temporary WAVs go to pytest's
tmp_path and are never committed.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze  # noqa: E402
from synth import make_capture  # noqa: E402

SEED = 1974


def latencies(cap: np.ndarray, rate: int) -> np.ndarray:
    res = analyze.analyze(cap, rate)
    return np.array([(t.onset - t.t0) * 1000.0 / rate for t in res.trials if t.valid])


@pytest.mark.parametrize("rate", [48000, 96000])
def test_recovers_known_17ms_delay_within_0_1ms(rate: int) -> None:
    cap, t0, _ = make_capture(rate=rate, presses=40, delay_ms=17.0, seed=SEED)
    lat = latencies(cap, rate)
    assert lat.size == 40, "every press detected once despite contact bounce"
    assert np.all(np.abs(lat - 17.0) <= 0.1), f"max error {np.max(np.abs(lat - 17.0)):.4f} ms"


def test_soft_attack_counts_time_to_threshold() -> None:
    # By definition (QA-STRATEGY 4.1) onset is the -50 dBFS crossing, so a 2 ms ramp from a sine
    # zero-crossing is reported a little after the true start (about 0.15 ms at -12 dBFS): the
    # attack is part of the budget, not an error to correct for.
    cap, _, _ = make_capture(rate=96000, presses=20, delay_ms=17.0, attack_ms=2.0, seed=SEED)
    lat = latencies(cap, 96000)
    assert np.all((lat > 17.0) & (lat < 17.3))
    assert np.ptp(lat) < 0.02


def test_distribution_percentiles_match_truth() -> None:
    rng = np.random.default_rng(SEED)
    truth = 10.0 + rng.gamma(2.0, 2.0, size=600)
    cap, _, d = make_capture(rate=96000, presses=600, delay_ms=truth, spacing_ms=260.0, seed=SEED)
    lat = latencies(cap, 96000)
    assert lat.size == 600
    for q in (50, 95, 99):
        assert abs(np.percentile(lat, q) - np.percentile(d, q)) < 0.1
    s = analyze.summarize(lat, seed=SEED)
    lo, hi = s["p95_ci95_ms"]
    assert lo <= s["p95_ms"] <= hi


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    x = np.random.default_rng(3).normal(15, 2, 500)
    assert analyze.summarize(x, seed=7) == analyze.summarize(x, seed=7)


def test_press_with_audio_already_sounding_is_invalid() -> None:
    cap, t0, _ = make_capture(
        rate=48000,
        presses=5,
        delay_ms=17.0,
        tone_ms=400.0,
        spacing_ms=300.0,
        spacing_jitter_ms=0.0,
        seed=SEED,
    )
    res = analyze.analyze(cap, 48000)
    reasons = [t.reason for t in res.trials if not t.valid]
    assert reasons and all("above -50 dBFS at t0" in r for r in reasons)


def test_missing_onset_is_reported_not_guessed() -> None:
    cap, _, _ = make_capture(rate=48000, presses=3, delay_ms=17.0, seed=SEED)
    cap[:, 1] = np.random.default_rng(0).normal(0, 1e-4, len(cap))  # -80 dBFS noise only
    res = analyze.analyze(cap, 48000)
    assert all(not t.valid and "no onset" in t.reason for t in res.trials)


def test_rig_offset_is_subtracted() -> None:
    cap, _, _ = make_capture(rate=96000, presses=10, delay_ms=17.0, seed=SEED)
    rec = analyze.report(analyze.analyze(cap, 96000), rig_offset_ms=1.5, seed=SEED)
    assert abs(rec["latency_at_-50dBFS"]["p50_ms"] - 15.5) <= 0.1


def write_wav(path: Path, cap: np.ndarray, rate: int, kind: str) -> None:
    ch = cap.shape[1]
    if kind == "float32":
        body, tag, bits = cap.astype("<f4").tobytes(), 3, 32
    elif kind == "pcm16":
        body, tag, bits = (
            np.clip(np.round(cap * 32767), -32768, 32767).astype("<i2").tobytes(),
            1,
            16,
        )
    else:  # pcm24
        v = np.clip(np.round(cap * 8388607), -8388608, 8388607).astype(np.int32).reshape(-1)
        b = np.stack([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF], axis=1).astype(np.uint8)
        body, tag, bits = b.tobytes(), 1, 24
    fmt = struct.pack("<HHIIHH", tag, ch, rate, rate * ch * bits // 8, ch * bits // 8, bits)
    data = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(body))
        + body
    )
    path.write_bytes(b"RIFF" + struct.pack("<I", len(data)) + data)


@pytest.mark.parametrize("kind", ["float32", "pcm16", "pcm24"])
def test_cli_on_generated_wav(
    tmp_path: Path, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    cap, _, _ = make_capture(rate=48000, presses=12, delay_ms=17.0, noise_dbfs=-70.0, seed=SEED)
    wav = tmp_path / f"synthetic-{kind}.wav"
    write_wav(wav, cap, 48000, kind)
    rc = analyze.main([str(wav), "--p95-max", "25", "--p99-max", "40"])
    rec = json.loads(capsys.readouterr().out)
    assert rc == 0 and rec["verdict"] == "pass"
    s = rec["latency_at_-50dBFS"]
    assert s["n"] == 12 and abs(s["p50_ms"] - 17.0) <= 0.1
    assert len(rec["capture_sha256"]) == 64


def test_cli_fails_the_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cap, _, _ = make_capture(rate=48000, presses=12, delay_ms=30.0, seed=SEED)
    wav = tmp_path / "late.wav"
    write_wav(wav, cap, 48000, "float32")
    assert analyze.main([str(wav), "--p95-max", "25"]) == 1
    assert json.loads(capsys.readouterr().out)["verdict"] == "fail"
