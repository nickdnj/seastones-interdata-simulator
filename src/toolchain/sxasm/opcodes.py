"""The Interdata 16b instruction table, parsed out of the vendored SIMH disassembler.

ADR-004 and VS-07: `sxasm` takes its mnemonics, opcode values and operand classes from
`src/engine/simh/Interdata/id16_sys.c` (the `opcode[]`, `opc_val[]` and `masks[]` tables
that `fprint_sym` uses), so the assembler and the disassembler the code view shows can
never drift apart (ASM-04).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SYS_C = ROOT / "src" / "engine" / "simh" / "Interdata" / "id16_sys.c"

# Operand classes, in the order id16_sys.c numbers them (I_V_MR = 0 ... I_V_SX = 0xA).
CLASSES = ["MR", "RR", "R", "MX", "RX", "X", "FF", "FX", "SI", "SB", "SX"]


@dataclass(frozen=True)
class Op:
    mnemonic: str
    base: int  # the 16-bit pattern with every fixed field set
    cls: str  # one of CLASSES
    mask: int  # bits of the first halfword that identify the instruction

    @property
    def opcode(self) -> int:
        return self.base >> 8

    @property
    def words(self) -> int:
        return 2 if self.cls in ("MX", "RX", "X", "FX") else 1


def _c_array(text: str, name: str) -> str:
    m = re.search(rf"{name}\s*\[\]\s*=\s*\{{(.*?)\}};", text, flags=re.S)
    if not m:
        raise RuntimeError(f"{SYS_C}: no {name}[] table")
    return re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)


@lru_cache(maxsize=1)
def table() -> tuple[Op, ...]:
    text = SYS_C.read_text(encoding="latin-1")
    names = re.findall(r'"([A-Z0-9]+)"', _c_array(text, "opcode"))
    vals = re.findall(r"0x([0-9A-Fa-f]{4})(?:\+I_([A-Z]+))?", _c_array(text, "opc_val"))
    masks = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{4})", _c_array(text, "masks"))]
    vals = [(int(v, 16), c) for v, c in vals if c]  # drop the 0xFFFF terminator
    if len(names) != len(vals):
        raise RuntimeError(f"{SYS_C}: {len(names)} names but {len(vals)} values")
    return tuple(
        Op(n, v, c, masks[CLASSES.index(c)]) for n, (v, c) in zip(names, vals, strict=True)
    )


@lru_cache(maxsize=1)
def by_name() -> dict[str, Op]:
    out: dict[str, Op] = {}
    for op in table():
        out.setdefault(op.mnemonic, op)
    return out


def canonical(op: Op) -> str:
    """The base instruction an extended mnemonic stands for (B -> BFC, BES -> BFBS, BER ->
    BFCR); a base instruction maps to itself. Used for the subset check."""
    if op.cls in ("R", "SX", "X"):
        for o in table():
            if o.opcode == op.opcode and o.cls in ("MR", "RR", "MX", "RX", "SB"):
                return o.mnemonic
    return op.mnemonic  # includes the true X-class instructions: LPSW, AL, LPS
