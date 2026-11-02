"""VS-19, engine half: AUDIO-5 and the AUDIO-1 build-time guard (PRG-06, FLT-12).

* AUDIO-5: from a cold start (engine created, image loaded, no command, no UI), the first key
  sounds: silent before it, the right pitch within 25 ms after it.
* AUDIO-1 guard: no sound source outside the D/A and gate path. The engine's DSP has no input but
  the period's write list (tests/engine/test_audio1.c); this test also scans the host and web
  trees, read-only, for any oscillator or sample playback. Those trees belong to other lanes;
  the UI lane's own test (VS-15, UI-32) may cover src/web too.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RENDER = ROOT / "build" / "engine" / "sx-render"
IMAGE = ROOT / "build" / "program" / "rig.img.json"
SCRIPT = ROOT / "tests" / "engine" / "scripts" / "cold-first-key.txt"


@pytest.mark.lockstep  # needs build outputs: runs under `make conformance`
@pytest.mark.skipif(not RENDER.exists() or not IMAGE.exists(), reason="make engine program")
def test_first_key_from_cold_start_sounds(tmp_path: Path) -> None:
    feat = tmp_path / "f.json"
    r = subprocess.run(
        [str(RENDER), "--image", str(IMAGE), "--script", str(SCRIPT), "--seconds", "0.8",
         "--stats", "--features", str(feat)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    w = {round(x["t"], 1): x for x in json.loads(feat.read_text())["windows"]}
    assert all(w[t]["peak_dbfs"] < -100 for t in (0.0, 0.1, 0.2, 0.3, 0.4)), "sound before a key"
    assert w[0.5]["rms_dbfs"] > -30 and abs(w[0.6]["f0_hz"] - 261.6) < 2
    lat = r.stdout.splitlines()[2].split()
    t = dict(zip(lat[1::2], map(int, lat[2::2]), strict=True))
    onset_ms = (t["onset"] - 24000) / 48
    print(
        f"cold start: key at 500 ms, first write +{(t['first_write'] - 24000) / 48:.2f} ms, "
        f"onset +{onset_ms:.2f} ms"
    )
    assert 0 < onset_ms <= 25


SOUND = re.compile(r"AudioContext|webkitAudioContext|new\s+Audio\s*\(|<audio\b|OscillatorNode|"
                   r"createOscillator|AudioWorklet|HTMLAudioElement")  # fmt: skip


def test_no_sound_source_outside_the_engine() -> None:
    hits = []
    for tree in ("src/web", "src/host", "src/rigd"):
        base = ROOT / tree
        if not base.exists():
            continue
        for p in base.rglob("*"):
            # Vendored upstream files are kept byte-identical (src/host/vendor/miniaudio): its
            # header carries an Emscripten WebAudio backend that is never compiled (src/host/
            # ma_config.h; tests/host/test_vendor_miniaudio.py checks the build has none).
            if "vendor" in p.relative_to(base).parts:
                continue
            if p.is_file() and p.suffix in (".js", ".mjs", ".html", ".py", ".c", ".h"):
                for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                    if SOUND.search(line):
                        hits.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not hits, "a sound source outside the D/A and gate path:\n" + "\n".join(hits)


def test_the_guard_can_fail(tmp_path: Path) -> None:
    planted = "const ctx = new AudioContext();\nconst a = new Audio('x');\n"
    assert len([ln for ln in planted.splitlines() if SOUND.search(ln)]) == 2
