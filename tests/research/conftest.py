"""Shared setup for the research-tool tests (lane E).

Puts the repo root (for ``research.tools``) and ``src/`` (for ``toolchain.sxscore``) on
``sys.path``. Every fixture here is generated at test time; no audio, no recording,
no transcription is ever read (RE-1, LEGAL-REVIEW 2.3).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Belt and braces: the research tests must never see a real recordings folder.
os.environ.pop("SEASTONES_AUDIO_DIR", None)
os.environ.pop("SEASTONES_NOTEBOOK_DIR", None)
os.environ.pop("SEASTONES_NOTEBOOKS_IN_REPO", None)
