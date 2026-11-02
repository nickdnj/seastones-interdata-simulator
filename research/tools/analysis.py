"""Analysis toolkit for the research notebooks (RS-04, RE-6, RE-7 questions 1 to 3 and 5).

* ``pitch_track``: frame-wise f0 (librosa YIN, parabolic interpolation) in Hz and cents.
* ``detect_steps``: piecewise-constant pitch: plateau levels, step size in cents, the
  smallest step (the likely D/A quantum) and the update rate (RE-7 q2).
* ``onsets`` / ``inter_onset_intervals`` / ``loop_length``: the computer rhythm (RE-7 q3).
* ``zipper``: is a sweep a run of steps (a program-expanded ramp) or smooth (RE-7 q5)?
* ``implied_dac_bits``: what D/A word size a step size would mean, for the ledger's
  inference line, with the assumption written out.

Built and tested only on generated signals (``research/tools/synth.py``). Notebooks run it
locally on Nick's machine; nothing here uploads or writes anything (RE-1, LEGAL-REVIEW 2.3).
Every result is a hypothesis for the ledger, never a fact.

Needs numpy, scipy and librosa (in a local venv; see research/README.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

REF_HZ = 440.0


def _librosa():
    import librosa  # deferred so the light tools import without it

    return librosa


# ---------------------------------------------------------------- pitch


@dataclass
class PitchTrack:
    times: np.ndarray  # seconds, frame centres
    hz: np.ndarray
    cents: np.ndarray  # relative to REF_HZ
    hop_s: float


def _peak_track(y: np.ndarray, sr: int, fmin: float, fmax: float, n: int, hop: int):
    """Strongest spectral peak in [fmin, fmax] per frame, refined by the phase advance of
    that bin over a one-sample lag. For one dominant partial this is far more precise
    than YIN's interpolation (sub-cent on a clean tone), which step-size work needs."""
    y = np.asarray(y, dtype=float)
    frames = 1 + (len(y) - n - 1) // hop
    if frames <= 0:
        return np.array([])
    win = np.hanning(n)
    nfft = 4 * n
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    band = (freqs >= fmin) & (freqs <= fmax)
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    x0 = np.fft.rfft(y[idx] * win, nfft)
    x1 = np.fft.rfft(y[idx + 1] * win, nfft)
    mag = np.where(band[None, :], np.abs(x0), 0.0)
    k = np.argmax(mag, axis=1)
    rows = np.arange(frames)
    adv = np.angle(x1[rows, k] * np.conj(x0[rows, k]))
    hz = np.mod(adv, 2 * np.pi) * sr / (2 * np.pi)
    hz[mag[rows, k] == 0] = np.nan
    return hz


def pitch_track(
    y: np.ndarray,
    sr: int,
    fmin: float = 100.0,
    fmax: float = 2000.0,
    frame_length: int = 1024,
    hop_length: int = 128,
    method: str = "peak",
) -> PitchTrack:
    """Frame-wise pitch. Keep ``frame_length`` shorter than the shortest plateau you hope to
    see, and long enough for ``fmin`` (at least 2 periods).

    ``method="peak"`` (default): the strongest partial in [fmin, fmax], phase-refined. Use
    it on a monophonic stretch with the band set around the fundamental (or one partial).
    ``method="yin"``: librosa's YIN. More robust when the fundamental is weak, but its
    interpolation jitters by several cents, too coarse for D/A step sizes.
    """
    if method == "peak":
        hz = _peak_track(y, sr, fmin, fmax, frame_length, hop_length)
    elif method == "yin":
        hz = _librosa().yin(
            np.asarray(y, dtype=float),
            fmin=fmin,
            fmax=fmax,
            sr=sr,
            frame_length=frame_length,
            hop_length=hop_length,
            center=False,
        )
    else:
        raise ValueError(f"method must be 'peak' or 'yin', not {method!r}")
    times = (np.arange(len(hz)) * hop_length + frame_length / 2) / sr
    cents = 1200.0 * np.log2(hz / REF_HZ)
    return PitchTrack(times=times, hz=hz, cents=cents, hop_s=hop_length / sr)


# ---------------------------------------------------------------- steps


@dataclass
class StepAnalysis:
    plateau_cents: np.ndarray  # level of each plateau
    plateau_times: np.ndarray  # (start, end) seconds of each plateau
    change_times: np.ndarray  # seconds, one per detected change
    steps_cents: np.ndarray  # signed differences between consecutive plateaus
    step_cents: float  # median |step|
    quantum_cents: float  # the unit the |steps| are whole multiples of (one LSB?)
    update_period_s: float  # the unit the change intervals are whole multiples of
    update_hz: float
    threshold_cents: float  # the stability tolerance used
    notes: list[str] = field(default_factory=list)


def _unit(values: np.ndarray, ratio: float = 1.5) -> float:
    """The unit that the values are whole multiples of (one LSB, one update period).

    A step of 2 LSBs, or a missed plateau, doubles a value. Start from the cluster of
    values within ``ratio`` of the 10th percentile, then refine over every value:
    unit = sum(values) / sum(round(values / unit))."""
    v = np.abs(values[np.isfinite(values)])
    v = v[v > 0]
    if len(v) == 0:
        return float("nan")
    base = float(np.percentile(v, 10))
    small = v[v <= ratio * base]
    unit = float(np.median(small)) if len(small) else base
    for _ in range(3):
        k = np.maximum(np.round(v / unit), 1)
        keep = np.abs(v / k - unit) <= 0.15 * unit
        if not np.any(keep):
            break
        unit = float(v[keep].sum() / k[keep].sum())
    return unit


def _crossing(c, t, span_a, span_b, level_a, level_b) -> float:
    """When the track crosses halfway between two plateau levels. The analysis window
    smears a step symmetrically, so the halfway crossing marks the step itself."""
    mid = (level_a + level_b) / 2
    lo, hi = span_a[1], span_b[0]
    sign = np.sign(level_b - level_a)
    for i in range(lo, hi):
        x0, x1 = c[i], c[i + 1]
        if np.isfinite(x0) and np.isfinite(x1) and sign * (x0 - mid) <= 0 < sign * (x1 - mid):
            return float(t[i] + (mid - x0) / (x1 - x0) * (t[i + 1] - t[i]))
    return float((t[lo] + t[hi]) / 2)


def detect_steps(
    track: PitchTrack,
    min_step_cents: float = 0.5,
    tol_k: float = 3.0,
    tol_floor_cents: float = 0.15,
    min_plateau_frames: int = 3,
) -> StepAnalysis:
    """Segment a pitch track into plateaus and measure the steps between them.

    The analysis window smears each step over several frames, so steps are found by their
    plateaus, not by their jumps. A frame is *stable* when it differs from both neighbours
    by less than ``max(tol_k * 20th percentile of the frame changes, tol_floor_cents)``.
    A run of at least ``min_plateau_frames`` stable frames is a plateau (level = median).
    Neighbouring plateaus closer than ``min_step_cents`` are merged (same D/A code). A
    change is timed where the track crosses halfway between two plateau levels.
    """
    c = np.asarray(track.cents, dtype=float)
    d = np.abs(np.diff(c))
    finite = d[np.isfinite(d)]
    notes: list[str] = []
    if len(finite) < 2:
        notes.append("pitch track too short or empty")
        finite = np.array([0.0])
    tol = max(tol_k * float(np.percentile(finite, 20)), tol_floor_cents)
    flat = np.isfinite(d) & (d < tol)
    stable = np.zeros(len(c), dtype=bool)
    stable[1:-1] = flat[:-1] & flat[1:]
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(stable):
        if stable[i]:
            j = i
            while j + 1 < len(stable) and stable[j + 1]:
                j += 1
            if j - i + 1 >= min_plateau_frames:
                runs.append((i, j))
            i = j + 1
        else:
            i += 1

    def merge(min_gap: float) -> tuple[list[float], list[list[int]]]:
        levels: list[float] = []
        spans: list[list[int]] = []
        for a, b in runs:
            level = float(np.median(c[a : b + 1]))
            if levels and abs(level - levels[-1]) < min_gap:
                spans[-1][1] = b  # same level: one plateau broken by noisy frames
                levels[-1] = float(np.median(c[spans[-1][0] : b + 1]))
            else:
                levels.append(level)
                spans.append([a, b])
        return levels, spans

    levels, spans = merge(min_step_cents)
    # Second pass: noise can split one plateau into two a fraction of a step apart.
    # Re-merge anything closer than half the quantum the first pass found.
    q0 = _unit(np.diff(np.array(levels))) if len(levels) > 2 else float("nan")
    if np.isfinite(q0) and q0 / 2 > min_step_cents:
        levels, spans = merge(q0 / 2)
    t = track.times
    plateaus_a = np.array(levels)
    ptimes = np.array([(t[a], t[b]) for a, b in spans])
    change_times = np.array([_crossing(c, t, spans[k], spans[k + 1], levels[k], levels[k + 1])
                             for k in range(len(spans) - 1)])  # fmt: skip
    steps = np.diff(plateaus_a) if len(plateaus_a) > 1 else np.array([])
    if len(plateaus_a) < 3:
        notes.append("fewer than three plateaus: not enough to call this stepped")
    intervals = np.diff(change_times) if len(change_times) > 1 else np.array([])
    period = _unit(intervals)
    return StepAnalysis(
        plateau_cents=plateaus_a,
        plateau_times=ptimes,
        change_times=change_times,
        steps_cents=steps,
        step_cents=float(np.median(np.abs(steps))) if len(steps) else float("nan"),
        quantum_cents=_unit(steps),
        update_period_s=period,
        update_hz=1.0 / period if np.isfinite(period) and period > 0 else float("nan"),
        threshold_cents=tol,
        notes=notes,
    )


def implied_dac_bits(quantum_cents: float, range_v: float, volts_per_octave: float = 1.0) -> float:
    """D/A word size that would give this pitch quantum, ASSUMING a V/oct oscillator, the
    given full-scale range and one LSB per step. Each assumption is an alternative
    explanation for the ledger (a different range or scaling gives a different answer)."""
    lsb_v = quantum_cents / 1200.0 * volts_per_octave
    return float(np.log2(range_v / lsb_v))


# ---------------------------------------------------------------- rhythm


def onsets(y: np.ndarray, sr: int, hop_length: int = 128, backtrack: bool = False) -> np.ndarray:
    """Onset times in seconds (librosa spectral-flux onset detector).

    ``backtrack=False`` (default) reports the flux peak: consistent to one hop on
    generated bursts. Backtracking to the preceding energy minimum moved onsets by up
    to 25 ms in noise, which breaks loop detection."""
    lr = _librosa()
    env = lr.onset.onset_strength(y=np.asarray(y, dtype=float), sr=sr, hop_length=hop_length)
    frames = lr.onset.onset_detect(
        onset_envelope=env, sr=sr, hop_length=hop_length, backtrack=backtrack, units="frames"
    )
    return lr.frames_to_time(frames, sr=sr, hop_length=hop_length)


def inter_onset_intervals(onset_times: np.ndarray) -> np.ndarray:
    return np.diff(np.asarray(onset_times, dtype=float))


@dataclass
class LoopEstimate:
    period_onsets: int  # onsets per loop
    loop_s: float
    pattern_s: np.ndarray  # one loop's inter-onset intervals
    max_error_s: float  # worst mismatch between repeats


def loop_length(
    onset_times: np.ndarray, tolerance_s: float = 0.015, min_repeats: int = 2
) -> LoopEstimate | None:
    """The shortest repeating inter-onset pattern: the smallest p such that interval i
    matches interval i + p (within ``tolerance_s``) for every i, seen at least
    ``min_repeats`` times. Returns None if nothing repeats."""
    ioi = inter_onset_intervals(onset_times)
    n = len(ioi)
    for p in range(1, n // min_repeats + 1):
        err = np.abs(ioi[p:] - ioi[:-p])
        if len(err) and np.all(err <= tolerance_s):
            reps = n // p
            pattern = np.mean(ioi[: reps * p].reshape(reps, p), axis=0)
            return LoopEstimate(p, float(pattern.sum()), pattern, float(err.max()))
    return None


# ---------------------------------------------------------------- zipper


@dataclass
class ZipperResult:
    is_zipper: bool
    jump_fraction: float  # share of the total pitch movement carried by jump frames
    n_steps: int
    step_cents: float
    total_cents: float


def zipper(
    track: PitchTrack, jump_k: float = 5.0, min_steps: int = 3, threshold: float = 0.8
) -> ZipperResult:
    """Stepped or smooth? In a zipper most frames are flat and a few carry all the
    movement; in a smooth glide every frame moves a little. A frame is a jump when its
    change exceeds ``jump_k`` times the median change."""
    c = np.asarray(track.cents, dtype=float)
    d = np.abs(np.diff(c[np.isfinite(c)]))
    total = float(d.sum())
    if total == 0:
        return ZipperResult(False, 0.0, 0, float("nan"), 0.0)
    med = float(np.median(d))
    jumps = d > max(jump_k * med, 1e-6)
    frac = float(d[jumps].sum() / total)
    # Count steps as groups of consecutive jump frames.
    n_steps = int(np.sum(jumps[1:] & ~jumps[:-1]) + (1 if jumps[0] else 0))
    span = float(abs(np.nanmedian(c[-5:]) - np.nanmedian(c[:5])))
    return ZipperResult(
        is_zipper=frac >= threshold and n_steps >= min_steps,
        jump_fraction=frac,
        n_steps=n_steps,
        step_cents=span / n_steps if n_steps else float("nan"),
        total_cents=span,
    )
