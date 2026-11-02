"""VS-20 acceptance: sxscore.compile, the score to the table the 7/16 program plays (RE-5,
MACH-8; SCR-01, SCR-02 for the source side). The player's half is tests/program/test_score.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "toolchain"))

from sxscore import parse  # noqa: E402
from sxscore.compile import ScoreError, compile_file, compile_score, emit_table, main  # noqa: E402

HEAD = "score: 1\ntitle: t\nstatus: draft-hidden\norigin: {origin}\nkind: test\ntick: 1ms\nvoices: 2\n\n"


def table(events: str, origin: str = "synthetic") -> list[int]:
    s, problems = parse(HEAD.format(origin=origin) + events)
    assert not problems, problems
    return compile_score(s)


def test_records_are_three_halfwords_with_waits_between() -> None:
    w = table("@0 note v1 C4\n@5 cv d8 0x4000\n+3 off v1\n@10 trig g9\n@12 end\n")
    assert w[:3] == [0, 2, 1]  # generation (the engine's), voices, 1 ms ticks
    recs = [tuple(w[i : i + 3]) for i in range(3, len(w), 3)]
    assert recs == [(0, 0x1001, 60), (5, 0x3008, 0x4000), (3, 0x2001, 0), (2, 0x5009, 0),
                    (2, 0x0000, 0)]  # fmt: skip


def test_voltages_become_codes_and_ramps_take_two_records() -> None:
    w = table("@0 ramp d8 5.00V steps 20 over 500\n@500 end\n")
    assert w[3:9] == [0, 0x4008, 32000, 500, 0x4108, 20]


def test_a_loop_lands_on_a_record_and_gets_a_wait_if_needed() -> None:
    w = table("@0 note v0 C3\n@10 off v0\n@20 loop @5\n")
    recs = [tuple(w[i : i + 3]) for i in range(3, len(w), 3)]
    assert recs[1] == (5, 0x7000, 0)  # WAIT at the loop target, tick 5
    assert recs[-1] == (10, 0x6000, 1)  # loop: no wait, record 1


def test_seastones_derived_scores_are_refused() -> None:
    s, _ = parse(HEAD.format(origin="seastones-derived").replace("status: draft-hidden",
                                                                  "status: draft-hidden") +
                 "@0 end\n")  # fmt: skip
    with pytest.raises(ScoreError, match="Layer 6 stays off"):
        compile_score(s)


def test_the_repo_scores_compile_deterministically(tmp_path: Path) -> None:
    for p in sorted((ROOT / "research" / "scores").glob("*.score")):
        a, b = compile_file(p), compile_file(p)
        assert a == b and len(a) >= 6
        out = tmp_path / f"{p.stem}.tbl"
        assert main([str(p), "-o", str(out)]) == 0
        lines = out.read_text().splitlines()
        assert lines[0].startswith("# seastones.table/1 ")
        assert [int(x, 16) for ln in lines[1:] for x in ln.split()] == a
    assert emit_table([1, 2, 3], "x") == "# seastones.table/1 x\n0001 0002 0003\n"


def test_an_invalid_score_is_reported_not_compiled(tmp_path: Path) -> None:
    bad = tmp_path / "bad.score"
    bad.write_text(HEAD.format(origin="synthetic") + "@0 note v5 C4\n@1 end\n")
    with pytest.raises(ScoreError, match="v5"):
        compile_file(bad)
    assert main([str(bad)]) == 1
