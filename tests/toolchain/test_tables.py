"""PO-01, PO-05: sxasm's TABLE directive and block rule, and the rig data parser (ASM-06, CNT-08).

The program-level checks (both channel maps, image differs only in the map) are in
tests/program/test_poly.py; these are the assembler's own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "toolchain"))

from sxasm import Assembler, RigDataError, RigTables, SxasmError  # noqa: E402
from sxasm.tables import CHANNEL_MAP_WORDS, pitch_code, read_dac  # noqa: E402

RIG = ROOT / "src" / "program" / "rig"


def asm(src: str, tables=None, blocks: bool = True) -> Assembler:
    a = Assembler(tables=tables, require_blocks=blocks)
    a.parse("t.s", src)
    a.assemble()
    return a


def test_table_emits_generated_words_at_its_label() -> None:
    t = RigTables(RIG / "channel-map.md", RIG / "dac.md")
    a = asm(
        "*@block b\n         ORG   X'1000'\nP        TABLE pitch\nM        TABLE channel-map\n", t
    )
    words = [w for ln in a.lines for w in ln.words]
    assert a.symbols["P"] == 0x1000 and a.symbols["M"] == 0x1000 + 256
    assert words[60] == 0x6400  # C4 is 4 V
    assert len(words) == 128 + CHANNEL_MAP_WORDS
    m = words[128:]
    assert m[0] == 4 and m[1] == 1  # four voices, gates on the D/A
    assert m[2:6] == [0x80, 0x81, 0x82, 0x83] and m[10:14] == [0x84, 0x85, 0x86, 0x87]
    assert m[18] == 0x7D00  # 5.0 V


def test_first_and_last_set_bit_tables() -> None:
    t = RigTables(RIG / "channel-map.md", RIG / "dac.md")
    first = t.words("first-set-bit")
    last = t.words("last-set-bit")
    byte = lambda ws, i: (ws[i // 2] >> (8 if i % 2 == 0 else 0)) & 0xFF  # noqa: E731
    assert byte(first, 0x80) == 0 and byte(first, 0x01) == 7 and byte(first, 0x00) == 0xFF
    assert byte(last, 0x81) == 7 and byte(last, 0x80) == 0 and byte(last, 0x30) == 3


def test_word_bits_never_changes_the_pitch_table(tmp_path: Path) -> None:
    """MACH-3: the table is for an ideal 16-bit converter, so only range_v moves it."""
    d8 = tmp_path / "dac.md"
    d8.write_text((RIG / "dac.md").read_text().replace("word_bits: 12", "word_bits: 8"))
    a = RigTables(RIG / "channel-map.md", RIG / "dac.md").words("pitch")
    b = RigTables(RIG / "channel-map.md", d8).words("pitch")
    assert a == b and read_dac(d8).word_bits == 8
    assert pitch_code(72, 10.24) == 0x7D00 and pitch_code(72, 5.12) == 0xFA00


def test_table_needs_rig_data_and_a_known_name() -> None:
    with pytest.raises(SxasmError, match=r"t.s:2: TABLE 'pitch': no rig data"):
        asm("*@block b\nP        TABLE pitch\n")
    t = RigTables(RIG / "channel-map.md", RIG / "dac.md")
    with pytest.raises(SxasmError, match=r"t.s:2: TABLE 'chords': known tables"):
        asm("*@block b\nP        TABLE chords\n", t)


def test_code_outside_a_block_fails_with_file_and_line() -> None:
    with pytest.raises(SxasmError, match=r"t.s:1: LHI is outside any \*@block"):
        asm("         LHI   R1,0\n*@block b\n         LHI   R2,0\n")
    asm("         LHI   R1,0\n", blocks=False)  # allowed when not required


def test_dac_file_errors_are_plain_english(tmp_path: Path) -> None:
    bad = tmp_path / "dac.md"
    bad.write_text("word_bits: twelve\nrange_v: 10.24\noutput_hz: 2000\nstrobe_hz: 1000\n")
    with pytest.raises(RigDataError, match=r"dac.md:1: 'word_bits' should be a number"):
        read_dac(bad)
    bad.write_text("word_bits: 12\nrange_v: 10.24\noutput_hz: 2000\n")
    with pytest.raises(RigDataError, match=r"the 'strobe_hz:' line is missing"):
        read_dac(bad)
