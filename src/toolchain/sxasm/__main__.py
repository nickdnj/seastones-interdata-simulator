"""sxasm command line.

    python3 -m sxasm SOURCE.s [MORE.s ...] -o OUTDIR [--name rig] [--subset FILE]
                     [--map CHANNEL-MAP.md --dac DAC.md] [--no-blocks]

Sources are assembled as one unit, in the order given. Writes NAME.img.json, NAME.sym,
NAME.dep.sim and NAME.lst.json to OUTDIR only if assembly succeeds: an error writes nothing
(ASM-13: no partial image). Errors print as FILE:LINE: message and exit 1.

`--map` and `--dac` name the rig data the TABLE directive reads (PO-01, PO-05). Every
instruction must sit inside a `*@block` unless `--no-blocks` is given (PO-01, CODE-2).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from .asm import Assembler, SxasmError, load_subset
from .image import build
from .tables import RigDataError, RigTables


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sxasm", description="Interdata 7/16 subset assembler")
    ap.add_argument("sources", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--name", default="rig")
    ap.add_argument("--subset", type=Path, help="mnemonic list; anything else is an error")
    ap.add_argument("--map", type=Path, help="channel-map data file (TABLE channel-map)")
    ap.add_argument("--dac", type=Path, help="D/A model data file (TABLE pitch)")
    ap.add_argument("--no-blocks", action="store_true", help="allow code outside *@block")
    a = ap.parse_args(argv)
    subset = load_subset(a.subset) if a.subset else None
    tables = None
    if a.map or a.dac:
        if not (a.map and a.dac):
            print("sxasm: --map and --dac go together", file=sys.stderr)
            return 1
        try:
            tables = RigTables(a.map, a.dac)
        except RigDataError as e:
            print(f"sxasm: {e}", file=sys.stderr)
            return 1
    asm = Assembler(subset, tables=tables, require_blocks=not a.no_blocks)
    try:
        for src in a.sources:
            asm.parse(src.name, src.read_text(encoding="utf-8"))
        asm.assemble()
    except SxasmError as e:
        print(f"sxasm: {e}", file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError) as e:
        print(f"sxasm: {e}", file=sys.stderr)
        return 1
    outputs = build(asm, a.name, [s.name for s in a.sources], a.subset.name if a.subset else None)
    a.out.mkdir(parents=True, exist_ok=True)
    for fname, text in outputs.items():  # write-then-rename: never a partial file
        fd, tmp = tempfile.mkstemp(dir=a.out, prefix=f".{fname}.")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, a.out / fname)
    return 0


if __name__ == "__main__":
    sys.exit(main())
