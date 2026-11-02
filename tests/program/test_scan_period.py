"""PO-08 (MACH-5; CNF-08, PRG-02): the scan loop's period measured in the engine against the
period tools/cycle-calc.py computes from the cycle table for the very instructions that ran.

The engine (patch 0001 with the generated cycles.c) and cycle-calc (reading cycles-716.tsv) are
two readings of one table, whose STATUS is ESTIMATE; this checks they agree within 10 % on real
passes of the final program: an idle pass, a pass that takes one key, and one that takes K keys
with a steal. Numbers are recorded in docs/qa/results/M3/scan-period.md. What this cannot prove
is that the table matches a real 7/16 (SP-S4A's open item).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from progtools import ROOT, L, assemble, engine_ok, load_ops  # noqa: E402
from sxasm import by_name, canonical  # noqa: E402

pytestmark = [pytest.mark.lockstep, pytest.mark.skipif(not engine_ok(), reason="engine not built")]

spec = importlib.util.spec_from_file_location("cycle_calc", ROOT / "tools" / "cycle-calc.py")
CC = importlib.util.module_from_spec(spec)
sys.modules["cycle_calc"] = CC
spec.loader.exec_module(CC)

BRANCHY = {"BTC", "BFC", "BTCR", "BFCR", "BTBS", "BTFS", "BFBS", "BFFS", "BAL", "BALR"}
SHIFTS = {"SLLS", "SRLS", "SLHL", "SRHL", "SLHA", "SRHA", "SLL", "SRL", "SLA", "SRA"}
HIST = re.compile(
    r"^([0-9A-F]{4})\s+([0-9A-F]{4})\s+([0-9A-F]{4})\s+(?:([0-9A-F]{4})\s+)?(\S+)\s*(\S*)"
)


def passes(schedule: list[tuple], m: str = "all-da-4") -> tuple[list[list[dict]], list[int]]:
    """The instructions of every complete pass (LOOP to LOOP) from the CPU's history, and the
    measured pass lengths in cycles from the same schedule run with `period`."""
    a, out = assemble(m)
    loop = a.symbols["LOOP"]
    ops = [("raw_engine", "cycles 250")] + load_ops(out["rig.dep.sim"]) + [("hist", 65536)]
    total = 0
    for op in schedule:
        if op[0] == "keys":
            ops.append(op)
        else:
            ops.append(("step", op[1]))
            total += op[1]
    ops.append(("showhist", min(total, 65536)))
    hist = []
    for ln in L.run_engine(ops).splitlines():
        mm = HIST.match(ln)
        if mm:
            hist.append((int(mm.group(1), 16), mm.group(5), mm.group(6)))
    runs, cur = [], None
    for k, (pc, opc, operands) in enumerate(hist):
        if pc == loop:
            if cur is not None:
                runs.append(cur)
            cur = []
        if cur is None:
            continue
        op = by_name().get(opc)
        base = canonical(op) if op else opc
        nxt = hist[k + 1][0] if k + 1 < len(hist) else None
        length = 4 if op and op.words == 2 else 2
        item = {"mnemonic": base, "count": 1, "taken": False, "n": 0}
        if base in BRANCHY and base not in ("BAL", "BALR"):
            item["taken"] = nxt is not None and nxt != pc + length
        if base in SHIFTS:
            item["n"] = int(operands.split(",")[1], 16) if "," in operands else 0
        cur.append(item)
    period = [("raw_engine", "cycles 250")] + load_ops(out["rig.dep.sim"])
    for op in schedule:
        period.append(op if op[0] == "keys" else ("raw_engine", f"period {loop:X} {op[1]}"))
    measured = [int(ln.split()[7]) for ln in L.run_engine(period).splitlines()
                if ln.startswith("period ")]  # fmt: skip
    return runs, measured


def calc_cycles(items: list[dict]) -> float:
    table = CC.load_table()
    for it in items:  # BAL/BALR "taken" is their base cost; the table has no taken column
        if it["taken"] and not table.rows[it["mnemonic"]].taken_ns:
            it["taken"] = False
    r = CC.compute(CC.parse_listing({"instructions": items}), table)
    return r.total_ns / 250.0


# Keys are set before the program starts, so the passes that take them lie wholly inside the
# measured window (a key set mid-window could be taken by a pass the window only half sees).
CASES = {
    "idle": [("step", 2000)],
    "one key": [("keys", 1 << 20), ("step", 2000)],
    "K keys, stealing": [("keys", (1 << 37) - 1), ("step", 3000)],
}


@pytest.mark.parametrize("case", list(CASES))
def test_measured_period_agrees_with_cycle_calc(case: str) -> None:
    runs, measured = passes(CASES[case])
    longest = max(measured)
    worst = max(runs, key=calc_cycles)
    calc = calc_cycles(worst)
    err = (calc - longest) / longest
    print(f"{case}: measured {longest * 0.25:.1f} us, cycle-calc {calc * 0.25:.1f} us over "
          f"{len(worst)} instructions ({err * 100:+.1f} %; table ESTIMATE)")  # fmt: skip
    assert abs(err) <= 0.10
    assert longest * 0.25 <= 1000.0  # inside the NFR-1 budget line (1.0 ms)
