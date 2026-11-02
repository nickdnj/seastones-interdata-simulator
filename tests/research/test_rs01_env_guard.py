"""RS-01 / RSC-01: the research environment guard.

The variables are passed as a dict; os.environ is never set, and every folder is a
fresh temporary directory (no real recordings folder is ever named or looked for).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from research.tools import env


def _outside(tmp_path):
    audio = tmp_path / "private" / "seastones-audio"
    audio.mkdir(parents=True)
    notebooks = tmp_path / "private" / env.DEFAULT_NOTEBOOK_NAME
    notebooks.mkdir()
    return audio, notebooks


def test_unset_fails_with_plain_message():
    with pytest.raises(env.EnvGuardError, match="SEASTONES_AUDIO_DIR is not set"):
        env.check({})


def test_blank_counts_as_unset():
    with pytest.raises(env.EnvGuardError, match="is not set"):
        env.check({env.AUDIO_VAR: "   "})


def test_missing_folder_fails(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(env.EnvGuardError, match="does not exist"):
        env.check({env.AUDIO_VAR: str(missing)})


def test_relative_path_fails():
    with pytest.raises(env.EnvGuardError, match="relative path"):
        env.check({env.AUDIO_VAR: "seastones-audio"})


def test_file_not_folder_fails(tmp_path):
    f = tmp_path / "a-file"
    f.write_text("x")
    with pytest.raises(env.EnvGuardError, match="a file, not a folder"):
        env.check({env.AUDIO_VAR: str(f)})


def test_inside_this_repo_fails():
    inside = env.REPO_ROOT / "research"
    with pytest.raises(env.EnvGuardError, match="inside this repository"):
        env.check({env.AUDIO_VAR: str(inside)})


def test_inside_another_git_work_tree_fails(tmp_path):
    repo = tmp_path / "some-repo"
    sub = repo / "deep" / "audio"
    sub.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    with pytest.raises(env.EnvGuardError, match="inside the git work tree"):
        env.check({env.AUDIO_VAR: str(sub)})


def test_sync_folder_fails(tmp_path):
    synced = tmp_path / "Dropbox" / "audio"
    synced.mkdir(parents=True)
    with pytest.raises(env.EnvGuardError, match="cloud-sync folder"):
        env.check({env.AUDIO_VAR: str(synced)})


def test_outside_git_passes_with_default_notebook_dir(tmp_path):
    audio, notebooks = _outside(tmp_path)
    paths = env.check({env.AUDIO_VAR: str(audio)})
    assert paths.audio_dir == audio.resolve()
    assert paths.notebook_dir == notebooks.resolve()
    assert paths.notebooks_in_repo is False


def test_default_notebook_dir_missing_fails(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    with pytest.raises(
        env.EnvGuardError, match="SEASTONES_NOTEBOOK_DIR points to .* does not exist"
    ):
        env.check({env.AUDIO_VAR: str(audio)})


def test_explicit_notebook_dir_in_git_fails(tmp_path):
    audio, _ = _outside(tmp_path)
    repo = tmp_path / "nb-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    with pytest.raises(env.EnvGuardError, match="SEASTONES_NOTEBOOK_DIR .* git work tree"):
        env.check({env.AUDIO_VAR: str(audio), env.NOTEBOOK_VAR: str(repo)})


def test_notebooks_in_repo_switch(tmp_path):
    audio, _ = _outside(tmp_path)
    nb = env.REPO_ROOT / "research" / "notebooks"
    environ = {env.AUDIO_VAR: str(audio), env.NOTEBOOKS_IN_REPO_VAR: "1"}
    if nb.is_dir():
        paths = env.check(environ)
        assert paths.notebooks_in_repo is True
    else:
        with pytest.raises(env.EnvGuardError, match="does not exist"):
            env.check(environ)


def test_cli_fails_when_unset():
    clean = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin"}
    r = subprocess.run(
        [sys.executable, "-m", "research.tools.env"],
        cwd=env.REPO_ROOT,
        env=clean,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert "SEASTONES_AUDIO_DIR is not set" in r.stderr
