"""Shared helpers for the 7/16 program tests (tests/program): assemble the program for a channel
map, load it into sx-cpu (the engine's CPU) or id16-seastones (the oracle), and read the device
writes back. Engine runs key schedules by instruction count (`step`) or on the emulated clock
(`frames`), whose cycle table is labelled ESTIMATE (SP-S4B).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "toolchain"))
sys.path.insert(0, str(ROOT / "tests" / "conformance"))

import lockstep as L  # noqa: E402
from sxasm import Assembler, RigTables, build, load_subset  # noqa: E402

PROGRAM = [
    ROOT / "src" / "program" / n
    for n in ("rig.s", "scan.s", "voices.s", "routines.s", "score.s", "memory.s", "tables.s")
]
RIG = ROOT / "src" / "program" / "rig"
SUBSET = ROOT / "src" / "program" / "subset" / "m74-portable-1.txt"
MAPS = {"all-da-4": RIG / "channel-map.md", "latch-8": RIG / "channel-map-8.md"}
BASENOTE = 48
RATE = 48000
MS = RATE / 1000
GATE_HI = 0x7D00  # 5.0 V on the all-D/A map, as the 12-bit converter latches it


@lru_cache(maxsize=8)
def assemble(map_name: str = "all-da-4", dac: Path = RIG / "dac.md"):
    a = Assembler(load_subset(SUBSET), RigTables(MAPS[map_name], dac), require_blocks=True)
    for p in PROGRAM:
        a.parse(p.name, p.read_text())
    a.assemble()
    return a, build(a, "rig", [p.name for p in PROGRAM], SUBSET.name)


def pitch(note: int, word_bits: int = 12) -> int:
    code = max(0, min(0xFFFF, round((note - 12) / 12 * 65536 / 10.24)))
    return code & (0xFFFF << (16 - word_bits)) & 0xFFFF


def load_ops(dep_sim: str) -> list[tuple]:
    ops: list[tuple] = [("mem", 32768)]
    for ln in dep_sim.splitlines():
        _, where, val = ln.split()
        ops.append(("reg", where.upper(), int(val, 16)) if where in ("pc", "psw") else
                   ("dep", int(where, 16), int(val, 16)))  # fmt: skip
    return ops


class Voices:
    """Where each voice's pitch and gate live, for a channel map (the map file is the truth)."""

    def __init__(self, map_name: str):
        a, _ = assemble(map_name)
        t = a.tables.map
        self.n = t.voices
        self.dac_gates = t.gate_source == "dac"
        self.pitch_ch = list(t.pitch)
        self.gate = list(t.gate)
        self.lanes = dict(t.lanes)

    def gates_from(self, writes: list[tuple]) -> list[list[int]]:
        """Replay writes (dev, ch, val) into per-voice gate states after each write."""
        state = [0] * self.n
        out = []
        for dev, ch, val in writes:
            if self.dac_gates and dev == 0x21 and ch in self.gate:
                state[self.gate.index(ch)] = 1 if val >= 0x4000 else 0
            elif not self.dac_gates and dev == 0x22:
                state = [1 if val & (0x8000 >> line) else 0 for line in self.gate]
            out.append(list(state))
        return out


def engine_writes(ops: list[tuple]) -> list[tuple[int, int, int, int]]:
    """(dev, ch, val, time) for every D/A and gate write, from sx-cpu's `trace on`."""
    out = L.run_engine([("trace",)] + ops)
    res = []
    for ln in out.splitlines():
        if ln.startswith("W "):
            _, dev, ch, val, t = ln.split()
            res.append((int(dev, 16), int(ch, 16), int(val, 16), int(t)))
    return res


def oracle_lines(ops: list[tuple]) -> list[str]:
    seastones = subprocess.run(
        [str(ROOT / "scripts" / "build-oracle.sh"), "--seastones"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[-1]
    with tempfile.TemporaryDirectory() as d:
        trace = Path(d) / "trace"
        L.run_oracle(ops, oracle=seastones, env={"SX_DEV_TRACE": str(trace)})
        return trace.read_text().splitlines() if trace.exists() else []


def clocked(out: dict[str, str], schedule: list[tuple], sr: int = 0) -> list[tuple]:
    """Run on the engine clock at RUN. `schedule`: ("keys", bits) at the current frame, ("frames",
    n) to render n frames in periods of at most 128. Returns (frame, dev, ch, val) per write."""
    ops: list[tuple] = [("raw_engine", f"clock {RATE} 250")] + load_ops(out["rig.dep.sim"])
    if sr:
        ops.append(("reg", "SR", sr))
    ops += [("trace",), ("raw_engine", "run")]
    for kind, v in schedule:
        ops.append(("keys", v) if kind == "keys" else ("raw_engine", f"frames {v} {min(v, 128)}"))
    writes = []
    for ln in L.run_engine(ops).splitlines():
        if ln.startswith("F "):
            _, f, dev, ch, val = ln.split()
            writes.append((int(f), int(dev, 16), int(ch, 16), int(val, 16)))
    return writes


def engine_ok() -> bool:
    return Path(L.engine_path()).exists()
