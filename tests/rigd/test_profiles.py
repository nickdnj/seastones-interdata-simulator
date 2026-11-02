"""VS-27, rigd's half: hello reports the profile, and a production build has no test hooks and
refuses every developer switch (the fault-injection tests run only on the test profile).

Needs `make host-production` (build/prod/; `make test` builds it)."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from conftest import ROOT, Client, free_port, sounding

from rigd import engine as eng

PROD = ROOT / "build" / "prod"
PROD_LIB = eng.default_lib_path(PROD)


def need_prod() -> None:
    if not PROD_LIB.exists() or not (PROD / "program" / "rig.img.json").exists():
        pytest.skip("needs `make host-production` (UNVERIFIED)")


def rigd(*args: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "rigd", "--build", str(PROD), "--audio", "null", "--no-midi", *args],
        cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
        capture_output=True, text=True, timeout=timeout,
    )  # fmt: skip


@pytest.mark.parametrize(
    "switch", [["--test-hooks"], ["--no-ui-mute"], ["--capture", "x.f32"], ["--latency-log", "x"]]
)
def test_production_refuses_developer_switches(switch):
    need_prod()
    out = rigd(*switch)
    assert out.returncode == 2 and "production profile refuses" in out.stderr, out.stderr


def test_production_library_has_no_test_hook_symbols():
    need_prod()
    nm = subprocess.run(["nm", "-g", str(PROD_LIB)], capture_output=True, text=True)
    if nm.returncode != 0:
        pytest.skip("no nm (UNVERIFIED)")
    exported = nm.stdout
    for sym in ("sx_test_inject", "sx_test_replay", "sxh_test_freeze"):
        assert sym not in exported
    assert b"SEASTONES_PROFILE=production" in PROD_LIB.read_bytes()


def test_production_hello_says_so_and_test_inject_is_unknown(tmp_path):
    need_prod()
    port = free_port()
    log = open(tmp_path / "prod.log", "w")  # noqa: SIM115
    p = subprocess.Popen(
        [sys.executable, "-m", "rigd", "--build", str(PROD), "--audio", "null", "--no-midi",
         "--port", str(port)],
        cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")), stdout=log,
        stderr=subprocess.STDOUT,
    )  # fmt: skip
    try:
        import time

        for _ in range(200):
            if "listening on" in (tmp_path / "prod.log").read_text():
                break
            time.sleep(0.05)
        c = Client(f"ws://127.0.0.1:{port}")
        c.pump(0.4)
        assert "profile production" in c.last("hello")["engine_build"]
        assert c.command({"t": "test.inject", "what": "nan"})["code"] == "unknown"
        c.touch(1 << 12)
        c.until(lambda m: m["t"] == "state" and sounding(m))  # and it plays
        c.close()
    finally:
        p.terminate()
        p.wait(5)
        log.close()
