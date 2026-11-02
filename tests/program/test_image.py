"""PO-07 (MACH-4, NFR-13; ASM-02, ASM-03, ASM-12): the program image is a pure function of the
source and the rig data. Two separate assemblies, in fresh processes and directories, give
byte-identical outputs; the image holds only our own assembled ranges (code at X'0080', the
tables from X'1000'), nothing below X'0080' and nothing from any Interdata file.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = ["rig.s", "scan.s", "voices.s", "routines.s", "score.s", "memory.s", "tables.s"]


def build(out: Path, mapfile: str) -> dict[str, str]:
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src" / "toolchain"), PYTHONHASHSEED="1")
    src = [str(ROOT / "src" / "program" / n) for n in PROGRAM]
    subprocess.run(
        [sys.executable, "-m", "sxasm", *src, "-o", str(out), "--name", "rig",
         "--subset", str(ROOT / "src" / "program" / "subset" / "m74-portable-1.txt"),
         "--map", str(ROOT / "src" / "program" / "rig" / mapfile),
         "--dac", str(ROOT / "src" / "program" / "rig" / "dac.md")],
        check=True, cwd=out.parent, env=env,
    )  # fmt: skip
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    for mapfile in ("channel-map.md", "channel-map-8.md"):
        a = build(tmp_path / f"a-{mapfile}" / "out", mapfile)
        b = build(tmp_path / f"b-{mapfile}" / "out", mapfile)
        assert a == b and set(a) == {"rig.img.json", "rig.lst.json", "rig.sym", "rig.dep.sim"}


def test_the_image_holds_only_our_ranges(tmp_path: Path) -> None:
    out = tmp_path / "x" / "out"
    build(out, "channel-map.md")
    img = json.loads((out / "rig.img.json").read_text())
    spans = [
        (int(s["addr"], 16), int(s["addr"], 16) + 2 * len(s["words"])) for s in img["segments"]
    ]
    assert spans[0][0] == 0x0080 and spans[0][1] <= 0x1000, "code at X'0080', under X'1000'"
    assert all(0x1000 <= lo and hi <= 0x2000 for lo, hi in spans[1:]), "tables in X'1000'-X'1FFF'"
    assert img["sources"] == PROGRAM and img["subset"] == "m74-portable-1.txt"
    text = (out / "rig.lst.json").read_text().lower()
    assert "copyright" not in text or "nick" in text  # no Interdata source was assembled
