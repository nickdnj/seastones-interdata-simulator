"""VS-12 acceptance through sx-render: golden renders, determinism, where audio may be written,
and the tampered-image refusal (ASM-09). DSP-14, DSP-18, DSP-19, LAT-01 (internal part).

Golden renders are a SHA-256 of the float32 PCM plus a compact feature JSON, never audio
(QA-STRATEGY 13.2): tests/engine/golden/render-*.json. Re-bless after a deliberate change with

    SX_REBLESS=1 python3 -m pytest tests/engine/test_golden_render.py -m lockstep

and add a line to tests/engine/golden/CHANGES.md giving the reason (DEV-PLAN 7.2).
Needs the engine and the program built (`make engine program`; `make conformance` does both).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RENDER = ROOT / "build" / "engine" / "sx-render"
IMAGE = ROOT / "build" / "program" / "rig.img.json"
GOLDEN = ROOT / "tests" / "engine" / "golden"
SCRIPT = ROOT / "tests" / "engine" / "scripts" / "mono-phrase.txt"

pytestmark = [
    pytest.mark.lockstep,  # needs build outputs: runs under `make conformance`
    pytest.mark.skipif(
        not RENDER.exists() or not IMAGE.exists(), reason="run `make engine program` first"
    ),
]


def render(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(RENDER), *args], capture_output=True, text=True, timeout=300)


def phrase(*extra: str) -> subprocess.CompletedProcess:
    return render(
        "--image", str(IMAGE), "--script", str(SCRIPT), "--seconds", "2.2", "--stats", *extra
    )


def test_golden_phrase_is_bit_identical_and_pinned(tmp_path: Path) -> None:
    feat = tmp_path / "f.json"
    a, b = phrase("--features", str(feat)), phrase()
    assert a.returncode == 0 and b.returncode == 0, a.stderr + b.stderr
    sha_a, sha_b = a.stdout.split()[1], b.stdout.split()[1]
    assert sha_a == sha_b, "two runs of the same script differ"
    features = json.loads(feat.read_text())
    golden = GOLDEN / "render-poly-phrase.json"
    if os.environ.get("SX_REBLESS"):
        golden.write_text(feat.read_text())
        pytest.skip(f"re-blessed {golden.name}: record the reason in golden/CHANGES.md")
    pinned = json.loads(golden.read_text())
    assert features["sha256"] == pinned["sha256"], "golden render moved: re-bless with a reason"
    assert features == pinned
    # The program actually played, polyphonically, through the engine's built-in four-voice
    # patch: notes sound where the script holds keys, silence after.
    wins = {round(w["t"], 1): w for w in features["windows"]}
    assert wins[0.3]["rms_dbfs"] > -30 and abs(wins[0.3]["f0_hz"] - 261.6) < 2  # key 12: C4
    # keys 0 and 7 together: two voices, C3 and G3 (the 125 Hz band holds C3's fundamental)
    assert wins[0.8]["rms_dbfs"] > wins[0.3]["rms_dbfs"] + 1.5 and wins[0.8]["bands_db"][0] > -30
    assert abs(wins[1.1]["f0_hz"] - 196.0) < 2  # key 0 up: G3 alone, still on its voice
    assert wins[2.1]["rms_dbfs"] < -60


def test_method_b_timestamps_and_latency_histogram() -> None:
    out = phrase().stdout.splitlines()
    t = dict(zip(out[2].split()[1::2], map(int, out[2].split()[2::2]), strict=True))
    assert t["arrival"] <= t["latch"] <= t["first_write"] <= t["onset"]
    assert (t["first_write"] - t["latch"]) / 48 <= 1.0  # the program's part: L1, ms
    hist = list(map(int, out[3].split()[1:]))
    assert sum(hist) == 3  # three presses in the phrase


def test_wav_only_under_build_or_outside_any_work_tree(tmp_path: Path) -> None:
    base = ("--image", str(IMAGE), "--seconds", "0.05")
    inside = ROOT / "tests" / "engine" / "x.wav"
    r = render(*base, "--wav", str(inside))
    assert r.returncode == 3 and "refusing" in r.stderr and not inside.exists()
    r = render(*base, "--wav", str(ROOT / "docs" / "x.wav"))
    assert r.returncode == 3
    ok = ROOT / "build" / "render-test.wav"
    try:
        r = render(*base, "--wav", str(ok))
        assert r.returncode == 0 and ok.stat().st_size == 44 + 2400 * 8
    finally:
        ok.unlink(missing_ok=True)
    outside = tmp_path / "listen.wav"  # pytest's tmp dir is outside the work tree
    r = render(*base, "--wav", str(outside))
    assert r.returncode == 0 and outside.exists()


def test_tampered_image_is_refused_silently(tmp_path: Path) -> None:
    img = json.loads(IMAGE.read_text())
    img["segments"][0]["words"][3] = f"{int(img['segments'][0]['words'][3], 16) ^ 1:04X}"
    bad = tmp_path / "bad.img.json"
    bad.write_text(json.dumps(img))
    wav = tmp_path / "never.wav"
    r = render("--image", str(bad), "--seconds", "0.05", "--wav", str(wav))
    assert r.returncode == 4 and "image_hash_mismatch" in r.stderr
    assert not wav.exists() and "sha256" not in r.stdout
