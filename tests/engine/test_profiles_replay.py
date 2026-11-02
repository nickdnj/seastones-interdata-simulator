"""VS-27 (production and test profiles) and VS-26 (sx-render replay mode).

VS-27: the production binary has no test hook and no research-only (`jitter`) symbol, carries
"SEASTONES_PROFILE=production", and sx_profile() reports it (rigd's `hello` will report the same
value, VS-14). The same greps find the hooks in the test build, so the check can fail.
VS-26: a D/A and gate trace recorded from a CPU run, replayed into the DSP alone through the same
seam, renders bit-identically to the run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEST_B = ROOT / "build" / "engine"
PROD_B = ROOT / "build" / "prod" / "engine"
SOEXT = "dylib" if sys.platform == "darwin" else "so"
IMAGE = ROOT / "build" / "program" / "rig.img.json"
SCRIPT = ROOT / "tests" / "engine" / "scripts" / "mono-phrase.txt"

pytestmark = pytest.mark.lockstep  # needs build outputs: runs under `make conformance`


@pytest.fixture(scope="module")
def production() -> Path:
    subprocess.run(["make", "--no-print-directory", "engine-production"], cwd=ROOT, check=True,
                   capture_output=True)  # fmt: skip
    return PROD_B


def symbols(path: Path) -> str:
    return subprocess.run(["nm", str(path)], capture_output=True, text=True, check=True).stdout


def test_production_binary_has_no_hooks_and_says_so(production: Path) -> None:
    for binary in (production / f"libseastones.{SOEXT}", production / "sx-render"):
        syms = symbols(binary)
        assert "sx_test_" not in syms, f"{binary.name}: a test hook in the production build"
        assert "jitter" not in syms.lower(), f"{binary.name}: a research-only symbol"
        data = binary.read_bytes()
        assert b"SEASTONES_PROFILE=production" in data
        assert b"SEASTONES_PROFILE=test" not in data


def test_the_grep_finds_hooks_in_the_test_build() -> None:
    lib = TEST_B / f"libseastones.{SOEXT}"
    if not lib.exists():
        pytest.skip("run `make engine`")
    syms = symbols(lib)
    for hook in ("sx_test_inject", "sx_test_replay", "sx_test_set_event_tap"):
        assert hook in syms
    assert b"SEASTONES_PROFILE=test" in lib.read_bytes()


def test_sx_profile_reports_the_build(production: Path) -> None:
    for build, want in ((TEST_B, b"test"), (production, b"production")):
        out = subprocess.run(
            [sys.executable, "-c", PROBE, str(build / f"libseastones.{SOEXT}")],
            capture_output=True, check=True,
        )  # fmt: skip
        assert out.stdout.strip() == want


# Each library is loaded in its own process: the engine keeps SIMH state in globals.
PROBE = (
    "import ctypes, sys; lib = ctypes.CDLL(sys.argv[1]); lib.sx_profile.restype = ctypes.c_char_p;"
    " sys.stdout.buffer.write(lib.sx_profile())"
)


def test_production_sx_render_refuses_replay(production: Path) -> None:
    r = subprocess.run([str(production / "sx-render"), "--replay", "x", "--seconds", "1"],
                       capture_output=True, text=True)  # fmt: skip
    assert r.returncode == 2 and "test profile" in r.stderr


@pytest.mark.skipif(not IMAGE.exists(), reason="run `make program`")
def test_replay_of_a_recorded_run_is_bit_identical(tmp_path: Path) -> None:
    render = TEST_B / "sx-render"
    trace = tmp_path / "phrase.trace"
    run = subprocess.run([str(render), "--image", str(IMAGE), "--script", str(SCRIPT),
                          "--seconds", "2.2", "--trace-out", str(trace)],
                         capture_output=True, text=True, check=True)  # fmt: skip
    lines = [ln for ln in trace.read_text().splitlines() if not ln.startswith("#")]
    assert len(lines) >= 8  # gates and pitches of the phrase
    rep = subprocess.run([str(render), "--replay", str(trace), "--script", str(SCRIPT),
                          "--seconds", "2.2"], capture_output=True, text=True, check=True)  # fmt: skip
    assert run.stdout.split()[1] == rep.stdout.split()[1]
    # and the trace really drives the sound: an empty trace renders something else
    empty = tmp_path / "empty.trace"
    empty.write_text("# seastones.trace/1\n")
    none = subprocess.run([str(render), "--replay", str(empty), "--seconds", "2.2"],
                          capture_output=True, text=True, check=True)  # fmt: skip
    assert none.stdout.split()[1] != run.stdout.split()[1]
