"""VS-02 acceptance and ADR-008's S-3 conditions 2 and 3 (SP-S3E): the emulated clock.

* SINGLE executes exactly one instruction per STEP, and the state after N steps equals stock
  `id16` stepping N instructions (CNF-10).
* A known loop's iteration count over 1 s of emulated audio equals tools/cycle-calc.py's
  calculation from the cycle table within 1 percent (CNF-09).
* The 20 S-3 streams stay identical to stock with the cycle table loaded (ADR-008 condition 2).
* The PIC and LFC tick in emulated time, scale with the speed, and the wait state jumps to the
  next event (ADR-008 condition 3, CNF-11 shim half): C unit tests, see the end of this file.

The cycle table's STATUS is ESTIMATE (Model 74 proxy, SP-S4B): every printed time says so.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import lockstep as L  # noqa: E402

spec = importlib.util.spec_from_file_location("cycle_calc", ROOT / "tools" / "cycle-calc.py")
cc = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
assert spec and spec.loader
sys.modules["cycle_calc"] = cc
spec.loader.exec_module(cc)

STREAMS = int(os.environ.get("SX_STREAMS", "20"))
INSTRUCTIONS = int(os.environ.get("SX_INSTRUCTIONS", "1000000"))
FINE = int(os.environ.get("SX_FINE", "2000"))
SEED_BASE = int(os.environ.get("SX_SEED_BASE", "1974"))
JOBS = int(os.environ.get("SX_JOBS", str(os.cpu_count() or 4)))

needs_engine = pytest.mark.skipif(not Path(L.engine_path()).exists(), reason="engine not built")

# X'100' AIS R1,1 / MHR R2,R3 / SLHL R4,5 / BTFS 0,+1 (never taken) / B X'100'
LOOP = [0x2611, 0x0C23, 0xCD40, 0x0005, 0x2101, 0x4300, 0x0100]
LOOP_SKETCH = """
*@block known-loop
AIS
MHR
SLHL  n=5
BTFS
BFC   taken
"""


def loop_ops() -> list[tuple]:
    ops: list[tuple] = [("mem", 32768)]
    ops += [("dep", 0x100 + 2 * i, w) for i, w in enumerate(LOOP)]
    return ops + [("reg", "PC", 0x100)]


def run(ops: list[tuple]) -> list[str]:
    return L.run_engine(ops).splitlines()


@pytest.mark.lockstep  # needs the built engine: runs under `make conformance`
@needs_engine
def test_known_loop_over_one_second_matches_cycle_calc() -> None:
    table = cc.load_table()
    assert table.status == "ESTIMATE"
    items, _ = cc.parse_sketch(LOOP_SKETCH)
    per_iter_us = cc.compute(items, table).total_ns / 1000
    expected = 1e6 / per_iter_us
    out = run(
        [("raw_engine", "status"), ("raw_engine", "clock 48000 250"), *loop_ops()]
        + [("raw_engine", "run"), ("raw_engine", "frames 48000 128"), ("ex", ["R1"])]
    )
    assert out[0] == "cycle table: ESTIMATE, 113 rows"
    got = int(out[-1].split()[-1], 16)
    print(f"ESTIMATE: {per_iter_us} us per iteration; cycle-calc {expected:.1f}, engine {got}")
    assert abs(got - expected) <= 0.01 * expected


@pytest.mark.lockstep
@needs_engine
@pytest.mark.parametrize("divisor", [1, 10, 100, 1000, 3000])
def test_speed_divides_emulated_time(divisor: int) -> None:
    out = run(
        [("raw_engine", "clock 48000 250"), *loop_ops(), ("raw_engine", f"divisor {divisor}")]
        + [("raw_engine", "run"), ("raw_engine", "frames 144000 128")]
    )
    cycles = int(out[-1].split()[-1])
    want = 3 * 4_000_000 // divisor
    assert want <= cycles < want + 200, (divisor, cycles)  # + one instruction's overshoot


@pytest.mark.lockstep
@needs_engine
@pytest.mark.parametrize("seed", [SEED_BASE, SEED_BASE + 1, SEED_BASE + 2])
def test_single_step_equals_stock_stepping(seed: int) -> None:
    """CNF-10: STEP in SINGLE, with the cycle table loaded, one instruction each, full state
    after every one, equal to stock `step 1`."""
    s = L.Stream(seed)
    base = L.load_ops(s.mem, s.regs)
    n = 1500
    oracle_ops = base + [op for _ in range(n) for op in (("step", 1), ("ex", L.REG_NAMES))]
    engine_ops = (
        [("raw_engine", "clock 48000 250")]
        + base
        + [("raw_engine", "speed 5"), ("raw_engine", "run")]
        + [op for _ in range(n) for op in (("raw_engine", "single 1"), ("ex", L.REG_NAMES))]
    )
    a = L.normalise(L.run_oracle(oracle_ops))
    b = L.normalise(L.run_engine(engine_ops))
    c = L.compare(a, b)
    assert c.equal, "\n".join(c.context)
    assert sum(ln.startswith("Step expired") for ln in b) == n


@pytest.mark.lockstep
@needs_engine
def test_s3_streams_identical_with_the_cycle_table_loaded() -> None:
    """ADR-008 condition 2: the S-3 streams with every instruction costed from the table."""
    seeds = [SEED_BASE + i for i in range(STREAMS)]
    results = L.run_streams(seeds, INSTRUCTIONS, FINE, JOBS, cycle_ns=250)
    bad = [r for r in results if not r["equal"]]
    for r in bad:
        print(f"seed {r['seed']} differs at line {r['first_diff']}:\n" + "\n".join(r["context"]))
    assert not bad, f"cycle-table lockstep divergence on seeds {[r['seed'] for r in bad]}"
    assert all(r["history_lines"] == INSTRUCTIONS - min(FINE, INSTRUCTIONS) for r in results)
    print(f"{len(seeds)} streams x {INSTRUCTIONS} instructions identical with cycles 250")


# ADR-008 condition 3 (PIC at 1, 10, 100, 1000 us and LFC at 60 Hz in emulated time, scaling
# with the speed, sim_idle consuming the slice) is tested in C: tests/engine/test_shim.c
# test_cycle_mode_clocks and tests/engine/test_clock.c test_wait_state, run by make test-engine.
