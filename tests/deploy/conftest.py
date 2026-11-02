"""Fixtures for the station-stack tests (helpers in stackutil.py)."""

from __future__ import annotations

import pytest
from stackutil import Stack


@pytest.fixture
def stack_factory(tmp_path):
    made: list[Stack] = []

    def make(**kw) -> Stack:
        s = Stack(tmp_path, **kw)
        made.append(s)
        return s

    yield make
    for s in made:
        s.stop()
