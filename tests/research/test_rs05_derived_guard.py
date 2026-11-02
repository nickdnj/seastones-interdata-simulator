"""RS-05 / GAT-01 (early form): the seastones-derived and recording guard.

Every violating fixture is generated at run time in a temporary tree (QA-STRATEGY 13):
synthetic scores tagged derived, a generated sine written as WAV, renamed audio headers.
"""

from __future__ import annotations

import importlib.util
import json
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "derived_guard.py"
_spec = importlib.util.spec_from_file_location("derived_guard", GUARD)
guard = importlib.util.module_from_spec(_spec)
sys.modules["derived_guard"] = guard
_spec.loader.exec_module(guard)

DERIVED_SCORE = """\
score: 1
title: Synthetic stand-in for a transcription
status: draft-hidden
origin: seastones-derived
ledger: H-900
tick: 1ms
voices: 1

@0 note v0 C3
@100 end
"""

ORIGINAL_SCORE = DERIVED_SCORE.replace("origin: seastones-derived", "origin: original").replace(
    "ledger: H-900\n", ""
)


def tree(tmp_path: Path) -> Path:
    for d in ("content/passages", "src", "deploy", "research/scores"):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


def findings(root: Path, images: list[Path] | None = None) -> list[str]:
    found, _ = guard.run(root, images or [])
    return [str(f) for f in found]


def write_sine_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 8000)))
            for i in range(800)
        )
        w.writeframes(frames)


def test_planted_derived_score_under_content_fails(tmp_path):
    root = tree(tmp_path)
    (root / "content/passages/p.score").write_text(DERIVED_SCORE)
    out = findings(root)
    assert any("content/passages/p.score" in f and "seastones-derived" in f for f in out), out


def test_same_score_under_research_scores_passes(tmp_path):
    root = tree(tmp_path)
    (root / "research/scores/p.score").write_text(DERIVED_SCORE)
    assert findings(root) == []


def test_original_score_under_content_passes(tmp_path):
    root = tree(tmp_path)
    (root / "content/passages/p.score").write_text(ORIGINAL_SCORE)
    assert findings(root) == []


@pytest.mark.parametrize("where", ["src/x.score", "deploy/x.score"])
def test_derived_under_src_and_deploy_fails(tmp_path, where):
    root = tree(tmp_path)
    (root / where).write_text(DERIVED_SCORE)
    assert findings(root)


@pytest.mark.parametrize(
    "text",
    [
        "title: x\ntags: original, seastones-derived\n",
        "kind: seastones-derived\n",
        "Origin:   SEASTONES-DERIVED   # shouting\r\n",
    ],
)
def test_header_tag_variants_fail(tmp_path, text):
    root = tree(tmp_path)
    (root / "content/slot.md").write_text(text)
    assert findings(root)


@pytest.mark.parametrize(
    "obj",
    [{"origin": "seastones-derived"}, {"tags": ["preset", "seastones-derived"]}],
)
def test_json_tag_fails(tmp_path, obj):
    root = tree(tmp_path)
    (root / "content/p.patch.json").write_text(json.dumps(obj, indent=2))
    assert findings(root)


def test_mention_in_prose_or_code_is_not_a_tag(tmp_path):
    root = tree(tmp_path)
    (root / "src/rules.py").write_text(
        'DERIVED = "seastones-derived"\nHELP = {"origin": "original, synthetic or seastones-derived"}\n'
    )
    (root / "content/guide.md").write_text("A seastones-derived score never ships.\n")
    assert findings(root) == []


def test_generated_wav_and_renamed_audio_fail(tmp_path):
    root = tree(tmp_path)
    write_sine_wav(root / "content/tone.wav")
    write_sine_wav(root / "src/innocent.txt")  # renamed: caught by magic bytes
    out = findings(root)
    assert any("tone.wav" in f and "extension" in f for f in out), out
    assert any("innocent.txt" in f and "RIFF/WAVE" in f for f in out), out


@pytest.mark.parametrize(
    "head,name",
    [
        (b"fLaC\x00\x00\x00\x22", "FLAC"),
        (b"ID3\x04\x00\x00\x00\x00", "ID3"),
        (b"\xff\xfb\x90\x64\x00\x00", "MPEG audio frame"),
        (b"OggS\x00\x02\x00\x00", "Ogg"),
        (b"FORM\x00\x00\x00\x10AIFF", "AIFF"),
        (b"\x00\x00\x00\x20ftypM4A \x00\x00", "MPEG-4"),
        (b"\x1a\x45\xdf\xa3\x01\x00", "Matroska"),
        (b"MThd\x00\x00\x00\x06", "MIDI"),
    ],
)
def test_audio_magic_bytes_fail(tmp_path, head, name):
    root = tree(tmp_path)
    (root / "deploy/blob.dat").write_bytes(head + b"\x00" * 32)
    out = findings(root)
    assert any(name in f for f in out), out


@pytest.mark.parametrize(
    "head",
    [
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff\xe0\x00\x10JFIF",
        b"\xff\xfeh\x00i\x00",  # UTF-16 text
        b"\x00\x00\x00\x18ftypheic",
        b'{\n  "a": 1\n}',
    ],
)
def test_non_audio_files_pass(tmp_path, head):
    root = tree(tmp_path)
    (root / "content/file.bin").write_bytes(head + b"\x00" * 16)
    assert findings(root) == []


def test_research_folder_on_image_fails(tmp_path):
    root = tree(tmp_path)
    image = tmp_path / "image"
    (image / "opt/seastones/research").mkdir(parents=True)
    out = findings(root, [image])
    assert any("research/ folder is on the image" in f for f in out), out


def test_derived_on_image_fails(tmp_path):
    root = tree(tmp_path)
    image = tmp_path / "image"
    (image / "content").mkdir(parents=True)
    (image / "content/x.score").write_text(DERIVED_SCORE)
    assert findings(root, [image])


def test_repo_tree_is_clean():
    found, _ = guard.run(REPO_ROOT, [])
    assert found == [], [str(f) for f in found]


def test_cli_exit_codes(tmp_path):
    root = tree(tmp_path)
    cmd = [sys.executable, str(GUARD), "--root", str(root)]
    ok = subprocess.run(cmd, capture_output=True, text=True)
    assert ok.returncode == 0 and "derived guard passed" in ok.stdout
    (root / "content/p.score").write_text(DERIVED_SCORE)
    bad = subprocess.run(cmd, capture_output=True, text=True)
    assert bad.returncode == 1
    assert "content/p.score" in bad.stderr and "FAILED" in bad.stderr
    missing = subprocess.run(
        cmd + ["--image-dir", str(tmp_path / "nope")], capture_output=True, text=True
    )
    assert missing.returncode == 2
