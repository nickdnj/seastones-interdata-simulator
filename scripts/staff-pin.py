#!/usr/bin/env python3
"""Set the staff PIN on a station (KP-07; docs/OPERATIONS.md). The PIN is never in the repo.

Writes ``sha256:<hex>`` of the PIN (the form rigd's ``--staff-pin-file`` accepts, see
src/rigd/staff.py) to the file, atomically, readable by its owner and group only. rigd reads
it at start, so restart the station afterwards.

    sudo python3 scripts/staff-pin.py /data/staff-pin                      (Linux station)
    python3 scripts/staff-pin.py /Users/Shared/Seastones/data/staff-pin   (macOS station)

It asks twice and never echoes. 4 to 8 digits. ``--stdin`` reads one line instead (tests).
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="staff-pin.py")
    ap.add_argument("file")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--group", default="seastones", help="when run as root: the file's group")
    args = ap.parse_args(argv)
    if args.stdin:
        pin = sys.stdin.readline().strip()
    else:
        pin = getpass.getpass("New staff PIN (4 to 8 digits): ").strip()
        if getpass.getpass("The same PIN again: ").strip() != pin:
            print("staff-pin: the two PINs differ; nothing was changed", file=sys.stderr)
            return 1
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        print("staff-pin: the PIN must be 4 to 8 digits; nothing was changed", file=sys.stderr)
        return 1
    path = os.path.abspath(args.file)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w") as fh:
        fh.write("sha256:" + hashlib.sha256(pin.encode()).hexdigest() + "\n")
    os.chmod(tmp, 0o640)
    if os.geteuid() == 0:  # rigd runs as the seastones user and must be able to read it
        try:
            import grp

            os.chown(tmp, 0, grp.getgrnam(args.group).gr_gid)
        except (KeyError, OSError):
            print(f"staff-pin: no group {args.group!r}; rigd may not be able to read the file",
                  file=sys.stderr)  # fmt: skip
    os.replace(tmp, path)
    print(f"staff-pin: written to {path}. Restart the station for it to take effect.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
