#!/usr/bin/env python3
"""Early release guard: no Seastones-derived file and no recording where it could ship (RS-05).

PRD SEA-3, RE-2; LEGAL-REVIEW 1.7 item 1; TEST-PLAN GAT-01 (the full gate is CT-05's
``scripts/release-gate.sh``, which absorbs this scan).

Scans ``content/``, ``src/`` and ``deploy/`` under the repo root, plus every ``--image-dir``
(a mounted or unpacked station image or content volume). It fails if it finds:

1. a file tagged ``seastones-derived``: a header line ``origin: seastones-derived`` (or
   ``kind:``/``tags:`` carrying it), or the same in JSON (``"origin": "seastones-derived"``,
   ``"tags": [..., "seastones-derived"]``);
2. a recording: an audio or MIDI file by extension, or by magic bytes whatever its name
   (RIFF/WAVE, fLaC, ID3, OggS, FORM/AIFF, ftyp M4A/MP4, MPEG frame sync, Matroska, MThd);
3. in an image directory, any ``research/`` directory at all (research is never copied
   into the image).

``research/`` in the repo is not scanned: transcriptions may live there in the private
repo (PRD 6.2), and original and synthetic scores live in ``research/scores/``.

Exit 0 when clean, 1 with a plain-English list of paths when anything is found, 2 when an
``--image-dir`` given on the command line does not exist. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = ("content", "src", "deploy")
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
TAG = b"seastones-derived"
MAX_TEXT_SCAN = 8 * 1024 * 1024

AUDIO_EXTENSIONS = {
    ".wav", ".wave", ".flac", ".mp3", ".aiff", ".aif", ".aifc", ".m4a", ".m4b", ".ogg",
    ".oga", ".opus", ".shn", ".ape", ".caf", ".wma", ".mp4", ".mka", ".wv", ".alac",
    ".mid", ".midi", ".cue",
}  # fmt: skip

# Header style: "origin: seastones-derived", "tags: original, seastones-derived".
_HEADER_TAG = re.compile(
    rb"^[ \t]*(?:origin|kind|tags?)[ \t]*:[ \t]*(?:[^\n#]*[, \t])?seastones-derived[ \t]*(?:[,#][^\n]*)?\r?$",
    re.IGNORECASE | re.MULTILINE,
)
# JSON style: "origin": "seastones-derived", "tags": ["x", "seastones-derived"].
_JSON_TAG = re.compile(
    rb'"(?:origin|kind)"\s*:\s*"seastones-derived"|"tags?"\s*:\s*\[[^\]]*"seastones-derived"',
    re.IGNORECASE,
)
# Image formats that also use an ISO-BMFF "ftyp" box and are not recordings.
_FTYP_IMAGE_BRANDS = (b"heic", b"heix", b"heim", b"heis", b"hevc", b"mif1", b"msf1", b"avif")


@dataclass(frozen=True)
class Finding:
    path: Path
    reason: str

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


def _mpeg_frame(head: bytes) -> bool:
    """A plausible MPEG audio frame header (11 sync bits, legal version, layer, rates)."""
    if len(head) < 3 or head[0] != 0xFF or (head[1] & 0xE0) != 0xE0:
        return False
    if head[1] in (0xFE, 0xFF):  # UTF-16 byte-order mark, or padding
        return False
    version, layer = (head[1] >> 3) & 3, (head[1] >> 1) & 3
    bitrate, rate = head[2] >> 4, (head[2] >> 2) & 3
    return version != 1 and layer != 0 and bitrate not in (0, 15) and rate != 3


def audio_magic(head: bytes) -> str | None:
    """Name the audio container if ``head`` (the first bytes of a file) is one."""
    if head[:4] == b"RIFF" and head[8:12] in (b"WAVE", b"RMID"):
        return "RIFF/WAVE audio"
    if head[:4] == b"fLaC":
        return "FLAC audio"
    if head[:3] == b"ID3":
        return "MP3 audio (ID3 tag)"
    if head[:4] == b"OggS":
        return "Ogg audio"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "AIFF audio"
    if head[4:8] == b"ftyp" and not head[8:12].lower().startswith(_FTYP_IMAGE_BRANDS):
        return f"MPEG-4 audio or video (ftyp {head[8:12].decode('latin-1')!r})"
    if _mpeg_frame(head):
        return "MPEG audio frame"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "Matroska/WebM audio or video"
    if head[:4] == b"MThd":
        return "MIDI file"
    if head[:4] == b"MAC ":
        return "Monkey's Audio"
    if head[:4] == b"caff":
        return "Core Audio file"
    if head[:4] == b"wvpk":
        return "WavPack audio"
    return None


def check_file(path: Path) -> list[Finding]:
    found: list[Finding] = []
    name = path.name.lower()
    ext = Path(name).suffix
    if ext in AUDIO_EXTENSIONS or name.endswith(".flac.cue"):
        found.append(Finding(path, f"audio or MIDI file by extension '{ext}'"))
    try:
        with path.open("rb") as fh:
            data = fh.read(MAX_TEXT_SCAN)
    except OSError as exc:
        return found + [Finding(path, f"cannot be read ({exc}); the guard fails closed")]
    kind = audio_magic(data[:16])
    if kind:
        found.append(Finding(path, f"{kind} by its first bytes, whatever the name says"))
    if TAG in data.lower() and (_HEADER_TAG.search(data) or _JSON_TAG.search(data)):
        found.append(Finding(path, "tagged seastones-derived (a transcription of Lagin's work)"))
    return found


def scan(root: Path, image: bool = False) -> list[Finding]:
    found: list[Finding] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        keep = []
        for d in sorted(dirnames):
            if d in SKIP_DIRS:
                continue
            if image and d == "research":
                found.append(
                    Finding(here / d, "a research/ folder is on the image; it never ships")
                )
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            p = here / f
            if p.is_symlink() and not p.exists():
                continue
            if p.is_file():
                found.extend(check_file(p))
    return found


def run(repo_root: Path, image_dirs: list[Path]) -> tuple[list[Finding], list[Path]]:
    scanned: list[Path] = []
    found: list[Finding] = []
    for name in DEFAULT_ROOTS:
        root = repo_root / name
        if root.is_dir():
            scanned.append(root)
            found.extend(scan(root))
    for img in image_dirs:
        scanned.append(img)
        found.extend(scan(img, image=True))
    return found, scanned


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fail if a Seastones-derived file or a recording "
                                 "is where it could reach the station.")  # fmt: skip
    ap.add_argument("--root", type=Path, default=REPO_ROOT, help="repo root (default: this repo)")
    ap.add_argument("--image-dir", type=Path, action="append", default=[],
                    help="a mounted or unpacked image or content volume; repeatable")  # fmt: skip
    args = ap.parse_args(argv)
    missing = [d for d in args.image_dir if not d.is_dir()]
    if missing:
        for d in missing:
            print(f"derived guard: image directory {d} does not exist", file=sys.stderr)
        return 2
    found, scanned = run(args.root, args.image_dir)
    if found:
        print("derived guard FAILED. These must not be where they could ship (SEA-3, RE-2):",
              file=sys.stderr)  # fmt: skip
        for f in found:
            print(f"  {f}", file=sys.stderr)
        print("Move transcriptions to the private folder and recordings off the tree.",
              file=sys.stderr)  # fmt: skip
        return 1
    where = ", ".join(str(s) for s in scanned) or "nothing (no content/, src/ or deploy/ yet)"
    print(f"derived guard passed: no seastones-derived file or recording in {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
