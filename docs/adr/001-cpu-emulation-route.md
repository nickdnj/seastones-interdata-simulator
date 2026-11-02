# ADR-001: CPU emulation route — SIMH's id16 CPU source inside the engine

**Status:** Accepted (confirmed by ADR-008, S-3 GO) · **Date:** 2026-10-31 · **Changes PRD:** D6, MACH-1, CODE-3, PANEL-2 (ARCHITECTURE §17)

> **Amended by ADR-008 (2026-10-31).** S-3 found that five files are vendored (`id_fp.c` as well,
> because the CPU calls it), that only two patches are needed (0001 cycle cost, 0004 devices; the
> emulated clocks and idle live in the shim), and that the shim is 430 lines. The Decision text
> below is kept as written; ADR-008 and ARCHITECTURE §4.2 are current.

## Context

The PRD requires that every note come from our 7/16 program running on an emulated CPU (D6). It
also requires ≤ 25 ms p95 key-to-sound (NFR-1), ≤ 5 ms D/A jitter with authentic stepping (NFR-2),
a speed knob down to single-step (PLAY-7, PANEL-2), lamps at ≥ 30 Hz and a live code view (PANEL-1,
CODE-1/3), fidelity to a real 7/16, and unattended robustness (G5).

Probed facts (2026-10-31, `id16` V3.12-3 and pinned source `c0f0a88`):
- `set cpu 716` is accepted, `set cpu 7/16` is rejected, and 7/16 is the power-up default. SIMH's
  716 class covers the Model 5, 70, 80 and 7/16.
- 716 vs I4: 36 more instructions (Model 5 group, including halfword I/O), PSW mask FF0F vs F40F,
  FP-fault trap, display device wraps mod 8, console interrupt (ARCHITECTURE §2.1).
- **SIMH has no instruction timing**: one instruction is one tick, and `set throttle` regulates
  instructions per host second in bursts.
- In SIMH 3.x, examining state needs the simulator stopped. The Model 4 kiosk therefore steps in
  bounded batches and never free-runs, which quantises timing to its batch tick.

## Decision

**Route C.** Vendor `id16_cpu.c`, `id_io.c`, `id_uvc.c` and `id16_sys.c` from the pinned tag into
`src/engine/simh/`. Replace SCP with a ~300-line shim. Clock the CPU from the audio sample counter
(cycles of 250 ns, costs from a cited 7/16 timing table). Run it in the same render call as our
devices and the synthesizer. Patches are limited to cycle cost, emulated-time clocks, wait-state
handling and device registration.

SIMH is still used as: the CPU source; **stock `id16` as the CI conformance oracle** (instruction
lockstep through `set cpu history` / `show history`); **`id16-seastones`** (pinned tag + the
identical device source file) as the device-trace oracle and Phase 2 reference; and `ex -m` as the
disassembly check.

## Consequences

- Positive: deterministic, bit-exact output; D/A writes land on their exact audio frame (zero host
  jitter); the speed knob and single-step are exact; one process, no console ports; SIMH's tested
  instruction semantics; SIMH's own disassembler in the code view; offline renders for research.
- Negative: the PRD's literal "the running process is `id16`" no longer holds; we own a small shim
  and patch set; "authentic speed" depends on a cycle table SIMH never had; SIMH globals mean one
  engine per process.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| A. `id16` out-of-process, C devices, bridge + IPC to audio | literal MACH-1; Model 4 bridge patterns | throttled bursts make D/A timing clumpy, so NFR-2 costs most of the latency budget; speed changes need Ctrl-E/`cont` (input dropped for seconds); lamps need stopping the sim; three processes + IPC + console-port hygiene |
| B. Purpose-built core (Rust/TS → WASM) | clean, full control | ~100 instructions × CC/PSW/I/O semantics to get right; must also write a disassembler; fidelity rests on us, with SIMH only checking |
| **C. SIMH CPU source in the engine** | SIMH fidelity + in-process determinism | shim/patch maintenance; PRD wording change |

## Risk note

The extraction may hide SCP coupling (event queue, stop semantics). **Spike S-3** builds it first
and must show identical traces against stock `id16` over 10⁶ instructions before anything is built
on it. If S-3 fails, fall back to **B with SIMH as oracle**, which keeps every other ADR intact
because the engine API (ARCHITECTURE §4.3) does not depend on whose CPU code is behind it.
