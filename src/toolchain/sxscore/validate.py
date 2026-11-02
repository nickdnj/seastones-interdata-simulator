"""Validate ``seastones.score/1`` files (RS-03, RE-5, RE-4, SEA-3; SCR-01, SCR-02).

Every rule is in docs/score-format.md section 5. Every message names the line and says what
to change. Usage::

    python -m toolchain.sxscore.validate [--ledger DIR] [--range-v 10.24] FILE...

(run with ``src/`` on PYTHONPATH). Exit 0 if every file is valid, 1 otherwise.

Standard library only. It reads the score files it is given and, when a score has a
``ledger:`` header, the *names* of the files in the ledger folder. Nothing else.
"""

from __future__ import annotations

import argparse
import re
import sys
from decimal import Decimal
from pathlib import Path

from .score import FORMAT_NAME, Problem, Score, parse

VALID_STATUS = ("ready", "draft-hidden")
VALID_ORIGIN = ("original", "synthetic", "seastones-derived")
VALID_KIND = ("pattern", "passage", "test")
VALID_GROUNDING = ("none", "recordings")
VALID_TICK = {"1ms": 1, "10ms": 10}
DERIVED = "seastones-derived"

MAX_VOICES = 8
DAC_CHANNELS = 16
GATE_LINES = 16
DEFAULT_RANGE_V = Decimal("10.24")  # ARCHITECTURE 6.3: default D/A range 0 to +10.24 V
MAX_CODE = 0xFFFF
MAX_NOTE = 127
MAX_DELTA = 0xFFFF  # [delta ticks:16] in the 3-halfword record
MAX_RAMP_STEPS = 4096
PASSAGE_MAX_MS = 120_000  # SEA-1: passages at most 2 minutes
SCORE_AREA_BYTES = 24 * 1024  # the score area at X'2000'
RECORD_BYTES = 6  # 3 halfwords
LEDGER_ID_RE = re.compile(r"^H-\d{3,}$")

REPO_LEDGER = Path(__file__).resolve().parents[3] / "research" / "ledger"


def record_count(score: Score) -> int:
    """Upper bound on table records: one per event, two per ramp (target; steps and span)."""
    return sum(2 if e.op == "ramp" else 1 for e in score.events)


def find_ledger_dir(score_path: Path | None) -> Path | None:
    """The nearest ``research/ledger`` above the score, else this repo's ledger."""
    if score_path is not None:
        for parent in score_path.resolve().parents:
            cand = parent / "research" / "ledger"
            if cand.is_dir():
                return cand
    return REPO_LEDGER if REPO_LEDGER.is_dir() else None


def ledger_ids(ledger_dir: Path) -> set[str]:
    return {
        p.stem for p in ledger_dir.iterdir() if p.suffix == ".md" and LEDGER_ID_RE.match(p.stem)
    }


def validate(
    score: Score,
    ledger_dir: Path | None = None,
    range_v: Decimal = DEFAULT_RANGE_V,
) -> list[Problem]:
    """Semantic checks on a parsed score. Returns problems; empty means valid."""
    src = score.source
    p: list[Problem] = []
    h = score.headers

    def at(key: str) -> int:
        return score.header_lines.get(key, 0)

    def bad(line: int, msg: str) -> None:
        p.append(Problem(line, msg, src))

    for key in ("score", "title", "status", "origin", "tick", "voices"):
        if key not in h or not h[key]:
            bad(at(key), f"missing header '{key}:'")

    status = h.get("status")
    if status and status not in VALID_STATUS:
        bad(at("status"), f"status '{status}' must be ready or draft-hidden")
    origin = h.get("origin")
    if origin and origin not in VALID_ORIGIN:
        bad(at("origin"), f"origin '{origin}' must be one of: {', '.join(VALID_ORIGIN)}")
    kind = score.header("kind")
    if kind not in VALID_KIND:
        bad(at("kind"), f"kind '{kind}' must be one of: {', '.join(VALID_KIND)}")
    grounding = score.header("grounding")
    if grounding not in VALID_GROUNDING:
        bad(at("grounding"), f"grounding '{grounding}' must be none or recordings")

    tick_ms = VALID_TICK.get(h.get("tick", ""))
    if "tick" in h and tick_ms is None:
        bad(at("tick"), f"tick '{h['tick']}' must be 1ms or 10ms")

    voices = None
    if h.get("voices"):
        if h["voices"].isdigit() and 1 <= int(h["voices"]) <= MAX_VOICES:
            voices = int(h["voices"])
        else:
            bad(
                at("voices"),
                f"voices '{h['voices']}' must be a whole number from 1 to {MAX_VOICES}",
            )

    # Rights and grounding (RE-4, SEA-3, LEGAL-REVIEW 1.7).
    derived = origin == DERIVED
    claims_grounding = derived or grounding == "recordings"
    ids = score.ledger_ids
    if derived and status == "ready":
        bad(
            at("status"),
            "a seastones-derived score must be 'status: draft-hidden'. It can never be ready "
            "in v1 (SEA-3); it lives in the private folder, never under content/",
        )
    if derived and "grounding" in h and grounding == "none":
        bad(
            at("grounding"), "a seastones-derived score is grounded in the recordings by definition"
        )
    if origin == "synthetic" and grounding == "recordings":
        bad(at("grounding"), "a synthetic score cannot claim grounding in the recordings")
    if claims_grounding and not ids:
        why = "it is seastones-derived" if derived else "it says 'grounding: recordings'"
        bad(at("origin") if derived else at("grounding"),
            f"this score needs a 'ledger:' line because {why} (RE-4)")  # fmt: skip
    if ids:
        malformed = [i for i in ids if not LEDGER_ID_RE.match(i)]
        for i in malformed:
            bad(at("ledger"), f"ledger id '{i}' must look like H-004")
        good = [i for i in ids if LEDGER_ID_RE.match(i)]
        if good:
            if ledger_dir is None or not ledger_dir.is_dir():
                bad(at("ledger"), "cannot find the research/ledger folder to check the ledger "
                                  "ids; pass --ledger DIR")  # fmt: skip
            else:
                known = ledger_ids(ledger_dir)
                for i in good:
                    if i not in known:
                        bad(at("ledger"), f"ledger id {i} does not exist in {ledger_dir}")

    # Events.
    events = score.events
    if not events:
        bad(0, "the score has no events; it must end with 'end' or 'loop @T'")
    prev = None
    voice_on: set[int] = set()
    end_time = None
    for i, e in enumerate(events):
        if prev is not None and e.time < prev.time:
            bad(
                e.line,
                f"time goes backwards: @{e.time} comes after @{prev.time} (line {prev.line})",
            )
        delta = e.time - (prev.time if prev else 0)
        if delta > MAX_DELTA:
            bad(e.line, f"a gap of {delta} ticks is longer than the {MAX_DELTA} a table record "
                        f"can hold; split it with an event in between")  # fmt: skip
        if end_time is not None:
            bad(e.line, f"event after the score's '{events[i - 1].op}' on line "
                        f"{events[i - 1].line}; nothing may follow end or loop")  # fmt: skip
        if e.op in ("note", "off") and e.channel is not None:
            if voices is not None and e.channel >= voices:
                bad(e.line, f"voice v{e.channel} is out of range: this score reserves "
                            f"{voices} voice(s), v0 to v{voices - 1}")  # fmt: skip
            if e.op == "note":
                if e.pitch is not None and not 0 <= e.pitch <= MAX_NOTE:
                    bad(e.line, f"note number {e.pitch} is out of range 0 to {MAX_NOTE}")
                voice_on.add(e.channel)
            else:
                voice_on.discard(e.channel)
        if e.op in ("cv", "ramp") and e.channel is not None:
            if e.channel >= DAC_CHANNELS:
                bad(e.line, f"D/A channel d{e.channel} is out of range d0 to d{DAC_CHANNELS - 1}")
            _check_value(e, range_v, bad)
        if e.op == "ramp" and e.steps is not None:
            if not 1 <= e.steps <= MAX_RAMP_STEPS:
                bad(e.line, f"ramp steps {e.steps} must be from 1 to {MAX_RAMP_STEPS}")
            if e.over is not None and e.over < e.steps:
                bad(e.line, f"ramp over {e.over} ticks is shorter than its {e.steps} steps; "
                            f"each step needs at least one tick")  # fmt: skip
            if e.over is not None and e.over > MAX_DELTA:
                bad(e.line, f"ramp over {e.over} ticks is longer than {MAX_DELTA}")
        if e.op == "trig" and e.channel is not None and e.channel >= GATE_LINES:
            bad(e.line, f"gate g{e.channel} is out of range g0 to g{GATE_LINES - 1}")
        if e.op == "loop" and e.target is not None and e.target >= e.time:
            bad(e.line, f"loop target @{e.target} must be earlier than the loop itself (@{e.time})")
        if e.op in ("end", "loop"):
            end_time = e.time
        prev = e
    if events and end_time is None:
        bad(events[-1].line, "the score must finish with 'end' or 'loop @T'")
    if end_time is not None:
        for e in events:
            if e.op == "ramp" and e.over is not None and e.time + e.over > end_time:
                bad(e.line, f"ramp runs to tick {e.time + e.over}, after the score finishes at "
                            f"tick {end_time}")  # fmt: skip
        if kind == "passage" and tick_ms is not None and end_time * tick_ms > PASSAGE_MAX_MS:
            bad(events[-1].line, f"a passage may be at most 2 minutes; this one is "
                                 f"{end_time * tick_ms / 1000:.1f} s")  # fmt: skip

    size = record_count(score) * RECORD_BYTES
    if size > SCORE_AREA_BYTES:
        bad(0, f"the score needs about {size} bytes of table, more than the {SCORE_AREA_BYTES} "
               f"byte score area; shorten it or use a loop")  # fmt: skip
    return p


def _check_value(e, range_v: Decimal, bad) -> None:
    v = e.value
    if v is None:
        return
    if v.volts is not None:
        top = range_v * Decimal(MAX_CODE) / Decimal(MAX_CODE + 1)
        if v.volts < 0 or v.volts > top:
            bad(e.line, f"{v.volts} V is out of range: the D/A gives 0 V up to just below "
                        f"{range_v} V")  # fmt: skip
    elif v.code is not None and not 0 <= v.code <= MAX_CODE:
        bad(e.line, f"code 0x{v.code:X} is out of range 0x0000 to 0xFFFF")


def validate_file(
    path: Path, ledger_dir: Path | None = None, range_v: Decimal = DEFAULT_RANGE_V
) -> list[Problem]:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Problem(0, f"cannot read this file as UTF-8 text ({exc})", str(path))]
    score, problems = parse(text, str(path))
    if problems and any("unknown score version" in x.message for x in problems):
        return problems
    lp = ledger_dir if ledger_dir is not None else find_ledger_dir(path)
    return problems + validate(score, lp, range_v)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sxscore-validate", description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--ledger", type=Path, help="research/ledger folder for ledger ids")
    ap.add_argument("--range-v", type=Decimal, default=DEFAULT_RANGE_V, help="D/A range in volts")
    args = ap.parse_args(argv)
    bad_files = 0
    for f in args.files:
        problems = validate_file(f, args.ledger, args.range_v)
        for prob in problems:
            print(prob, file=sys.stderr)
        if problems:
            bad_files += 1
        else:
            print(f"{f}: valid {FORMAT_NAME}")
    return 1 if bad_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
