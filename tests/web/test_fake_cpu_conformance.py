"""The fake engine's interpreter agrees with the real CPU on the shipped program (VS-28, ENG-10).

The fake engine (tests/web/fake-engine/) runs `build/program/rig.img.json` on a small
interpreter so the UI tests see real PCs, registers, key rows, D/A codes and gates. This test
drives the real engine CPU (`build/engine/sx-cpu`: vendored SIMH id16 + our devices) and the
fake with the same key script and requires identical PC, R0-R15 and CC after every
instruction, and identical D/A and gate writes. It is what stops the fake drifting from the
engine it stands in for.

Needs `make engine program` and Node. Skips with the reason when either is missing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SX_CPU = os.path.join(ROOT, "build", "engine", "sx-cpu")
IMAGE = os.path.join(ROOT, "build", "program", "rig.img.json")
DEP = os.path.join(ROOT, "build", "program", "rig.dep.sim")
TRACE = os.path.join(ROOT, "tests", "web", "fake-engine", "cpu-trace.mjs")

# Key script: idle laps, one key, a chord, keys in every row, release, the top key, more
# key changes in one pass than K (ADR-009), more keys than voices (the oldest is stolen,
# PRG-04), then the routines the switch register picks (switches 8-11), long enough for the
# interval clock to tick several times (every 1000 instructions in sx-cpu's instruction mode).
# Each entry is (64-bit key bitmap, instructions to run, switch register or None to keep it).
SCRIPT = [
    (0, 120, 0),
    (1 << 0, 90, None),
    ((1 << 12) | (1 << 19), 90, None),
    ((1 << 7) | (1 << 8) | (1 << 30), 90, None),
    (1 << 36, 90, None),
    (0, 90, None),
    (1 << 24, 60, None),
    ((1 << 24) | (1 << 3), 60, None),
    (0, 80, None),
    ((1 << 1) | (1 << 2) | (1 << 5) | (1 << 9) | (1 << 17) | (1 << 33), 300, None),
    (1 << 20, 200, None),
    # ten keys held: more than the voices, so the oldest is taken
    (sum(1 << k for k in (2, 4, 6, 9, 11, 14, 16, 21, 23, 26)), 600, None),
    (0, 300, None),
    # rhythm (routine 1) from a held key, transposed up 3 (switches 4-7)
    (1 << 12, 5200, 0x0310),
    (0, 600, None),
    # steps (routine 2): the lanes move every 4 ms
    (1 << 5, 9500, 0x0020),
    # arpeggio (routine 3), up and down, on a chord
    ((1 << 0) | (1 << 4) | (1 << 7), 3500, 0x0032),
    (0, 400, 0),
]


def _skip_reason() -> str | None:
    if not os.path.exists(SX_CPU):
        return "build/engine/sx-cpu missing: run `make engine`"
    if not os.path.exists(IMAGE):
        return "build/program/rig.img.json missing: run `make program`"
    if not shutil.which("node"):
        return "node is not installed"
    return None


def _real_trace() -> tuple[list[tuple[str, ...]], list[str]]:
    lines = ["model 716", "mem 32768", "reset"]
    with open(DEP, encoding="utf-8") as fh:
        lines += [
            ln.strip() for ln in fh if ln.strip() and not ln.startswith(("dep pc", "dep psw"))
        ]
    image = json.load(open(IMAGE, encoding="utf-8"))
    lines += [f"reg PC {image['entry_pc']}", "reg PSW 0", "trace on"]
    regs = ",".join(["PC"] + [f"R{i}" for i in range(16)] + ["CC"])
    for bits, n, sr in SCRIPT:
        lines.append(f"keys {bits:016X}")
        if sr is not None:
            lines.append(f"reg SR {sr:X}")
        for _ in range(n):
            lines += ["step 1", f"ex {regs}"]
    out = subprocess.run(
        [SX_CPU], input="\n".join(lines) + "\n", capture_output=True, text=True, check=True
    ).stdout
    states: list[tuple[str, ...]] = []
    writes: list[str] = []
    cur: dict[str, str] = {}
    for ln in out.splitlines():
        m = re.match(r"^(PC|R\d+|CC):\s*([0-9A-Fa-f]+)", ln)
        if m:
            cur[m.group(1)] = m.group(2).upper()
            if m.group(1) == "CC":
                states.append(
                    tuple(
                        [cur["PC"].zfill(4)]
                        + [cur[f"R{i}"].zfill(4) for i in range(16)]
                        + [format(int(cur["CC"], 16), "X")]
                    )
                )
                cur = {}
        w = re.match(r"^W (\w\w) (\w+) (\w+)", ln)
        if w:
            writes.append(f"{w.group(1)} {int(w.group(2), 16):X} {w.group(3).upper().zfill(4)}")
    return states, writes


def _fake_trace() -> tuple[list[tuple[str, ...]], list[str]]:
    script = "".join(
        f"keys {bits:016X}\n" + (f"sr {sr:X}\n" if sr is not None else "") + f"step {n}\n"
        for bits, n, sr in SCRIPT
    )
    out = subprocess.run(
        ["node", TRACE, IMAGE], input=script, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, f"fake interpreter stopped: {out.stdout[-300:]} {out.stderr}"
    states: list[tuple[str, ...]] = []
    writes: list[str] = []
    last_dac, last_g = ["0000"] * 16, "0000"
    for ln in out.stdout.splitlines():
        m = re.match(r"PC=(\w+) R=([\w,]+) CC=(\w) KS=\w+ DAC=([\w,]+) G=(\w+)", ln)
        assert m, ln
        states.append(tuple([m.group(1)] + m.group(2).split(",") + [m.group(3)]))
        dac = m.group(4).split(",")
        for ch in range(16):
            if dac[ch] != last_dac[ch]:
                writes.append(f"21 {ch:X} {dac[ch]}")
        if m.group(5) != last_g:
            writes.append(f"22 0 {m.group(5)}")
        last_dac, last_g = dac, m.group(5)
    return states, writes


def test_fake_cpu_matches_real_cpu_instruction_by_instruction():
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    real, real_writes = _real_trace()
    fake, fake_writes = _fake_trace()
    assert len(real) == len(fake) == sum(n for _, n, _ in SCRIPT)
    for i, (a, b) in enumerate(zip(real, fake, strict=True)):
        assert a == b, f"instruction {i}: real {a} fake {b}"
    # The fake reports a write only when the value changes; compare the changes.
    changed: list[str] = []
    last: dict[tuple[str, str], str] = {}
    for w in real_writes:
        dev, ch, val = w.split()
        if val != last.get((dev, ch), "0000"):
            changed.append(f"{dev} {ch} {val}")
            last[(dev, ch)] = val
    assert changed == fake_writes
    assert len({w.split()[1] for w in changed if w.startswith("21")}) > 1, "one D/A channel only"
