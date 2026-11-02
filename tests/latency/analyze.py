#!/usr/bin/env python3
"""Key-contact to onset latency from a two-channel loopback capture (SP-S1A, QA-STRATEGY 4.2).

Method A analysis. One channel carries the key-top foil contact (t0), the other the station's
line-out tap. Per press:

- t0 is the first sample of a rising edge on the contact channel above ``--contact-threshold``
  (absolute, full scale = 1.0), with a refractory period so contact bounce counts once.
- onset is the first sample at or after t0 where the audio channel, rectified and smoothed by a
  causal moving average over 0.25 ms, exceeds -50 dBFS (QA-STRATEGY 4.1). The -30 dBFS figure is
  reported alongside as the sensitivity check.
- a press whose audio is already above threshold at t0 (a previous note still sounding) is marked
  invalid and excluded, and counted.

Reports n, p50, p95, p99, max, a 0.5 ms histogram and a seeded bootstrap 95 % interval on p95 and
p99. The rig's own offset (measured by the rig-only loopback before each session) is subtracted
with ``--rig-offset-ms``. The capture's SHA-256 goes in the record; the capture itself never goes
in git (QA-STRATEGY 13 item 5).

Inputs: a WAV file (PCM 16/24/32-bit or IEEE float 32/64), a ``.npy`` array shaped (frames,
channels) or (channels, frames), or raw interleaved float32 with ``--raw-rate`` and
``--raw-channels``. Only numpy is needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ONSET_DBFS = -50.0
SENSITIVITY_DBFS = -30.0
SMOOTH_MS = 0.25


# --------------------------------------------------------------------------- reading


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Return (frames x channels float64 in [-1, 1], rate). Handles PCM and IEEE float."""
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a RIFF/WAVE file")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos : pos + 4], struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        body = data[pos + 8 : pos + 8 + size]
        if cid == b"fmt ":
            tag, ch, rate, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:  # WAVE_FORMAT_EXTENSIBLE: subformat GUID
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, ch, rate, bits)
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if fmt is None or raw is None:
        raise ValueError(f"{path}: missing fmt or data chunk")
    tag, ch, rate, bits = fmt
    if tag == 3 and bits in (32, 64):
        x = np.frombuffer(raw, dtype="<f4" if bits == 32 else "<f8").astype(np.float64)
    elif tag == 1 and bits == 16:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif tag == 1 and bits == 32:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    elif tag == 1 and bits == 24:
        b = (
            np.frombuffer(raw[: len(raw) - len(raw) % 3], dtype=np.uint8)
            .reshape(-1, 3)
            .astype(np.int32)
        )
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        x = v.astype(np.float64) / 8388608.0
    else:
        raise ValueError(f"{path}: unsupported WAV format tag {tag} with {bits} bits")
    x = x[: len(x) - len(x) % ch]
    return x.reshape(-1, ch), rate


def load_capture(path: Path, raw_rate: int | None, raw_channels: int) -> tuple[np.ndarray, int]:
    if path.suffix.lower() == ".npy":
        if raw_rate is None:
            raise ValueError(".npy input needs --raw-rate")
        a = np.load(path).astype(np.float64)
        if a.ndim != 2:
            raise ValueError(".npy input must be 2-D")
        return (a.T if a.shape[0] < a.shape[1] else a), raw_rate
    if raw_rate is not None:
        a = np.fromfile(path, dtype="<f4").astype(np.float64)
        a = a[: len(a) - len(a) % raw_channels]
        return a.reshape(-1, raw_channels), raw_rate
    return read_wav(path)


# --------------------------------------------------------------------------- analysis


def dbfs_to_amp(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def contact_edges(
    contact: np.ndarray, rate: int, threshold: float = 0.25, refractory_ms: float = 20.0
) -> np.ndarray:
    """Sample indices of rising edges above threshold, one per press (bounce suppressed)."""
    above = np.abs(contact) >= threshold
    rising = np.flatnonzero(above[1:] & ~above[:-1]) + 1
    if above.size and above[0]:
        rising = np.concatenate(([0], rising))
    gap = int(round(refractory_ms * rate / 1000.0))
    out: list[int] = []
    for idx in rising:
        if not out or idx - out[-1] >= gap:
            out.append(int(idx))
    return np.asarray(out, dtype=np.int64)


def smoothed_envelope(audio: np.ndarray, rate: int, smooth_ms: float = SMOOTH_MS) -> np.ndarray:
    """Causal moving average of |x| over smooth_ms (window at least one sample)."""
    w = max(1, int(round(smooth_ms * rate / 1000.0)))
    c = np.cumsum(np.abs(audio), dtype=np.float64)
    env = c.copy()
    env[w:] = c[w:] - c[:-w]
    return env / w


def first_above(env: np.ndarray, start: int, stop: int, level: float) -> int | None:
    seg = env[start:stop]
    hit = np.flatnonzero(seg > level)
    return int(start + hit[0]) if hit.size else None


@dataclass
class Trial:
    t0: int
    onset: int | None
    onset_sens: int | None
    valid: bool
    reason: str = ""


@dataclass
class Result:
    rate: int
    trials: list[Trial] = field(default_factory=list)


def analyze(
    capture: np.ndarray,
    rate: int,
    contact_ch: int = 0,
    audio_ch: int = 1,
    contact_threshold: float = 0.25,
    refractory_ms: float = 20.0,
    max_latency_ms: float = 200.0,
) -> Result:
    contact = capture[:, contact_ch]
    audio = capture[:, audio_ch]
    env = smoothed_envelope(audio, rate)
    lvl = dbfs_to_amp(ONSET_DBFS)
    lvl_s = dbfs_to_amp(SENSITIVITY_DBFS)
    window = int(round(max_latency_ms * rate / 1000.0))
    res = Result(rate=rate)
    for t0 in contact_edges(contact, rate, contact_threshold, refractory_ms):
        t0 = int(t0)
        if env[t0] > lvl:
            res.trials.append(Trial(t0, None, None, False, "audio above -50 dBFS at t0"))
            continue
        on = first_above(env, t0, min(len(env), t0 + window), lvl)
        sens = first_above(env, t0, min(len(env), t0 + window), lvl_s)
        if on is None:
            res.trials.append(
                Trial(t0, None, None, False, f"no onset within {max_latency_ms:g} ms")
            )
            continue
        res.trials.append(Trial(t0, on, sens, True))
    return res


def bootstrap_ci(x: np.ndarray, q: float, n_boot: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    qs = np.percentile(x[idx], q, axis=1)
    return float(np.percentile(qs, 2.5)), float(np.percentile(qs, 97.5))


def summarize(
    lat_ms: np.ndarray, n_boot: int = 2000, seed: int = 1974, hist_bin_ms: float = 0.5
) -> dict[str, object]:
    if lat_ms.size == 0:
        return {"n": 0}
    out: dict[str, object] = {
        "n": int(lat_ms.size),
        "p50_ms": round(float(np.percentile(lat_ms, 50)), 4),
        "p95_ms": round(float(np.percentile(lat_ms, 95)), 4),
        "p99_ms": round(float(np.percentile(lat_ms, 99)), 4),
        "max_ms": round(float(lat_ms.max()), 4),
        "mean_ms": round(float(lat_ms.mean()), 4),
    }
    if lat_ms.size >= 2:
        lo, hi = bootstrap_ci(lat_ms, 95, n_boot, seed)
        out["p95_ci95_ms"] = [round(lo, 4), round(hi, 4)]
        lo, hi = bootstrap_ci(lat_ms, 99, n_boot, seed + 1)
        out["p99_ci95_ms"] = [round(lo, 4), round(hi, 4)]
        out["bootstrap"] = {"resamples": n_boot, "seed": seed}
    edges = np.arange(0.0, float(lat_ms.max()) + hist_bin_ms * 2, hist_bin_ms)
    counts, _ = np.histogram(lat_ms, bins=edges)
    out["histogram"] = {"bin_ms": hist_bin_ms, "counts": [int(c) for c in counts]}
    return out


def report(res: Result, rig_offset_ms: float = 0.0, **kw: object) -> dict[str, object]:
    valid = [t for t in res.trials if t.valid]
    lat = (
        np.array([(t.onset - t.t0) * 1000.0 / res.rate for t in valid], dtype=np.float64)
        - rig_offset_ms
    )
    sens = (
        np.array(
            [(t.onset_sens - t.t0) * 1000.0 / res.rate for t in valid if t.onset_sens is not None],
            dtype=np.float64,
        )
        - rig_offset_ms
    )
    invalid: dict[str, int] = {}
    for t in res.trials:
        if not t.valid:
            invalid[t.reason] = invalid.get(t.reason, 0) + 1
    return {
        "method": "A (loopback rig), onset -50 dBFS, 0.25 ms causal smoothing",
        "rate": res.rate,
        "presses_detected": len(res.trials),
        "invalid": invalid,
        "rig_offset_ms": rig_offset_ms,
        "latency_at_-50dBFS": summarize(lat, **kw),  # type: ignore[arg-type]
        "latency_at_-30dBFS": summarize(sens, **kw),  # type: ignore[arg-type]
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("capture", type=Path)
    ap.add_argument("--contact-ch", type=int, default=0)
    ap.add_argument("--audio-ch", type=int, default=1)
    ap.add_argument("--contact-threshold", type=float, default=0.25)
    ap.add_argument("--refractory-ms", type=float, default=20.0)
    ap.add_argument("--max-latency-ms", type=float, default=200.0)
    ap.add_argument("--rig-offset-ms", type=float, default=0.0)
    ap.add_argument("--raw-rate", type=int)
    ap.add_argument("--raw-channels", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1974)
    ap.add_argument("--p95-max", type=float, help="pass line for p95 (e.g. 25 for S-9, 7 for S-1)")
    ap.add_argument("--p99-max", type=float)
    ap.add_argument("--trials-csv", type=Path, help="write per-press t0, onset and latency")
    args = ap.parse_args(argv)

    cap, rate = load_capture(args.capture, args.raw_rate, args.raw_channels)
    res = analyze(
        cap,
        rate,
        args.contact_ch,
        args.audio_ch,
        args.contact_threshold,
        args.refractory_ms,
        args.max_latency_ms,
    )
    rec = report(res, args.rig_offset_ms, seed=args.seed)
    rec["capture_sha256"] = hashlib.sha256(args.capture.read_bytes()).hexdigest()
    rec["capture_name"] = args.capture.name
    verdict = None
    s = rec["latency_at_-50dBFS"]
    if args.p95_max is not None and isinstance(s, dict) and s.get("n"):
        ok = s["p95_ms"] <= args.p95_max
        if "p95_ci95_ms" in s:
            rec["p95_upper_ci_within_line"] = s["p95_ci95_ms"][1] <= args.p95_max
        if args.p99_max is not None:
            ok = ok and s["p99_ms"] <= args.p99_max
        verdict = "pass" if ok else "fail"
    rec["verdict"] = verdict
    if args.trials_csv:
        with args.trials_csv.open("w") as f:
            f.write("t0_s,onset_s,latency_ms,valid,reason\n")
            for t in res.trials:
                on = "" if t.onset is None else f"{t.onset / rate:.6f}"
                lat = (
                    ""
                    if t.onset is None
                    else f"{(t.onset - t.t0) * 1000.0 / rate - args.rig_offset_ms:.4f}"
                )
                f.write(f"{t.t0 / rate:.6f},{on},{lat},{int(t.valid)},{t.reason}\n")
    json.dump(rec, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if verdict in (None, "pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
