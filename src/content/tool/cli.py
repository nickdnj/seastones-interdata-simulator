"""Command line for the content tool (CT-01).

    python -m content.tool build CONTENT_DIR OUT_DIR [--source usb|baked]
        Write OUT_DIR/index.json and OUT_DIR/report.txt. Exit 0 even when some files are
        broken (they become error cards; the station never stops for content), 2 only if
        the index could not be written.

    python -m content.tool check CONTENT_DIR
        Print every problem in plain English. Exit 1 if there is any error.

Run with ``src/`` on PYTHONPATH.
"""

from __future__ import annotations

import argparse
import sys

from .index import build, build_index, report
from .parse import load_content_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="content.tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write index.json and report.txt")
    b.add_argument("content_dir")
    b.add_argument("out_dir")
    b.add_argument("--source", default="usb")
    c = sub.add_parser("check", help="validate and print problems")
    c.add_argument("content_dir")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        try:
            index = build(args.content_dir, args.out_dir, args.source)
        except OSError as exc:
            print(f"content tool: could not write the index in {args.out_dir}: {exc.strerror}")
            return 2
        print(report(index), end="")
        return 0
    index = build_index(load_content_dir(args.content_dir), "check")
    print(report(index), end="")
    return 1 if index["counts"]["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
