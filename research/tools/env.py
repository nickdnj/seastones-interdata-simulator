"""Environment guard for the Seastones research workstream (RS-01, RE-1, D-PLAN-1).

Every notebook and every research tool that could touch the private material calls
``check()`` first. It fails, with a plain-English message, unless:

* ``SEASTONES_AUDIO_DIR`` is set, names an existing directory, is outside every git
  work tree, and is not inside a cloud-sync folder (iCloud, Dropbox, Google Drive,
  OneDrive);
* ``SEASTONES_NOTEBOOK_DIR`` (default: a ``seastones-notebooks`` folder beside the
  audio folder) passes the same checks.

Decision D-PLAN-1 keeps notebooks outside git. Setting ``SEASTONES_NOTEBOOKS_IN_REPO=1``
flips back to the PRD RE-6 layout: notebooks then live in ``research/notebooks/`` of this
repo (outputs stripped on commit) and that one directory is allowed inside the work tree.

This module only asks whether the directories exist and where they are. It never lists,
opens or reads anything inside them.

Standard library only. Usage from a notebook::

    from research.tools import env
    paths = env.check()

or from a shell: ``python -m research.tools.env`` (exit 0 on pass, 2 on failure).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

AUDIO_VAR = "SEASTONES_AUDIO_DIR"
NOTEBOOK_VAR = "SEASTONES_NOTEBOOK_DIR"
NOTEBOOKS_IN_REPO_VAR = "SEASTONES_NOTEBOOKS_IN_REPO"
DEFAULT_NOTEBOOK_NAME = "seastones-notebooks"

#: The root of this repository's work tree (research/tools/env.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Path fragments that mean "this folder is synced to a cloud service".
SYNC_MARKERS = (
    "Library/Mobile Documents",  # iCloud Drive on macOS
    "Library/CloudStorage",  # Dropbox, Google Drive, OneDrive file providers on macOS
    "iCloud Drive",
    "iCloudDrive",
    "Dropbox",
    "Google Drive",
    "GoogleDrive",
    "My Drive",
    "OneDrive",
)


class EnvGuardError(RuntimeError):
    """The private folders are not set up safely. The message says what to do."""


@dataclass(frozen=True)
class PrivatePaths:
    audio_dir: Path
    notebook_dir: Path
    notebooks_in_repo: bool


def git_work_tree(path: Path) -> Path | None:
    """Return the top of the git work tree containing ``path``, or None.

    Uses ``git -C <path> rev-parse --show-toplevel``. GIT_DIR and friends are removed
    from the child's environment so an inherited setting cannot hide a work tree.
    Raises EnvGuardError if git cannot be run at all: we fail closed.
    """
    child_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            env=child_env,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvGuardError(
            f"Could not run git to check whether {path} is inside a git work tree "
            f"({exc}). Install git, then try again. The check fails closed."
        ) from exc
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return None


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _sync_marker(path: Path) -> str | None:
    text = str(path)
    for marker in SYNC_MARKERS:
        if marker in text:
            return marker
    return None


def _check_private_dir(label: str, var: str, raw: str | None) -> Path:
    """Shared checks for the audio folder and the notebook folder."""
    if raw is None or not raw.strip():
        raise EnvGuardError(
            f"{var} is not set. Set it to the {label} folder on the encrypted disk, "
            f"outside every git repository and outside iCloud, Dropbox, Google Drive "
            f"or OneDrive, for example: export {var}=/Volumes/Research/seastones-audio"
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise EnvGuardError(
            f"{var} is set to '{raw}', which is a relative path. Use the full path to "
            f"the {label} folder so it cannot change with the current directory."
        )
    if not path.exists():
        raise EnvGuardError(
            f"{var} points to {path}, which does not exist. Mount the encrypted disk "
            f"or create the {label} folder, then try again."
        )
    if not path.is_dir():
        raise EnvGuardError(f"{var} points to {path}, which is a file, not a folder.")
    resolved = path.resolve()
    if _is_within(resolved, REPO_ROOT.resolve()):
        raise EnvGuardError(
            f"{var} points to {resolved}, which is inside this repository "
            f"({REPO_ROOT}). The {label} folder must live outside every git work tree."
        )
    top = git_work_tree(resolved)
    if top is not None:
        raise EnvGuardError(
            f"{var} points to {resolved}, which is inside the git work tree {top}. "
            f"Move the {label} folder outside every git repository (RE-1)."
        )
    marker = _sync_marker(resolved)
    if marker is not None:
        raise EnvGuardError(
            f"{var} points to {resolved}, which looks like a cloud-sync folder "
            f"('{marker}'). The {label} folder must not be in iCloud, Dropbox, "
            f"Google Drive or OneDrive (RE-1)."
        )
    return resolved


def audio_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Check and return the private audio folder. Never reads anything inside it."""
    env = os.environ if environ is None else environ
    return _check_private_dir("recordings", AUDIO_VAR, env.get(AUDIO_VAR))


def notebook_dir(
    environ: Mapping[str, str] | None = None, audio: Path | None = None
) -> tuple[Path, bool]:
    """Check and return (notebook folder, notebooks_in_repo)."""
    env = os.environ if environ is None else environ
    if env.get(NOTEBOOKS_IN_REPO_VAR, "").strip() == "1":
        path = REPO_ROOT / "research" / "notebooks"
        if not path.is_dir():
            raise EnvGuardError(
                f"{NOTEBOOKS_IN_REPO_VAR}=1 asks for notebooks in {path}, which does "
                f"not exist. Create it, or unset {NOTEBOOKS_IN_REPO_VAR} to keep "
                f"notebooks in the private folder (decision D-PLAN-1)."
            )
        return path, True
    raw = env.get(NOTEBOOK_VAR)
    if raw is None or not raw.strip():
        if audio is None:
            audio = audio_dir(env)
        raw = str(audio.parent / DEFAULT_NOTEBOOK_NAME)
    return _check_private_dir("notebook", NOTEBOOK_VAR, raw), False


def check(environ: Mapping[str, str] | None = None) -> PrivatePaths:
    """Run every check. Raises EnvGuardError with a plain message on the first failure."""
    audio = audio_dir(environ)
    notebooks, in_repo = notebook_dir(environ, audio)
    return PrivatePaths(audio_dir=audio, notebook_dir=notebooks, notebooks_in_repo=in_repo)


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        paths = check()
    except EnvGuardError as exc:
        print(f"research env check FAILED: {exc}", file=sys.stderr)
        return 2
    where = "research/notebooks/ (in repo)" if paths.notebooks_in_repo else paths.notebook_dir
    print(f"research env check passed. Audio: {paths.audio_dir}. Notebooks: {where}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
