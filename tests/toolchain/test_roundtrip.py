"""VS-08 acceptance: sxasm round trip against stock id16 (ASM-01, ASM-10).

For every entry of SIMH's instruction table, several random instances are assembled, loaded
into stock `id16` with the generated `rig.dep.sim`, and disassembled with `ex -m`. The
disassembled text is then assembled again at the same address: it must give exactly the
same words, and name the same base instruction as the source.

Three documented SIMH disassembler quirks are mapped, not hidden:
1. forward short branches print with the backward mnemonic (BTFS as BTBS, BFFS as BFBS;
   the target address is correct), and extended short mnemonics (BOS, BLS, ...) name the
   backward base whichever way they go;
2. an extended mnemonic prints for any base instruction whose fields match it (BFC 0,X
   prints as B X), because `fprint_sym` takes the first table match;
3. a zero-distance short branch (N = 0) prints the same text with or without the
   direction bit, so re-assembly may flip that bit; with N = 0 it changes nothing.

Provisional on the S-3 decision (SP-S3D).
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "toolchain"))
sys.path.insert(0, str(ROOT / "tests" / "conformance"))

import lockstep as L  # noqa: E402
from sxasm import Assembler, build, by_name, canonical, table  # noqa: E402

pytestmark = [
    pytest.mark.lockstep,
    pytest.mark.skipif(not Path(L.engine_path()).exists(), reason="engine not built"),
]

BASE = 0x1000
STRIDE = 8
VARIANTS = 6


def operands(op, addr: int, rng: random.Random) -> str:
    r = rng.randrange
    reg = lambda even=False: f"R{r(8) * 2 if even else r(16)}"  # noqa: E731
    a = rng.choice([0, 1, 0x7FFF, 0x8000, 0xFFFE, r(0x10000)]) & ~0  # any 16-bit value
    idx = f"(R{r(1, 16)})" if rng.random() < 0.5 else ""
    c = op.cls
    if c == "MR":
        return f"{r(16)},{reg()}"
    if c in ("RR", "FF"):
        return f"{reg(c == 'FF')},{reg(c == 'FF')}"
    if c == "R":
        return reg()
    if c == "MX":
        return f"{r(16)},X'{a:X}'{idx}"
    if c in ("RX", "FX"):
        return f"{reg(c == 'FX')},X'{a:X}'{idx}"
    if c == "X":
        return f"X'{a:X}'{idx}"
    if c == "SI":
        return f"{reg()},{r(16)}"
    n = r(16)
    if c == "SB":
        target = addr + 2 * n if op.base & 0x0100 else addr - 2 * n
        return f"{r(16)},X'{target:X}'"
    target = addr + (2 * n if rng.random() < 0.5 else -2 * n)  # SX: either way
    return f"X'{target:X}'"


def generate(seed: int) -> list[tuple[int, str]]:
    rng = random.Random(seed)
    lines, addr = [], BASE
    for op in table():
        for _ in range(VARIANTS):
            lines.append((addr, f"       {op.mnemonic:<6} {operands(op, addr, rng)}"))
            addr += STRIDE
    return lines


def assemble_at(items: list[tuple[int, str]]) -> Assembler:
    a = Assembler()
    a.parse("rt.s", "".join(f"       ORG   X'{at:X}'\n{text}\n" for at, text in items))
    a.assemble()
    return a


def to_source(addr: int, text: str) -> str:
    """`ex -m` text back to sxasm source: bare hex becomes X'..', and the forward short
    branch quirk is undone (BTBS/BFBS with a forward target are BTFS/BFFS)."""
    mnem, _, ops = text.partition(" ")

    def conv(m: re.Match) -> str:
        t = m.group(0)
        return t if re.fullmatch(r"R\d+", t) else f"X'{t}'"

    ops = re.sub(r"[0-9A-Z]+", conv, ops)
    if mnem in ("BTBS", "BFBS"):
        target = int(re.search(r"X'([0-9A-F]+)'$", ops).group(1), 16)
        if target > addr:
            mnem = {"BTBS": "BTFS", "BFBS": "BFFS"}[mnem]
    return f"       {mnem:<6} {ops}"


FOLD = {"BTFS": "BTBS", "BFFS": "BFBS"}


def family(mnemonic: str) -> str:
    """The base instruction, with the two short-branch directions folded together (an
    extended short mnemonic such as BOS names the backward form whichever way it goes)."""
    c = canonical(by_name()[mnemonic])
    return FOLD.get(c, c)


def zero_distance_short(w: int) -> bool:
    return (w >> 10) == 0x08 and (w & 0x000F) == 0  # BTBS BTFS BFBS BFFS, N = 0


def dep_ops(dep_sim: str) -> list[tuple]:
    ops: list[tuple] = []
    for ln in dep_sim.splitlines():
        _, where, val = ln.split()
        if where in ("pc", "psw"):
            ops.append(("reg", where.upper(), int(val, 16)))
        else:
            ops.append(("dep", int(where, 16), int(val, 16)))
    return ops


@pytest.mark.parametrize("seed", [1974, 1975])
def test_round_trip_every_table_entry(seed: int) -> None:
    items = generate(seed)
    asm = assemble_at(items)
    words = {ln.addr: ln.words for ln in asm.lines if ln.words}
    out = build(asm, "rt", ["rt.s"], None)
    ops = [("mem", 65536)] + dep_ops(out["rt.dep.sim"])
    ops += [("disasm", at, at) for at, _ in items]
    text = {}
    for ln in L.normalise(L.run_oracle(ops)):
        m = re.match(r"^([0-9A-F]+):\t(.*)$", ln)
        if m:
            text[int(m.group(1), 16)] = m.group(2)
    assert len(text) == len(items), f"oracle printed {len(text)} of {len(items)} lines"
    failures = []
    for at, src in items:
        dis = text[at]
        back = to_source(at, dis)
        try:
            again = assemble_at([(at, back)])
            got = next(ln.words for ln in again.lines if ln.words)
        except Exception as e:  # noqa: BLE001 - report every failure with both texts
            failures.append(f"{at:04X}: source {src.strip()!r} -> ex -m {dis!r}: {e}")
            continue
        same = got == words[at]
        if not same and zero_distance_short(words[at][0]) and got[0] ^ words[at][0] == 0x0100:
            same = True  # quirk 3: N = 0, so the lost direction bit changes nothing
        if not same or family(src.split()[0]) != family(back.split()[0]):
            failures.append(
                f"{at:04X}: source {src.strip()!r} {words[at]} -> ex -m {dis!r} -> {got}"
            )
    assert not failures, f"{len(failures)} round-trip failures:\n" + "\n".join(failures[:20])


def test_program_in_memory_is_the_program_assembled() -> None:
    """ASM-10: rig.dep.sim loaded into the oracle and into the engine gives memory equal to
    the image's segments."""
    asm = assemble_at(generate(1976)[:400])
    out = build(asm, "rt", ["rt.s"], None)
    lo = BASE
    hi = BASE + 400 * STRIDE
    ops = [("mem", 65536)] + dep_ops(out["rt.dep.sim"]) + [("exmem", lo, hi)]
    oracle, engine = L.normalise(L.run_oracle(ops)), L.normalise(L.run_engine(ops))
    assert oracle == engine
    mem = {int(a, 16): int(v, 16) for a, v in (ln.split(":\t") for ln in oracle)}
    for ln in asm.lines:
        for i, w in enumerate(ln.words):
            assert mem[ln.addr + 2 * i] == w, f"{ln.addr + 2 * i:04X}"
