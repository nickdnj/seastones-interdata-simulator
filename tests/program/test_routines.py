"""The program's clocked routines, picked by the switch register (rig.s): computer rhythm,
stepped voltages, arpeggio. Original material in the spirit of a 1974 computer-controlled
synthesizer (SEA-4), not derived from any recording. Device-level tests on the engine clock
(cycle table ESTIMATE), keyed to the interval clock X'6C' that the routines keep time by.

Timing: the interval clock is SIMH's PIC, which schedules each tick from the moment the last
one was serviced, at an instruction boundary; in emulated cycles that runs about 0.15 % slow.
Step times are checked to 2 ms plus 0.3 % (DRIFT): a 125 ms step is 125.2 ms.

Switch register: switches 8-11 the routine (0 play, 1 rhythm, 2 steps, 3 arpeggio), 12-15 the
variant (bits 12-13: pattern, direction or step size; 14-15: speed), 4-7 the transposition.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from progtools import BASENOTE, MS, Voices, assemble, clocked, engine_ok, pitch  # noqa: E402

pytestmark = [pytest.mark.lockstep, pytest.mark.skipif(not engine_ok(), reason="engine not built")]

M = "all-da-4"
TEMPO = [125, 100, 160, 200]
DRIFT = 0.003


def near(t: float, want: float) -> bool:
    return abs(t - want) <= 2 + DRIFT * want


STEPSZ = [16, 64, 256, 1024]
UPD = [4, 15, 60, 250]


def sr(routine: int, variant: int = 0, transpose: int = 0) -> int:
    return (transpose & 0xF) << 8 | routine << 4 | variant


def notes(writes: list[tuple], m: str = M) -> list[tuple[float, int, int]]:
    """(ms, voice, pitch code) for every gate rise, with the pitch the voice held then."""
    v = Voices(m)
    last_pitch: dict[int, int] = {}
    on = [0] * v.n
    out = []
    for f, dev, ch, val in writes:
        if dev == 0x21 and ch in v.pitch_ch:
            last_pitch[v.pitch_ch.index(ch)] = val
        if dev == 0x21 and ch in v.gate:
            i = v.gate.index(ch)
            if val >= 0x4000 and not on[i]:
                out.append((f / MS, i, last_pitch.get(i, -1)))
            on[i] = 1 if val >= 0x4000 else 0
    return out


def gate_offs(writes: list[tuple], m: str = M) -> list[tuple[float, int]]:
    v = Voices(m)
    return [(f / MS, v.gate.index(ch)) for f, dev, ch, val in writes
            if dev == 0x21 and ch in v.gate and val == 0]  # fmt: skip


def lane(writes: list[tuple], ch: int) -> list[tuple[float, int]]:
    return [(f / MS, val) for f, dev, c, val in writes if dev == 0x21 and c == ch]


PATTERNS: list[list[tuple[int | None, int, bool]]] = []


def _patterns() -> list[list[tuple[int | None, int, bool]]]:
    """The four patterns, read back from the assembled image (offset, length ms, accent)."""
    if PATTERNS:
        return PATTERNS
    a, _ = assemble(M)
    base = a.symbols["PATTERNS"]
    words = {}
    for ln in a.lines:
        for i, w in enumerate(ln.words):
            words[ln.addr + 2 * i] = w
    for p in range(4):
        steps = []
        for s in range(16):
            w = words[base + 32 * p + 2 * s]
            off, lb = w >> 8, w & 0xFF
            steps.append((None if off == 0x80 else (off - 256 if off > 0x80 else off),
                          (lb & 0x7F) * 4, bool(lb & 0x80)))  # fmt: skip
        PATTERNS.append(steps)
    return PATTERNS


@pytest.mark.parametrize("variant", [0, 1, 2, 3, 6])
def test_rhythm_plays_its_pattern_from_the_lowest_key(variant: int) -> None:
    """Hold keys 12 and 20: every TEMPO ms the next step plays (rests skip), its note the lowest
    key plus the step's interval, round-robin over the voices, each for its own length; the
    cutoff lane jumps on accents. Let go and it stops; the next key starts it at once."""
    _, out = assemble(M)
    tempo = TEMPO[variant >> 2]
    pat = _patterns()[variant & 3]
    v = Voices(M)
    w = clocked(out, [("frames", 480), ("keys", (1 << 12) | (1 << 20)), ("frames", int(2.5 * 16 * tempo * MS))]
                + [("keys", 0), ("frames", int(600 * MS))], sr=sr(1, variant))  # fmt: skip
    got = notes(w)
    t0 = got[0][0]
    assert 10 <= t0 <= 11.5, f"the first step plays at once on the key (key at 10 ms): {t0}"
    expect = []
    for k in range(40):
        step = pat[k % 16]
        if step[0] is not None:
            expect.append((k * tempo, pitch(BASENOTE + 12 + step[0])))
    played = [(round(t - t0), code) for t, _v, code in got]
    n = min(len(played), len(expect))
    assert n >= 15
    for (pt, pc), (et, ec) in zip(played[:n], expect[:n], strict=True):
        assert pc == ec and near(pt, et), (played[:n], expect[:n])
    assert [vv for _t, vv, _c in got[: v.n * 2]] == [i % v.n for i in range(v.n * 2)]
    end = (480 + int(2.5 * 16 * tempo * MS)) / MS
    assert all(t <= end + 1 for t, _v, _c in got), "nothing plays after the keys come up"
    offs = gate_offs(w)
    assert offs and max(t for t, _ in offs) <= end + 260
    cut = lane(w, v.lanes["cutoff"])
    accents = sum(1 for k in range(n) if pat[k % 16][0] is not None and pat[k % 16][2])
    assert sum(1 for _t, val in cut if val == 0x5000) >= min(accents, 1)


def test_rhythm_gate_lengths_follow_the_pattern() -> None:
    _, out = assemble(M)
    pat = _patterns()[0]
    w = clocked(out, [("frames", 480), ("keys", 1 << 5), ("frames", int(2100 * MS))], sr=sr(1, 0))
    ons = notes(w)
    offs = gate_offs(w)
    played = [s for s in pat if s[0] is not None]
    for k, (t, voice, _c) in enumerate(ons[:8]):
        stop = next(o for o, vv in offs if vv == voice and o > t)
        assert abs((stop - t) - played[k % len(played)][1]) <= 2.5, (k, stop - t)


@pytest.mark.parametrize("variant", [0, 1, 2, 3, 8, 15])
def test_steps_move_the_lanes_by_the_step_size_at_the_update_rate(variant: int) -> None:
    """Stepped voltages: every UPD ms the cutoff lane moves by STEPSZ codes, bouncing between
    X'1000' and X'7000'; the detune lane does the same between 0 and X'0400'. The converter's
    word (12 bits here) then decides what is heard: a 16-code step is one 12-bit LSB."""
    _, out = assemble(M)
    v = Voices(M)
    step, upd = STEPSZ[variant & 3], UPD[variant >> 2]
    span = max(40 * upd, 600)
    w = clocked(out, [("frames", 480), ("frames", int(span * MS))], sr=sr(2, variant))
    cut = [(t, val) for t, val in lane(w, v.lanes["cutoff"]) if t > 5]
    assert len(cut) >= 4
    deltas = {abs(b[1] - a[1]) for a, b in zip(cut, cut[1:], strict=False)}
    assert deltas <= {step, 0} | {abs(0x7000 - 0x1000) % step}, deltas
    gaps = [round(b[0] - a[0]) for a, b in zip(cut, cut[1:], strict=False)]
    assert all(abs(g - upd) <= 1 + DRIFT * upd for g in gaps), gaps
    assert all(0x1000 <= val <= 0x7000 for _t, val in cut)
    det = [val for t, val in lane(w, v.lanes["detune"]) if t > 5]
    assert all(0 <= val <= 0x0400 for val in det)
    if step <= 256:
        assert max(det) - min(det) >= min(0x400, step * 8)


def test_steps_still_play_the_keys() -> None:
    _, out = assemble(M)
    w = clocked(out, [("frames", 480), ("keys", 1 << 9), ("frames", 960)], sr=sr(2, 8))
    got = notes(w)
    assert got and got[0][2] == pitch(BASENOTE + 9)


@pytest.mark.parametrize(
    "variant,order",
    [
        (0, [0, 4, 7, 0, 4, 7, 0]),  # up
        (1, [7, 4, 0, 7, 4, 0, 7]),  # down
        (2, [0, 4, 7, 4, 0, 4, 7]),  # up and down
        (3, [0, 4, 7, 12, 16, 19, 0]),  # up over two octaves (+12 the second time)
    ],
)
def test_arpeggio_plays_the_chord_in_order(variant: int, order: list[int]) -> None:
    _, out = assemble(M)
    tempo = TEMPO[variant >> 2]
    base = 10
    keys = (1 << base) | (1 << (base + 4)) | (1 << (base + 7))
    w = clocked(out, [("frames", 480), ("keys", keys), ("frames", int(7.5 * tempo * MS))],
                sr=sr(3, variant))  # fmt: skip
    got = notes(w)
    assert len(got) >= 7
    assert [c for _t, _v, c in got[:7]] == [pitch(BASENOTE + base + k) for k in order]
    times = [t - got[0][0] for t, _v, _c in got[:7]]
    assert all(near(t, k * tempo) for k, t in enumerate(times)), times
    assert got[0][0] <= 11.5, "the first note sounds at once"


def test_arpeggio_follows_the_keys_held() -> None:
    """Adding a key joins the cycle; letting go of all stops it; a new chord starts at once."""
    _, out = assemble(M)
    w = clocked(out, [("frames", 480), ("keys", 1 << 3 | 1 << 8), ("frames", int(520 * MS)),
                      ("keys", 1 << 3 | 1 << 8 | 1 << 15), ("frames", int(700 * MS)),
                      ("keys", 0), ("frames", int(500 * MS)), ("keys", 1 << 20),
                      ("frames", int(300 * MS))], sr=sr(3, 0))  # fmt: skip
    got = notes(w)
    codes = [c for _t, _v, c in got]
    assert pitch(BASENOTE + 15) in codes[4:]
    late = [t for t, _v, c in got if c == pitch(BASENOTE + 20)]
    assert late and abs(late[0] - (480 + 520 * 48 + 700 * 48 + 500 * 48) / MS) <= 1.5
    silent = [t for t, _v, _c in got if 10 + 1220 + 100 < t < 10 + 1720]
    assert not silent, "nothing plays while no key is held"


def test_switches_4_to_7_transpose() -> None:
    """Switches 4-7 transpose the keyboard: 0-7 up, 8-15 down 8 to down 1."""
    _, out = assemble(M)
    w = clocked(out, [("frames", 480), ("keys", 1 << 12), ("frames", 960)], sr=sr(0, 0, 3))
    assert notes(w)[0][2] == pitch(BASENOTE + 12 + 3)
    w = clocked(out, [("frames", 480), ("keys", 1 << 12), ("frames", 960)], sr=sr(0, 0, -2))
    assert notes(w)[0][2] == pitch(BASENOTE + 12 - 2)


@pytest.mark.parametrize("routine,variant", [(1, 2), (2, 0), (3, 1), (3, 3)])
def test_every_pass_is_short_in_the_routines(routine: int, variant: int) -> None:
    """ADR-009 P in the clocked routines too: no pass longer than 0.5 ms, with keys held, notes
    starting and stopping, and the lanes stepping. The one pass in which the operator's switches
    change (silence, then the routine's settings) is reported apart and held to 1.0 ms: it is an
    operator action, like HOME, not something the keys or the clock can cause."""
    from progtools import L, load_ops

    a, out = assemble(M)
    ops = [("raw_engine", "cycles 250")] + load_ops(out["rig.dep.sim"])
    ops += [("reg", "SR", sr(routine, variant))]
    loop = a.symbols["LOOP"]
    sched = [("period", 3000), ("keys", (1 << 3) | (1 << 9) | (1 << 14) | (1 << 30)),
             ("period", 400000), ("keys", (1 << 37) - 1), ("period", 100000), ("keys", 0),
             ("period", 100000)]  # fmt: skip
    for op in sched:
        ops.append(op if op[0] == "keys" else ("raw_engine", f"period {loop:X} {op[1]}"))
    windows = [int(ln.split()[7]) for ln in L.run_engine(ops).splitlines()
               if ln.startswith("period ")]  # fmt: skip
    switch, worst = windows[0], max(windows[1:])
    print(f"routine {routine} variant {variant}: longest pass {worst * 0.25:.1f} us, the switch "
          f"change's pass {switch * 0.25:.1f} us (ESTIMATE)")  # fmt: skip
    assert worst * 0.25 <= 500
    assert switch * 0.25 <= 1000
