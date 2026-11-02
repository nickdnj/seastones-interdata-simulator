"""Parse and emit ``seastones.score/1`` (RS-03, RE-5, MACH-8; spec in docs/score-format.md).

``parse`` turns text into a ``Score`` plus the syntax problems it found, each with a line
number and a plain-English message. ``emit`` writes the canonical form, so that
emit(parse(emit(s))) == emit(s) (SCR-01). Semantic rules (ranges, voices, ledger, rights)
live in ``validate.py``.

Standard library only. This module never reads any file except the one it is given.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

VERSION = "1"
FORMAT_NAME = "seastones.score/1"

#: Header keys in canonical (emit) order, with a one-line meaning for error text.
HEADER_KEYS = {
    "score": "the format version; must be 1",
    "title": "a short name for the score",
    "status": "ready or draft-hidden",
    "origin": "original, synthetic or seastones-derived",
    "kind": "pattern (default), passage or test",
    "grounding": "none (default) or recordings",
    "ledger": "comma-separated ledger ids, e.g. H-004, H-009",
    "tick": "the program's time step: 1ms or 10ms",
    "voices": "how many voices the score reserves (1 to 8)",
    "technique": "for original patterns: the technique used (optional)",
    "note": "anything else a reader should know (optional)",
}
REQUIRED_HEADERS = ("score", "title", "status", "origin", "tick", "voices")
DEFAULTS = {"kind": "pattern", "grounding": "none"}

OPS = ("note", "off", "cv", "ramp", "trig", "loop", "end")

NOTE_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

_PITCH_RE = re.compile(r"^([A-Ga-g])([#b]?)(-1|[0-9])$")
_NOTENUM_RE = re.compile(r"^n(\d{1,3})$")
_VOLT_RE = re.compile(r"^(-?\d+(?:\.\d+)?)[Vv]$")
_CODE_RE = re.compile(r"^0[xX]([0-9A-Fa-f]{1,4})$")
_CHAN_RE = {"v": re.compile(r"^v(\d{1,2})$"), "d": re.compile(r"^d(\d{1,2})$"),
            "g": re.compile(r"^g(\d{1,2})$")}  # fmt: skip
_TIME_RE = re.compile(r"^([@+])(\d+)$")
_HEADER_RE = re.compile(r"^([a-z]+)\s*:\s*(.*)$")


@dataclass
class Problem:
    line: int
    message: str
    source: str = "<score>"

    def __str__(self) -> str:
        return (
            f"{self.source}:{self.line}: {self.message}"
            if self.line
            else (f"{self.source}: {self.message}")
        )


@dataclass
class Value:
    """A D/A value: a voltage (``2.50V``) or a raw 16-bit code (``0x4000``)."""

    volts: Decimal | None = None
    code: int | None = None

    def emit(self) -> str:
        if self.volts is not None:
            return f"{self.volts}V"
        return f"0x{self.code:04X}"


@dataclass
class Event:
    line: int
    time: int  # absolute ticks
    op: str
    channel: int | None = None  # voice for note/off, D/A channel for cv/ramp, gate for trig
    pitch: int | None = None  # note number (MIDI numbering, C4 = 60)
    value: Value | None = None
    steps: int | None = None
    over: int | None = None
    target: int | None = None  # loop target, absolute ticks

    def emit(self) -> str:
        t = f"@{self.time}"
        if self.op == "note":
            return f"{t} note v{self.channel} {pitch_name(self.pitch)}"
        if self.op == "off":
            return f"{t} off v{self.channel}"
        if self.op == "cv":
            return f"{t} cv d{self.channel} {self.value.emit()}"
        if self.op == "ramp":
            return (
                f"{t} ramp d{self.channel} {self.value.emit()} steps {self.steps} over {self.over}"
            )
        if self.op == "trig":
            return f"{t} trig g{self.channel}"
        if self.op == "loop":
            return f"{t} loop @{self.target}"
        return f"{t} end"


@dataclass
class Score:
    source: str = "<score>"
    headers: dict[str, str] = field(default_factory=dict)
    header_lines: dict[str, int] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    def header(self, key: str) -> str | None:
        return self.headers.get(key, DEFAULTS.get(key))

    @property
    def ledger_ids(self) -> list[str]:
        raw = self.headers.get("ledger", "")
        return [x.strip() for x in raw.split(",") if x.strip()]


def pitch_name(number: int) -> str:
    octave, pc = divmod(number, 12)
    return f"{SHARP_NAMES[pc]}{octave - 1}"


def parse_pitch(token: str) -> int | None:
    m = _NOTENUM_RE.match(token)
    if m:
        return int(m.group(1))
    m = _PITCH_RE.match(token)
    if not m:
        return None
    letter, accidental, octave = m.groups()
    pc = NOTE_NAMES[letter.upper()] + {"": 0, "#": 1, "b": -1}[accidental]
    return (int(octave) + 1) * 12 + pc


def parse_value(token: str) -> Value | None:
    m = _VOLT_RE.match(token)
    if m:
        try:
            return Value(volts=Decimal(m.group(1)))
        except InvalidOperation:
            return None
    m = _CODE_RE.match(token)
    if m:
        return Value(code=int(m.group(1), 16))
    return None


def _strip_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    m = re.search(r"\s#", line)
    return line[: m.start()] if m else line


def _channel(kind: str, token: str, line: int, src: str, problems: list[Problem]) -> int | None:
    m = _CHAN_RE[kind].match(token)
    if not m:
        what = {"v": "a voice like v0", "d": "a D/A channel like d8", "g": "a gate like g8"}[kind]
        problems.append(Problem(line, f"expected {what}, found '{token}'", src))
        return None
    return int(m.group(1))


def parse(text: str, source: str = "<score>") -> tuple[Score, list[Problem]]:
    """Parse score text. Tolerates a UTF-8 BOM, CRLF line endings, comments, blank lines."""
    if text.startswith("﻿"):
        text = text[1:]
    score = Score(source=source)
    problems: list[Problem] = []
    in_events = False
    seen_version = False
    prev_time = 0
    for n, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if not in_events and line[0] in "@+":
            in_events = True
        if not in_events:
            m = _HEADER_RE.match(line)
            if not m:
                problems.append(
                    Problem(
                        n,
                        f"expected a header line 'key: value' or an event, found '{line}'",
                        source,
                    )  # fmt: skip
                )
                continue
            key, value = m.group(1), m.group(2).strip()
            if not seen_version:
                if key != "score":
                    problems.append(
                        Problem(n, "the first line must be 'score: 1' (the format version)", source)
                    )
                    seen_version = True
                elif value != VERSION:
                    problems.append(
                        Problem(
                            n,
                            f"unknown score version '{value}'; this tool reads version "
                            f"{VERSION} ({FORMAT_NAME})",
                            source,
                        )
                    )
                    return score, problems
                seen_version = True
            if key not in HEADER_KEYS:
                problems.append(
                    Problem(
                        n,
                        f"unknown header '{key}'. Known headers: {', '.join(HEADER_KEYS)}",
                        source,
                    )  # fmt: skip
                )
                continue
            if key in score.headers:
                problems.append(
                    Problem(
                        n,
                        f"header '{key}' appears twice (first on line {score.header_lines[key]})",
                        source,
                    )  # fmt: skip
                )
                continue
            score.headers[key] = value
            score.header_lines[key] = n
            continue

        tokens = line.split()
        tm = _TIME_RE.match(tokens[0])
        if not tm:
            problems.append(
                Problem(
                    n,
                    f"an event must start with a time like @250 or +250, found '{tokens[0]}'",
                    source,
                )  # fmt: skip
            )
            continue
        t = int(tm.group(2)) if tm.group(1) == "@" else prev_time + int(tm.group(2))
        if len(tokens) < 2:
            problems.append(Problem(n, "a time with no event after it", source))
            continue
        op, args = tokens[1], tokens[2:]
        if op not in OPS:
            problems.append(Problem(n, f"unknown event '{op}'. Events: {', '.join(OPS)}", source))
            continue
        ev = _parse_event(n, t, op, args, source, problems)
        if ev is not None:
            score.events.append(ev)
            prev_time = t
    if not seen_version:
        problems.append(Problem(0, "the score is empty: the first line must be 'score: 1'", source))
    return score, problems


_USAGE = {
    "note": "note vN PITCH   (e.g. note v0 C3)",
    "off": "off vN",
    "cv": "cv dN VALUE   (VALUE like 2.50V or 0x4000)",
    "ramp": "ramp dN VALUE steps S over T",
    "trig": "trig gN",
    "loop": "loop @T",
    "end": "end",
}


def _parse_event(
    n: int, t: int, op: str, args: list[str], src: str, problems: list[Problem]
) -> Event | None:
    before = len(problems)
    arity = {"note": 2, "off": 1, "cv": 2, "ramp": 6, "trig": 1, "loop": 1, "end": 0}[op]
    if len(args) != arity:
        problems.append(Problem(n, f"'{op}' takes: {_USAGE[op]}", src))
        return None
    ev = Event(line=n, time=t, op=op)
    if op in ("note", "off"):
        ev.channel = _channel("v", args[0], n, src, problems)
        if op == "note":
            ev.pitch = parse_pitch(args[1])
            if ev.pitch is None:
                problems.append(
                    Problem(n, f"'{args[1]}' is not a pitch; write C3, F#4, Bb2 or n60", src)
                )
    elif op in ("cv", "ramp"):
        ev.channel = _channel("d", args[0], n, src, problems)
        ev.value = parse_value(args[1])
        if ev.value is None:
            problems.append(
                Problem(
                    n,
                    f"'{args[1]}' is not a D/A value; write a voltage like 2.50V or "
                    f"a code like 0x4000",
                    src,
                )  # fmt: skip
            )
        if op == "ramp":
            if args[2] != "steps" or args[4] != "over":
                problems.append(Problem(n, f"'ramp' takes: {_USAGE['ramp']}", src))
            elif not (args[3].isdigit() and args[5].isdigit()):
                problems.append(Problem(n, "ramp steps and over must be whole numbers", src))
            else:
                ev.steps, ev.over = int(args[3]), int(args[5])
    elif op == "trig":
        ev.channel = _channel("g", args[0], n, src, problems)
    elif op == "loop":
        m = re.match(r"^@(\d+)$", args[0])
        if not m:
            problems.append(
                Problem(n, f"loop needs an absolute time like @0, found '{args[0]}'", src)
            )
        else:
            ev.target = int(m.group(1))
    return ev if len(problems) == before else None


def emit(score: Score) -> str:
    """The canonical text of a score: headers in fixed order, absolute times, no comments."""
    out = []
    for key in HEADER_KEYS:
        value = score.headers.get(key, DEFAULTS.get(key))
        if value is not None and value != "":
            if key == "ledger":
                value = ", ".join(score.ledger_ids)
            out.append(f"{key}: {value}")
    out.append("")
    out.extend(ev.emit() for ev in score.events)
    return "\n".join(out) + "\n"
