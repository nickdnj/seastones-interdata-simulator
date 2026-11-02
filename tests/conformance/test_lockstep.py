"""S-3 conformance: the engine's CPU against stock id16 (SP-S3B, SP-S3C; CNF-01/02/07/12).

Runs under `make conformance` (which builds the oracle and the engine first). Sizes default
to the S-3 GO criteria and can be raised for the nightly run:

    SX_STREAMS (20)  SX_INSTRUCTIONS (1000000)  SX_FINE (2000)  SX_SEED_BASE (1974)

Period programs (lamps.ini, the M-70 light display) are local fixtures read through
SX_FIXTURES_DIR and are never copied into the repo (RIGHTS-6); without it those tests skip
with a message. Random streams need no fixtures.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import lockstep as L  # noqa: E402
from subset_v0 import SUBSET_V0  # noqa: E402

STREAMS = int(os.environ.get("SX_STREAMS", "20"))
INSTRUCTIONS = int(os.environ.get("SX_INSTRUCTIONS", "1000000"))
FINE = int(os.environ.get("SX_FINE", "2000"))
SEED_BASE = int(os.environ.get("SX_SEED_BASE", "1974"))
JOBS = max(1, (os.cpu_count() or 2) // 2)
SEEDS_FILE = HERE / "seeds.txt"
SHIM = ROOT / "src" / "engine" / "shim" / "scp_shim.c"
SHIM_LIMIT = 600  # S-3 GO criterion 5 (DEV-PLAN D-PLAN-3: amber above 600)

pytestmark = [
    pytest.mark.lockstep,
    pytest.mark.skipif(
        not Path(L.engine_path()).exists(), reason="engine not built: run `make engine`"
    ),
]


def regression_seeds() -> list[int]:
    if not SEEDS_FILE.exists():
        return []
    return [int(t) for ln in SEEDS_FILE.read_text().splitlines() if (t := ln.split("#")[0].strip())]


def record_failing(seeds: list[int]) -> None:
    known = set(regression_seeds())
    with SEEDS_FILE.open("a") as f:
        for s in seeds:
            if s not in known:
                f.write(f"{s}  # failed lockstep {INSTRUCTIONS} instructions\n")


def test_random_subset_streams_are_identical() -> None:
    seeds = [SEED_BASE + i for i in range(STREAMS)]
    print(f"seeds {seeds[0]}..{seeds[-1]}, {INSTRUCTIONS} instructions each, fine {FINE}")
    results = L.run_streams(seeds, INSTRUCTIONS, FINE, JOBS)
    bad = [r for r in results if not r["equal"]]
    record_failing([r["seed"] for r in bad])
    for r in bad:
        print(f"seed {r['seed']} differs at line {r['first_diff']}:\n" + "\n".join(r["context"]))
    assert not bad, f"lockstep divergence on seeds {[r['seed'] for r in bad]}"
    assert all(r["history_lines"] == INSTRUCTIONS - min(FINE, INSTRUCTIONS) for r in results)
    executed = Counter()
    for r in results:
        executed.update(r["mnemonics"])
    missing = sorted(set(SUBSET_V0) - set(executed))
    assert not missing, f"subset instructions never executed: {missing}"


def test_regression_seeds_replay() -> None:
    seeds = regression_seeds()
    if not seeds:
        pytest.skip("seeds.txt holds no failing seeds (none has ever failed)")
    results = L.run_streams(seeds, INSTRUCTIONS, FINE, JOBS)
    assert all(r["equal"] for r in results), [r["seed"] for r in results if not r["equal"]]


def test_disassembly_of_every_first_word() -> None:
    """CNF-07 / GO criterion 2: sx_disasm (SIMH fprint_sym in the engine) equals stock
    `ex -m` for all 65,536 values of the first halfword, each with a random second word."""
    results = L.run_disasm(65536, SEED_BASE, JOBS)
    assert sum(r["words"] for r in results) == 65536
    bad = [r for r in results if not r["equal"]]
    assert not bad, "\n".join(ln for r in bad for ln in r["context"])


def test_disassembly_of_stream_images() -> None:
    """Every word of the code region of three stream images, one word at a time."""
    for seed in (SEED_BASE, SEED_BASE + 1, SEED_BASE + 2):
        s = L.Stream(seed)
        c = L.image_disasm(s.mem, 0, s.body_end + 2)
        assert c.equal, "\n".join(c.context)


def test_wait_state_and_illegal_instruction() -> None:
    """CNF-12 short form: the wait state (idle passes, no history) and the illegal-
    instruction trap behave the same in both, and the engine returns at the tick count."""
    mem = {0x100: 0x4300, 0x102: 0x0100, 0x34: 0x0000, 0x36: 0x0200, 0x200: 0x0000}
    for psw in (0x8000, 0xC000, 0x0000):
        ops = L.load_ops(mem, {"PC": 0x100, "PSW": psw})
        ops = L.run_ops(ops, 5000, 50, chunk=1000)
        c = L.compare(L.normalise(L.run_oracle(ops)), L.normalise(L.run_engine(ops)))
        assert c.equal, f"PSW {psw:04X}:\n" + "\n".join(c.context)


def fixtures() -> Path:
    fx = L.fixtures_dir()
    if fx is None:
        pytest.skip(
            "SX_FIXTURES_DIR is not set: the period programs (lamps.ini, the M-70 light "
            "display tape) are local fixtures and never live in this repo (RIGHTS-6)"
        )
    return fx


@pytest.mark.parametrize("program", ["lamps-i4", "lamps-716", "m70", "m70-sr00A5"])
def test_period_program_is_identical(program: str) -> None:
    fixtures()
    n = 2000 if program.startswith("lamps") else INSTRUCTIONS
    r = L.program_job((program, n, 5 if program.startswith("lamps") else FINE))
    assert r["equal"], f"{program} differs:\n" + "\n".join(r["context"])
    assert r["dr_samples"] > 0 and r["dr_distinct"] >= 2, "the display never changed"


def test_period_program_images_disassemble_identically() -> None:
    fx = fixtures()
    mem, _, _ = L.m70_snapshot(fx)
    c = L.image_disasm(mem, 0, 0x7FFE)
    assert c.equal, "\n".join(c.context)
    lamps, model, _ = L.lamps_program(fx)
    c = L.image_disasm(lamps, 0x100, 0x110, model=model)
    assert c.equal, "\n".join(c.context)


def test_a_planted_cc_bug_is_caught(tmp_path: Path) -> None:
    """SP-S3C negative test: build the engine with one condition-code rule flipped and
    show the lockstep sees it."""
    build = tmp_path / "mutant"
    mk = subprocess.run(
        [
            "make",
            "-s",
            "engine",
            f"BUILD={build}",
            "SX_EXTRA_PATCHES=tests/conformance/mutations/flip-clh-carry.patch",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert mk.returncode == 0, mk.stdout + mk.stderr
    os.environ["SX_ENGINE"] = str(build / "engine" / "sx-cpu")
    try:
        seeds = [SEED_BASE + i for i in range(STREAMS)]
        results = L.run_streams(seeds, INSTRUCTIONS, FINE, JOBS)
    finally:
        del os.environ["SX_ENGINE"]
    caught = [r["seed"] for r in results if not r["equal"]]
    print(f"mutant caught by {len(caught)} of {len(seeds)} streams: {caught}")
    assert caught, "the lockstep did not notice a flipped carry rule"


def test_shim_is_within_the_size_line() -> None:
    lines = SHIM.read_text().count("\n")
    print(f"scp_shim.c: {lines} lines (plan about 300, amber above {SHIM_LIMIT})")
    assert lines <= SHIM_LIMIT, f"shim is {lines} lines: amber, Nick decides at SP-S3D"


def test_subset_matches_program_file() -> None:
    f = ROOT / "src" / "program" / "subset" / "m74-portable-1.txt"
    if not f.exists():
        pytest.skip("src/program/subset/m74-portable-1.txt not written yet (SP-S5)")
    named = set(re.findall(r"^\s*([A-Z]{1,5})\b", f.read_text(), flags=re.M))
    # SP-S5 removed block I/O from the portable subset (Models 70, 80 only). The lockstep
    # harness still exercises it against the oracle: extra 716 coverage, not program use.
    oracle_only = {"WBR", "RBR", "WB", "RB"}
    expected = set(SUBSET_V0) - oracle_only
    assert named == expected, (
        f"subset drift: only in file {sorted(named - expected)}, "
        f"only in harness {sorted(expected - named)}"
    )
