"""SP-02 acceptance (RSC-02, RSC-03, GAT-02): the private-material hook and CI check.

Every violating fixture is generated here, at run time, inside a throwaway git repo
under pytest's tmp_path. Nothing audio-like is committed to this repo, ever
(QA-STRATEGY 13 items 2 and 4).
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts" / "check-private.py"
SETUP = ROOT / "scripts" / "dev-setup.sh"
GIT_ID = ["-c", "user.name=fixture", "-c", "user.email=fixture@example.com"]


def make_wav(seconds: float = 0.01, rate: int = 8000) -> bytes:
    """A tiny valid PCM WAV of silence, built by hand (no audio library, no file on disk)."""
    frames = int(seconds * rate)
    data = b"\0\0" * frames
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def notebook(outputs: list) -> bytes:
    nb = {
        "cells": [{"cell_type": "code", "source": ["x = 1"], "metadata": {}, "outputs": outputs}],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(nb).encode()


AUDIO_OUTPUT = [
    {
        "output_type": "display_data",
        "data": {"audio/wav": "UklGRg==", "text/plain": ["<IPython.lib.display.Audio>"]},
        "metadata": {},
    }
]


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *GIT_ID, *args], capture_output=True, text=True, check=check
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    (r / "scripts").mkdir()
    shutil.copy(CHECK, r / "scripts" / "check-private.py")
    shutil.copy(SETUP, r / "scripts" / "dev-setup.sh")
    (r / "README.md").write_text("fixture repo\n")
    git(r, "add", "README.md", "scripts")
    git(r, "commit", "-q", "-m", "base")
    return r


def run_check(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(repo / "scripts" / "check-private.py"), "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


CASES = {
    "generated wav": ("take1.wav", make_wav(), "audio file (.wav)"),
    "upper-case extension": ("TAKE2.WAV", make_wav(), "audio file (.wav)"),
    "renamed RIFF file": ("notes.txt", make_wav(), "RIFF/WAVE audio"),
    "flac magic": ("data.dat", b"fLaC" + b"\0" * 64, "FLAC audio"),
    "id3 magic": ("song.bin.txt", b"ID3\x04\x00" + b"\0" * 64, "MP3 (ID3) audio"),
    "ogg magic": ("x.json", b"OggS" + b"\0" * 64, "Ogg audio"),
    "aiff magic": ("a.raw", b"FORM\0\0\0\x20AIFF" + b"\0" * 32, "AIFF audio"),
    "m4a magic": ("a.mp4", b"\0\0\0\x20ftypM4A " + b"\0" * 32, "MPEG-4 audio"),
    "notebook with audio output": ("research/a.ipynb", notebook(AUDIO_OUTPUT), "audio/* MIME"),
    "notebook with any output": (
        "research/b.ipynb",
        notebook([{"output_type": "stream", "name": "stdout", "text": ["hi"]}]),
        "has cell outputs",
    ),
    "notebook calling IPython Audio": (
        "research/c.ipynb",
        notebook([]).replace(b"x = 1", b"IPython.display.Audio(y)"),
        "IPython.display.Audio",
    ),
    "big research file": ("research/dump.csv", b"1,2,3\n" * 400_000, "limit 2 MB"),
    "paper tape": ("fixtures/178259.pt", b"\x00\x99" * 50, "paper tape"),
    "tape by other name": ("fixtures/light.tape", b"\x00\x99" * 50, "paper tape"),
    "binary under src": ("src/engine/rig.bin", b"\x01\x02", ".bin file under src/"),
    "manual scan": ("docs/manual.pdf", b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024 + 10), "manual"),
    "lfs pointer": (
        "research/clip.dat",
        b"version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 9\n",
        "Git LFS pointer",
    ),
    # Split so this source file does not itself contain a phone number.
    "contact detail": ("docs/notes.md", b"call 609-555" + b"-0142 today\n", "phone number"),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_staged_violation_is_rejected(repo: Path, name: str) -> None:
    path, blob, message = CASES[name]
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    git(repo, "add", "-f", path)  # -f: .gitignore is layer 1; this tests layer 2 on its own
    out = run_check(repo, "--staged")
    assert out.returncode == 1, out.stdout
    assert message in out.stdout, out.stdout
    assert path in out.stdout


def test_clean_staged_set_passes(repo: Path) -> None:
    (repo / "docs").mkdir()
    (repo / "docs" / "ok.md").write_text("no audio here; email nobody@example.com is reserved\n")
    (repo / "research").mkdir()
    (repo / "research" / "template.ipynb").write_bytes(notebook([]))
    git(repo, "add", "docs/ok.md", "research/template.ipynb")
    out = run_check(repo, "--staged")
    assert out.returncode == 0, out.stdout


def test_hook_installed_by_dev_setup_refuses_the_commit(repo: Path) -> None:
    setup = subprocess.run(
        ["bash", str(repo / "scripts" / "dev-setup.sh")], capture_output=True, text=True
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr
    hook = Path(git(repo, "rev-parse", "--git-path", "hooks").stdout.strip())
    if not hook.is_absolute():
        hook = repo / hook
    assert (hook / "pre-commit").exists()
    for path, blob in (("take.wav", make_wav()), ("renamed.txt", make_wav())):
        (repo / path).write_bytes(blob)
        git(repo, "add", "-f", path)
        commit = git(repo, "commit", "-q", "-m", "should be refused", check=False)
        assert commit.returncode != 0, f"hook let {path} through"
        assert "Private material check FAILED" in commit.stdout + commit.stderr
        git(repo, "rm", "-q", "--cached", path)
    nb = repo / "research" / "n.ipynb"
    nb.parent.mkdir(exist_ok=True)
    nb.write_bytes(notebook(AUDIO_OUTPUT))
    git(repo, "add", "research/n.ipynb")
    commit = git(repo, "commit", "-q", "-m", "should be refused", check=False)
    assert commit.returncode != 0, "hook let a notebook with audio output through"
    assert "audio/* MIME bundle" in commit.stdout + commit.stderr


def test_tree_mode_and_range_mode(repo: Path) -> None:
    # Commit a violation with the hook absent (as a bypassed hook would), then show the
    # tree check and the commit-range check both catch it (RE-1 layer 3).
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "hidden.txt").write_bytes(make_wav())
    git(repo, "add", "hidden.txt")
    git(repo, "commit", "-q", "-m", "violation")
    (repo / "hidden.txt").unlink()
    git(repo, "rm", "-q", "hidden.txt")
    git(repo, "commit", "-q", "-m", "removed again")

    tree = run_check(repo, "--tree", str(repo))
    assert tree.returncode == 0, "the file is gone from the tree, so the tree check passes"

    rng = run_check(repo, "--range", f"{base}..HEAD")
    assert rng.returncode == 1 and "hidden.txt" in rng.stdout, rng.stdout

    hist = run_check(repo, "--all-history")
    assert hist.returncode == 1 and "RIFF/WAVE" in hist.stdout


def test_tree_mode_sees_untracked_files(repo: Path) -> None:
    (repo / "loose.bin.dat").write_bytes(b"OggS" + b"\0" * 10)
    out = run_check(repo, "--tree", str(repo))
    assert out.returncode == 1 and "loose.bin.dat" in out.stdout


def test_this_repo_is_clean() -> None:
    out = subprocess.run(
        ["python3", str(CHECK), "--tree", str(ROOT)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stdout
