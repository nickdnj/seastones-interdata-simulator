"""HOME forgets the sound (FLT-12; the host lane's finding, round 4): nothing that was sounding
before HOME may come back after it, through any module's state (envelopes, filters, the echo's
lines) or the audio held in the safety chain. HOME first fades out over the 5 ms mute ramp, then
resets at a period start, so it is not a click either.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "engine"))
sys.path.insert(0, str(ROOT / "tools"))

import listen as A  # noqa: E402
import presets as P  # noqa: E402

pytestmark = [
    pytest.mark.lockstep,
    pytest.mark.skipif(
        not P.RENDER.exists() or not P.IMAGES["all-da-4"].exists(),
        reason="run `make engine program` first",
    ),  # fmt: skip
]


def render(tmp: Path, script: str, name: str) -> np.ndarray:
    pr = {p.slug: p for p in P.presets()}["stadium-drone"]  # long release, echo: the worst case
    s = tmp / f"{name}.txt"
    s.write_text(script)
    wav = tmp / f"{name}.wav"
    P.render(
        P.Preset(pr.slug, pr.patch, s, pr.graph, pr.sr, pr.map, 3.0, pr.flat), "--wav", str(wav)
    )
    return A.read_wav(wav)


def test_home_leaves_nothing_of_the_note_before_it(tmp_path: Path) -> None:
    keys = "0.0 keys 0\n0.10 keys 1000\n1.00 keys 0\n"
    plain = render(tmp_path, keys, "plain")
    home = render(tmp_path, keys + "1.05 home\n", "home")
    before = A.rms_db(plain, 1.10, 3.0)  # without HOME the release and echo ring on
    after = A.rms_db(home, 1.10, 3.0)
    print(f"after the key: {before:.1f} dBFS without HOME, {after:.1f} dBFS after HOME")
    assert before > -40.0, "the control: the note's tail is there without HOME"
    assert after < -100.0
    # and HOME fades out rather than cutting: no step above -50 dBFS around it
    x = home.mean(axis=1)
    a = int(1.05 * 48000)
    assert np.max(np.abs(np.diff(x[a : a + 1200]))) < np.max(np.abs(np.diff(x[a - 4800 : a]))) * 1.5


def test_a_key_held_across_home_plays_again(tmp_path: Path) -> None:
    held = render(tmp_path, "0.0 keys 0\n0.10 keys 1000\n1.05 home\n", "held")
    assert A.rms_db(held, 2.0, 3.0) > -40.0, "the program starts again and sees the key"
