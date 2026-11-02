"""VS-02: the engine's cycle table is generated from tools/cycles/cycles-716.tsv and carries its
STATUS label (ESTIMATE until a 7/16 source is cited, QA CNF-08)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "tools" / "cycles" / "gen-cycles-c.py"
TABLE_C = ROOT / "src" / "engine" / "machine" / "cycles_table.c"
TSV = ROOT / "tools" / "cycles" / "cycles-716.tsv"


def test_committed_table_matches_the_tsv() -> None:
    out = subprocess.run([sys.executable, str(GEN), "--check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_status_label_travels_into_the_engine() -> None:
    status = next(ln.split(":", 1)[1].strip() for ln in TSV.read_text().splitlines()
                  if ln.startswith("# STATUS:"))  # fmt: skip
    text = TABLE_C.read_text()
    assert f'const char sx_cycles_status[] = "{status}";' in text
    assert f"STATUS: {status}" in text
    assert status == "ESTIMATE", "a cited table must also update MACH-5's wording (CT-02)"
