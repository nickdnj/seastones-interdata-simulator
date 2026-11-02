"""PO-03, PO-04, PO-13 acceptance: the polyphonic program, voice allocation in 7/16 code
(PRG-01, PRG-03, PRG-04, PRG-05, PRG-12, DEV-18), on both channel maps, and its device traces
against id16-seastones (DEV-14, CNF-01 for our program).

The program is assembled by sxasm from src/program/ with the rig data (src/program/rig/) and
run in sx-cpu (the engine's CPU, devices and clock) and in id16-seastones (stock id16 at the
pin plus the same device file). Times on the engine clock use the cycle table, whose STATUS is
ESTIMATE, so "RUN" means "as fast as the ESTIMATE says".
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from progtools import (  # noqa: E402
    BASENOTE,
    GATE_HI,
    MAPS,
    MS,
    L,
    Voices,
    assemble,
    clocked,
    engine_ok,
    engine_writes,
    load_ops,
    oracle_lines,
    pitch,
)

_skip = pytest.mark.skipif(not engine_ok(), reason="engine not built")


def needs_engine(f):
    """Engine tests run under `make conformance`, after the engine and program are built."""
    return pytest.mark.lockstep(_skip(f))


BOTH = pytest.mark.parametrize("m", list(MAPS))


# --- static checks (no engine) -------------------------------------------------------------


def test_program_stays_in_the_subset_and_uses_only_contract_io() -> None:
    """DEV-18: every instruction is in m74-portable-1 and inside a *@block (PO-01); devices are
    reached only by I/O instructions through registers loaded with a device number."""
    a, _ = assemble()
    io = {"OC", "RD", "RH", "WD", "WH", "WHR", "WDR", "RDR", "RHR", "OCR", "SS", "SSR"}
    devices = {"KEYS", "DAC", "GATE", "PANEL", "PIC"}
    loaded = {}
    for ln in a.lines:
        if ln.opc == "LHI" and ln.operands.split(",")[1] in devices:
            loaded.setdefault(ln.operands.split(",")[0], set()).add(ln.operands.split(",")[1])
    for ln in a.lines:
        if ln.opc in io:
            reg = ln.operands.split(",")[0]
            assert reg in loaded, f"{ln.file}:{ln.number}: I/O through {reg}"
        if ln.words:
            assert ln.block, f"{ln.file}:{ln.number} is outside a block"
    assert loaded["R10"] == {"KEYS"} and loaded["R11"] == {"DAC"} and loaded["R12"] == {"GATE"}
    assert loaded["R6"] == {"PIC"} and loaded["R9"] == {"PANEL"}


def test_changing_the_channel_map_changes_the_map_table_and_nothing_else() -> None:
    """PO-01, PO-05: the two maps give images that differ only inside the channel-map table."""
    a4, o4 = assemble("all-da-4")
    _, o8 = assemble("latch-8")
    m = a4.symbols["MAP"]
    w4 = {int(s["addr"], 16) + 2 * i: w for s in _segs(o4) for i, w in enumerate(s["words"])}
    w8 = {int(s["addr"], 16) + 2 * i: w for s in _segs(o8) for i, w in enumerate(s["words"])}
    assert w4.keys() == w8.keys()
    diff = sorted(k for k in w4 if w4[k] != w8[k])
    assert diff and all(m <= k < m + 70 for k in diff), [hex(k) for k in diff]


def _segs(out: dict[str, str]) -> list[dict]:
    import json

    return json.loads(out["rig.img.json"])["segments"]


def test_planted_violations_fail_with_file_and_line(tmp_path: Path) -> None:
    """PO-01: an out-of-subset instruction, and an instruction outside any block."""
    from progtools import PROGRAM, RIG, SUBSET
    from sxasm.__main__ import main as sxasm_main

    srcs = {p.name: p.read_text() for p in PROGRAM}
    bad = dict(srcs)
    bad["scan.s"] = srcs["scan.s"].replace(
        "LOOP     OC    R10,FROMROW0", "LOOP     OC    R10,FROMROW0\n         SVC   1,0"
    )
    bad2 = dict(srcs)
    bad2["rig.s"] = srcs["rig.s"].replace(
        "         ORG   X'0080'\n", "         ORG   X'0080'\n         LHI   R1,0\n"
    )
    for case, files in (("subset", bad), ("block", bad2)):
        d = tmp_path / case
        d.mkdir()
        for n, t in files.items():
            (d / n).write_text(t)
        args = [str(d / p.name) for p in PROGRAM] + ["-o", str(d / "out"), "--subset", str(SUBSET)]
        args += ["--map", str(RIG / "channel-map.md"), "--dac", str(RIG / "dac.md")]
        assert sxasm_main(args) == 1
        assert not (d / "out").exists()


@pytest.mark.parametrize(
    "edit,expect",
    [
        (("voices: 4", "voices: 9"), r"channel-map\.md:2: 'voices' is 9; it must be from 1 to 8"),
        (
            ("pitch: 0 1 2 3", "pitch: 0 1 2"),
            r":4: 'pitch' lists 3 channel\(s\) but 'voices' says 4",
        ),
        (("cutoff: 8", "cutoff: 3"), r":7: D/A channel 3 is used twice: pitch of voice 4 and"),
        (("gates: dac", "gates: maybe"), r":3: 'gates' must be 'latch' or 'dac'"),
        (("rate: 10", "rate 10"), r":9: expected 'key: value', found 'rate 10'"),
    ],
)
def test_channel_map_errors_are_plain_english_with_file_and_line(tmp_path, edit, expect) -> None:
    """PO-05: parser errors name the file and the line, in plain words."""
    from progtools import RIG
    from sxasm import RigDataError, RigTables

    text = (RIG / "channel-map.md").read_text().replace(*edit)
    (tmp_path / "channel-map.md").write_text(text)
    with pytest.raises(RigDataError) as e:
        RigTables(tmp_path / "channel-map.md", RIG / "dac.md")
    assert re.search(expect, str(e.value)), str(e.value)


# --- the engine: keys to voices -------------------------------------------------------------


def run_keys(m: str, schedule: list[tuple], warm: int = 3000) -> list[tuple]:
    _, out = assemble(m)
    return engine_writes(load_ops(out["rig.dep.sim"]) + [("step", warm)] + schedule)


def voice_events(m: str, writes: list[tuple]) -> list[tuple]:
    """('on', voice, note) / ('off', voice) in order, from pitch then gate writes."""
    v = Voices(m)
    ev, last_pitch = [], {}
    prev = [0] * v.n
    for (dev, ch, val, _t), g in zip(writes, v.gates_from([w[:3] for w in writes]), strict=True):
        if dev == 0x21 and ch in v.pitch_ch:
            last_pitch[v.pitch_ch.index(ch)] = val
        for i in range(v.n):
            if g[i] != prev[i]:
                ev.append(("on", i, last_pitch.get(i)) if g[i] else ("off", i))
        prev = g
    return ev


@needs_engine
@BOTH
def test_start_up_silences_every_gate_and_lane(m: str) -> None:
    w = run_keys(m, [], warm=3000)
    v = Voices(m)
    assert all(val == 0 for _d, _c, val, _t in w)
    lanes = {c for d, c, _v, _t in w if d == 0x21}
    assert set(v.lanes.values()) <= lanes


@needs_engine
@BOTH
def test_every_key_plays_its_pitch(m: str) -> None:
    """PRG-03: each key alone gets voice 1 (after release the free queue moves on), its note's
    code on that voice's pitch channel, and the gate; release lowers it."""
    v = Voices(m)
    sched = []
    for k in range(37):
        sched += [("keys", 1 << k), ("step", 400), ("keys", 0), ("step", 400)]
    ev = voice_events(m, run_keys(m, sched))
    ons = [e for e in ev if e[0] == "on"]
    offs = [e for e in ev if e[0] == "off"]
    assert len(ons) == 37 and len(offs) == 37
    for k, (on, off) in enumerate(zip(ons, offs, strict=True)):
        assert on[2] == pitch(BASENOTE + k), (k, on)
        assert on[1] == off[1] == k % v.n, "the voice that rested longest is taken first"


@needs_engine
@BOTH
def test_voice_allocation_and_documented_steal_order(m: str) -> None:
    """PRG-04: the first N keys get distinct voices; key N+1 steals the oldest note's voice,
    whose gate drops and rises again; a released voice is reused before a busy one is stolen."""
    v = Voices(m)
    n = v.n
    sched = []
    for k in range(n + 2):  # n keys, then two more: steal voice 0, then voice 1
        sched += [("keys", (1 << (k + 1)) - 1), ("step", 600)]
    ev = voice_events(m, run_keys(m, sched))
    ons = [e for e in ev if e[0] == "on"]
    assert [o[1] for o in ons[:n]] == list(range(n))
    assert ons[n][1] == 0 and ons[n][2] == pitch(BASENOTE + n)  # the oldest note's voice
    assert ons[n + 1][1] == 1
    i = ev.index(ons[n])
    assert ev[i - 1] == ("off", 0), "the stolen voice's gate drops before it rises again"
    # release key 2 (voice 2): the next new key takes voice 2, not a busy one
    held = (1 << (n + 2)) - 1
    sched += [("keys", held & ~(1 << 2)), ("step", 600), ("keys", held & ~(1 << 2) | 1 << 30)]
    sched += [("step", 600)]
    ev = voice_events(m, run_keys(m, sched))
    last_on = [e for e in ev if e[0] == "on"][-1]
    assert last_on[1] == 2 and last_on[2] == pitch(BASENOTE + 30)


PRG05_RUNS = 1000


@needs_engine
@BOTH
def test_ten_keys_random_release_never_sticks(m: str) -> None:
    """PRG-05: 1,000 seeded permutations of press-ten-then-release-in-random-order, in one
    session: after each last release and one scan, every gate is down and the voice table is
    empty (every voice free, the age queue empty)."""
    a, out = assemble(m)
    rng = random.Random(1974)
    print(f"seed 1974, {PRG05_RUNS} runs, map {m}")
    lo, hi = a.symbols["AHEAD"], a.symbols["FCOUNT"]
    sched: list[tuple] = []
    for _ in range(PRG05_RUNS):
        keys = rng.sample(range(37), 10)
        bits = 0
        for k in keys:
            bits |= 1 << k
            sched += [("keys", bits), ("step", rng.randrange(60, 400))]
        rng.shuffle(keys)
        for k in keys:
            bits &= ~(1 << k)
            sched += [("keys", bits), ("step", rng.randrange(60, 400))]
        sched += [("step", 400), ("exmem", lo, hi), ("echo", "END-OF-RUN")]
    ops = [("trace",)] + load_ops(out["rig.dep.sim"]) + [("step", 3000)] + sched
    v = Voices(m)
    writes, mem, runs = [], {}, 0
    for ln in L.run_engine(ops).splitlines():
        if ln.startswith("W "):
            _, dev, ch, val, _t = ln.split()
            writes.append((int(dev, 16), int(ch, 16), int(val, 16)))
        elif re.match(r"^[0-9A-F]{4}:", ln):
            addr, word = ln.split()
            mem[int(addr[:-1], 16)] = int(word, 16) >> 8
            mem[int(addr[:-1], 16) + 1] = int(word, 16) & 0xFF
        elif ln.strip() == "END-OF-RUN":
            runs += 1
            assert v.gates_from(writes)[-1] == [0] * v.n, f"run {runs}: a gate stuck"
            assert mem[a.symbols["AHEAD"]] == 0xFF, f"run {runs}: the age ring is not empty"
            assert mem[a.symbols["FCOUNT"]] == 0 and mem[a.symbols["FCOUNT"] + 1] == v.n, runs
    assert runs == PRG05_RUNS


@needs_engine
@BOTH
def test_ten_keys_gates_all_down_after_each_run(m: str) -> None:
    """PRG-05, the gate half, replayed precisely: per run, the gate state after the last
    release is all down."""
    a, out = assemble(m)
    rng = random.Random(1975)
    v = Voices(m)
    for run in range(60):
        keys = rng.sample(range(37), 10)
        bits, sched = 0, []
        for k in keys:
            bits |= 1 << k
            sched += [("keys", bits), ("step", rng.randrange(60, 400))]
        rng.shuffle(keys)
        for k in keys:
            bits &= ~(1 << k)
            sched += [("keys", bits), ("step", rng.randrange(60, 400))]
        w = run_keys(m, sched + [("step", 400)])
        g = v.gates_from([x[:3] for x in w])
        assert g[-1] == [0] * v.n, (run, keys)
        assert max(sum(s) for s in g) == v.n  # every voice was used


# --- PRG-01: the four latency limits (ADR-009) -----------------------------------------------


def _pitch_and_gate_frames(m: str, w: list[tuple], t0: int, key: int) -> tuple[int, int]:
    """The frame of `key`'s pitch write and of the gate rise that follows it."""
    v = Voices(m)
    code = pitch(BASENOTE + key)
    pf = next(f for f, dev, ch, val in w if f >= t0 and dev == 0x21 and val == code and
              ch in v.pitch_ch)  # fmt: skip
    voice = v.pitch_ch.index(next(ch for f, dev, ch, val in w if f == pf and val == code))
    if v.dac_gates:
        gf = next(f for f, dev, ch, val in w if f >= pf and dev == 0x21 and
                  ch == v.gate[voice] and val == GATE_HI)  # fmt: skip
    else:
        mask = 0x8000 >> v.gate[voice]
        gf = next(f for f, dev, _ch, val in w if f >= pf and dev == 0x22 and val & mask)
    return pf, gf


@needs_engine
@BOTH
def test_prg01_l1_one_key_change_to_writes(m: str) -> None:
    """L1: one key change to its pitch and gate writes at most 1.0 ms, at many loop phases,
    with every voice already busy (so the press steals); a release to its gate write."""
    _, out = assemble(m)
    v = Voices(m)
    busy = sum(1 << k for k in range(v.n))
    worst = 0.0
    for k in (20, 33, 36):
        for lead in range(1, 12):
            t0 = 200 + lead
            w = clocked(
                out, [("keys", busy), ("frames", t0), ("keys", busy | 1 << k), ("frames", 96)]
            )
            pf, gf = _pitch_and_gate_frames(m, w, t0, k)
            worst = max(worst, (max(pf, gf) - t0) / MS)
            w = clocked(out, [("keys", 1 << k), ("frames", t0), ("keys", 0), ("frames", 96)])
            offs = [f for f, dev, ch, val in w if f >= t0 and ((dev == 0x21 and ch in v.gate and
                    val == 0) if v.dac_gates else dev == 0x22)]  # fmt: skip
            assert offs, (k, lead)
            worst = max(worst, (offs[0] - t0) / MS)
    print(f"L1 worst ({m}): {worst:.3f} ms (limit 1.0, cycle table ESTIMATE)")
    assert worst <= 1.0


@needs_engine
@BOTH
def test_prg01_l8_l37_chords_and_a_smash(m: str) -> None:
    """L8: an 8-key chord with every voice busy, every key at most 2.0 ms. L37: all 37 keys at
    once, every key handled (none lost) within 6.0 ms, the first within 1.0 ms. 'Handled' is the
    key's pitch write and gate rise; with 4 or 8 voices most keys of a smash are stolen from at
    once, so for each key we time its own pitch write."""
    a, out = assemble(m)
    v = Voices(m)
    t0 = 300
    results = {}
    for case, keys in (("L8", [3, 7, 12, 16, 19, 24, 28, 31]), ("L37", list(range(37)))):
        bits = sum(1 << k for k in keys)
        # L8 starts with keys 33-36 held (voices busy); L37 is every key changing at once
        busy = 0 if case == "L37" else sum(1 << k for k in range(33, 37))
        w = clocked(out, [("keys", busy), ("frames", t0), ("keys", busy | bits), ("frames", 600)])
        times = []
        for k in sorted(keys):
            code = pitch(BASENOTE + k)
            f = [fr for fr, dev, ch, val in w if fr >= t0 and dev == 0x21 and val == code and
                 ch in v.pitch_ch]  # fmt: skip
            assert f, f"{case}: key {k} was lost"
            times.append((f[0] - t0) / MS)
        results[case] = (min(times), max(times))
    print(f"{m}: L8 {results['L8'][1]:.2f} ms, L37 first {results['L37'][0]:.2f} ms, "
          f"last {results['L37'][1]:.2f} ms (limits 2.0, 1.0, 6.0; cycle table ESTIMATE)")  # fmt: skip
    assert results["L8"][1] <= 2.0
    assert results["L37"][0] <= 1.0
    assert results["L37"][1] <= 6.0


def pass_ticks(out: dict[str, str], loop: int, schedule: list[tuple]) -> list[tuple[int, int]]:
    ops: list[tuple] = [("raw_engine", "cycles 250")] + load_ops(out["rig.dep.sim"])
    for op in schedule:
        ops.append(op if op[0] == "keys" else ("raw_engine", f"period {loop:X} {op[1]}"))
    res = []
    for ln in L.run_engine(ops).splitlines():
        if ln.startswith("period "):
            parts = ln.split()
            res.append((int(parts[5]), int(parts[7])))
    return res


@needs_engine
@BOTH
def test_prg01_p_every_pass_is_short(m: str) -> None:
    """P: any single pass at most 0.5 ms, an idle pass at most 0.15 ms, through a 37-key smash
    with every voice stolen K times a pass, and its release."""
    a, out = assemble(m)
    loop = a.symbols["LOOP"]
    all37 = (1 << 37) - 1
    w = pass_ticks(
        out,
        loop,
        [("period", 3000), ("keys", all37), ("period", 6000), ("keys", 0), ("period", 6000)]
        + [("keys", 1 << 36), ("period", 600), ("keys", 0b1010101), ("period", 900)],
    )
    idle_us = w[0][1] * 0.25
    busy_us = max(hi for _, hi in w) * 0.25
    print(f"P ({m}): idle pass {idle_us:.1f} us, longest {busy_us:.1f} us (ESTIMATE)")
    assert idle_us <= 150
    assert busy_us <= 500


# --- VS-06 / DEV-14: device traces equal id16-seastones ------------------------------------


def schedule(seed: int) -> list[tuple]:
    rng = random.Random(seed)
    ops: list[tuple] = []
    for _ in range(25):
        kind = rng.random()
        if kind < 0.3:
            bits = 0
        elif kind < 0.7:
            bits = 1 << rng.randrange(37)
        else:
            bits = rng.getrandbits(37)
        ops += [("keys", bits), ("step", rng.randrange(1, 3000))]
    return ops


def trace_lines(ops: list[tuple]) -> list[str]:
    return [ln for ln in L.run_engine([("trace",)] + ops).splitlines() if ln.startswith("W ")]


@needs_engine
@BOTH
@pytest.mark.parametrize("seed", range(1974, 1980))
def test_device_traces_equal_id16_seastones(m: str, seed: int) -> None:
    """DEV-14: the same key schedule (by instruction count) into the engine and id16-seastones
    gives identical D/A and gate writes: device, channel, value, time."""
    _, out = assemble(m)
    ops = load_ops(out["rig.dep.sim"]) + schedule(seed)
    eng, orc = trace_lines(ops), oracle_lines(ops)
    print(f"{m} seed {seed}: {len(eng)} writes")
    assert len(eng) > 20
    assert eng == orc, "\n".join(
        f"{x!r:30} {y!r}" for x, y in zip(eng, orc, strict=False) if x != y
    )


@needs_engine
@BOTH
def test_program_lockstep_against_id16_seastones(m: str) -> None:
    """CNF-01 for our program: instruction by instruction (history, registers) against
    id16-seastones, with a random key schedule, in the play routine."""
    import subprocess

    from progtools import ROOT

    _, out = assemble(m)
    seastones = subprocess.run(
        [str(ROOT / "scripts" / "build-oracle.sh"), "--seastones"],
        capture_output=True, text=True, check=True,
    ).stdout.split()[-1]  # fmt: skip
    ops = load_ops(out["rig.dep.sim"]) + [("hist", 65536)]
    for op in schedule(1974):
        ops.append(op)
        if op[0] == "step":
            ops += [("showhist", op[1]), ("ex", L.REG_NAMES)]
    c = L.compare(L.normalise(L.run_oracle(ops, oracle=seastones)), L.normalise(L.run_engine(ops)))
    assert c.equal, "\n".join(c.context)
