"""SP-S3A: `make oracle` builds the stock id16 named by deploy/simh.pin."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_make_oracle_builds_the_pinned_banner() -> None:
    out = subprocess.run(["make", "-s", "oracle"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    oracle = Path(out.stdout.strip().splitlines()[-1])
    assert oracle.is_file(), oracle
    assert "c0f0a8877e222ed85c0bbafe83b42816402f7428" in str(oracle), "not the pinned build"
    run = subprocess.run([str(oracle)], input="", capture_output=True, text=True, timeout=10)
    first = next(ln for ln in run.stdout.splitlines() if ln.strip())
    assert first == "Interdata 16b simulator V3.12-3"
    assert (oracle.parent / ".pinned-at").read_text().strip() == (
        "c0f0a8877e222ed85c0bbafe83b42816402f7428"
    )
