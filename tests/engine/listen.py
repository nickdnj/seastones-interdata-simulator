"""Listen-quality analysis for offline renders (PM-09, PO-11): no person listens overnight, so
these numbers stand in for an ear until the DES-3 listening gate (PM-17).

Reads the float32 stereo WAV that sx-render writes (outside the work tree, or under build/), and
measures what an engineer would check first:

    peak_dbfs      the largest sample; under the -3 dBFS soft-clip knee means the safety chain
                   never had to touch the sound (headroom under the limiter)
    dc_dbfs        the mean, per channel: DC offset
    rms windows    loudness over time (the envelope), in 10 ms windows
    f0             the fundamental of a window: FFT peak with parabolic interpolation, checked
                   against autocorrelation
    hf_ratio_db    energy above 16 kHz relative to all of it (aliasing would show here)
    jumps          the largest one-millisecond rise and fall of the peak envelope, in dB: an
                   instant cut or start (a click) is a big jump in one millisecond
    correlation    between left and right (1: mono)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RATE = 48000


def read_wav(path: Path) -> np.ndarray:
    """(frames, 2) float64 from sx-render's IEEE-float stereo WAV."""
    b = path.read_bytes()
    assert b[:4] == b"RIFF" and b[8:16] == b"WAVEfmt "
    fmt, ch, rate = struct.unpack("<HHI", b[20:28])
    assert fmt == 3 and ch == 2 and rate == RATE, (fmt, ch, rate)
    n = struct.unpack("<I", b[40:44])[0]
    return np.frombuffer(b[44 : 44 + n], dtype="<f4").astype(np.float64).reshape(-1, 2)


def db(x: float) -> float:
    return 20.0 * np.log10(max(float(x), 1e-12))


@dataclass
class Report:
    peak_dbfs: float
    dc_dbfs: float
    finite: bool
    correlation: float


def report(x: np.ndarray) -> Report:
    finite = bool(np.all(np.isfinite(x)))
    peak = float(np.max(np.abs(x))) if finite else float("inf")
    dc = float(np.max(np.abs(np.mean(x, axis=0))))
    if np.std(x[:, 0]) > 0 and np.std(x[:, 1]) > 0:
        corr = float(np.corrcoef(x[:, 0], x[:, 1])[0, 1])
    else:
        corr = 1.0
    return Report(db(peak), db(dc), finite, corr)


def rms_db(x: np.ndarray, t0: float, t1: float) -> float:
    a, b = int(t0 * RATE), int(t1 * RATE)
    seg = x[a:b]
    return db(float(np.sqrt(np.mean(seg**2)))) if len(seg) else -240.0


def envelope_db(mono: np.ndarray, win: int = 48) -> np.ndarray:
    """Peak of each 1 ms window, in dB."""
    n = len(mono) // win
    pk = np.max(np.abs(mono[: n * win].reshape(n, win)), axis=1)
    return 20.0 * np.log10(np.maximum(pk, 1e-9))


def jumps(mono: np.ndarray, floor_db: float = -60.0) -> tuple[float, float]:
    """The largest rise and fall of the 1 ms peak envelope between neighbouring windows, in dB,
    counting only windows above `floor_db` (below it a jump is inaudible)."""
    e = envelope_db(mono)
    d = np.diff(e)
    loud = np.maximum(e[1:], e[:-1]) > floor_db
    if not np.any(loud):
        return 0.0, 0.0
    return float(np.max(d[loud])), float(-np.min(d[loud]))


def f0(mono: np.ndarray, t0: float, t1: float) -> float:
    """The fundamental of a held note between t0 and t1 seconds: the autocorrelation's first
    major peak, refined by parabolic interpolation (good to well under a cent here)."""
    a, b = int(t0 * RATE), int(t1 * RATE)
    seg = mono[a:b] - np.mean(mono[a:b])
    n = 1 << int(np.ceil(np.log2(2 * len(seg))))
    spec = np.fft.rfft(seg, n)
    ac = np.fft.irfft(np.abs(spec) ** 2, n)[: len(seg)]
    ac /= ac[0] if ac[0] else 1.0
    lo = int(RATE / 2000)  # nothing above 2 kHz is a fundamental here
    k = lo + int(np.argmax(ac[lo : int(RATE / 30)]))
    # the first peak close to the maximum (avoid octave errors)
    for j in range(lo + 1, k):
        if ac[j] > 0.9 * ac[k] and ac[j] >= ac[j - 1] and ac[j] >= ac[j + 1]:
            k = j
            break
    y0, y1, y2 = ac[k - 1], ac[k], ac[k + 1]
    den = y0 - 2 * y1 + y2
    frac = 0.5 * (y0 - y2) / den if den else 0.0
    return RATE / (k + frac)


def hf_ratio_db(mono: np.ndarray, t0: float, t1: float, f_lo: float = 16000.0) -> float:
    a, b = int(t0 * RATE), int(t1 * RATE)
    seg = mono[a:b] * np.hanning(b - a)
    p = np.abs(np.fft.rfft(seg)) ** 2
    f = np.fft.rfftfreq(len(seg), 1 / RATE)
    tot = float(np.sum(p[f > 20]))
    return 10.0 * np.log10(max(float(np.sum(p[f >= f_lo])), 1e-30) / max(tot, 1e-30))


def cents(f: float, want: float) -> float:
    return 1200.0 * float(np.log2(f / want))


def note_hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def lpc_residual(x: np.ndarray, order: int = 16, block: int = 960) -> np.ndarray:
    """The forward linear-prediction residual, coefficients refit every block (autocorrelation
    method, Levinson-Durbin). A band-limited synth is predicted almost exactly; a click is not."""
    e = np.zeros_like(x)
    for b0 in range(order, len(x) - block, block):
        seg = x[b0 - order : b0 + block]
        w = seg * np.hanning(len(seg))
        r = np.array([np.dot(w[: len(w) - k], w[k:]) for k in range(order + 1)])
        if r[0] < 1e-18:
            continue
        r[0] *= 1.0 + 1e-9
        a = np.zeros(order + 1)
        a[0], err = 1.0, r[0]
        for i in range(1, order + 1):  # Levinson-Durbin
            k = -(r[i] + np.dot(a[1:i], r[i - 1 : 0 : -1])) / err
            a[1 : i + 1] = a[1 : i + 1] + k * np.concatenate((a[i - 1 : 0 : -1], [1.0]))
            err *= 1.0 - k * k
        cur = x[b0 - order : b0 + block]
        pred = np.convolve(cur, a)[order : order + block]
        e[b0 : b0 + block] = pred
    return e


def event_clicks(mono: np.ndarray, event_frames: list[int], k: float = 4.0,
                 floor_db: float = -50.0, rel_db: float = -32.0,
                 latency: int = 47) -> list[float]:  # fmt: skip
    """Clicks at the program's writes (a gate, a pitch, a lane step: the only moments a click
    could come from). For each write, the linear-prediction residual peak in the 2.5 ms after it
    reaches the output (the safety chain's latency later) must stand out three ways to count:
    above floor_db; k times above the residual's own level in the 20 ms before and after (a
    band-limited note, even a sawtooth's edges, is there all the time); and within rel_db of the
    sound's own peak there (a note starting from silence leaves a residual far below itself; a
    discontinuity leaves one close to its own size)."""
    e = np.abs(lpc_residual(mono))
    w = 120  # 2.5 ms
    out = []
    for f in sorted(set(event_frames)):
        a = f + latency
        if a < 4 * w or a + 5 * w >= len(e):
            continue
        here = float(np.max(e[a : a + w]))
        before = float(np.median([np.max(e[a - j * w : a - (j - 1) * w]) for j in range(2, 9)]))
        after = float(np.median([np.max(e[a + j * w : a + (j + 1) * w]) for j in range(2, 9)]))
        sound = float(np.max(np.abs(mono[a - 4 * w : a + 5 * w])))
        if (here > 10 ** (floor_db / 20.0) and here > k * max(before, after, 1e-9)
                and here > sound * 10 ** (rel_db / 20.0)):  # fmt: skip
            out.append(a / RATE)
    return out


def trace_frames(path: Path) -> list[int]:
    """The frames of every D/A and gate write in a seastones.trace/1 file."""
    out = []
    for ln in path.read_text().splitlines():
        if ln and not ln.startswith("#"):
            out.append(int(ln.split()[0]))
    return out


def clicks(mono: np.ndarray, k: float = 12.0, floor_db: float = -60.0) -> list[float]:
    """Times (s) of clicks: linear-prediction residual samples more than k times the block's
    robust residual level and above floor_db. Returns the start of each block that has one."""
    e = lpc_residual(mono)
    out = []
    block = 960
    for b0 in range(0, len(e) - block, block):
        seg = e[b0 : b0 + block]
        sigma = 1.4826 * np.median(np.abs(seg)) + 1e-12
        pk = float(np.max(np.abs(seg)))
        if pk > 10 ** (floor_db / 20.0) and pk > k * sigma:
            out.append(b0 / RATE)
    return out
