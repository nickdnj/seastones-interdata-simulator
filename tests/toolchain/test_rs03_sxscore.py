"""RS-03 / SCR-01, SCR-02: seastones.score/1 parse, round trip and validator.

Every fixture is a synthetic score written here at test time. Nothing is derived from a
recording.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from toolchain.sxscore import emit, parse  # noqa: E402
from toolchain.sxscore.validate import validate, validate_file  # noqa: E402

SCORES = sorted((REPO_ROOT / "research" / "scores").glob("*.score"))

BASE = """\
score: 1
title: Fixture
status: ready
origin: original
tick: 1ms
voices: 2

@0 note v0 C3
@0 cv d8 2.50V
@100 ramp d8 7.50V steps 20 over 500
@600 trig g8
+250 off v0
@1000 end
"""


def problems_for(text: str, ledger_dir: Path | None = None) -> list[str]:
    score, probs = parse(text, "fx.score")
    if any("unknown score version" in p.message for p in probs):
        return [str(p) for p in probs]
    return [str(p) for p in probs + validate(score, ledger_dir)]


def make_ledger(tmp_path: Path, *ids: str) -> Path:
    d = tmp_path / "research" / "ledger"
    d.mkdir(parents=True)
    for i in ids:
        (d / f"{i}.md").write_text(f"id: {i}\n")
    return d


# ---------------------------------------------------------------- SCR-01


def test_base_fixture_is_valid():
    assert problems_for(BASE) == []


@pytest.mark.parametrize("path", SCORES, ids=lambda p: p.name)
def test_example_scores_validate(path):
    assert validate_file(path) == []


@pytest.mark.parametrize("path", SCORES, ids=lambda p: p.name)
def test_emit_parse_emit_is_identical(path):
    score, probs = parse(path.read_text(encoding="utf-8"))
    assert probs == []
    once = emit(score)
    again, probs2 = parse(once)
    assert probs2 == []
    assert emit(again) == once


def test_relative_times_become_absolute():
    score, _ = parse(BASE)
    assert [e.time for e in score.events] == [0, 0, 100, 600, 850, 1000]


def test_comments_blank_lines_crlf_and_bom_tolerated():
    noisy = "﻿# leading comment\r\n\r\n" + BASE.replace("\n", "   # c\r\n").replace(
        "@600 trig g8   # c\r\n", "\r\n# whole-line comment\r\n@600 trig g8\r\n"
    )
    score, probs = parse(noisy)
    assert probs == []
    clean, _ = parse(BASE)
    assert emit(score) == emit(clean)


def test_pitch_spellings():
    text = BASE.replace("@0 note v0 C3", "@0 note v0 Db3\n@0 note v1 n49")
    score, probs = parse(text)
    assert probs == []
    assert [e.pitch for e in score.events if e.op == "note"] == [49, 49]
    assert "note v0 C#3" in emit(score)


# ---------------------------------------------------------------- SCR-02
# One fixture per error class. Each gives (text, regex the message must match).

ERROR_CASES = {
    "unknown-version": (BASE.replace("score: 1", "score: 2"), r":1: unknown score version '2'"),
    "version-not-first": (
        BASE.replace("score: 1\ntitle: Fixture", "title: Fixture\nscore: 1"),
        r":1: the first line must be 'score: 1'",
    ),
    "missing-header": (BASE.replace("origin: original\n", ""), r"missing header 'origin:'"),
    "unknown-header": (
        BASE.replace("tick: 1ms", "tick: 1ms\ntempo: 120"),
        r"unknown header 'tempo'",
    ),
    "duplicate-header": (BASE.replace("voices: 2", "voices: 2\nvoices: 3"), r"appears twice"),
    "bad-status": (BASE.replace("status: ready", "status: live"), r"status 'live' must be"),
    "bad-origin": (BASE.replace("origin: original", "origin: borrowed"), r"origin 'borrowed'"),
    "bad-kind": (BASE.replace("tick: 1ms", "kind: song\ntick: 1ms"), r"kind 'song'"),
    "bad-tick": (BASE.replace("tick: 1ms", "tick: 5ms"), r":5: tick '5ms' must be 1ms or 10ms"),
    "bad-voices": (BASE.replace("voices: 2", "voices: 9"), r"voices '9' must be"),
    "non-monotonic": (BASE.replace("@600 trig g8", "@50 trig g8"), r"time goes backwards: @50"),
    "voice-out-of-range": (
        BASE.replace("@0 note v0 C3", "@0 note v2 C3"),
        r"voice v2 is out of range",
    ),
    "volts-out-of-range": (BASE.replace("2.50V", "10.24V"), r"10.24 V is out of range"),
    "negative-volts": (BASE.replace("2.50V", "-1.00V"), r"-1.00 V is out of range"),
    "dac-channel-out-of-range": (
        BASE.replace("cv d8", "cv d16"),
        r"D/A channel d16 is out of range",
    ),
    "gate-out-of-range": (BASE.replace("trig g8", "trig g16"), r"gate g16 is out of range"),
    "note-out-of-range": (BASE.replace("note v0 C3", "note v0 n200"), r"note number 200"),
    "bad-pitch": (BASE.replace("note v0 C3", "note v0 H3"), r"'H3' is not a pitch"),
    "bad-value": (BASE.replace("2.50V", "2.5 volts"), r"'cv' takes"),
    "bad-value-token": (BASE.replace("2.50V", "loud"), r"'loud' is not a D/A value"),
    "unknown-event": (BASE.replace("@600 trig g8", "@600 bend g8"), r"unknown event 'bend'"),
    "bad-time": (
        BASE.replace("@600 trig g8", "t600 trig g8"),
        r":11: an event must start with a time",
    ),
    "ramp-syntax": (BASE.replace("steps 20 over 500", "in 20 over 500"), r"'ramp' takes"),
    "ramp-too-fast": (
        BASE.replace("steps 20 over 500", "steps 20 over 10"),
        r"shorter than its 20 steps",
    ),
    "ramp-past-end": (BASE.replace("over 500", "over 950"), r"ramp runs to tick 1050"),
    "no-end": (BASE.replace("@1000 end\n", ""), r"must finish with 'end' or 'loop @T'"),
    "event-after-end": (BASE + "@1100 trig g8\n", r"nothing may follow end or loop"),
    "loop-forward": (
        BASE.replace("@1000 end", "@1000 loop @1000"),
        r"loop target @1000 must be earlier",
    ),
    "gap-too-long": (BASE.replace("@1000 end", "@70000 end"), r"gap of 69150 ticks"),
    "passage-too-long": (
        BASE.replace("tick: 1ms", "kind: passage\ntick: 10ms").replace("@1000 end", "@12500 end"),
        r"a passage may be at most 2 minutes; this one is 125.0 s",
    ),
    "table-too-large": (
        BASE.replace(
            "@1000 end\n", "".join(f"@{1000 + i} trig g1\n" for i in range(4100)) + "@6000 end\n"
        ),
        r"more than the 24576 byte score area",
    ),
    "grounded-without-ledger": (
        BASE.replace("tick: 1ms", "grounding: recordings\ntick: 1ms"),
        r"needs a 'ledger:' line because it says 'grounding: recordings'",
    ),
    "derived-without-ledger": (
        BASE.replace("status: ready", "status: draft-hidden").replace(
            "origin: original", "origin: seastones-derived"
        ),
        r"needs a 'ledger:' line because it is seastones-derived",
    ),
    "synthetic-grounded": (
        BASE.replace("origin: original", "origin: synthetic").replace(
            "tick: 1ms", "grounding: recordings\nledger: H-001\ntick: 1ms"
        ),
        r"synthetic score cannot claim grounding",
    ),
    "malformed-ledger-id": (BASE.replace("tick: 1ms", "ledger: X9\ntick: 1ms"), r"ledger id 'X9'"),
}


@pytest.mark.parametrize("case", sorted(ERROR_CASES))
def test_error_class_rejected_with_line_numbered_message(case, tmp_path):
    text, pattern = ERROR_CASES[case]
    probs = problems_for(text, make_ledger(tmp_path, "H-001"))
    assert probs, f"{case}: expected a problem"
    assert any(re.search(pattern, p) for p in probs), (case, probs)


def test_messages_carry_line_numbers():
    text, _ = ERROR_CASES["non-monotonic"]
    probs = problems_for(text)
    assert any(re.match(r"fx\.score:11: time goes backwards", p) for p in probs), probs


def test_derived_ready_is_rejected(tmp_path):
    led = make_ledger(tmp_path, "H-001")
    text = BASE.replace("origin: original", "origin: seastones-derived").replace(
        "tick: 1ms", "ledger: H-001\ntick: 1ms"
    )
    probs = problems_for(text, led)
    assert any("must be 'status: draft-hidden'" in p for p in probs), probs


def test_derived_draft_hidden_with_ledger_is_valid(tmp_path):
    led = make_ledger(tmp_path, "H-001")
    text = (
        BASE.replace("status: ready", "status: draft-hidden")
        .replace("origin: original", "origin: seastones-derived")
        .replace("tick: 1ms", "ledger: H-001\ntick: 1ms")
    )
    assert problems_for(text, led) == []


def test_ledger_ids_must_exist(tmp_path):
    led = make_ledger(tmp_path, "H-001")
    text = BASE.replace("tick: 1ms", "grounding: recordings\nledger: H-001, H-002\ntick: 1ms")
    probs = problems_for(text, led)
    assert any("ledger id H-002 does not exist" in p for p in probs), probs
    assert not any("H-001 does not exist" in p for p in probs)


def test_ledger_dir_found_above_score(tmp_path):
    make_ledger(tmp_path, "H-001")
    f = tmp_path / "research" / "scores" / "x.score"
    f.parent.mkdir(parents=True)
    f.write_text(BASE.replace("tick: 1ms", "grounding: recordings\nledger: H-001\ntick: 1ms"))
    assert validate_file(f) == []


def test_cli_exit_codes(tmp_path):
    good = tmp_path / "good.score"
    good.write_text(BASE)
    bad = tmp_path / "bad.score"
    bad.write_text(ERROR_CASES["bad-tick"][0])
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    cmd = [sys.executable, "-m", "toolchain.sxscore.validate"]
    ok = subprocess.run(cmd + [str(good)], env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert "valid seastones.score/1" in ok.stdout
    no = subprocess.run(cmd + [str(good), str(bad)], env=env, capture_output=True, text=True)
    assert no.returncode == 1
    assert "bad.score:5: tick '5ms'" in no.stderr


def test_spec_example_validates():
    spec = (REPO_ROOT / "docs" / "score-format.md").read_text(encoding="utf-8")
    example = re.search(r"```\n(score: 1\n.*?)```", spec, re.S).group(1)
    assert problems_for(example, REPO_ROOT / "research" / "ledger") == []
