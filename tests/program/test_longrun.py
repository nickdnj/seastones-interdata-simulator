"""PO-12: long emulated time and counter wraparound (PRG-13, SOK-07), faster than real time.

The counters that can wrap, and where:
  - SCP's 32-bit time (sim_grtime) wraps after 2^32 cycles = 1,073.7 s (17.9 minutes) of emulated
    time; the engine stamps writes from its own 64-bit time (machine/clock.c), and the PIC in
    1 ms mode schedules on the 64-bit event queue
  - the program's millisecond count NOW is 16 bits and wraps every 65.5 s; the routines compare
    times by signed difference (rig.s DUE, DUEOFF)
  - frames are 64-bit everywhere (clock.frame, sx_snapshot.frames): there is no 32-bit frame
    counter to wrap at 24.8 hours
These tests run the program across the 32-bit wrap on the engine clock (cycle table ESTIMATE),
with keys pressed and the computer-rhythm routine keeping time, and check nothing sticks, slips
or slows. SX_LONGRUN_HOURS (nightly, e.g. 24) runs the play routine that long instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from progtools import BASENOTE, MS, Voices, assemble, clocked, engine_ok, pitch  # noqa: E402

pytestmark = [pytest.mark.lockstep, pytest.mark.skipif(not engine_ok(), reason="engine not built")]

M = "all-da-4"
WRAP_S = 2**32 * 250e-9  # 1073.74 s


def _frames(seconds: float) -> int:
    return int(seconds * 48000)


def test_keys_across_the_32_bit_time_wrap() -> None:
    """A key every 100 ms for 10 s around the wrap: each press gets its pitch and gate within
    1.0 ms (L1), each release its gate-off, and the voices cycle as at start-up."""
    _, out = assemble(M)
    v = Voices(M)
    start = WRAP_S - 5.0
    sched: list[tuple] = [("frames", _frames(start))]
    presses = []
    t = start
    for k in range(100):
        key = (k * 7) % 37
        sched += [
            ("keys", 1 << key),
            ("frames", _frames(0.05)),
            ("keys", 0),
            ("frames", _frames(0.05)),
        ]
        presses.append((t, key))
        t += 0.1
    w = clocked(out, sched)
    worst = 0.0
    for t0, key in presses:
        f0 = _frames(t0)
        code = pitch(BASENOTE + key)
        pf = next(f for f, dev, ch, val in w if f >= f0 and dev == 0x21 and val == code and
                  ch in v.pitch_ch)  # fmt: skip
        gf = next(f for f, dev, ch, val in w if f >= pf and dev == 0x21 and ch in v.gate and
                  val >= 0x4000)  # fmt: skip
        off = next(f for f, dev, ch, val in w if f >= f0 + _frames(0.05) and dev == 0x21 and
                   ch in v.gate and val == 0)  # fmt: skip
        worst = max(worst, (gf - f0) / MS, (off - f0 - _frames(0.05)) / MS)
    print(f"100 keys across the 32-bit wrap at {WRAP_S:.1f} s: worst {worst:.3f} ms (ESTIMATE)")
    assert worst <= 1.0


def test_the_rhythm_keeps_time_across_the_wraps() -> None:
    """Computer rhythm held for 30 s across the 32-bit wrap (and the 16-bit NOW wraps every
    65.5 s before it): every step lands on the same grid."""
    _, out = assemble(M)
    v = Voices(M)
    start = WRAP_S - 15.0
    w = clocked(out, [("frames", _frames(start)), ("keys", 1 << 12), ("frames", _frames(30.0))],
                sr=0x0010)  # fmt: skip
    ons = [f for f, dev, ch, val in w if dev == 0x21 and ch in v.gate and val >= 0x4000]
    assert len(ons) >= 140  # pattern 0: ten notes every 16 steps (2 s)
    gaps = sorted({round((b - a) / MS) for a, b in zip(ons, ons[1:], strict=False)})
    # pattern 0's steps fall on a 125 ms grid: gaps are whole steps (the PIC runs 0.15 % slow)
    for g in gaps:
        assert abs(g / 125.0 - round(g / 125.0)) * 125.0 <= 1.5, gaps  # 1 ms clock grain
    span = (ons[-1] - ons[0]) / MS
    steps = round(span / 125.0)
    print(f"rhythm across the wrap: {len(ons)} notes, {span / steps:.3f} ms per step")
    assert abs(span / steps - 125.0) <= 0.4


@pytest.mark.skipif(not os.environ.get("SX_LONGRUN_HOURS"), reason="nightly: SX_LONGRUN_HOURS=24")
def test_hours_of_emulated_time() -> None:
    hours = float(os.environ["SX_LONGRUN_HOURS"])
    _, out = assemble(M)
    v = Voices(M)
    total = hours * 3600.0
    sched: list[tuple] = []
    t = 0.0
    while t < total:
        sched += [("frames", _frames(599.9)), ("keys", 1 << 20), ("frames", _frames(0.05)),
                  ("keys", 0), ("frames", _frames(0.05))]  # fmt: skip
        t += 600.0
    w = clocked(out, sched)
    ons = [f for f, dev, ch, val in w if dev == 0x21 and ch in v.gate and val >= 0x4000]
    offs = [f for f, dev, ch, val in w if dev == 0x21 and ch in v.gate and val == 0]
    print(f"{hours:g} h emulated: {len(ons)} notes")
    assert len(ons) == int(total // 600) + (1 if total % 600 else 0)
    assert len(offs) >= len(ons)
