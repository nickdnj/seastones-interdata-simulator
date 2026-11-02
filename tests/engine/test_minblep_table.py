"""VS-30 / ADR-010: CI regenerates the VCO kernel table and it is byte-identical to the
committed src/engine/dsp/minblep_tables.c. A change is a golden-render re-bless, never drift."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "tools" / "dsp" / "gen-minblep.py"
TABLE = ROOT / "src" / "engine" / "dsp" / "minblep_tables.c"


@pytest.mark.skipif(
    importlib.util.find_spec("numpy") is None,
    reason="UNVERIFIED: numpy missing (make ci-deps installs it); run tools/dsp/gen-minblep.py --check",
)
def test_regenerated_table_is_byte_identical(tmp_path: Path) -> None:
    out = tmp_path / "minblep_tables.c"
    subprocess.run([sys.executable, str(GEN), "-o", str(out)], check=True, capture_output=True)
    assert out.read_bytes() == TABLE.read_bytes(), "regenerate with tools/dsp/gen-minblep.py"


def test_table_header_names_its_parameters() -> None:
    head = TABLE.read_text().split("*/", 1)[0]
    for word in ("oversampling 64", "span 32", "cutoff 0.875", "real cepstrum", "SHA-256"):
        assert word in head, word
