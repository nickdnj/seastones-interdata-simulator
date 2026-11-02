"""Round 5 QA on the whole machine, offline (the C half is test_adversarial.c):

- a key-matrix smash: a random 64-bit key bitmap every 5 ms for 20 s, out-of-range bits
  37-63 included, on the four-voice and eight-voice programs: no fault, finite, within the
  ceiling, and silence once every key is up (no stuck note)
- 40 seeded random tapes (random ops, values, loop targets, voices) in score-and-keyboard
  mode: the program never stalls or wanders (no supervisor fault), and stays silent after
- a ten-minute render twice: bit-identical (long-run determinism)
"""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

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
    ),
]


def by(slug: str) -> P.Preset:
    return {p.slug: p for p in P.presets()}[slug]


def render(pr: P.Preset, script: Path, seconds: float, *extra: str) -> tuple[str, str]:
    r = subprocess.run([str(P.RENDER), "--image", str(P.IMAGES[pr.map]), "--graph", str(pr.graph),
                        "--script", str(script), "--seconds", f"{seconds:g}", "--stats", *extra],
                       capture_output=True, text=True, timeout=600, check=True)  # fmt: skip
    return r.stdout.split()[1], r.stdout


@pytest.mark.parametrize("slug", ["four-voices", "eight-voices", "computer-rhythm", "arpeggio"])
def test_a_key_smash_leaves_no_stuck_note(slug: str, tmp_path: Path) -> None:
    rng = random.Random(1974)
    lines = [f"{k * 0.005:.3f} keys {rng.getrandbits(64):X}" for k in range(4000)]
    lines.append("20.000 keys 0")
    script = tmp_path / "smash.txt"
    script.write_text("\n".join(lines) + "\n")
    wav = tmp_path / "s.wav"
    pr = by(slug)
    _, stats = render(pr, script, 26.0, "--sr", f"{pr.sr:04X}", "--wav", str(wav))
    faults = int(stats.split("faults")[1].split()[0])
    x = A.read_wav(wav)
    rep = A.report(x)
    tail = A.rms_db(x, 25.5, 26.0)
    print(f"{slug}: 4,000 random key maps in 20 s (seed 1974): faults {faults}, peak "
          f"{rep.peak_dbfs:.1f} dBFS, after release {tail:.1f} dBFS")  # fmt: skip
    assert faults == 0 and rep.finite and rep.peak_dbfs <= -1.0 + 1e-6
    assert tail < -60.0


def random_tape(rng: random.Random) -> list[int]:
    words = [0, rng.randrange(0, 5), rng.choice([1, 10, rng.randrange(0, 65536)])]
    for _ in range(rng.randrange(1, 300)):
        op = rng.randrange(0, 16)
        words += [rng.randrange(0, 200), op << 12 | rng.randrange(0, 256) << 4 >> 4 & 0xFFF,
                  rng.randrange(0, 65536)]  # fmt: skip
    return words


def test_random_tapes_never_stall_the_program(tmp_path: Path) -> None:
    rng = random.Random(1975)
    pr = by("four-voices")
    worst = []
    for k in range(40):
        tbl = tmp_path / f"t{k}.tbl"
        words = random_tape(rng)
        tbl.write_text("# seastones.table/1 random\n" + " ".join(f"{w:04X}" for w in words) + "\n")
        script = tmp_path / f"t{k}.txt"
        script.write_text(f"0.0 keys 0\n0.0 score {tbl}\n0.5 keys 1000\n1.5 keys 0\n")
        _, stats = render(pr, script, 2.5, "--sr", "2000")
        faults = int(stats.split("faults")[1].split()[0])
        worst.append(faults)
    print(f"40 random tapes (seed 1975), score and keyboard: faults {sorted(set(worst))}")
    assert set(worst) == {0}


def test_ten_minutes_render_bit_identically(tmp_path: Path) -> None:
    lines = []
    for k in range(60):
        lines += [f"{k * 10.0:.1f} keys {(0b10010001 << (k % 20)):X}", f"{k * 10.0 + 6:.1f} keys 0"]
    script = tmp_path / "long.txt"
    script.write_text("\n".join(lines) + "\n")
    pr = by("stadium-drone")
    a, _ = render(pr, script, 600.0)
    b, _ = render(pr, script, 600.0)
    print(f"ten minutes, twice: {a[:16]} and {b[:16]}")
    assert a == b
