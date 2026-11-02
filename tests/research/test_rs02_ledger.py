"""RS-02 / RSC-04: the hypothesis ledger validator. Fixtures are written at test time."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from research.tools import ledger

VALID = """\
id: H-001
passage: invented passage for the test
recording: test recording label
time_range: 1:05-1:20
observed: plateaus in a pitch track
inference: stepped control voltage
alternatives: tracker frame grid
confidence: plausible
status: hypothesis
sources: -

Notes body.
"""


def _write(tmp_path, text, name="H-001.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _problems(tmp_path, text, name="H-001.md"):
    _write(tmp_path, text, name)
    _, problems = ledger.load([tmp_path])
    return [str(p) for p in problems]


def _replace(key, value, text=VALID):
    return re.sub(rf"^{key}:.*$", f"{key}: {value}", text, flags=re.M)


def test_valid_entry_passes(tmp_path):
    assert _problems(tmp_path, VALID) == []


def test_crlf_and_bom_tolerated(tmp_path):
    p = tmp_path / "H-001.md"
    p.write_bytes(b"\xef\xbb\xbf" + VALID.replace("\n", "\r\n").encode())
    _, problems = ledger.load([tmp_path])
    assert problems == []


@pytest.mark.parametrize("key", ledger.REQUIRED_KEYS)
def test_missing_field_rejected(tmp_path, key):
    text = re.sub(rf"^{key}:.*\n", "", VALID, flags=re.M)
    probs = _problems(tmp_path, text)
    assert any(f"missing required field '{key}'" in p for p in probs), probs


def test_bad_confidence_enum_rejected(tmp_path):
    probs = _problems(tmp_path, _replace("confidence", "certain"))
    assert any("confidence 'certain' is not one of" in p for p in probs)


def test_bad_status_enum_rejected(tmp_path):
    probs = _problems(tmp_path, _replace("status", "probably true"))
    assert any("status 'probably true' must be one of" in p for p in probs)


@pytest.mark.parametrize("value", ["confirmed by", "confirmed by tbd", "confirmed by ?"])
def test_confirmed_without_named_source_rejected(tmp_path, value):
    probs = _problems(tmp_path, _replace("status", value))
    assert any("does not name a source" in p for p in probs), probs


def test_confirmed_by_ledger_id_rejected(tmp_path):
    probs = _problems(tmp_path, _replace("status", "confirmed by H-002"))
    assert any("named first-hand source" in p for p in probs)


def test_confirmed_by_named_source_passes(tmp_path):
    text = _replace("status", "confirmed by Ned Lagin, letter of 2027-01-12")
    assert _problems(tmp_path, text) == []


def test_corrected_by_missing_entry_rejected(tmp_path):
    probs = _problems(tmp_path, _replace("status", "corrected by H-777"))
    assert any("there is no entry H-777" in p for p in probs)


def test_bad_time_range_rejected(tmp_path):
    assert any(
        "ends before it starts" in p
        for p in _problems(tmp_path, _replace("time_range", "2:00-1:00"))
    )
    assert any("M:SS" in p for p in _problems(tmp_path, _replace("time_range", "2m-3m")))


def test_unknown_and_duplicate_keys_rejected(tmp_path):
    text = VALID.replace("sources: -\n", "sources: -\nsource: x\nconfidence: plausible\n")
    probs = _problems(tmp_path, text)
    assert any("unknown header key 'source'" in p for p in probs)
    assert any("'confidence' appears twice" in p for p in probs)


def test_id_must_match_file_name(tmp_path):
    probs = _problems(tmp_path, VALID, name="H-002.md")
    assert any("does not match the file name" in p for p in probs)


def test_messages_carry_line_numbers(tmp_path):
    probs = _problems(tmp_path, _replace("confidence", "certain"))
    assert any(re.search(r"H-001\.md:8: ", p) for p in probs), probs


def test_high_ids_must_be_marked_synthetic(tmp_path):
    text = _replace("id", "H-901")
    probs = _problems(tmp_path, text, name="H-901.md")
    assert any("reserved for fictional fixtures" in p for p in probs)


def test_repo_ledger_validates():
    entries, problems = ledger.load()
    assert problems == [], [str(p) for p in problems]
    assert "H-900" in {e.id for e in entries}


# Words that would identify a real Seastones source. The fixture must contain none of them.
REAL_IDENTIFIERS = [
    "seastones",
    "lagin",
    "lesh",
    "grateful",
    "dead",
    "rykodisc",
    "round records",
    "rx-",
    "dave's picks",
    "set 4",
    "set 5",
    "roosevelt",
    "winterland",
    "archive.org",
    "1974",
    "1975",
    "1990",
    "lp",
    "cd",
    "sbd",
    "aud",
]


def test_fixture_entry_contains_no_real_recording_identifier():
    text = (ledger.DEFAULT_DIR / "H-900.md").read_text(encoding="utf-8").lower()
    header = text.split("\n\n", 1)[0]
    for word in REAL_IDENTIFIERS:
        assert not re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", header), word
    entry, _ = ledger.parse(ledger.DEFAULT_DIR / "H-900.md")
    assert entry.fields["synthetic"] == "yes"
    assert entry.fields["recording"].startswith("synthetic:")


def test_cli_validate_and_list(tmp_path):
    _write(tmp_path, VALID)
    ok = subprocess.run(
        [sys.executable, "-m", "research.tools.ledger", "validate", str(tmp_path)],
        cwd=ledger.DEFAULT_DIR.parents[1],
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr
    listed = subprocess.run(
        [sys.executable, "-m", "research.tools.ledger", "list", str(tmp_path)],
        cwd=ledger.DEFAULT_DIR.parents[1],
        capture_output=True,
        text=True,
    )
    assert "H-001" in listed.stdout
    _write(tmp_path, _replace("confidence", "certain", VALID))
    bad = subprocess.run(
        [sys.executable, "-m", "research.tools.ledger", "validate", str(tmp_path)],
        cwd=ledger.DEFAULT_DIR.parents[1],
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 1
    assert "confidence 'certain'" in bad.stderr
