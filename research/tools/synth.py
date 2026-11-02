"""Synthetic test signals for the analysis toolkit (RS-04). Generated, never recorded.

Every generator is deterministic for a given seed and returns ``(signal, truth)``: the
float32 samples in [-1, 1] and a dict of the parameters the analysis should recover. The
toolkit is built and tested only on these signals; no real audio is ever needed to
develop or test it (RE-1, LEGAL-REVIEW 2.3).

Needs numpy.
"""

from __future__ import annotations

import numpy as np

SR = 44_100


def dac_step_cents(bits: int = 12, range_v: float = 10.24, volts_per_octave: float = 1.0) -> float:
    """The pitch step of one D/A LSB on a V/oct oscillator: 1200 * (range / 2^bits) / V_oct.

    The default 12-bit word over 10.24 V (ARCHITECTURE 6.3) gives 3.0 cents.
    """
    return 1200.0 * (range_v / 2**bits) / volts_per_octave


def _noise(n: int, snr_db: float | None, seed: int) -> np.ndarray:
    if snr_db is None:
        return np.zeros(n)
    rng = np.random.default_rng(seed)
    # A unit-amplitude sine has power 0.5.
    sigma = np.sqrt(0.5 / 10 ** (snr_db / 10))
    return rng.normal(0.0, sigma, n)


def _render_pitch(f_inst: np.ndarray, sr: int, amp: float, snr_db: float | None, seed: int):
    phase = 2 * np.pi * np.cumsum(f_inst) / sr
    y = np.sin(phase) + _noise(len(f_inst), snr_db, seed)
    return (amp * y / max(1.0, float(np.max(np.abs(y))))).astype(np.float32)


def stepped_sine(
    f0: float = 440.0,
    step_cents: float = 3.0,
    update_hz: float = 25.0,
    duration: float = 4.0,
    codes_per_update: int | list[int] = 1,
    sr: int = SR,
    snr_db: float | None = 40.0,
    seed: int = 1,
    amp: float = 0.5,
):
    """A sine whose pitch moves in quantised steps at a fixed update rate.

    Models a voice whose pitch CV comes from a D/A that the program rewrites
    ``update_hz`` times a second. ``codes_per_update`` is how many LSBs the code moves each
    update (an int, or a list cycled through; negative values step down).
    """
    n = int(round(duration * sr))
    t = np.arange(n) / sr
    k = np.floor(t * update_hz).astype(int)
    moves = np.atleast_1d(np.asarray(codes_per_update, dtype=int))
    code = np.concatenate([[0], np.cumsum(np.resize(moves, k.max()))])[k]
    f = f0 * 2 ** (code * step_cents / 1200.0)
    truth = {
        "step_cents": step_cents,
        "update_hz": update_hz,
        "update_period_s": 1.0 / update_hz,
        "f0": f0,
        "n_updates": int(k.max()),
        "seed": seed,
    }
    return _render_pitch(f, sr, amp, snr_db, seed), truth


def glide(
    f0: float = 330.0,
    cents: float = 1200.0,
    duration: float = 2.0,
    steps: int | None = None,
    sr: int = SR,
    snr_db: float | None = 40.0,
    seed: int = 2,
    amp: float = 0.5,
):
    """A pitch sweep of ``cents`` over ``duration``: smooth if ``steps`` is None, else a
    zipper of ``steps`` equal jumps (what a program-expanded ramp sounds like, ADR-004)."""
    n = int(round(duration * sr))
    frac = np.arange(n) / n
    if steps is not None:
        frac = np.floor(frac * steps) / steps
    f = f0 * 2 ** (frac * cents / 1200.0)
    truth = {"cents": cents, "steps": steps, "zipper": steps is not None, "seed": seed}
    return _render_pitch(f, sr, amp, snr_db, seed), truth


def rhythm_loop(
    pattern_ms: list[float] | tuple[float, ...] = (250, 125, 125, 250, 500),
    repeats: int = 4,
    burst_ms: float = 30.0,
    freq: float = 880.0,
    sr: int = SR,
    snr_db: float | None = 40.0,
    seed: int = 3,
    jitter_ms: float = 0.0,
):
    """Short decaying tone bursts on a repeating inter-onset pattern (a "computer rhythm").

    ``pattern_ms`` is one loop's inter-onset intervals; the loop length is their sum.
    ``jitter_ms`` adds seeded uniform timing jitter to each onset.
    """
    rng = np.random.default_rng(seed)
    iois = np.tile(np.asarray(pattern_ms, dtype=float), repeats)
    onsets_ms = np.concatenate([[100.0], 100.0 + np.cumsum(iois)[:-1]])
    if jitter_ms:
        onsets_ms = onsets_ms + rng.uniform(-jitter_ms, jitter_ms, len(onsets_ms))
    total = int((onsets_ms[-1] + pattern_ms[-1] + 200) * sr / 1000)
    y = np.zeros(total)
    nb = int(burst_ms * sr / 1000)
    tb = np.arange(nb) / sr
    burst = np.sin(2 * np.pi * freq * tb) * np.exp(-tb / (burst_ms / 4000))
    for o in onsets_ms:
        i = int(round(o * sr / 1000))
        y[i : i + nb] += burst[: max(0, min(nb, total - i))]
    y = y + _noise(total, snr_db, seed + 1000) * 0.2
    y = 0.5 * y / np.max(np.abs(y))
    truth = {
        "onsets_s": (onsets_ms / 1000).tolist(),
        "pattern_ms": list(pattern_ms),
        "loop_ms": float(sum(pattern_ms)),
        "repeats": repeats,
        "seed": seed,
    }
    return y.astype(np.float32), truth
