"""VS-20: compile a seastones.score/1 score into the table the 7/16 program plays ("the tape").

    python3 -m sxscore.compile SCORE [-o OUT.tbl]     (src/toolchain on PYTHONPATH)

The table is deposited at X'2000' (ARCHITECTURE 5.5, 9.3) and read by the score player in
src/program/score.s. Layout, all halfwords:

    X'2000'  generation   0 here; the engine writes a new number at each deposit, so the
                          program notices a new tape (sx_score_load)
    X'2002'  voices       the voices the score reserves, v0 up (the keyboard keeps the rest)
    X'2004'  tick         milliseconds per tick: 1 or 10
    X'2006'  records      three halfwords each:  [delta ticks] [op:4 | arg:4 | channel:8] [value]

Ops (delta is the wait after the previous record):

    0 END    stop                              4 RAMP   arg 0: value = target code
    1 NOTE   channel = voice, value = note              arg 1: delta = over (ticks), value = steps
    2 OFF    channel = voice                            (always the next record after arg 0)
    3 CV     channel = D/A, value = code       5 TRIG   channel = gate line (one tick)
    6 LOOP   value = record index to play next, with no wait
    7 WAIT   nothing (put at a loop target that has no event of its own)

Notes stay note numbers, so the program's pitch table and the D/A model stay in force; voltages
become codes for an ideal 16-bit converter over range_v (the converter truncates).

Rights (LEGAL-REVIEW 1.1, SEA-3): a score with `origin: seastones-derived` is refused here. Those
are Nick's, kept outside every work tree, and Layer 6 stays off in v1.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from .score import Score, parse
from .validate import DEFAULT_RANGE_V, find_ledger_dir, validate

OPS = {"end": 0, "note": 1, "off": 2, "cv": 3, "ramp": 4, "trig": 5, "loop": 6, "wait": 7}
HEADER_WORDS = 3
MAX_WORDS = 24576 // 2


class ScoreError(Exception):
    pass


def _code(value, range_v: Decimal) -> int:
    if value.code is not None:
        return value.code
    return max(0, min(0xFFFF, int((value.volts * 65536 / range_v).to_integral_value())))


def compile_score(score: Score, range_v: Decimal = DEFAULT_RANGE_V) -> list[int]:
    """The table's halfwords for a valid score."""
    if score.header("origin") == "seastones-derived":
        raise ScoreError(f"{score.source}: a seastones-derived score is not compiled here: "
                         "Layer 6 stays off (SEA-3, LEGAL-REVIEW 1.1)")  # fmt: skip
    events = list(score.events)
    loops = [e.target for e in events if e.op == "loop"]
    # a loop target with no event of its own gets a WAIT, so the jump lands on a record
    for t in loops:
        if not any(e.time == t and e.op != "loop" for e in events):
            k = next(i for i, e in enumerate(events) if e.time > t)
            events.insert(k, type(events[0])(line=0, time=t, op="wait"))
    words: list[int] = [0, int(score.header("voices")), 10 if score.header("tick") == "10ms" else 1]
    first = {}
    recs: list[tuple[int, int, int]] = []
    prev = 0
    for e in events:
        delta = e.time - prev
        prev = e.time
        first.setdefault(e.time, len(recs))
        op = OPS[e.op]
        ch = e.channel or 0
        if e.op == "note":
            recs.append((delta, op << 12 | ch, e.pitch))
        elif e.op in ("off", "trig", "wait", "end"):
            recs.append((delta, op << 12 | ch, 0))
        elif e.op == "cv":
            recs.append((delta, op << 12 | ch, _code(e.value, range_v)))
        elif e.op == "ramp":
            recs.append((delta, op << 12 | ch, _code(e.value, range_v)))
            recs.append((e.over, op << 12 | 1 << 8 | ch, e.steps))
        elif e.op == "loop":
            recs.append((delta, op << 12, -1 - e.target))  # resolved below
    out = []
    for d, w1, v in recs:
        if v < 0:
            v = first[-1 - v]
        if not 0 <= d <= 0xFFFF:
            raise ScoreError(f"{score.source}: a gap of {d} ticks does not fit one record")
        out += [d, w1, v & 0xFFFF]
    words += out
    if len(words) > MAX_WORDS:
        raise ScoreError(f"{score.source}: the table is {len(words) * 2} bytes; the score area "
                         "holds 24,576")  # fmt: skip
    return words


def compile_file(path: Path, range_v: Decimal = DEFAULT_RANGE_V) -> list[int]:
    text = path.read_text(encoding="utf-8")
    score, problems = parse(text, str(path))
    problems += validate(score, find_ledger_dir(path), range_v)
    if problems:
        raise ScoreError("\n".join(str(p) for p in problems))
    return compile_score(score, range_v)


def emit_table(words: list[int], title: str) -> str:
    """seastones.table/1: a comment line, then the halfwords in hex, eight to a line."""
    lines = [f"# seastones.table/1 {title}"]
    for i in range(0, len(words), 8):
        lines.append(" ".join(f"{w:04X}" for w in words[i : i + 8]))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sxscore.compile", description=__doc__.splitlines()[0])
    ap.add_argument("score", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--range-v", type=Decimal, default=DEFAULT_RANGE_V)
    a = ap.parse_args(argv)
    try:
        words = compile_file(a.score, a.range_v)
    except (ScoreError, OSError, UnicodeDecodeError) as e:
        print(f"sxscore.compile: {e}", file=sys.stderr)
        return 1
    title = parse(a.score.read_text(encoding="utf-8"), str(a.score))[0].header("title") or ""
    text = emit_table(words, title)
    if a.out:
        a.out.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
