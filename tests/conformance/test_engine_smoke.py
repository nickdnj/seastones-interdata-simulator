"""SP-S3B: libseastones builds from the vendored CPU + shim and runs a display program.

The program is the five instructions lamps.ini deposits (LHI, LHI, WDR, LHI, WDR), written
out here from the Model 4 feasibility notes rather than read from the fixture, so this
smoke test needs no fixtures. The full period-program and random-stream lockstep is
test_lockstep.py (SP-S3C).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = Path(os.environ.get("SX_ENGINE", ROOT / "build" / "engine" / "sx-cpu"))
SHIM = ROOT / "src" / "engine" / "shim" / "scp_shim.c"

pytestmark = [
    pytest.mark.lockstep,
    pytest.mark.skipif(not ENGINE.exists(), reason="engine not built: run `make engine`"),
]

PROGRAM = [(0x100, 0xC810), (0x102, 0x0001), (0x104, 0xC820), (0x106, 0x00A5),
           (0x108, 0x9A12), (0x10A, 0xC820), (0x10C, 0x003C), (0x10E, 0x9A12)]  # fmt: skip


def oracle() -> str:
    env = os.environ.get("SX_ORACLE")
    if env:
        return env
    out = subprocess.run(
        [str(ROOT / "scripts" / "build-oracle.sh")], capture_output=True, text=True, check=True
    )
    return out.stdout.strip().splitlines()[-1]


def dr_sequence_engine() -> list[str]:
    script = "".join(f"dep {a:X} {v:04X}\n" for a, v in PROGRAM) + "reg PC 100\n"
    script += "step 1\nex DR\n" * 5
    out = subprocess.run([str(ENGINE)], input=script, capture_output=True, text=True, check=True)
    return [ln for ln in out.stdout.splitlines() if ln.startswith("DR:")]


def dr_sequence_oracle() -> list[str]:
    script = "".join(f"dep 0{a:X} {v:04X}\n" for a, v in PROGRAM) + "dep pc 100\n"
    script += "step 1\nex dr\n" * 5 + "exit\n"
    with tempfile.NamedTemporaryFile("w", suffix=".sim", delete=False) as f:
        f.write(script)
    try:
        out = subprocess.run(
            [oracle(), f.name], stdin=subprocess.DEVNULL, capture_output=True, text=True
        ).stdout
    finally:
        os.unlink(f.name)
    return [ln for ln in out.splitlines() if ln.startswith("DR:")]


def test_display_register_sequence_matches_stock() -> None:
    eng = dr_sequence_engine()
    assert eng == ["DR:\t00000000", "DR:\t00000000", "DR:\t000000A5", "DR:\t000000A5",
                   "DR:\t0000003C"]  # fmt: skip
    assert eng == dr_sequence_oracle()


def test_engine_links_no_scp_source() -> None:
    syms = subprocess.run(
        ["nm", str(ROOT / "build" / "engine" / "libseastones.a")], capture_output=True, text=True
    ).stdout
    for scp_only in ("_run_cmd", "run_cmd", "sim_os_msec", "tmxr_poll_conn", "sim_poll_kbd"):
        assert f" T {scp_only}\n" not in syms and f" T _{scp_only}\n" not in syms, scp_only


def test_shim_line_count_is_recorded() -> None:
    lines = SHIM.read_text().count("\n")
    print(f"scp_shim.c: {lines} lines (plan about 300, amber above 600)")
    assert lines <= 600
