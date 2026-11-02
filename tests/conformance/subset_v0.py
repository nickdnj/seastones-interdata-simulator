"""Portable instruction subset v0, as ARCHITECTURE 5.7 defines it, for the S-3 random streams.

`m74-portable-1` = SIMH's 716 class minus all floating point, minus the list-processing
instructions ATL ABL RTL RBL, minus SVC and SINT, and without the PSW AIO, SQI and PRO
features. The 8/16-only instructions (SETMR, LPSR, SETM, LPS, double precision, STME,
LME) are already outside the 716 class.

This list is the conformance harness's own reading of section 5.7. The authoritative
file is `src/program/subset/m74-portable-1.txt` (SP-S5, provisional until checked
against the Model 74 manual 29-261); once it lands, `test_subset_matches_program_file`
in test_lockstep.py compares the two and fails on any drift.

Each entry: mnemonic -> (opcode, form). Forms follow id16_cpu.c's decode:
RR register-register, NO short (R1, N), RS register-storage (immediate, indexable),
RX register-memory.
"""

from __future__ import annotations

SUBSET_V0: dict[str, tuple[int, str]] = {
    # register-register
    "BALR": (0x01, "RR"),
    "BTCR": (0x02, "RR"),
    "BFCR": (0x03, "RR"),
    "NHR": (0x04, "RR"),
    "CLHR": (0x05, "RR"),
    "OHR": (0x06, "RR"),
    "XHR": (0x07, "RR"),
    "LHR": (0x08, "RR"),
    "CHR": (0x09, "RR"),
    "AHR": (0x0A, "RR"),
    "SHR": (0x0B, "RR"),
    "MHR": (0x0C, "RR"),
    "DHR": (0x0D, "RR"),
    "ACHR": (0x0E, "RR"),
    "SCHR": (0x0F, "RR"),
    "LBR": (0x93, "RR"),  # LDBR in the CPU source; SIMH's table names it LBR
    "EXBR": (0x94, "RR"),
    "WBR": (0x96, "RR"),
    "RBR": (0x97, "RR"),
    "WHR": (0x98, "RR"),
    "RHR": (0x99, "RR"),
    "WDR": (0x9A, "RR"),
    "RDR": (0x9B, "RR"),
    "MHUR": (0x9C, "RR"),
    "SSR": (0x9D, "RR"),
    "OCR": (0x9E, "RR"),
    "AIR": (0x9F, "RR"),
    # short format
    "BTBS": (0x20, "NO"),
    "BTFS": (0x21, "NO"),
    "BFBS": (0x22, "NO"),
    "BFFS": (0x23, "NO"),
    "LIS": (0x24, "NO"),
    "LCS": (0x25, "NO"),
    "AIS": (0x26, "NO"),
    "SIS": (0x27, "NO"),
    "SRLS": (0x90, "NO"),
    "SLLS": (0x91, "NO"),
    "STBR": (0x92, "NO"),
    "EPSR": (0x95, "NO"),
    # register-memory
    "STH": (0x40, "RX"),
    "BAL": (0x41, "RX"),
    "BTC": (0x42, "RX"),
    "BFC": (0x43, "RX"),
    "NH": (0x44, "RX"),
    "CLH": (0x45, "RX"),
    "OH": (0x46, "RX"),
    "XH": (0x47, "RX"),
    "LH": (0x48, "RX"),
    "CH": (0x49, "RX"),
    "AH": (0x4A, "RX"),
    "SH": (0x4B, "RX"),
    "MH": (0x4C, "RX"),
    "DH": (0x4D, "RX"),
    "ACH": (0x4E, "RX"),
    "SCH": (0x4F, "RX"),
    "AHM": (0x61, "RX"),
    "BXH": (0xC0, "RX"),
    "BXLE": (0xC1, "RX"),
    "LPSW": (0xC2, "RX"),
    "STM": (0xD0, "RX"),
    "LM": (0xD1, "RX"),
    "STB": (0xD2, "RX"),
    "LB": (0xD3, "RX"),  # LDB in the CPU source; LB in the table
    "CLB": (0xD4, "RX"),
    "AL": (0xD5, "RX"),
    "WB": (0xD6, "RX"),
    "RB": (0xD7, "RX"),
    "WH": (0xD8, "RX"),
    "RH": (0xD9, "RX"),
    "WD": (0xDA, "RX"),
    "RD": (0xDB, "RX"),
    "MHU": (0xDC, "RX"),
    "SS": (0xDD, "RX"),
    "OC": (0xDE, "RX"),
    "AI": (0xDF, "RX"),
    # register-storage (immediate)
    "THI": (0xC3, "RS"),
    "NHI": (0xC4, "RS"),
    "CLHI": (0xC5, "RS"),
    "OHI": (0xC6, "RS"),
    "XHI": (0xC7, "RS"),
    "LHI": (0xC8, "RS"),
    "CHI": (0xC9, "RS"),
    "AHI": (0xCA, "RS"),
    "SHI": (0xCB, "RS"),
    "SRHL": (0xCC, "RS"),
    "SLHL": (0xCD, "RS"),
    "SRHA": (0xCE, "RS"),
    "SLHA": (0xCF, "RS"),
    "RRL": (0xEA, "RS"),
    "RLL": (0xEB, "RS"),
    "SRL": (0xEC, "RS"),
    "SLL": (0xED, "RS"),
    "SRA": (0xEE, "RS"),
    "SLA": (0xEF, "RS"),
}

#: The 716-class instructions outside the subset, by reason (ARCHITECTURE 5.7).
EXCLUDED_716: dict[str, str] = {
    **{
        m: "floating point" for m in "LER CER AER SER MER DER FXR FLR STE LE CE AE SE ME DE".split()
    },
    **{m: "list processing" for m in "ATL ABL RTL RBL".split()},
    "SVC": "supervisor call",
    "SINT": "simulate interrupt",
}
