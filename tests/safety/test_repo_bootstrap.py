"""SP-01 acceptance: the bootstrap rules that later layers rely on (NFR-13, RIGHTS-10)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

AUDIO_EXTENSIONS = ["wav", "flac", "mp3", "aiff", "aif", "m4a", "ogg", "shn", "opus", "ape"]


@pytest.mark.parametrize("ext", AUDIO_EXTENSIONS)
def test_gitignore_rejects_audio_extension(ext: str) -> None:
    # `git check-ignore` exits 0 when the path is ignored. The file need not exist.
    # Lower case only: .gitignore is case-sensitive on Linux. The hook (SP-02) checks
    # extensions case-insensitively and by magic bytes, so case is not a way round it.
    for where in (f"x.{ext}", f"research/deep/x.{ext}", f"content/a b.{ext}"):
        rc = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", where]
        ).returncode
        assert rc == 0, f".gitignore does not ignore {where}"


def test_gitignore_rejects_private_research_and_tapes() -> None:
    for where in ("research/private/anything.txt", "fixtures/178259.pt", "x.tape"):
        rc = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", where]
        ).returncode
        assert rc == 0, f".gitignore does not ignore {where}"


def _pin(key: str) -> str:
    # Same parse as the Model 4 kiosk: `grep '^key' | cut -d= -f2`, trimmed.
    out = subprocess.run(
        f"grep '^{key}[[:space:]]*=' deploy/simh.pin | cut -d= -f2 | tr -d ' '",
        shell=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return out


def test_simh_pin_parses_with_grep_cut() -> None:
    assert _pin("commit") == "c0f0a8877e222ed85c0bbafe83b42816402f7428"
    assert _pin("ref") == "refs/tags/v3.12-3"
    assert _pin("target") == "id16"
    assert _pin("repo") == "https://github.com/open-simh/simh"


def test_contributing_states_the_commit_rules() -> None:
    text = (ROOT / "docs" / "CONTRIBUTING.md").read_text()
    for needle in ("make ci", "--no-verify", "What never enters the repo"):
        assert needle in text, f"CONTRIBUTING.md does not mention {needle!r}"


def test_makefile_has_the_bootstrap_targets() -> None:
    text = (ROOT / "Makefile").read_text()
    for target in (
        "ci",
        "lint",
        "test",
        "engine",
        "oracle",
        "program",
        "web-test",
        "release-check",
    ):
        assert f"\n{target}:" in text, f"Makefile has no {target} target"
