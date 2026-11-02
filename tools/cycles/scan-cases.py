#!/usr/bin/env python3
"""Run tools/cycle-calc.py over the scan-loop sketch for the cases recorded in
docs/qa/results/M1/S4.md and print them as one JSON document (SP-S4B evidence).

    python3 tools/cycles/scan-cases.py > docs/qa/results/M1/S4-scan-cases.json
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cycle_calc", HERE.parent / "cycle-calc.py")
cc = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
assert spec and spec.loader
sys.modules["cycle_calc"] = cc  # dataclasses look the module up while it executes
spec.loader.exec_module(cc)

CASES = [
    ("idle, no key changed, no score", {"N": 4, "C": 0, "R": 0, "S": 0}),
    ("idle with a score tick", {"N": 4, "C": 0, "R": 0, "S": 1}),
    ("one key pressed, 4 voices, all busy", {"N": 4, "C": 1, "R": 1, "S": 1}),
    ("one key pressed, 8 voices, all busy", {"N": 8, "C": 1, "R": 1, "S": 1}),
    ("4-note chord in 2 rows, 4 voices", {"N": 4, "C": 4, "R": 2, "S": 1}),
    ("8-note chord in 3 rows, 8 voices", {"N": 8, "C": 8, "R": 3, "S": 1}),
    ("forearm: 12 keys in 3 rows, 4 voices", {"N": 4, "C": 12, "R": 3, "S": 1}),
    ("ARCH 5.6 worst case: all 37 keys, 4 voices", {"N": 4, "C": 37, "R": 5, "S": 1}),
    ("ARCH 5.6 worst case: all 37 keys, 8 voices", {"N": 8, "C": 37, "R": 5, "S": 1}),
]


def main() -> int:
    table = cc.load_table()
    text = (HERE / "sketches" / "scan-37.txt").read_text()
    out = []
    for label, env in CASES:
        items, used = cc.parse_sketch(text, env)
        rep = cc.to_json(cc.compute(items, table), 1000.0, used)
        rep["case"] = label
        out.append(rep)
    json.dump(
        {
            "sketch": "tools/cycles/sketches/scan-37.txt",
            "table": "tools/cycles/cycles-716.tsv",
            "cases": out,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
