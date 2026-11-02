"""Hypothesis ledger: format, validator and lister (RS-02, RE-4, RSC-04).

One file per finding: ``research/ledger/H-NNN.md``. The same format as the content files
(ADR-007): a flat ``key: value`` header, a blank line, then free notes. No YAML, no
quoting, no nesting.

Header keys (all required unless marked optional)::

    id:           H-NNN, the same as the file name
    passage:      a short name for the passage
    recording:    which recording (release or tape); see the provenance log
    time_range:   M:SS-M:SS or H:MM:SS-H:MM:SS, start before end
    question:     optional; which RE-7 question (1 to 5)
    observed:     what was measured (pitch track, onset grid, step size, sweep rate)
    inference:    what it seems to mean
    alternatives: other explanations that fit the same observation
    confidence:   speculative | plausible | well-supported
    status:       hypothesis | confirmed by <named first-hand source>
                  | corrected by <H-NNN or named source> | rejected
    sources:      who or what the entry rests on (``-`` if only our own listening)
    synthetic:    optional; ``yes`` marks a fictional fixture (ids H-900 and up)

Outputs are hypotheses by default. Nothing is ``confirmed`` without a named source.

Usage::

    python -m research.tools.ledger validate [DIR_OR_FILES...]   # exit 1 on any error
    python -m research.tools.ledger list [DIR]

Standard library only.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "ledger"

REQUIRED_KEYS = (
    "id",
    "passage",
    "recording",
    "time_range",
    "observed",
    "inference",
    "alternatives",
    "confidence",
    "status",
    "sources",
)
OPTIONAL_KEYS = ("question", "synthetic")
KNOWN_KEYS = REQUIRED_KEYS + OPTIONAL_KEYS

CONFIDENCE = ("speculative", "plausible", "well-supported")
SIMPLE_STATUS = ("hypothesis", "rejected")

ID_RE = re.compile(r"^H-\d{3,}$")
FILE_RE = re.compile(r"^H-\d{3,}\.md$")
KEY_RE = re.compile(r"^([a-z_]+)\s*:\s?(.*)$")
TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.(\d+))?$")

#: Words that do not name a source. "confirmed by tbd" is not a confirmation.
PLACEHOLDER_SOURCES = {
    "",
    "-",
    "?",
    "tbd",
    "todo",
    "unknown",
    "someone",
    "n/a",
    "na",
    "none",
    "me",
    "us",
    "listening",
    "our listening",
    "the recordings",
    "recordings",
}

#: Ids from here up are fictional fixtures and must say so.
SYNTHETIC_ID_FLOOR = 900


@dataclass
class Problem:
    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else str(self.path)
        return f"{where}: {self.message}"


@dataclass
class Entry:
    path: Path
    fields: dict[str, str] = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)
    body: str = ""

    @property
    def id(self) -> str:
        return self.fields.get("id", "")


def _seconds(text: str) -> float | None:
    m = TIME_RE.match(text.strip())
    if not m:
        return None
    hours, minutes, secs, frac = m.groups()
    if int(secs) >= 60 or (hours is not None and int(minutes) >= 60):
        return None
    value = int(hours or 0) * 3600 + int(minutes) * 60 + int(secs)
    if frac:
        value += float("0." + frac)
    return float(value)


def parse(path: Path) -> tuple[Entry, list[Problem]]:
    """Parse one ledger file. Returns the entry and any format problems."""
    problems: list[Problem] = []
    entry = Entry(path=path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return entry, [Problem(path, 0, f"cannot read this file as UTF-8 text ({exc})")]
    lines = text.replace("\r\n", "\n").split("\n")
    body_start = len(lines)
    for i, raw in enumerate(lines, start=1):
        if raw.strip() == "":
            body_start = i
            break
        m = KEY_RE.match(raw)
        if not m:
            problems.append(
                Problem(path, i, f"expected 'key: value' in the header, found '{raw.strip()}'")
            )
            continue
        key, value = m.group(1), m.group(2).strip()
        if key not in KNOWN_KEYS:
            problems.append(
                Problem(path, i, f"unknown header key '{key}'. Known keys: {', '.join(KNOWN_KEYS)}")
            )
            continue
        if key in entry.fields:
            problems.append(
                Problem(path, i, f"'{key}' appears twice (first on line {entry.lines[key]})")
            )
            continue
        entry.fields[key] = value
        entry.lines[key] = i
    entry.body = "\n".join(lines[body_start:]).strip()
    return entry, problems


def validate_entry(entry: Entry) -> list[Problem]:
    """Check one parsed entry against the RE-4 rules."""
    p: list[Problem] = []
    path = entry.path
    f = entry.fields

    def at(key: str) -> int:
        return entry.lines.get(key, 0)

    for key in REQUIRED_KEYS:
        if key not in f:
            p.append(Problem(path, 0, f"missing required field '{key}'"))
        elif not f[key]:
            p.append(Problem(path, at(key), f"'{key}' is empty"))

    eid = f.get("id", "")
    if eid:
        if not ID_RE.match(eid):
            p.append(Problem(path, at("id"), f"id '{eid}' must look like H-001"))
        elif path.suffix == ".md" and path.stem != eid:
            p.append(Problem(path, at("id"), f"id '{eid}' does not match the file name"))

    conf = f.get("confidence")
    if conf and conf not in CONFIDENCE:
        p.append(
            Problem(
                path,
                at("confidence"),
                f"confidence '{conf}' is not one of: {', '.join(CONFIDENCE)}",
            )
        )

    status = f.get("status")
    if status:
        p.extend(_check_status(entry, status, at("status")))

    tr = f.get("time_range")
    if tr:
        parts = tr.split("-")
        if len(parts) != 2:
            p.append(Problem(path, at("time_range"), f"time_range '{tr}' must be START-END"))
        else:
            start, end = _seconds(parts[0]), _seconds(parts[1])
            if start is None or end is None:
                p.append(
                    Problem(
                        path,
                        at("time_range"),
                        f"time_range '{tr}' must use M:SS or H:MM:SS, e.g. 3:10-3:42",
                    )
                )
            elif start >= end:
                p.append(
                    Problem(path, at("time_range"), f"time_range '{tr}' ends before it starts")
                )

    q = f.get("question")
    if q is not None and q not in {"1", "2", "3", "4", "5"}:
        p.append(Problem(path, at("question"), f"question '{q}' must be 1, 2, 3, 4 or 5 (RE-7)"))

    syn = f.get("synthetic")
    if syn is not None and syn not in {"yes", "no"}:
        p.append(Problem(path, at("synthetic"), f"synthetic '{syn}' must be yes or no"))
    if ID_RE.match(eid or ""):
        number = int(eid.split("-")[1])
        if number >= SYNTHETIC_ID_FLOOR and syn != "yes":
            p.append(
                Problem(
                    path,
                    at("id"),
                    f"ids H-{SYNTHETIC_ID_FLOOR} and up are reserved for fictional fixtures; "
                    f"add 'synthetic: yes' or renumber",
                )
            )
        if syn == "yes" and number < SYNTHETIC_ID_FLOOR:
            p.append(
                Problem(
                    path,
                    at("synthetic"),
                    f"synthetic fixtures use ids H-{SYNTHETIC_ID_FLOOR} and up",
                )
            )
    if syn == "yes":
        if not f.get("recording", "").lower().startswith("synthetic:"):
            p.append(
                Problem(
                    path,
                    at("recording"),
                    "a synthetic entry's recording must start with 'synthetic:' and name "
                    "the generator, never a real release or tape",
                )
            )
        if f.get("status") != "hypothesis" or f.get("confidence") != "speculative":
            p.append(
                Problem(
                    path,
                    at("status"),
                    "a synthetic entry stays 'status: hypothesis' and 'confidence: speculative' "
                    "so it can never feed a label",
                )
            )
    return p


def _check_status(entry: Entry, status: str, line: int) -> list[Problem]:
    path = entry.path
    if status in SIMPLE_STATUS:
        return []
    for verb in ("confirmed by", "corrected by"):
        if status == verb or status.startswith(verb + " "):
            who = status[len(verb) :].strip()
            if who.lower().rstrip(".") in PLACEHOLDER_SOURCES:
                return [
                    Problem(
                        path,
                        line,
                        f"status '{status}' does not name a source. Write who or what, e.g. "
                        f"'{verb} Ned Lagin, letter of 2027-01-12'",
                    )
                ]
            if verb == "confirmed by" and ID_RE.match(who):
                return [
                    Problem(
                        path,
                        line,
                        "'confirmed by' needs a named first-hand source, not another ledger "
                        "entry; use 'corrected by H-NNN' for a superseding entry",
                    )
                ]
            return []
    return [
        Problem(
            path,
            line,
            f"status '{status}' must be one of: hypothesis, confirmed by <source>, "
            f"corrected by <H-NNN or source>, rejected",
        )
    ]


def _expand(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for t in targets:
        if t.is_dir():
            files.extend(sorted(x for x in t.iterdir() if FILE_RE.match(x.name)))
        else:
            files.append(t)
    return files


def load(targets: list[Path] | None = None) -> tuple[list[Entry], list[Problem]]:
    """Parse and validate every entry. Also checks ids are unique and corrections resolve."""
    files = _expand(targets or [DEFAULT_DIR])
    entries: list[Entry] = []
    problems: list[Problem] = []
    for path in files:
        entry, parse_problems = parse(path)
        problems.extend(parse_problems)
        problems.extend(validate_entry(entry))
        entries.append(entry)
    seen: dict[str, Path] = {}
    for e in entries:
        if e.id and e.id in seen:
            problems.append(
                Problem(e.path, e.lines.get("id", 0), f"id {e.id} also in {seen[e.id]}")
            )
        elif e.id:
            seen[e.id] = e.path
    for e in entries:
        status = e.fields.get("status", "")
        if status.startswith("corrected by "):
            target = status[len("corrected by ") :].strip()
            if ID_RE.match(target) and target not in seen:
                problems.append(
                    Problem(
                        e.path,
                        e.lines.get("status", 0),
                        f"corrected by {target}, but there is no entry {target}",
                    )
                )
    return entries, problems


def ids(ledger_dir: Path | None = None) -> set[str]:
    """The set of ledger ids present in a directory (used by the score validator)."""
    directory = ledger_dir or DEFAULT_DIR
    if not directory.is_dir():
        return set()
    return {x.stem for x in directory.iterdir() if FILE_RE.match(x.name)}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"validate", "list"}:
        print("usage: python -m research.tools.ledger validate|list [DIR_OR_FILES...]")
        return 64
    cmd, rest = args[0], [Path(a) for a in args[1:]]
    entries, problems = load(rest or None)
    if cmd == "list":
        for e in sorted(entries, key=lambda x: x.id):
            f = e.fields
            print(
                f"{e.id:7} {f.get('confidence', '?'):15} {f.get('status', '?'):30} "
                f"{f.get('passage', '')}"
            )
    for prob in problems:
        print(prob, file=sys.stderr)
    if problems:
        print(f"ledger: {len(problems)} problem(s) in {len(entries)} entries", file=sys.stderr)
        return 1
    if cmd == "validate":
        print(f"ledger: {len(entries)} entries, all valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
