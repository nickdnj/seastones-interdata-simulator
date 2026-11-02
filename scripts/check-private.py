#!/usr/bin/env python3
"""RE-1 layers 2 and 3, RIGHTS-6, RIGHTS-8, RIGHTS-10: what must never enter this repo.

Ported from the Model 4 kiosk's `scripts/check_private.py` (OP-8: excluded files and
contact details, kept here with their allowlist) and extended per ARCHITECTURE 11.5:

  1. **Audio, by name.** Any file with an audio extension, in any case, anywhere.
  2. **Audio, by content.** Magic bytes RIFF/WAVE, fLaC, ID3, OggS, FORM/AIFF(-C), ftypM4A,
     whatever the file is called. A renamed recording is still a recording.
  3. **Big research files.** Anything over 2 MB under `research/`.
  4. **Notebooks.** Any `.ipynb` with a non-empty output, or anywhere mentioning an
     `audio/*` MIME bundle, `data:audio` or `IPython.display.Audio`.
  5. **Interdata material (RIGHTS-6).** A `.pdf` under `docs/` over 2 MB (a manual scan),
     any paper tape (`.pt`, `.tape`), any `.bin` under `src/`.
  6. **Git LFS pointers** (GAT-02: nothing may hide in LFS).
  7. **Model 4 OP-8 rules:** excluded museum file names; contact details outside the
     reviewed allowlist.

Modes (all exit 1 with a plain-English list on any finding):

  check-private.py --tree [ROOT]     every tracked or untracked-not-ignored file
  check-private.py --staged          the index, as `git commit` would record it (pre-commit)
  check-private.py --range A..B      every blob introduced by a commit in the range (CI)
  check-private.py --all-history     every blob reachable from any ref

Fixture policy (QA-STRATEGY 13): the tests generate every violating file at run time in a
temporary repo. Nothing audio-like is ever committed, not even as a test fixture.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass

MB = 1024 * 1024
RESEARCH_LIMIT = 2 * MB
DOCS_PDF_LIMIT = 2 * MB

AUDIO_EXTENSIONS = (
    ".wav",
    ".flac",
    ".mp3",
    ".aiff",
    ".aif",
    ".aifc",
    ".m4a",
    ".ogg",
    ".oga",
    ".shn",
    ".opus",
    ".ape",
    ".wma",
    ".caf",
)

TAPE_EXTENSIONS = (".pt", ".tape")

EXCLUDED_PATHS = (
    ("*email-provenance*", "the Model 4 email-provenance research (OP-8)"),
    ("*interview-guide*", "the donor interview guide (OP-8)"),
    ("*draft-email*", "a draft email (OP-8)"),
)

CONTACT_PATTERNS = (
    (
        "email address",
        re.compile(r"[A-Za-z0-9_%+][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ),
    (
        "phone number",
        re.compile(r"(?<![\d-])(?:\+?1[ .\-])?\(?[2-9]\d{2}\)?[ .\-]\d{3}[ .\-]\d{4}(?!\d)"),
    ),
)

#: Exact text, each with the reason it is allowed (Model 4 rule: public routes only).
CONTACT_ALLOWLIST = {
    "noreply@anthropic.com": "the commit attribution trailer address; not a person.",
    "getty@tty1.service": "a systemd unit name (the console autologin, KP-11); not an address.",
}

#: RFC 2606 / 6761 reserved names: documentation examples, never a real person.
RESERVED_DOMAIN = re.compile(r"@(?:[\w.-]+\.)?(?:example\.(?:com|org|net)|example|invalid|test)$")

#: Vendored upstream files keep their headers verbatim (GAT-04); contact text there is
#: the upstream authors' published credit, not museum material.
CONTACT_SKIP_PREFIXES = ("src/engine/simh/", "src/host/vendor/miniaudio/")

LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"


@dataclass
class Entry:
    path: str
    size: int
    read: Callable[[], bytes]
    where: str = ""  # commit or "index" or "" for the work tree

    def label(self) -> str:
        return f"{self.path} ({self.where})" if self.where else self.path


def audio_magic(head: bytes) -> str | None:
    """Name of the audio container if `head` starts like one."""
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "RIFF/WAVE"
    if head[:4] == b"fLaC":
        return "FLAC"
    if head[:3] == b"ID3":
        return "MP3 (ID3)"
    if head[:4] == b"OggS":
        return "Ogg"
    if len(head) >= 12 and head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "AIFF"
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:11] in (b"M4A", b"M4B", b"M4P"):
        return "MPEG-4 audio"
    if len(head) >= 4 and head[:4] == b"caff":
        return "Core Audio"
    return None


def check_notebook(blob: bytes) -> list[str]:
    reasons = []
    text = blob.decode("utf-8", errors="replace")
    for needle, why in (
        ("data:audio", "embeds audio as a data: URL"),
        ("IPython.display.Audio", "calls IPython.display.Audio"),
    ):
        if needle in text:
            reasons.append(why)
    if re.search(r'"audio/[A-Za-z0-9.+-]+"', text):
        reasons.append("carries an audio/* MIME bundle")
    try:
        nb = json.loads(text)
    except ValueError:
        reasons.append("is not valid notebook JSON, so its outputs cannot be checked")
        return reasons
    for cell in nb.get("cells", []):
        if cell.get("outputs"):
            reasons.append(
                "has cell outputs (clear them: outputs can hold audio, waveforms or "
                "spectrograms of a recording)"
            )
            break
    return reasons


def check_entry(e: Entry) -> list[str]:
    problems: list[str] = []
    lower = e.path.lower()
    base = os.path.basename(lower)
    ext = os.path.splitext(lower)[1]

    if ext in AUDIO_EXTENSIONS:
        problems.append(
            f"{e.label()}: this is an audio file ({ext}). No audio of any kind goes in git, "
            f"not even our own renders (RE-1). Keep it in the private folder outside the repo."
        )
    blob: bytes | None = None
    try:
        blob = e.read()
    except OSError:
        blob = b""
    magic = audio_magic(blob[:16])
    if magic and ext not in AUDIO_EXTENSIONS:
        problems.append(
            f"{e.label()}: the contents are {magic} audio, whatever the name says. "
            f"A renamed recording is still a recording (RE-1). Remove it."
        )
    if blob.startswith(LFS_POINTER):
        problems.append(
            f"{e.label()}: this is a Git LFS pointer. Nothing in this repo may live in LFS "
            f"(GAT-02), because LFS content is not checked here."
        )
    if lower.startswith("research/") and e.size > RESEARCH_LIMIT:
        problems.append(
            f"{e.label()}: {e.size} bytes under research/ (limit 2 MB). Large research "
            f"files are usually audio, renders or analysis dumps; they stay in the private folder."
        )
    if ext == ".ipynb":
        for why in check_notebook(blob):
            problems.append(
                f"{e.label()}: notebook {why}. Notebooks live outside git (D-PLAN-1) and any "
                f"template committed here must have empty outputs (RSC-03)."
            )
    if ext in TAPE_EXTENSIONS:
        problems.append(
            f"{e.label()}: this looks like a paper tape image. No Interdata binary or tape "
            f"lives in this repo (RIGHTS-6); read fixtures through SX_FIXTURES_DIR."
        )
    if ext == ".bin" and lower.startswith("src/"):
        problems.append(
            f"{e.label()}: a .bin file under src/. Binaries do not belong in the source tree "
            f"(RIGHTS-6); build outputs go to build/, which is ignored."
        )
    if ext == ".pdf" and lower.startswith("docs/") and e.size > DOCS_PDF_LIMIT:
        problems.append(
            f"{e.label()}: a {e.size}-byte PDF under docs/. A PDF this size is usually a "
            f"manual scan, and manual scans stay out of the repo (RIGHTS-6). Cite the "
            f"bitsavers URL instead."
        )
    for pattern, what in EXCLUDED_PATHS:
        if fnmatch.fnmatch(lower, pattern) or fnmatch.fnmatch(base, pattern):
            problems.append(f"{e.label()}: this is {what}; it must not be in this repo.")
    if not any(e.path.startswith(p) for p in CONTACT_SKIP_PREFIXES) and b"\0" not in blob[:8192]:
        try:
            lines = blob.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            lines = []
        for number, line in enumerate(lines, 1):
            for kind, pattern in CONTACT_PATTERNS:
                for match in contact_matches(kind, pattern, line):
                    if match.group(0) in CONTACT_ALLOWLIST or RESERVED_DOMAIN.search(
                        match.group(0)
                    ):
                        continue
                    problems.append(
                        f"{e.label()}, line {number}: {kind} ({redact(kind, match.group(0))}). "
                        f"Personal contact details do not belong in this repo (RIGHTS-10). "
                        f"If it is a public route, add the exact text to CONTACT_ALLOWLIST "
                        f"in scripts/check-private.py with the reason."
                    )
    return problems


def contact_matches(kind: str, pattern: re.Pattern, line: str) -> Iterator[re.Match]:
    """The email pattern backtracks quadratically on long runs of word characters (a 2 MB
    line of digits takes hours), so it is only tried in a window around each '@'."""
    if kind != "email address":
        yield from pattern.finditer(line)
        return
    seen: set[str] = set()
    start = 0
    while (at := line.find("@", start)) != -1:
        window = line[max(0, at - 64) : at + 256]
        for m in pattern.finditer(window):
            if "@" in m.group(0) and m.group(0) not in seen:
                seen.add(m.group(0))
                yield m
        start = at + 1


def redact(kind: str, text: str) -> str:
    if kind == "email address":
        local, _, domain = text.partition("@")
        return f"{local[:2]}{'*' * max(len(local) - 2, 1)}@{domain}"
    return re.sub(r"\d(?=\d{0,3}$)", "*", text)


# --- sources of entries ------------------------------------------------------


def git(root: str, *args: str, check: bool = True) -> bytes:
    out = subprocess.run(["git", "-C", root, *args], capture_output=True)
    if check and out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.decode().strip()}")
    return out.stdout


def tree_entries(root: str) -> Iterator[Entry]:
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True)
    if out.returncode == 0:
        tracked = [p for p in out.stdout.decode().split("\0") if p]
        others = git(root, "ls-files", "-z", "--others", "--exclude-standard").decode()
        paths = sorted(set(tracked) | {p for p in others.split("\0") if p})
    else:
        paths = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            for name in filenames:
                paths.append(os.path.relpath(os.path.join(dirpath, name), root))
    for p in paths:
        full = os.path.join(root, p)
        if not os.path.isfile(full):
            continue  # deleted in the work tree but still in the index

        def read(full: str = full) -> bytes:
            with open(full, "rb") as fh:
                return fh.read()

        yield Entry(p, os.path.getsize(full), read)


def blob_entries(root: str, pairs: list[tuple[str, str]], where: str) -> Iterator[Entry]:
    """`pairs` is (object id, path). Reads sizes and contents through `git cat-file`."""
    for oid, path in pairs:
        size = int(git(root, "cat-file", "-s", oid).decode().strip())

        def read(oid: str = oid) -> bytes:
            return git(root, "cat-file", "blob", oid)

        yield Entry(path, size, read, where)


def staged_entries(root: str) -> Iterator[Entry]:
    names = git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").decode()
    pairs = []
    for path in [p for p in names.split("\0") if p]:
        line = git(root, "ls-files", "-s", "--", path).decode().split()
        if len(line) >= 2:
            pairs.append((line[1], path))
    yield from blob_entries(root, pairs, "staged")


def objects_entries(root: str, rev_args: list[str], where: str) -> Iterator[Entry]:
    out = git(root, "rev-list", "--objects", *rev_args).decode().splitlines()
    candidates = [(ln.split(" ", 1)[0], ln.split(" ", 1)[1]) for ln in out if " " in ln]
    if not candidates:
        return
    batch = subprocess.run(
        ["git", "-C", root, "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        input="\n".join(oid for oid, _ in candidates).encode(),
        capture_output=True,
        check=True,
    ).stdout.decode()
    blobs = {ln.split()[0] for ln in batch.splitlines() if ln.endswith(" blob")}
    yield from blob_entries(root, [(o, p) for o, p in candidates if o in blobs], where)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--tree", nargs="?", const=".", metavar="ROOT")
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--range", metavar="A..B")
    mode.add_argument("--all-history", action="store_true")
    ap.add_argument("-C", dest="root", default=None, help="repository root (default: cwd)")
    args = ap.parse_args(argv[1:])

    root = os.path.abspath(args.root or (args.tree if args.tree not in (None, ".") else "."))
    if args.staged:
        entries, what = staged_entries(root), "staged files"
    elif args.range:
        entries, what = objects_entries(root, [args.range], f"range {args.range}"), "blobs"
    elif args.all_history:
        entries, what = objects_entries(root, ["--all"], "history"), "blobs in all history"
    else:
        entries, what = tree_entries(root), "files"

    problems: list[str] = []
    count = 0
    for e in entries:
        count += 1
        problems.extend(check_entry(e))
    if problems:
        print(f"Private material check FAILED: {len(problems)} problem(s) in {count} {what}.\n")
        for p in problems:
            print(f"  {p}\n")
        print(
            "Nothing here can be fixed by a later commit: what lands in git history stays "
            "there. Take it out before it is committed."
        )
        return 1
    print(
        f"Private material check passed: {count} {what}; no audio by name or content, "
        f"no oversized research file, no notebook output, no tape or manual scan, "
        f"no unreviewed contact detail."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
