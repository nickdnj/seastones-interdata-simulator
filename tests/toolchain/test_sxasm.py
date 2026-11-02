"""VS-07 acceptance: sxasm core (ASM-04, ASM-05, ASM-09, ASM-13 short form).

Provisional on the S-3 decision (SP-S3D).
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "toolchain"))

from sxasm import Assembler, SxasmError, build, by_name, canonical, table, validate  # noqa: E402
from sxasm.__main__ import main as sxasm_main  # noqa: E402

SAMPLE = """\
* A 20-line sample using every addressing form in the subset (VS-07 AC 1).
*@block sample
       ORG   X'0080'
START  LHI   R1,X'20'           RS immediate
       LHI   R2,MASK(R3)        RS immediate, indexed
       LHR   R4,R2              RR
       LIS   R5,7               short immediate
       BTCR  3,R6               RR with a condition mask
       LH    R7,DATA            RX direct
       STH   R7,DATA+2(R1)      RX indexed, expression
       BTC   2,NEXT             RX with a condition mask
LOOP   SIS   R5,1               short immediate
       BTBS  2,LOOP             short branch back
       BTFS  1,NEXT             short branch forward
NEXT   OC    R1,CMD             I/O, RX
       WHR   R1,R2              I/O, RR
       RD    R1,DATA            I/O read to memory
       EPSR  R8,R9              PSW
       LPSW  NEWPSW             memory only (X class)
       B     START              extended mnemonic
MASK   EQU   X'00FF'
CMD    DC    X'4100'
DATA   DC    0,C'AB',-1
NEWPSW DC    0,START
       END   START
"""


def assemble(src: str, subset=None) -> Assembler:
    a = Assembler(subset)
    a.parse("t.s", src)
    a.assemble()
    return a


def test_mnemonics_equal_the_vendored_table() -> None:
    """ASM-04: an independent parse of id16_sys.c gives exactly the assembler's mnemonics."""
    text = (ROOT / "src/engine/simh/Interdata/id16_sys.c").read_text(encoding="latin-1")
    body = re.search(r"opcode\[\]\s*=\s*\{(.*?)\};", text, re.S).group(1)
    names = set(re.findall(r'"([A-Z0-9]+)"', body))
    assert names == set(by_name()), "sxasm's mnemonics drifted from SIMH's table"
    assert len(table()) == 183


def test_sample_assembles_with_every_form() -> None:
    a = assemble(SAMPLE)
    forms = {by_name()[ln.opc].cls for ln in a.lines if ln.opc in by_name()}
    assert forms >= {"RR", "MR", "RX", "MX", "X", "SI", "SB"}
    words = {ln.text.split()[0] if ln.label else ln.opc: ln.words for ln in a.lines}
    assert words["START"] == [0xC810, 0x0020]
    assert a.symbols["MASK"] == 0xFF and a.symbols["START"] == 0x80
    assert a.entry == 0x80


def outputs(src: str) -> dict[str, str]:
    a = assemble(src)
    return build(a, "rig", ["t.s"], None)


#: Pinned on the developer Mac (2026-10-31). The CI matrix must produce the same bytes.
SAMPLE_SHA256 = "a1b47c099c2910a569c3a5b14d4fe0c52ad12fd8a7b1b138bf05a2b70ce091b9"


def test_output_is_deterministic() -> None:
    first, second = outputs(SAMPLE), outputs(SAMPLE)
    assert first == second
    img = json.loads(first["rig.img.json"])
    assert img["sha256"] == SAMPLE_SHA256, img["sha256"]
    assert not re.search(r"\d{4}-\d{2}-\d{2}", "".join(first.values()))


@pytest.mark.parametrize(
    "src, message",
    [
        ("       FOO   R1,R2\n", "t.s:1: unknown mnemonic 'FOO'"),
        ("       LHR   R1,R16\n", "t.s:1: bad register 'R16'"),
        ("A      LIS   R1,1\nA      LIS   R1,2\n", "t.s:2: duplicate label 'A'"),
        ("       LH    R1,NOWHERE\n", "t.s:1: undefined symbol 'NOWHERE'"),
        ("       LIS   R1,16\n", "t.s:1: short immediate '16' out of range"),
        ("X      BTFS  1,X+40\n", "t.s:1: short branch target 'X+40' out of reach"),
        ("X      BTBS  1,X+4\n", "t.s:1: BTBS cannot branch forward"),
        ("       LHR   R1\n", "t.s:1: LHR takes 2 operand(s), got 1"),
        ("       DC    C'AB\n", "t.s:1: unterminated quote"),
        ("       ORG   1\n", "t.s:1: ORG must be even"),
        ("       BTC   16,0\n", "t.s:1: condition mask '16' out of range"),
        ("       LER   1,2\n", "floating-point register '1' must be even"),
        ("       LH    R1,(R2\n", "bad expression"),
    ],
)
def test_errors_name_file_and_line(src: str, message: str) -> None:
    with pytest.raises(SxasmError) as e:
        assemble(src)
    assert message in str(e.value)


def test_forward_references_and_directives() -> None:
    a = assemble(
        "       B     LATER\n       DS    5\nLATER  DC    H'-2',X'7FFF',C'Z'\nV      EQU   LATER+2\n"
    )
    assert a.symbols["LATER"] == 4 + 6 and a.symbols["V"] == 12
    assert a.lines[0].words == [0x4300, 10]
    assert a.lines[2].words == [0xFFFE, 0x7FFF, 0x5A20]


def test_subset_is_enforced() -> None:
    subset = {"LHI", "LHR", "BFC"}
    a = assemble("       LHI   R1,1\n       B     0\n", subset)  # B is BFC 0
    assert a.lines[1].words == [0x4300, 0]
    with pytest.raises(SxasmError, match="MHR .* outside the active subset"):
        assemble("       MHR   R2,R3\n", subset)
    assert canonical(by_name()["BES"]) == "BFBS" and canonical(by_name()["LPSW"]) == "LPSW"


def test_image_validates_and_tampering_is_caught() -> None:
    img = json.loads(outputs(SAMPLE)["rig.img.json"])
    assert validate(img) == []
    img["segments"][0]["words"][1] = "0021"
    assert any("image_hash_mismatch" in p for p in validate(img))
    assert validate({"format": "x"})  # wrong format and missing fields


def test_cli_writes_all_outputs_or_nothing(tmp_path: Path) -> None:
    good, bad = tmp_path / "good.s", tmp_path / "bad.s"
    good.write_text(SAMPLE)
    bad.write_text(SAMPLE.replace("       END   START", "       NOPE  1\n       END   START"))
    assert sxasm_main([str(good), "-o", str(tmp_path / "out")]) == 0
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "rig.dep.sim",
        "rig.img.json",
        "rig.lst.json",
        "rig.sym",
    ]
    assert sxasm_main([str(bad), "-o", str(tmp_path / "out2")]) == 1
    assert not (tmp_path / "out2").exists()
    dep = (tmp_path / "out" / "rig.dep.sim").read_text()
    assert dep.startswith("dep 080 C810\n") and dep.endswith("dep pc 80\ndep psw 0\n")


def test_cli_runs_as_a_module(tmp_path: Path) -> None:
    (tmp_path / "a.s").write_text(SAMPLE)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src" / "toolchain"))
    out = subprocess.run(
        [sys.executable, "-m", "sxasm", str(tmp_path / "a.s"), "-o", str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr


FUZZ = int(os.environ.get("SX_ASM_FUZZ", "2000"))  # nightly: 100000 (ASM-13)


def test_fuzzed_sources_never_crash_or_write_partially(tmp_path: Path) -> None:
    rng = random.Random(1974)
    print(f"fuzz seed 1974, {FUZZ} mutations")
    alphabet = "ABCRX0123456789'(),+-* \t\n"
    for i in range(FUZZ):
        s = list(SAMPLE)
        for _ in range(rng.randint(1, 8)):
            k = rng.randrange(len(s))
            op = rng.random()
            if op < 0.4:
                s[k] = rng.choice(alphabet)
            elif op < 0.7:
                del s[k]
            else:
                s.insert(k, rng.choice(alphabet))
        src = "".join(s)
        try:
            assemble(src)
        except SxasmError:
            pass  # a clean, located error is the only acceptable failure
        if i % 500 == 0:  # the CLI path: never a partial output directory
            f = tmp_path / f"f{i}.s"
            f.write_text(src)
            out = tmp_path / f"o{i}"
            if sxasm_main([str(f), "-o", str(out)]) != 0:
                assert not out.exists()
