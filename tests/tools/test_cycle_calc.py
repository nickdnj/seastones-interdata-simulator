"""Tests for tools/cycle-calc.py and tools/cycles/cycles-716.tsv (SP-S4B; QA CNF-08 in its
pre-engine form: every 716-class opcode has an integer cost, and the header cites a source or says
ESTIMATE).

When the pinned open-simh source is reachable (SX_SIMH_DIR, or the dev cache
~/.cache/seastones/open-simh), the opcode list is cross-checked against id16_cpu.c's decode ROM.
Otherwise the frozen list below is used and that cross-check is skipped with a message.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cycle_calc", ROOT / "tools" / "cycle-calc.py")
cc = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
assert spec and spec.loader
sys.modules["cycle_calc"] = cc
spec.loader.exec_module(cc)

TABLE = ROOT / "tools" / "cycles" / "cycles-716.tsv"
SKETCH = ROOT / "tools" / "cycles" / "sketches" / "scan-37.txt"

# The 113 mnemonics SIMH accepts on the 716 class (decrom[] without OP_816/OP_816E), SIMH spelling.
FROZEN_716 = set(
    "BALR BTCR BFCR NHR CLHR OHR XHR LHR CHR AHR SHR MHR DHR ACHR SCHR BTBS BTFS BFBS BFFS LIS LCS AIS SIS "
    "LER CER AER SER MER DER STH BAL BTC BFC NH CLH OH XH LH CH AH SH MH DH ACH SCH STE AHM ATL ABL RTL RBL "
    "LE CE AE SE ME DE SRLS SLLS STBR LBR EXBR EPSR WBR RBR WHR RHR WDR RDR MHUR SSR OCR AIR BXH BXLE LPSW "
    "THI NHI CLHI OHI XHI LHI CHI AHI SHI SRHL SLHL SRHA SLHA STM LM STB LB CLB AL WB RB WH RH WD RD MHU SS "
    "OC AI SVC SINT RRL RLL SRL SLL SRA SLA".split()
)


def simh_dir() -> Path | None:
    for p in (
        os.environ.get("SX_SIMH_DIR"),
        str(Path.home() / ".cache" / "seastones" / "open-simh"),
    ):
        if p and (Path(p) / "Interdata" / "id16_cpu.c").exists():
            return Path(p)
    return None


def test_table_covers_every_716_opcode_with_integer_costs() -> None:
    t = cc.load_table(TABLE)
    assert set(t.rows) == FROZEN_716
    assert len(t.rows) == 113
    for c in t.rows.values():
        assert isinstance(c.base_ns, int) and c.base_ns > 0
        assert c.per_n_ns >= 0 and c.taken_ns >= 0
        assert c.form in {"RR", "SF", "RS", "RX"}
        assert c.conf in {"read", "unclear", "class", "estimate"}


def test_header_says_estimate_or_cites_a_7_16_source() -> None:
    text = TABLE.read_text()
    status = re.search(r"^#\s*STATUS:\s*(\S+)", text, re.M)
    assert status, "the table must carry a STATUS line"
    if status.group(1) != "ESTIMATE":
        assert re.search(r"7/16.*(Reference|Processor|User).*Manual.*p", text), (
            "non-estimate needs a 7/16 citation"
        )
    assert "29-261R01" in text and "A5-1" in text  # the proxy source is cited with pages
    assert cc.load_table(TABLE).status == "ESTIMATE"


def test_opcode_list_matches_pinned_simh_decode_rom() -> None:
    d = simh_dir()
    if d is None:
        pytest.skip("pinned open-simh not found (set SX_SIMH_DIR); frozen list used instead")
    src = (d / "Interdata" / "id16_cpu.c").read_text()
    body = src[src.index("const uint16 decrom[256]") :]
    body = body[body.index("{") + 1 : body.index("};")]
    names = set()
    for line in body.splitlines():
        m = re.match(r"\s*(.*?),?\s*/\*\s*(\w+)\s*\*/", line)
        if m and m.group(1) not in ("0",) and "OP_816" not in m.group(1):
            names.add({"LDBR": "LBR", "LDB": "LB"}.get(m.group(2), m.group(2)))
    assert names == FROZEN_716


def test_sketch_costs_add_up_by_hand() -> None:
    t = cc.load_table(TABLE)
    items, _ = cc.parse_sketch("LHR x3\nSRLS n=2\nBTBS taken\nBTBS\n")
    r = cc.compute(items, t)
    assert r.instructions == 6
    assert r.total_ns == 3 * 1500 + (3250 + 2 * 1250) + 4000 + 2000


def test_expressions_and_overrides() -> None:
    items, env = cc.parse_sketch("set N = 4\nset C = 2\nLH x(N*C)\nAIS x(N-1)\n", {"N": 8})
    assert env == {"N": 8, "C": 2}
    assert [i.count for i in items] == [16, 7]


def test_unknown_mnemonic_and_bad_taken_are_errors() -> None:
    t = cc.load_table(TABLE)
    with pytest.raises(KeyError):
        cc.compute(cc.parse_sketch("LDR\n")[0], t)  # 8/16 double precision: not a 7/16 instruction
    with pytest.raises(ValueError):
        cc.compute(cc.parse_sketch("LHR taken\n")[0], t)
    with pytest.raises(ValueError):
        cc.parse_sketch("LHR x(__import__('os'))\n")


def test_listing_json_input() -> None:
    t = cc.load_table(TABLE)
    items = cc.parse_listing(
        {
            "instructions": [
                {"mnemonic": "lh", "count": 2, "block": "b"},
                {"mnemonic": "BFC", "taken": True},
            ]
        }
    )
    r = cc.compute(items, t)
    assert r.total_ns == 2 * 3250 + 3500 and set(r.blocks) == {"b", "(none)"}


def test_draft_scan_loop_prints_a_period(capsys: pytest.CaptureFixture[str]) -> None:
    assert cc.main([str(SKETCH), "--set", "C=1", "--set", "R=1", "--set", "S=1"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"period [\d.]+ us at RUN \(ESTIMATE", out)


def test_idle_scan_is_inside_the_estimate_band() -> None:
    items, _ = cc.parse_sketch(SKETCH.read_text(), {"C": 0, "R": 0, "S": 0})
    r = cc.compute(items, cc.load_table(TABLE))
    kips = r.instructions / (r.total_ns / 1e9) / 1000
    assert 250 <= kips <= 450  # consistent with ARCHITECTURE 2.1's 250-450 k instructions/s


def test_fail_over_budget_flag() -> None:
    assert cc.main([str(SKETCH), "--set", "C=37", "--set", "R=5", "--fail-over-budget"]) == 1
