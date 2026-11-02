#!/usr/bin/env python3
"""Scan-loop period calculator for the 7/16 program at RUN speed (SP-S4B, MACH-5).

Given an instruction mix and the cycle table (tools/cycles/cycles-716.tsv), print the time the mix
takes in emulated microseconds, per ``*@block`` and in total, and check it against the scan-loop
budget (ARCHITECTURE 5.6: worst case at most 1.0 ms).

Inputs
------
* A hand-listed sketch (until the program exists), one instruction per line:

      *@block read-the-keys
      set N = 4                 # a variable; --set N=8 on the command line overrides it
      OCR                       # one execution
      RDR   x5                  # five executions
      SRLS  x8*R  n=1           # count can be an expression over variables
      BTFS  x5  taken           # a branch, taken
      BTC   x(N-1)              # not taken unless `taken` is given

  ``#`` and ``;`` start comments. ``n=K`` is the shift count, register count or byte count for
  rows with a per-n cost.
* Or a listing JSON (``rig.lst.json`` once PO-01 exists, or anything with the same shape):
  ``{"instructions": [{"mnemonic": "LHR", "count": 1, "taken": false, "n": 0, "block": "..."}]}``

The result carries the table's status line (``ESTIMATE`` until the table cites a 7/16 source).
"""

from __future__ import annotations

import argparse
import ast
import json
import operator
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TABLE = HERE / "cycles" / "cycles-716.tsv"


@dataclass(frozen=True)
class Cost:
    mnemonic: str
    form: str
    base_ns: int
    per_n_ns: int
    taken_ns: int
    conf: str


@dataclass
class Table:
    status: str
    rows: dict[str, Cost]


def load_table(path: Path = DEFAULT_TABLE) -> Table:
    status = "UNKNOWN"
    rows: dict[str, Cost] = {}
    header_seen = False
    for line in path.read_text().splitlines():
        if line.startswith("#"):
            m = re.match(r"#\s*STATUS:\s*(\S+)", line)
            if m:
                status = m.group(1)
            continue
        if not line.strip():
            continue
        cols = line.split("\t")
        if not header_seen:
            if cols[0] != "mnemonic":
                raise ValueError(f"{path}: expected a header row, got {cols[0]!r}")
            header_seen = True
            continue
        mn, _op, form, base, per_n, taken, conf = cols[:7]
        if mn in rows:
            raise ValueError(f"{path}: duplicate row {mn}")
        rows[mn] = Cost(mn, form, int(base), int(per_n), int(taken), conf)
    return Table(status, rows)


# ------------------------------------------------------------------ safe count expressions
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Div: operator.floordiv,
}


def eval_count(expr: str, env: dict[str, int]) -> int:
    def ev(node: ast.AST) -> int:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise ValueError(f"unknown variable {node.id!r} in count {expr!r}")
            return env[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        raise ValueError(f"unsupported count expression {expr!r}")

    return ev(ast.parse(expr, mode="eval"))


@dataclass
class Item:
    mnemonic: str
    count: int
    taken: bool
    n: int
    block: str


def parse_sketch(
    text: str, overrides: dict[str, int] | None = None
) -> tuple[list[Item], dict[str, int]]:
    env: dict[str, int] = {}
    overrides = overrides or {}
    items: list[Item] = []
    block = "(none)"
    for lineno, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("*@block"):
            block = raw.split(None, 1)[1].strip() if len(raw.split(None, 1)) > 1 else "(unnamed)"
            continue
        line = re.split(r"[#;]", raw, maxsplit=1)[0].strip()
        if not line:
            continue
        m = re.match(r"set\s+([A-Za-z_]\w*)\s*=\s*(.+)$", line)
        if m:
            name = m.group(1)
            env[name] = overrides[name] if name in overrides else eval_count(m.group(2), env)
            continue
        tok = line.split()
        mn, count, taken, n = tok[0].upper(), 1, False, 0
        for t in tok[1:]:
            if t.lower().startswith("x"):
                count = eval_count(t[1:], env)
            elif t.lower() == "taken":
                taken = True
            elif t.lower().startswith("n="):
                n = eval_count(t[2:], env)
            else:
                raise ValueError(f"line {lineno}: cannot read {t!r}")
        if count < 0 or n < 0:
            raise ValueError(f"line {lineno}: negative count or n")
        items.append(Item(mn, count, taken, n, block))
    for k, v in overrides.items():
        env.setdefault(k, v)
    return items, env


def parse_listing(data: dict) -> list[Item]:
    return [
        Item(
            i["mnemonic"].upper(),
            int(i.get("count", 1)),
            bool(i.get("taken", False)),
            int(i.get("n", 0)),
            i.get("block", "(none)"),
        )
        for i in data["instructions"]
    ]


@dataclass
class Report:
    status: str
    total_ns: int = 0
    instructions: int = 0
    blocks: dict[str, dict[str, int]] = field(default_factory=dict)
    by_conf: dict[str, int] = field(default_factory=dict)


def cost_of(item: Item, table: Table) -> int:
    if item.mnemonic not in table.rows:
        raise KeyError(f"{item.mnemonic} has no row in the cycle table")
    c = table.rows[item.mnemonic]
    if item.taken and not c.taken_ns:
        raise ValueError(f"{item.mnemonic} is not a branch but is marked taken")
    one = (c.taken_ns if item.taken else c.base_ns) + c.per_n_ns * item.n
    return one * item.count


def compute(items: list[Item], table: Table) -> Report:
    r = Report(status=table.status)
    for it in items:
        ns = cost_of(it, table)
        b = r.blocks.setdefault(it.block, {"instructions": 0, "ns": 0})
        b["instructions"] += it.count
        b["ns"] += ns
        r.total_ns += ns
        r.instructions += it.count
        conf = table.rows[it.mnemonic].conf
        r.by_conf[conf] = r.by_conf.get(conf, 0) + it.count
    return r


def to_json(r: Report, budget_us: float, env: dict[str, int]) -> dict[str, object]:
    period_us = r.total_ns / 1000.0
    out: dict[str, object] = {
        "table_status": r.status,
        "variables": env,
        "instructions": r.instructions,
        "period_us": round(period_us, 3),
        "mean_ns_per_instruction": round(r.total_ns / r.instructions, 1)
        if r.instructions
        else None,
        "implied_k_instructions_per_s": round(r.instructions / (r.total_ns / 1e9) / 1000.0, 1)
        if r.total_ns
        else None,
        # the same instruction count at ARCHITECTURE 2.1's flat 450k and 250k instructions/s
        "cross_check_250_450k_ips_us": [
            round(r.instructions * 1e6 / 450e3, 1),
            round(r.instructions * 1e6 / 250e3, 1),
        ]
        if r.instructions
        else None,
        "budget_us": budget_us,
        "within_budget": period_us <= budget_us,
        "instructions_by_confidence": r.by_conf,
        "blocks": {
            k: {"instructions": v["instructions"], "us": round(v["ns"] / 1000.0, 3)}
            for k, v in r.blocks.items()
        },
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("program", type=Path, help="sketch (.txt) or listing (.json)")
    ap.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    ap.add_argument(
        "--set", action="append", default=[], metavar="NAME=INT", help="override a sketch variable"
    )
    ap.add_argument("--budget-us", type=float, default=1000.0)
    ap.add_argument("--fail-over-budget", action="store_true")
    ap.add_argument("--json", action="store_true", help="JSON only")
    args = ap.parse_args(argv)

    overrides = {}
    for s in args.set:
        k, _, v = s.partition("=")
        overrides[k.strip()] = int(v)
    table = load_table(args.table)
    if args.program.suffix == ".json":
        items, env = parse_listing(json.loads(args.program.read_text())), overrides
    else:
        items, env = parse_sketch(args.program.read_text(), overrides)
    rep = to_json(compute(items, table), args.budget_us, env)
    rep["program"] = args.program.name
    if args.json:
        json.dump(rep, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(
            f"{args.program.name}: {rep['instructions']} instructions, period {rep['period_us']} us "
            f"at RUN ({rep['table_status']}; budget {args.budget_us:g} us: "
            f"{'within' if rep['within_budget'] else 'OVER'})"
        )
        for name, b in rep["blocks"].items():  # type: ignore[union-attr]
            print(f"  {name:24s} {b['instructions']:6d} instr  {b['us']:10.2f} us")
        print(
            f"  mean {rep['mean_ns_per_instruction']} ns/instr, {rep['implied_k_instructions_per_s']} k instr/s; "
            f"at 450..250 k instr/s the same count takes {rep['cross_check_250_450k_ips_us']} us"
        )
    return 1 if args.fail_over_budget and not rep["within_budget"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
