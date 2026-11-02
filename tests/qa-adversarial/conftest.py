"""Adversarial suite (docs/qa/results/adversarial-2026-11-03.md): rigd's own fixtures, reused.

A known, unfixed bug is ``xfail(strict=True)`` with its QA-ADV id, so `make test` stays green
while it stands and goes red the day it is fixed (then drop the marker).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "rigd_conftest", Path(__file__).resolve().parents[1] / "rigd" / "conftest.py"
)
_rigd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rigd)

rigd_factory = _rigd.rigd_factory
client_factory = _rigd.client_factory
need_build = _rigd.need_build
