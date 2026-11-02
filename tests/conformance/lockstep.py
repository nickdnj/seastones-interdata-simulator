#!/usr/bin/env python3
"""S-3 lockstep: the engine's CPU against stock id16, instruction by instruction (SP-S3C).

Both machines run the same program from the same state, driven by one abstract script:

* the **engine** is `build/engine/sx-cpu` (the vendored SIMH CPU, patched 0001 and 0004,
  linked against `src/engine/shim/scp_shim.c` instead of SIMH's SCP);
* the **oracle** is stock `id16` built from `deploy/simh.pin` (`scripts/build-oracle.sh`).

Evidence collected per run, all compared as text after a small normalisation (banner and
"Goodbye" dropped; the disassembly SCP appends to a stop line dropped):

1. a **fine segment**: the first `fine` instructions single-stepped, with PC, PSW (so CC),
   R0-R15, and the display registers after every instruction;
2. a **coarse segment**: the rest, in chunks of up to 65,536, with SIMH's own instruction
   history (`set cpu history`, `show cpu history`: PC, R1 before execution, operand,
   effective address, instruction text) for every instruction, and the full register
   state after every chunk;
3. the data memory at the end.

Random streams are generated from a seed over the portable subset v0 (subset_v0.py),
with every branch target, I/O device number, block-I/O range, PSW value and memory write
constrained so that both machines stay inside the program, never touch a device one of
them lacks, and never depend on host time (see `Stream`). Seeds are printed; a failing
seed is appended to seeds.txt by the pytest wrapper.

Usage:
    python3 tests/conformance/lockstep.py --streams 20 --instructions 1000000
    python3 tests/conformance/lockstep.py --seed 42 --instructions 200000 --verbose
    python3 tests/conformance/lockstep.py --disasm 65536
    python3 tests/conformance/lockstep.py --programs     # needs SX_FIXTURES_DIR
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from subset_v0 import SUBSET_V0  # noqa: E402

REG_NAMES = (
    ["PC", "PSW", "CC"] + [f"R{i}" for i in range(16)] + ["SR", "DR", "DRX", "DRMOD", "DRPOS"]
)
HIST_MAX = 65536


# --- the two machines ------------------------------------------------------------------


def oracle_path() -> str:
    env = os.environ.get("SX_ORACLE")
    if env:
        return env
    out = subprocess.run(
        [str(ROOT / "scripts" / "build-oracle.sh")], capture_output=True, text=True, check=True
    )
    return out.stdout.strip().splitlines()[-1]


def engine_path() -> str:
    return os.environ.get("SX_ENGINE", str(ROOT / "build" / "engine" / "sx-cpu"))


def to_scp(ops: list[tuple]) -> str:
    out = []
    for op in ops:
        k = op[0]
        if k == "model":
            out.append(f"set cpu {op[1]}")
        elif k == "mem":
            out.append(f"set cpu {op[1] // 1024}k")
        elif k == "hist":
            out.append(f"set cpu history={op[1]}")
        elif k == "dep":
            out.append(f"dep 0{op[1]:X} {op[2]:04X}")  # leading 0: "FD0" is a unit name
        elif k == "reg":
            out.append(f"dep {op[1]} {op[2]:X}")
        elif k == "step":
            out.append(f"step {op[1]}")
        elif k == "showhist":
            out.append(f"show cpu history={op[1]}")
        elif k == "ex":
            out.append("ex " + ",".join(op[1]))
        elif k == "exmem":
            out.append(f"ex 0{op[1]:X}-0{op[2]:X}")
        elif k == "disasm":
            out.append(f"ex -m 0{op[1]:X}-0{op[2]:X}")
        elif k == "echo":
            out.append(f"echo {op[1]}")
        elif k == "raw_scp":
            out.append(op[1])
        elif k == "raw_engine":
            continue  # an sx-cpu command with no SCP equivalent (the clock, VS-02)
        elif k == "trace":
            continue  # the oracle writes its trace to $SX_DEV_TRACE
        elif k == "keys":  # id16-seastones only: the KEYS device's latched rows
            for r, v in enumerate(key_rows(op[1])):
                out.append(f"dep keys rows[{r}] {v:X}")
        else:
            raise ValueError(op)
    out.append("exit")
    return "\n".join(out) + "\n"


def to_engine(ops: list[tuple]) -> str:
    out = []
    for op in ops:
        k = op[0]
        if k in ("model", "mem", "hist", "step", "showhist"):
            out.append(f"{k} {op[1]}")
        elif k == "dep":
            out.append(f"dep {op[1]:X} {op[2]:04X}")
        elif k == "reg":
            out.append(f"reg {op[1]} {op[2]:X}")
        elif k == "ex":
            out.append("ex " + ",".join(op[1]))
        elif k in ("exmem", "disasm"):
            out.append(f"{k} {op[1]:X} {op[2]:X}")
        elif k == "echo":
            out.append(f"echo {op[1]}")
        elif k == "raw_scp":
            continue
        elif k == "raw_engine":
            out.append(op[1])
        elif k == "keys":
            out.append(f"keys {op[1]:X}")
        elif k == "trace":
            out.append("trace on")
        else:
            raise ValueError(op)
    return "\n".join(out) + "\n"


def key_rows(bits: int) -> list[int]:
    """Key k is row k >> 3, mask 0x80 >> (k & 7) (ARCHITECTURE 5.1)."""
    rows = [0] * 8
    for k in range(64):
        if bits >> k & 1:
            rows[k >> 3] |= 0x80 >> (k & 7)
    return rows


STOP_LINE = re.compile(r"^(.+), PC: ([0-9A-F]{4})(?: \(.*\))?$")


def normalise(text: str) -> list[str]:
    lines = []
    for ln in text.splitlines():
        if ln in ("", "Goodbye") or ln.startswith("Interdata 16b simulator"):
            continue
        m = STOP_LINE.match(ln)
        lines.append(f"{m.group(1)}, PC: {m.group(2)}" if m else ln)
    return lines


def run_oracle(ops: list[tuple], timeout: int = 900, oracle: str | None = None,
               env: dict | None = None) -> str:  # fmt: skip
    fd, path = tempfile.mkstemp(suffix=".sim", prefix="sx-oracle-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(to_scp(ops))
        # stdin must not be the script: id16's Teletype polls the console and would eat it.
        return subprocess.run(
            [oracle or oracle_path(), path],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **(env or {})},
        ).stdout
    finally:
        os.unlink(path)


def run_engine(ops: list[tuple], timeout: int = 900) -> str:
    p = subprocess.run(
        [engine_path()], input=to_engine(ops), capture_output=True, text=True, timeout=timeout
    )
    if p.returncode != 0:
        raise RuntimeError(f"sx-cpu failed ({p.returncode}): {p.stderr.strip()}")
    return p.stdout


@dataclass
class Compare:
    equal: bool
    lines: int
    first_diff: int | None = None
    context: list[str] = field(default_factory=list)
    digest: str = ""


def compare(a: list[str], b: list[str]) -> Compare:
    digest = hashlib.sha256("\n".join(a).encode()).hexdigest()
    if a == b:
        return Compare(True, len(a), digest=digest)
    n = min(len(a), len(b))
    i = next((k for k in range(n) if a[k] != b[k]), n)
    ctx = [f"  oracle: {x}" for x in a[max(0, i - 3) : i + 2]]
    ctx += [f"  engine: {x}" for x in b[max(0, i - 3) : i + 2]]
    return Compare(False, max(len(a), len(b)), i, ctx, digest)


# --- random subset streams ------------------------------------------------------------

CODE_BASE = 0x0100
CONST_BASE = 0x3000
DATA_BASE, DATA_TOP = 0x4000, 0x7F00
MEMSIZE = 32768
EDGE = [0x0000, 0x0001, 0x7FFF, 0x8000, 0x8001, 0xFFFF, 0xFFFE, 0x00FF, 0xFF00]
#: Device numbers both machines treat identically: the display (X'01', inside
#: id16_cpu.c in both) and numbers no device answers in either (stock has TT 02, PT 03,
#: PAS 10-1F, LPT 62, PIC 6C, LFC 6D, MT 85, disks B6-C1 and FB, SELCH F0; the engine has
#: display, SELCH, PIC, LFC and our KEYS/DAC/GATE at X'20'-X'22', which stock lacks and
#: VS-06 checks against id16-seastones instead). PIC and LFC are excluded because stock
#: calibrates them against the host clock.
#:
#: The S-3 evidence run (commit 57a48e0, before the devices existed) also used X'20'-X'22'
#: here; from VS-03 on they are replaced, so stream digests differ from S3-evidence.json.
SAFE_DEVS = [0x01, 0x01, 0x01, 0x23, 0x2F, 0x30, 0x47, 0x7F, 0xE0]
#: PSW bits a stream may set: EXI, MCI, AFI, FPF (and any CC). Never WAIT, AIO, SQI, PRO.
SAFE_PSW_BITS = [0x4000, 0x2000, 0x1000, 0x0400]
SWAP_AREAS = [0x28, 0x30, 0x38, 0x40, 0x48]  # FPF, ILO, MCK, EXI, AFI new-PSW areas
TRAP_HANDLERS = 0x00E0  # one 4-byte `LPSW area` handler per swap area


def edge_or_random(rng: random.Random) -> int:
    return rng.choice(EDGE) if rng.random() < 0.35 else rng.randrange(0x10000)


class Stream:
    """One seeded random program over the subset, laid out as:

    X'0000'-X'00FF'  low core: every PSW-swap area points its new PC at a handler at
                     X'00E0' that returns with LPSW to the instruction after the fault
    X'0100'-...      the body: `units` instruction units, then `B body` (BFC 0)
    X'3000'-...      constants, never written: branch targets, device numbers, PSWs,
                     LPSW blocks, block-I/O descriptors
    X'4000'-X'7EFF'  data: every memory write lands here, unindexed
    """

    def __init__(self, seed: int, units: int = 1200):
        self.seed = seed
        self.rng = random.Random(seed)
        self.mem: dict[int, int] = {}
        self.code: dict[int, str] = {}  # instruction address -> mnemonic
        self.const_ptr = CONST_BASE
        self._build(units)

    # memory helpers
    def put(self, addr: int, word: int) -> None:
        self.mem[addr] = word & 0xFFFF

    def const(self, *words: int) -> int:
        at = self.const_ptr
        for w in words:
            self.put(self.const_ptr, w)
            self.const_ptr += 2
        assert self.const_ptr < DATA_BASE
        return at

    def safe_psw(self) -> int:
        bits = 0
        for b in SAFE_PSW_BITS:
            if self.rng.random() < (0.12 if b == 0x1000 else 0.3):
                bits |= b
        return bits | self.rng.randrange(16)

    def data_ea(self, span: int = 2) -> int:
        return self.rng.randrange(DATA_BASE, DATA_TOP - span) & ~1

    def _build(self, units: int) -> None:
        rng = self.rng
        # Plan the units first so branch targets can point at any unit start.
        kinds = [self._pick_kind() for _ in range(units)]
        sizes = [self._size(k) for k in kinds]
        starts, a = [], CODE_BASE
        for s in sizes:
            starts.append(a)
            a += s
        self.body_end = a
        self.starts = starts
        assert a + 4 < CONST_BASE, "body too large"
        for i in range(0, 0x100, 2):
            self.put(i, 0)
        for k, area in enumerate(SWAP_AREAS):
            # Each trap lands on its own handler, `LPSW <area>`, which reloads the old PSW
            # and PC the swap saved there: execution resumes after the faulting
            # instruction, as a real fault handler would, and no trap can loop.
            handler = TRAP_HANDLERS + 4 * k
            self.put(area + 4, self.safe_psw() & ~0x5000)  # handler runs with EXI, AFI off
            self.put(area + 6, handler)
            self._w(handler, "LPSW", 0, 0, area)
        self.put(0x78, 0x2300)  # AL device X'23' (absent everywhere), command 0
        for i in range(DATA_BASE, DATA_TOP + 0x40, 2):
            self.put(i, edge_or_random(rng))
        for i, (kind, at) in enumerate(zip(kinds, starts, strict=True)):
            self._emit(kind, at, i)
        self.put(self.body_end, 0x4300)  # B body (BFC 0,X'0100')
        self.put(self.body_end + 2, CODE_BASE)
        self.code[self.body_end] = "BFC"
        self.regs = {f"R{i}": edge_or_random(rng) for i in range(16)}
        self.regs["PSW"] = self.safe_psw()
        self.regs["PC"] = CODE_BASE

    KINDS = (
        ["rr"] * 22
        + ["short"] * 10
        + ["rs"] * 20
        + ["rx_read"] * 16
        + ["rx_write"] * 6
        + ["branch_rx"] * 8
        + ["branch_short"] * 3
        + ["loop_short"] * 2
        + ["branch_rr"] * 3
        + ["io"] * 6
        + ["blockio"] * 1
        + ["psw"] * 2
        + ["lpsw"] * 1
        + ["al"] * 1
    )

    def _pick_kind(self) -> str:
        return self.rng.choice(self.KINDS)

    @staticmethod
    def _size(kind: str) -> int:
        return {
            "rr": 2,
            "short": 2,
            "rs": 4,
            "rx_read": 4,
            "rx_write": 4,
            "branch_rx": 4,
            "branch_short": 2,
            "loop_short": 8,
            "branch_rr": 6,
            "io": 8,
            "blockio": 8,
            "psw": 6,
            "lpsw": 4,
            "al": 4,
        }[kind]

    def _w(self, at: int, mnem: str, r1: int, r2: int, addr: int | None = None) -> None:
        op, _form = SUBSET_V0[mnem]
        self.put(at, (op << 8) | ((r1 & 15) << 4) | (r2 & 15))
        self.code[at] = mnem
        if addr is not None:
            self.put(at + 2, addr)

    def _target(self, i: int) -> int:
        """A unit start after unit i, or the closing `B body`. Long branches only go
        forward, so every path reaches the end of the body and starts it again with the
        registers it has by then: no stream can lock into a loop of long branches.
        Backward motion comes only from short backward branches (`_emit`)."""
        later = self.starts[i + 1 : i + 40] + [self.body_end]
        return self.rng.choice(later)

    def _emit(self, kind: str, at: int, i: int) -> None:
        rng = self.rng
        r = rng.randrange
        if kind == "rr":
            m = rng.choice(
                "NHR CLHR OHR XHR LHR CHR AHR SHR MHR DHR ACHR SCHR LBR EXBR MHUR".split()
            )
            self._w(at, m, r(16), r(16))
        elif kind == "short":
            m = rng.choice("LIS LCS AIS SIS SRLS SLLS STBR".split())
            self._w(at, m, r(16), r(16))
        elif kind == "rs":
            m = rng.choice(
                "THI NHI CLHI OHI XHI LHI CHI AHI SHI SRHL SLHL SRHA SLHA RRL RLL SRL SLL SRA SLA".split()
            )
            imm = r(32) if m in ("RRL", "RLL", "SRL", "SLL", "SRA", "SLA") else edge_or_random(rng)
            self._w(at, m, r(16), r(16) if rng.random() < 0.3 else 0, imm)
        elif kind == "rx_read":
            m = rng.choice("NH CLH OH XH LH CH AH SH MH DH ACH SCH LB CLB MHU LM".split())
            x = r(16) if rng.random() < 0.4 else 0
            base = self.data_ea() if rng.random() < 0.8 else r(0x10000) & ~1
            self._w(at, m, r(16), x, base)
        elif kind == "rx_write":
            m = rng.choice("STH STB STM AHM".split())
            self._w(at, m, r(16), 0, self.data_ea(32))
        elif kind == "branch_rx":
            m = rng.choice("BTC BFC BAL BXH BXLE".split())
            self._w(at, m, r(16), 0, self._target(i))
        elif kind == "branch_short":
            # Forward short branches anywhere in reach of a later unit start.
            m = rng.choice("BTFS BFFS".split())
            options = [s for s in self.starts[i + 1 : i + 16] if 0 < s - at <= 30]
            if not options:
                self._w(at, "BTFS", 0, 1)  # mask 0: never taken
                return
            self._w(at, m, r(16), (rng.choice(options) - at) // 2)
        elif kind == "loop_short":
            # Backward short branches only in a bounded countdown, so a stream can never
            # lock into a loop: NHI Rn,F / T: SIS Rn,1 / BTBS G,T (or BFBS L,T or BFBS
            # G|L,T). At most 16 passes, then fall through.
            n = r(15)
            self._w(at, "NHI", n, 0, 0x000F)
            self._w(at + 4, "SIS", n, 1)
            m, mask = rng.choice([("BTBS", 2), ("BFBS", 1), ("BFBS", 3)])
            self._w(at + 6, m, mask, 1)
        elif kind == "branch_rr":
            self._w(at, "LM", 15, 0, self.const(self._target(i)))
            m = rng.choice("BTCR BFCR BALR".split())
            r1 = r(15) if m == "BALR" else r(16)  # BALR R15,R15 would link over the target
            self._w(at + 4, m, r1, 15)
        elif kind == "io":
            self._w(at, "LM", 15, 0, self.const(rng.choice(SAFE_DEVS)))
            m = rng.choice("OCR WDR WHR RDR RHR SSR AIR OC WD WH RD RH SS AI".split())
            if SUBSET_V0[m][1] == "RR":
                self._w(at + 4, m, 15, r(15))
                self._w(at + 6, "LHR", 0, 0)  # pad to a fixed unit size (NOP-like)
            else:
                writes = m in ("RD", "RH", "SS", "AI")
                ea = self.data_ea() if writes or rng.random() < 0.7 else r(0x8000) & ~1
                self._w(at + 4, m, 15, 0, ea)
        elif kind == "blockio":
            start = self.data_ea(20)
            end = start + r(16)
            self._w(at, "LM", 13, 0, self.const(start, end, rng.choice(SAFE_DEVS)))
            m = rng.choice("WBR RBR WB RB".split())
            if m in ("WBR", "RBR"):
                self._w(at + 4, m, 15, 13)
                self._w(at + 6, "LHR", 0, 0)
            else:
                self._w(at + 4, m, 15, 0, self.const(start, end))
        elif kind == "psw":
            self._w(at, "LM", 15, 0, self.const(self.safe_psw()))
            self._w(at + 4, "EPSR", r(16), 15)
        elif kind == "lpsw":
            self._w(at, "LPSW", 0, 0, self.const(self.safe_psw(), self._target(i)))
        elif kind == "al":
            self._w(at, "AL", r(16), 0, 0x0080 + r(8) * 2)
        else:
            raise ValueError(kind)


def load_ops(mem: dict[int, int], regs: dict[str, int], model: str = "716") -> list[tuple]:
    ops: list[tuple] = [("model", model), ("mem", MEMSIZE), ("hist", HIST_MAX)]
    ops += [("dep", a, v) for a, v in sorted(mem.items()) if v]
    ops += [("reg", k, v) for k, v in regs.items()]
    return ops


def run_ops(
    ops: list[tuple], instructions: int, fine: int, chunk: int = HIST_MAX, end_mem=None
) -> list[tuple]:
    ops = list(ops)
    ops.append(("echo", "== fine"))
    for _ in range(min(fine, instructions)):
        ops.append(("step", 1))
        ops.append(("ex", REG_NAMES))
    left = instructions - min(fine, instructions)
    ops.append(("echo", "== coarse"))
    while left > 0:
        k = min(chunk, left)
        ops += [("step", k), ("showhist", k), ("ex", REG_NAMES)]
        left -= k
    if end_mem:
        ops.append(("echo", "== memory"))
        ops.append(("exmem", end_mem[0], end_mem[1]))
    return ops


HIST_LINE = re.compile(r"^([0-9A-F]{4})  [0-9A-F]{4}  [0-9A-F]{4}  ")


def stream_job(args: tuple) -> dict:
    """One seeded stream through the oracle and the engine. With `cycle_ns` (SP-S3E, ADR-008
    condition 2) the engine costs every instruction from the cycle table (ESTIMATE): that changes
    when events fire, never what instructions do, so the traces must still be identical."""
    seed, instructions, fine = args[:3]
    cycle_ns = args[3] if len(args) > 3 else 0
    t0 = time.time()
    s = Stream(seed)
    ops = run_ops(load_ops(s.mem, s.regs), instructions, fine, end_mem=(DATA_BASE, DATA_TOP + 0x3E))
    if cycle_ns:
        ops = [("raw_engine", f"cycles {cycle_ns}")] + ops
    o, e = run_oracle(ops), run_engine(ops)
    a, b = normalise(o), normalise(e)
    c = compare(a, b)
    # Coverage: what the stream actually executed, from the oracle's own history.
    executed = Counter()
    pcs = set()
    for ln in a:
        m = HIST_LINE.match(ln)
        if m:
            pc = int(m.group(1), 16)
            pcs.add(pc)
            executed[s.code.get(pc, "?")] += 1
    hist_lines = sum(executed.values())
    return {
        "seed": seed,
        "instructions": instructions,
        "fine": fine,
        "equal": c.equal,
        "lines_compared": c.lines,
        "history_lines": hist_lines,
        "first_diff": c.first_diff,
        "context": c.context,
        "digest": c.digest,
        "distinct_pcs": len(pcs),
        "body_instructions": len(s.code),
        "mnemonics": dict(executed),
        "seconds": round(time.time() - t0, 1),
    }


def run_streams(
    seeds: list[int], instructions: int, fine: int, jobs: int, cycle_ns: int = 0
) -> list[dict]:
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(stream_job, [(s, instructions, fine, cycle_ns) for s in seeds]))


# --- disassembly cross-check ----------------------------------------------------------


def disasm_job(args: tuple[int, int, int]) -> dict:
    """`count` words starting at `first`, each at its own 4-byte slot with a random second
    word, compared `ex -m` (oracle) against sx_shim_disasm (engine)."""
    seed, first, count = args
    rng = random.Random(seed)
    mem = {}
    for k in range(count):
        mem[k * 4] = (first + k) & 0xFFFF
        mem[k * 4 + 2] = rng.randrange(0x10000)
    ops: list[tuple] = [("mem", 65536)]
    ops += [("dep", a, v) for a, v in sorted(mem.items()) if v]
    ops += [("disasm", k * 4, k * 4) for k in range(count)]
    a, b = normalise(run_oracle(ops)), normalise(run_engine(ops))
    c = compare(a, b)
    return {
        "seed": seed,
        "words": count,
        "equal": c.equal,
        "lines": c.lines,
        "first_diff": c.first_diff,
        "context": c.context,
    }


def run_disasm(total: int, seed: int, jobs: int) -> list[dict]:
    per = 8192  # 8192 slots of 4 bytes fill 32 KB of the 64 KB address space
    work = [(seed + i, i * per, min(per, total - i * per)) for i in range((total + per - 1) // per)]
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(disasm_job, work))


def image_disasm(mem: dict[int, int], lo: int, hi: int, model: str = "716") -> Compare:
    """`ex -m` against sx_shim_disasm over every word of an image's range [lo, hi]."""
    ops: list[tuple] = [("model", model), ("mem", MEMSIZE)]
    ops += [("dep", a, v) for a, v in sorted(mem.items()) if v]
    # one word at a time, so every word is compared even inside a two-word instruction
    ops += [("disasm", a, a) for a in range(lo, hi + 1, 2)]
    return compare(normalise(run_oracle(ops)), normalise(run_engine(ops)))


# --- period programs (SX_FIXTURES_DIR) -----------------------------------------------


def fixtures_dir() -> Path | None:
    d = os.environ.get("SX_FIXTURES_DIR")
    return Path(d).expanduser() if d else None


def lamps_program(fx: Path) -> tuple[dict[int, int], str, int]:
    """The `dep` lines of lamps.ini (read at test time, never copied into the repo)."""
    mem, model, start = {}, "716", 0x100
    for ln in (fx / "lamps.ini").read_text().splitlines():
        parts = ln.split()
        if parts[:2] == ["set", "cpu"] and parts[2] in ("i4", "716"):
            model = parts[2]
        if len(parts) == 3 and parts[0] == "dep":
            if parts[1].lower() == "pc":
                start = int(parts[2], 16)
            else:
                mem[int(parts[1], 16)] = int(parts[2], 16)
    return mem, model, start


M70_LOAD = """set cpu 716
set cpu 32k
d 50 D500
d 52 00CF
d 54 4300
d 56 0080
d 78 0399
attach pt0 {fx}/tapes/178267.pt
reset all
d pc 50
step 400000
attach pt0 {fx}/tapes/178259.pt
d psw 0
step 600000
echo == snapshot
ex {regs}
ex IRQ[0]-IRQ[7],IEN[0]-IEN[7]
ex 0-7FFE
exit
"""


def m70_snapshot(fx: Path) -> tuple[dict[int, int], dict[str, int], dict[str, int]]:
    """Load the M-70 light display through the General Loader in stock id16 (the recipe in
    the fixtures' model74/light-display.exp), then read back memory and registers. The
    snapshot lives only in memory and under build/ (git-ignored); never in the repo."""
    regs = ",".join(n for n in REG_NAMES if n != "CC") + ",SRPOS"
    script = M70_LOAD.format(fx=fx, regs=regs)
    fd, path = tempfile.mkstemp(suffix=".sim", prefix="sx-m70-")
    with os.fdopen(fd, "w") as f:
        f.write(script)
    try:
        out = subprocess.run(
            [oracle_path(), path], stdin=subprocess.DEVNULL, capture_output=True, text=True
        ).stdout
    finally:
        os.unlink(path)
    snap = out.split("== snapshot", 1)[1]
    mem, regs_v, ints = {}, {}, {}
    for ln in snap.splitlines():
        m = re.match(r"^([0-9A-Z\[\]]+):\t([0-9A-F]+)$", ln)
        if not m:
            continue
        k, v = m.group(1), int(m.group(2), 16)
        if re.fullmatch(r"[0-9A-F]+", k) and not k.startswith("R"):
            mem[int(k, 16)] = v
        elif "[" in k:
            ints[k] = v
        else:
            regs_v[k] = v
    return mem, regs_v, ints


def program_job(args: tuple[str, int, int]) -> dict:
    name, instructions, fine = args
    fx = fixtures_dir()
    assert fx is not None
    t0 = time.time()
    if name.startswith("lamps"):
        mem, model, start = lamps_program(fx)
        model = name.split("-", 1)[1] if "-" in name else model
        ops = load_ops(mem, {"PC": start}, model=model)
        mem_range = (0x100, 0x11E)
        # lamps is five instructions and then an illegal-instruction trap loop: keep the
        # fine segment to the program itself and count the rest in interval ticks.
        ops = run_ops(ops, instructions, fine, end_mem=mem_range)
    else:
        mem, regs, ints = m70_snapshot(fx)
        if not mem:
            return {"program": name, "equal": False, "error": "M-70 snapshot failed"}
        regs.pop("SRPOS", None)
        if "-sr" in name:  # the visitor's switches: the show's speed follows them
            regs["SR"] = int(name.split("-sr", 1)[1], 16)
        ops = load_ops(mem, regs)
        ops += [("raw_scp", f"dep {k} {v:X}") for k, v in ints.items() if v]
        # The engine CLI restores IEN through the same CPU registers only if nonzero
        # enables matter; they do not (PSW EXI is clear and no device in the engine
        # interrupts), which the identical traces below confirm.
        ops = run_ops(ops, instructions, fine, chunk=4096, end_mem=(0, 0x7FFE))
    o, e = run_oracle(ops), run_engine(ops)
    a, b = normalise(o), normalise(e)
    c = compare(a, b)
    dr = [ln for ln in a if ln.startswith("DR:\t")]
    hist = [ln for ln in a if HIST_LINE.match(ln)]
    io = Counter(ln.split()[-2] if len(ln.split()) > 4 else "" for ln in hist)
    return {
        "program": name,
        "instructions": instructions,
        "equal": c.equal,
        "lines_compared": c.lines,
        "history_lines": len(hist),
        "dr_samples": len(dr),
        "dr_distinct": len(set(dr)),
        "first_diff": c.first_diff,
        "context": c.context,
        "digest": c.digest,
        "top_mnemonics": io.most_common(8),
        "seconds": round(time.time() - t0, 1),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="S-3 lockstep: engine CPU vs stock id16")
    ap.add_argument("--streams", type=int, default=0, help="random subset streams to run")
    ap.add_argument("--seed-base", type=int, default=1974)
    ap.add_argument("--seed", type=int, action="append", help="run this seed (repeatable)")
    ap.add_argument("--instructions", type=int, default=100_000)
    ap.add_argument("--fine", type=int, default=2000)
    ap.add_argument("--disasm", type=int, default=0, help="random-word disassembly count")
    ap.add_argument("--programs", action="store_true", help="lamps.ini and M-70 (fixtures)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--json", type=Path, help="write the full result here")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv[1:])

    ok = True
    result: dict = {
        "engine": engine_path(),
        "oracle": oracle_path(),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    seeds = list(args.seed or []) + [args.seed_base + i for i in range(args.streams)]
    if seeds:
        t0 = time.time()
        rs = run_streams(seeds, args.instructions, args.fine, args.jobs)
        result["streams"] = rs
        result["streams_seconds"] = round(time.time() - t0, 1)
        for r in rs:
            flag = "ok  " if r["equal"] else "DIFF"
            print(
                f"{flag} seed {r['seed']}: {r['instructions']} instructions, "
                f"{r['lines_compared']} lines, {r['distinct_pcs']}/{r['body_instructions']} "
                f"body instructions reached, {r['seconds']} s"
            )
            if not r["equal"]:
                ok = False
                print(f"     first difference at normalised line {r['first_diff']}:")
                print("\n".join(r["context"]))
    if args.disasm:
        rs = run_disasm(args.disasm, args.seed_base, args.jobs)
        result["disasm"] = rs
        for r in rs:
            print(f"{'ok  ' if r['equal'] else 'DIFF'} disasm seed {r['seed']}: {r['words']} words")
            if not r["equal"]:
                ok = False
                print("\n".join(r["context"]))
    if args.programs:
        if fixtures_dir() is None:
            print("SKIP programs: SX_FIXTURES_DIR is not set (period programs are local fixtures)")
            result["programs"] = "skipped: SX_FIXTURES_DIR unset"
        else:
            work = [
                ("lamps-i4", 2000, 5),
                ("lamps-716", 2000, 5),
                ("m70", args.instructions, args.fine),
                ("m70-sr00A5", args.instructions, args.fine),
            ]
            with ProcessPoolExecutor(max_workers=args.jobs) as ex:
                rs = list(ex.map(program_job, work))
            result["programs"] = rs
            for r in rs:
                print(f"{'ok  ' if r['equal'] else 'DIFF'} program {r['program']}: {r}")
                ok = ok and r["equal"]
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=1, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
