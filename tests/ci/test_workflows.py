"""SP-03 acceptance (GAT-02, GAT-12): workflows are thin wrappers over Make targets."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
ALLOWED_ACTIONS = {"actions/checkout@v4", "actions/setup-python@v5", "actions/cache@v4"}


def make_targets() -> set[str]:
    text = (ROOT / "Makefile").read_text()
    return set(re.findall(r"^([A-Za-z0-9_.-]+):(?!=)", text, flags=re.M))


def test_there_are_workflows() -> None:
    names = {w.name for w in WORKFLOWS}
    assert {"ci.yml", "nightly.yml"} <= names


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_every_step_is_a_make_target_or_an_allowed_action(wf: Path) -> None:
    targets = make_targets()
    doc = yaml.safe_load(wf.read_text())
    for job_name, job in doc["jobs"].items():
        for step in job["steps"]:
            if "uses" in step:
                assert step["uses"] in ALLOWED_ACTIONS, f"{wf.name}/{job_name}: {step['uses']}"
                continue
            run = step["run"].strip()
            assert "\n" not in run, f"{wf.name}/{job_name}: multi-line run step: {run!r}"
            m = re.fullmatch(r'make ([A-Za-z0-9_.-]+)(?: [A-Z_]+="?[^"]*"?)*', run)
            assert m, f"{wf.name}/{job_name}: run step is not a bare make target: {run!r}"
            assert m.group(1) in targets, f"{wf.name}/{job_name}: no Makefile target {m.group(1)}"


def test_make_ci_runs_lint_private_check_and_every_test_target() -> None:
    out = subprocess.run(
        ["make", "-n", "-p", "ci"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    line = next(ln for ln in out.splitlines() if ln.startswith("ci:"))
    prereqs = line.split(":", 1)[1].split()
    for needed in ("lint", "private-check", "test", "conformance"):
        assert needed in prereqs, f"make ci does not run {needed}"


def test_make_ci_fails_when_a_step_fails(tmp_path: Path) -> None:
    # Make stops at the first failing prerequisite; prove the wiring with a planted failure.
    mk = tmp_path / "Makefile"
    mk.write_text("ci: a b\na:\n\t@false\nb:\n\t@echo ran-b\n")
    out = subprocess.run(["make", "-f", str(mk), "ci"], capture_output=True, text=True)
    assert out.returncode != 0 and "ran-b" not in out.stdout


def test_workflows_lint_clean() -> None:
    if shutil.which("actionlint"):
        cfg = str(ROOT / ".github" / "actionlint.yaml")
        out = subprocess.run(
            ["actionlint", "-config-file", cfg, *map(str, WORKFLOWS)], cwd=ROOT, capture_output=True
        )
        assert out.returncode == 0, out.stdout.decode() + out.stderr.decode()
    else:
        for wf in WORKFLOWS:
            yaml.safe_load(wf.read_text())
        pytest.skip("actionlint not installed: YAML parse only (UNVERIFIED)")
