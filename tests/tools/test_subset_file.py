"""Checks on src/program/subset/m74-portable-1.txt (SP-S5 acceptance; HUM-22 reads it).

The header must cite the Model 74 manual page for the list or say "provisional, manual not found";
the body must be a subset of the 716 class with the documented exclusions.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUBSET = ROOT / "src" / "program" / "subset" / "m74-portable-1.txt"
TABLE = ROOT / "tools" / "cycles" / "cycles-716.tsv"

EXCLUDED = set(
    "LER CER AER SER MER DER LE CE AE SE ME DE STE "  # floating point: Models 70, 80 only
    "ATL ABL RTL RBL "  # list processing: Models 70, 80 only
    "WBR RBR WB RB "  # block I/O: Models 70, 80 only (added by S-5)
    "SVC SINT".split()  # on the 74, excluded by design
)


def entries() -> list[str]:
    return [
        line.split()[0]
        for line in SUBSET.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def class_716() -> set[str]:
    return {
        line.split("\t")[0]
        for line in TABLE.read_text().splitlines()
        if line and not line.startswith("#") and not line.startswith("mnemonic")
    }


def test_header_cites_the_manual_page_or_says_provisional() -> None:
    head = "\n".join(line for line in SUBSET.read_text().splitlines() if line.startswith("#"))
    cited = "29-261" in head and re.search(r"pp?\. ?A1-\d", head)
    assert cited or "provisional, manual not found" in head


def test_subset_is_the_716_class_minus_the_documented_exclusions() -> None:
    e = entries()
    assert len(e) == len(set(e)), "duplicate mnemonic"
    assert set(e) <= class_716()
    assert set(e) == class_716() - EXCLUDED
    assert len(e) == 90


def test_the_rig_program_needs_are_in_the_subset() -> None:
    # polled I/O on KEYS/DAC/GATE, halfword arithmetic, short branches and shifts (ARCHITECTURE 5.6)
    for (
        m
    ) in "OC OCR RD RDR WH WHR SS SSR LH LHR STH AH XHR THI BTC BFC BTBS BTFS LIS AIS SRLS".split():
        assert m in entries(), m
