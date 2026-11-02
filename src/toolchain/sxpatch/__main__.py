"""sxpatch command line.

    python3 -m sxpatch FILE.patch.json [MORE ...] [-o OUTDIR]

Checks each patch and prints every problem as FILE:LINE: level: message. With -o, writes
OUTDIR/<slug>.graph (seastones.graph/1, for `sx-render --graph`) and OUTDIR/<slug>.sr (the
switch register the preset pairs with, hex) for each patch with no error. Exit 1 if any
patch has an error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .patch import compile_graph, load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sxpatch", description="seastones.patch/1 checker")
    ap.add_argument("patches", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    rc = 0
    for p in a.patches:
        problems, flat = load(p)
        for pr in problems:
            print(pr)
        if any(pr.level == "error" for pr in problems):
            rc = 1
            continue
        if a.out:
            a.out.mkdir(parents=True, exist_ok=True)
            slug = p.name.removesuffix(".patch.json")
            (a.out / f"{slug}.graph").write_text(compile_graph(flat))
            (a.out / f"{slug}.sr").write_text(f"{flat['program']['sr']:04X}\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
