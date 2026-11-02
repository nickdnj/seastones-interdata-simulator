#!/usr/bin/env python3
"""Vendor the pinned open-simh files into src/engine/simh/ and write PROVENANCE.md (SP-S3A).

    scripts/vendor-simh.py            copy the files from the pinned clone, regenerate PROVENANCE.md
    scripts/vendor-simh.py --check    verify the vendored files against the pin (no writes)

The files are taken from the pinned commit with `git show <commit>:<path>`, never from a
work tree, so they are byte-identical to the tag whatever the clone has checked out. The
pinned clone comes from `scripts/build-oracle.sh --source`.

PROVENANCE.md is generated from VENDORED and PATCHES below; edit those, not the file.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src" / "engine" / "simh"

#: (upstream path, why it is needed). Upstream layout is kept so patches read like upstream.
VENDORED = [
    ("Interdata/id16_cpu.c", "the 7/16 CPU: decode, execute, PSW, display device X'01'"),
    ("Interdata/id_io.c", "device table, interrupt evaluation, selector channel"),
    ("Interdata/id_uvc.c", "PIC X'6C' and LFC X'6D' clocks"),
    ("Interdata/id16_sys.c", "disassembler fprint_sym (CODE-3), sim_devices table"),
    ("Interdata/id_fp.c", "single-precision floating point, called from id16_cpu.c"),
    ("Interdata/id_defs.h", "Interdata definitions"),
    ("sim_defs.h", "SCP types and structures (header only; SCP itself is replaced)"),
    ("scp.h", "SCP prototypes the shim implements"),
    ("sim_console.h", "included by sim_defs.h"),
    ("sim_timer.h", "included by sim_defs.h; sim_rtcn_* and sim_idle prototypes"),
    ("sim_fio.h", "included by sim_defs.h"),
    ("sim_sock.h", "included by sim_defs.h"),
    ("sim_rev.h", "version numbers"),
]

#: Numbered patches, applied at build time to a copy under build/ (never in place).
PATCHES = [
    (
        "0001-cycle-cost.patch",
        "Interdata/id16_cpu.c",
        "cycle-cost hooks: `sim_interval -= SX_CYC (op)` after the opcode is decoded "
        "instead of `-= 1` before fetch, and `-= SX_CYC_X (op, r1, r2, opnd, cc)` (taken "
        "branch, shift count, registers moved) after the operand is decoded, both before "
        "the opcode dispatch. Stock defaults are 1 and 0; the engine's table "
        "(src/engine/machine/cycles.h, VS-02) is also stock until cycle mode is selected, so "
        "S-3 and the oracle traces run with the stock cost.",
    ),
    (
        "0004-devices.patch",
        "Interdata/id16_sys.c",
        "device registration: under SEASTONES_ENGINE, sim_devices lists only the devices "
        "the engine contains (CPU with display, selector channel, PIC, LFC, and our KEYS "
        "X'20', DAC X'21', GATE X'22' from src/engine/devices/id_seastones.c, declared "
        "extern) and sim_load returns SCPE_NOFNC, so the peripheral files are not linked.",
    ),
]

NOT_NEEDED = [
    (
        "0002-emulated-rtc",
        "Not needed as a patch. id_uvc.c calibrates only through sim_rtcn_init and "
        "sim_rtcn_calb, which the shim implements from emulated time (no host clock is ever "
        "read), so id_uvc.c is vendored unmodified.",
    ),
    (
        "0003-idle-in-engine",
        "Not needed as a patch. id16_cpu.c's wait state calls sim_idle, which the shim "
        "implements; S-3 keeps stock behaviour (one interval tick per idle pass, as stock "
        "SCP with idling disabled). In cycle mode (VS-02) the shim's sim_idle jumps to the "
        "next event instead, which needs no CPU change.",
    ),
]


def pin(key: str) -> str:
    for line in (ROOT / "deploy" / "simh.pin").read_text().splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() == key:
            return v.strip()
    raise SystemExit(f"deploy/simh.pin has no {key}")


def source_clone() -> Path:
    out = subprocess.run(
        [str(ROOT / "scripts" / "build-oracle.sh"), "--source"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(out.splitlines()[-1])


def upstream_bytes(clone: Path, commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(clone), "show", f"{commit}:{path}"], capture_output=True, check=True
    ).stdout


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def first_copyright(b: bytes) -> str:
    for line in b.decode("latin-1").splitlines()[:12]:
        if "Copyright" in line:
            return line.strip()
    return "(no copyright line in the first 12 lines)"


def provenance(commit: str, ref: str, repo: str, blobs: dict[str, bytes]) -> str:
    rows = "\n".join(
        f"| `{p}` | `{sha256(blobs[p])}` | {first_copyright(blobs[p])} | {why} |"
        for p, why in VENDORED
    )
    patch_rows = []
    for name, target, what in PATCHES:
        body = (DEST / "patches" / name).read_bytes() if (DEST / "patches" / name).exists() else b""
        patch_rows.append(f"| `{name}` | `{target}` | `{sha256(body)}` | {what} |")
    not_needed = "\n".join(f"- **{n}**: {why}" for n, why in NOT_NEEDED)
    if PATCHES:
        patch_note = (
            "No patch touches instruction semantics (S-3 GO criterion 4). Patch numbers follow "
            "ARCHITECTURE 4.2."
        )
        if NOT_NEEDED:
            patch_note += " Planned patches that turned out not to be needed:\n\n" + not_needed
    else:
        patch_note = "No patches yet: the vendored files are used as they are."
    licence = blobs["Interdata/id16_cpu.c"].decode("latin-1").split("*/", 1)[0]
    licence = "\n".join(
        ln.rstrip() for ln in licence.splitlines()[2:24] if "cpu " not in ln.lower()[:20]
    ).strip()
    return f"""# Provenance of the vendored open-simh files

Generated by `scripts/vendor-simh.py` from `deploy/simh.pin`. Do not edit by hand.

| | |
|---|---|
| Upstream | {repo} |
| Tag | `{ref}` |
| Commit | `{commit}` |
| Banner of the matching stock build | `{pin("banner")}` |

Every file below is **byte-identical** to the file at that commit. They are never edited in
place: the only changes are the numbered patches, applied at build time to a copy under
`build/engine/simh/`. `tests/conformance/test_vendor_hashes.py` fails if a vendored file
differs from the hash here or from the upstream blob, if a file appears that is not listed, or
if a patch hunk leaves its whitelisted function.

## Files

| File | SHA-256 | Original copyright line (header kept verbatim) | Why it is here |
|---|---|---|---|
{rows}

## Patches

| Patch | File | SHA-256 of the patch | Change |
|---|---|---|---|
{"\n".join(patch_rows)}

{patch_note}

## Licence notice

All vendored files carry Robert M Supnik's permissive licence (the SIMH licence, an X11/MIT
style notice), kept verbatim in each file. The notice as it appears in `id16_cpu.c`:

```
{licence}
```

The CPU and its support files are compiled into `libseastones` (RIGHTS-7). The licence text
and credit must appear in `THIRD-PARTY-NOTICES` on the image (GAT-04, CT-12).
"""


def main(argv: list[str]) -> int:
    commit, ref, repo = pin("commit"), pin("ref"), pin("repo")
    clone = source_clone()
    blobs = {p: upstream_bytes(clone, commit, p) for p, _ in VENDORED}
    if "--check" in argv:
        bad = [p for p in blobs if (DEST / p).read_bytes() != blobs[p]]
        for p in bad:
            print(f"{p}: differs from {commit}")
        return 1 if bad else 0
    for p, b in blobs.items():
        (DEST / p).parent.mkdir(parents=True, exist_ok=True)
        (DEST / p).write_bytes(b)
    (DEST / "PROVENANCE.md").write_text(provenance(commit, ref, repo, blobs))
    print(f"vendored {len(blobs)} files at {commit} into {DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
