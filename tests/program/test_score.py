"""VS-21 acceptance (MACH-8; PRG-11): the score player in the 7/16 program.

A score from research/scores/ (original and synthetic only: Layer 6 stays off) is compiled by
sxscore.compile, deposited at X'2000' as a tape, and played by the program with switches 0-3 at
1 (the score alone) or 2 (the score and the keyboard). The D/A and gate writes are compared with
a trace computed independently from the score text: every event's writes within 1.5 ms of its
time (a pass plus the 1 ms clock grain), loops included. Engine clock, cycle table ESTIMATE.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from progtools import (  # noqa: E402
    BASENOTE,
    GATE_HI,
    MS,
    RATE,
    ROOT,
    L,
    Voices,
    assemble,
    engine_ok,
    load_ops,
    pitch,
)
from sxscore import parse  # noqa: E402
from sxscore.compile import compile_file  # noqa: E402

pytestmark = [pytest.mark.lockstep, pytest.mark.skipif(not engine_ok(), reason="engine not built")]

M = "all-da-4"
SCORES = ROOT / "research" / "scores"
DRIFT = 0.003  # the PIC's 0.15 % in emulated cycles, doubled


def run(words: list[int], sched: list[tuple], sr: int, gen: int = 1) -> list[tuple]:
    """Deposit the tape, set the switches, run `sched` (("frames", n) / ("keys", bits) /
    ("raw", cmd)) on the engine clock; returns (ms, dev, ch, val) per write."""
    _, out = assemble(M)
    ops: list[tuple] = [("raw_engine", f"clock {RATE} 250")] + load_ops(out["rig.dep.sim"])
    ops += [("dep", 0x2000 + 2 * i, gen if i == 0 else w) for i, w in enumerate(words)]
    ops += [("reg", "SR", sr), ("trace",), ("raw_engine", "run")]
    for kind, v in sched:
        if kind == "keys":
            ops.append(("keys", v))
        elif kind == "raw":
            ops.append(("raw_engine", v))
        else:
            ops.append(("raw_engine", f"frames {v} {min(v, 128)}"))
    res = []
    for ln in L.run_engine(ops).splitlines():
        if ln.startswith("F "):
            _, f, dev, ch, val = ln.split()
            res.append((int(f) / MS, int(dev, 16), int(ch, 16), int(val, 16)))
    return res


def expected(path: Path, loops: int = 2) -> list[tuple[float, str, int, int]]:
    """The writes the score asks for, worked out from its text: (ms, kind, channel, value).
    kind: 'pitch' (channel = voice), 'gate' (voice; value 1 or 0), 'cv' (D/A), 'trig' (line)."""
    score, _ = parse(path.read_text(), str(path))
    tick = 10 if score.header("tick") == "10ms" else 1
    ev = score.events
    out: list[tuple[float, str, int, int]] = []
    level = {}
    offset = 0
    for _ in range(loops):
        for e in ev:
            t = (e.time + offset) * tick
            if e.op == "note":
                out += [(t, "pitch", e.channel, pitch(e.pitch)), (t, "gate", e.channel, 1)]
            elif e.op == "off":
                out.append((t, "gate", e.channel, 0))
            elif e.op == "cv":
                code = (
                    e.value.code
                    if e.value.code is not None
                    else int((e.value.volts * 65536 / Decimal("10.24")).to_integral_value())
                )
                level[e.channel] = code
                out.append((t, "cv", e.channel, code & 0xFFF0))
            elif e.op == "ramp":
                code = (
                    e.value.code
                    if e.value.code is not None
                    else int((e.value.volts * 65536 / Decimal("10.24")).to_integral_value())
                )
                # the documented ramp: equal steps of the move in half codes, rounded toward
                # zero, one every over // steps ticks; the last step is the target exactly
                start = level.get(e.channel, 0)
                per = e.over // e.steps
                move = (code >> 1) - (start >> 1)
                step = int(move / e.steps)
                for k in range(1, e.steps + 1):
                    v = code if k == e.steps else ((start >> 1) + step * k) << 1
                    out.append((t + k * per * tick, "cv", e.channel, v & 0xFFF0))
                level[e.channel] = code
            elif e.op == "trig":
                out.append((t, "trig", e.channel, 1))
            elif e.op == "loop":
                offset += e.time - e.target
                break
            elif e.op == "end":
                return out
    return out


def match(writes: list[tuple], want: list[tuple], v: Voices, cv_tolerance: int = 0) -> float:
    """Every wanted write appears, in order, near its time; returns the worst lateness, ms,
    after aligning the first."""
    got = []
    for t, dev, ch, val in writes:
        if dev == 0x21 and ch in v.pitch_ch:
            got.append((t, "pitch", v.pitch_ch.index(ch), val))
        if dev == 0x21 and ch in v.gate:
            got.append((t, "gate", v.gate.index(ch), 1 if val >= 0x4000 else 0))
        if dev == 0x21 and ch >= 8:
            got.append((t, "cv", ch, val))
        if dev == 0x22:
            for line in range(8, 16):
                if val & (0x8000 >> line):
                    got.append((t, "trig", line, 1))
    # align on the first wanted write, then each wanted write must have its own match near its
    # time (writes at the same tick may come in either order)
    first = want[0]
    t0 = next(g[0] for g in got if g[1:] == first[1:]) - first[0]
    used: set[int] = set()
    worst = 0.0
    for wt, kind, ch, val in want:
        cands = [i for i, g in enumerate(got) if i not in used and g[1] == kind and g[2] == ch
                 and abs(g[3] - val) <= cv_tolerance]  # fmt: skip
        assert cands, f"missing {kind} {ch} {val:#x} at {wt} ms"
        i = min(cands, key=lambda i: abs(got[i][0] - t0 - wt))
        used.add(i)
        late = got[i][0] - t0 - wt
        assert -1.5 <= late <= 1.5 + DRIFT * wt, (kind, ch, val, wt, late)
        worst = max(worst, abs(late))
    return worst


def test_an_original_score_plays_as_written_and_loops() -> None:
    """PRG-11: the four-step rhythm (two voices, a stepped CV, a trigger, a loop), twice round."""
    path = SCORES / "original-four-step-rhythm.score"
    words = compile_file(path)
    w = run(words, [("frames", int(5.0 * RATE))], sr=0x1000)
    want = expected(path, loops=2)
    worst = match(w, want, Voices(M))
    print(f"{path.name}: {len(want)} writes as the score says, worst {worst:.2f} ms off")


def test_a_ramp_is_stepped_by_the_program() -> None:
    """The ramp's steps come from the program, one write per step, ending exactly on target."""
    path = SCORES / "test-stepped-sweep.score"
    words = compile_file(path)
    w = run(words, [("frames", int(3.0 * RATE))], sr=0x1000)
    want = [x for x in expected(path, loops=1)]
    worst = match(w, want, Voices(M), cv_tolerance=0x20)  # half-code steps: within 2 LSB
    print(f"{path.name}: the ramp in {sum(1 for x in want if x[1] == 'cv')} writes, worst "
          f"{worst:.2f} ms")  # fmt: skip


def test_score_alone_ignores_the_keys_and_both_shares_the_voices() -> None:
    path = SCORES / "original-four-step-rhythm.score"  # keeps voices 1 and 2
    words = compile_file(path)
    v = Voices(M)
    w = run(words, [("frames", 4800), ("keys", 1 << 20), ("frames", 4800)], sr=0x1000)
    assert not [x for x in w if x[1] == 0x21 and x[2] in v.pitch_ch and
                x[3] == pitch(BASENOTE + 20)], "score alone: the key plays nothing"  # fmt: skip
    w = run(words, [("frames", 4800), ("keys", 1 << 20), ("frames", 4800)], sr=0x2000)
    key = [x for x in w if x[1] == 0x21 and x[3] == pitch(BASENOTE + 20)]
    assert key and key[0][2] == v.pitch_ch[2], "both: the key gets the first keyboard voice (3)"
    gate = [x for x in w if x[1] == 0x21 and x[2] == v.gate[2] and x[3] == GATE_HI]
    assert gate


def test_halting_the_computer_stops_the_score() -> None:
    path = SCORES / "original-four-step-rhythm.score"
    w = run(compile_file(path), [("frames", int(0.6 * RATE)), ("raw", "halt"),
                                 ("frames", int(2.0 * RATE))], sr=0x1000)  # fmt: skip
    assert w and max(t for t, *_ in w) <= 0.61 * 1000 + 1


def test_a_new_tape_starts_from_its_top() -> None:
    """Loading another tape (a new generation word) stops the old one and plays the new."""
    a = compile_file(SCORES / "original-four-step-rhythm.score")
    b = compile_file(SCORES / "test-stepped-sweep.score")
    _, out = assemble(M)
    ops: list[tuple] = [("raw_engine", f"clock {RATE} 250")] + load_ops(out["rig.dep.sim"])
    ops += [("dep", 0x2000 + 2 * i, 1 if i == 0 else x) for i, x in enumerate(a)]
    ops += [("reg", "SR", 0x1000), ("trace",), ("raw_engine", "run"),
            ("raw_engine", f"frames {RATE} 128")]  # fmt: skip
    ops += [("dep", 0x2000 + 2 * i, 2 if i == 0 else x) for i, x in enumerate(b)]
    ops += [("raw_engine", f"frames {RATE} 128")]
    w = [ln.split() for ln in L.run_engine(ops).splitlines() if ln.startswith("F ")]
    late = [x for x in w if int(x[1]) >= RATE and x[2] == "21" and x[3] == "8"]
    assert late and late[0][4] == "0000", "the new tape starts from silence on its own lanes"
    pitches_after = [x for x in w if int(x[1]) >= RATE and x[2] == "21" and x[3] == "0"]
    assert pitches_after, "the sweep score's note plays"


def test_the_demo_score_plays_through_and_loops() -> None:
    """The original demo (research/scores/original-tide-clock.score): three voices, four cutoff
    ramps, detune steps and triggers, written exactly as the text says on both passes of its
    16-second loop."""
    path = SCORES / "original-tide-clock.score"
    w = run(compile_file(path), [("frames", int(33.0 * RATE))], sr=0x1000)
    want = expected(path, loops=2)
    worst = match(w, want, Voices(M), cv_tolerance=0x20)
    print(f"{path.name}: {len(want)} writes over two loops, worst {worst:.2f} ms off")
