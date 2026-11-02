"""Synthetic loopback captures for the latency analysis tests (SP-S1A, SP-S2A).

Generated at test time from a seed; nothing here is a recording and nothing is written to the repo
(QA-STRATEGY 13 items 1 and 2). Fixture tied to NFR-1 / LAT-03.
"""

from __future__ import annotations

import numpy as np


def make_capture(
    rate: int = 96000,
    presses: int = 50,
    delay_ms: float | np.ndarray = 17.0,
    spacing_ms: float = 300.0,
    spacing_jitter_ms: float = 50.0,
    tone_hz: float = 1000.0,
    tone_dbfs: float = -12.0,
    tone_ms: float = 120.0,
    attack_ms: float = 0.0,
    noise_dbfs: float = -80.0,
    bounce: bool = True,
    seed: int = 1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (capture frames x 2, t0 sample indices, true delay in ms per press).

    Channel 0 is the key-top contact (0.5 FS while closed, with contact bounce), channel 1 the
    line-out tap: noise at noise_dbfs plus a tone starting delay_ms after each t0, at its crest
    when attack_ms is 0 (like sxlat) or with a linear attack ramp otherwise.
    """
    rng = np.random.default_rng(seed)
    delays = np.broadcast_to(np.asarray(delay_ms, dtype=np.float64), (presses,)).copy()
    gaps = spacing_ms + rng.uniform(0.0, spacing_jitter_ms, size=presses)
    t0_ms = 50.0 + np.concatenate(([0.0], np.cumsum(gaps[:-1])))
    total = int((t0_ms[-1] + delays[-1] + tone_ms + 100.0) * rate / 1000.0)
    cap = np.zeros((total, 2), dtype=np.float64)
    noise_rms = 10.0 ** (noise_dbfs / 20.0)
    cap[:, 1] = rng.normal(0.0, noise_rms, size=total)
    amp = 10.0 ** (tone_dbfs / 20.0)
    t0_idx = np.round(t0_ms * rate / 1000.0).astype(np.int64)
    hold = int(30.0 * rate / 1000.0)
    tone_n = int(tone_ms * rate / 1000.0)
    n = np.arange(tone_n)
    tone = amp * np.cos(2.0 * np.pi * tone_hz * n / rate)
    if attack_ms > 0:
        ramp = np.minimum(1.0, n / (attack_ms * rate / 1000.0))
        tone = amp * np.sin(2.0 * np.pi * tone_hz * n / rate) * ramp
    for t0, d in zip(t0_idx, delays, strict=True):
        cap[t0 : t0 + hold, 0] = 0.5
        if bounce:
            b = max(1, int(0.2 * rate / 1000.0))
            cap[t0 + b : t0 + 2 * b, 0] = 0.0
        start = t0 + int(round(d * rate / 1000.0))
        cap[start : start + tone_n, 1] += tone[: max(0, min(tone_n, total - start))]
    return cap, t0_idx, delays
