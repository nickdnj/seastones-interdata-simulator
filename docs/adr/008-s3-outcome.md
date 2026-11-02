# ADR-008: S-3 outcome — GO, ADR-001 route C stands

**Status:** Accepted · **Date:** 2026-10-31 · **Decides:** SP-S3D · **Confirms:** ADR-001
**Decision owner:** Nick (standing instruction for this review: take the lanes' recommendations unless
the evidence has a genuine hole). Written by the Software Architecture agent.
**Evidence:** `docs/qa/results/M1/S3.md`, `S3-evidence.json`, `S3D-recommendation.md`,
`docs/qa/results/overnight-2026-10-31-engine.md`

## Context

ADR-001 chose route C (SIMH's `id16` CPU source compiled into the engine, clocked from the sample
counter, stock `id16` as CI oracle) on the condition that spike S-3 showed identical traces against
stock `id16` over 10^6 instructions before anything was built on it. DEV-PLAN 4.1 and 4.2 set five GO
criteria, three no-go triggers and an amber line (shim over 600 lines, or part of the subset passing).

The engine lane ran S-3 unattended on the first overnight build and recommends **GO with no amber**:

| GO criterion | Measured |
|---|---|
| 1. Identical traces, 10^6 instructions, ≥ 20 seeded subset streams + both period programs | 20 streams (seeds 1974–1993) × 10^6 = 2×10^7 instructions, 0 differences. Full state after every instruction for the first 2,000 per stream; SIMH history (PC, R1, operand, EA, instruction text) for the rest, full registers every 65,536, whole data region at the end. `lamps.ini` (I4 and 716) and the M-70 light display (two SR settings, 10^6 each, once at 10^7) identical. Homebrew `id16` gives the same digests |
| 2. `sx_disasm` = `ex -m` | all 65,536 first halfwords (random second word), every code word of three stream images, all 16,384 words of the M-70 image: 0 differences |
| 3. Vendored files = pin except listed patches | 13 files hash-equal to `PROVENANCE.md` and the upstream blobs; patches apply and reverse to pinned bytes; a planted one-line change is caught |
| 4. No semantic patch | two patches only (0001 cycle cost, 0004 device list); a hunk audit attributes every hunk to the interval decrement, `sim_devices`/`sim_load`, or preprocessor lines, and rejects a planted CC mutation |
| 5. Shim ≤ 600 lines | 430 physical, 344 non-comment |

Negative control: a one-line carry-rule mutation in CLHR/CLH/CLHI diverges on 13 of 20 streams.

## Skeptical review

I looked for a hole that would make the GO unsafe, rather than taking the table on trust.

| Concern | Finding | Verdict |
|---|---|---|
| CC compared per instruction only in the first 2,000 of each stream | SIMH's history has no CC field. A wrong CC still surfaces through later branches, carry adds, PSW saves and chunk-end state; the mutant result (13/20) shows the streams read CC. CNF-03 (opcode × CC-outcome matrix) is the full check | Not a hole. CNF-03 must run before M3 (new issue SP-S3E) |
| The lockstep ran with `SX_CYC(op) = 1`, the stock cost | Patch 0001 moves the interval decrement to just after decode. With unit cost it is provably equivalent; with the real cycle table it changes **when events fire**, not what instructions do. No clock or device events exist in the streams, so instruction traces must be identical under any cost table. That has not been run | **Gap, cheap to close.** Rerun the 20 streams with `cycles-716.tsv` loaded (SP-S3E). Does not block GO: it tests the same code path with different integers |
| PIC and LFC are not exercised | Stock `id16` calibrates them against host time, so they cannot be lock-stepped. Patches 0002/0003 were dropped and their job moved into the shim's `sim_rtcn_*` and `sim_idle`, so **the shim, not a patch, now defines emulated-time clock behaviour** | Real gap, outside S-3's remit. CNF-11 (M3) must cover tick rate in emulated time, scaling with the speed detent, and wait-state slice consumption (SP-S3E pulls the shim half forward to M2, because VS-02 builds on it) |
| Our devices (X'20'–X'22') are absent from the streams | By design; VS-06 checks them against `id16-seastones` with the same source file | Not an S-3 question |
| 716-class instructions outside the subset (FP, list, SVC, SINT) not lock-stepped | The program cannot assemble them (`--subset`); `id_fp.c` is linked only because the CPU references it | Acceptable. CNF-03 nightly covers them |
| Mac arm64 only; Linux x86-64 unverified | The station is Linux x86-64. Host-dependent behaviour in this code is limited (integer CPU, no host clock), but it is unmeasured | **Condition on SP-GATE**, not on GO: `make ci` green on Debian/Ubuntu x86-64 with the same digests |
| Upstream UB in `display()` (shift into sign bit), ignored under UBSan for that function | Stock compiles the same line, so the lockstep compares like with like; behaviour is implementation-defined on both targets with clang/gcc | Accepted, recorded in `PROVENANCE.md` |
| Disassembler quirks (forward short branches print as BTBS/BFBS; `AL` with R1 ≠ 0 prints raw; `LB`/`LBR` names) | `ex -m` shows the same, so CODE-3's "listing equals SIMH's disassembly" still holds; the code view inherits SIMH's text | Not a hole. PR-11 labels it (new issue PR-16) |

No no-go trigger fired and no hole changes the verdict. The three gaps above become conditions with
owners and dates.

## Decision

**GO. ADR-001 route C stands**, and ADR-001 moves from Proposed to Accepted. FB-01 to FB-04 are not
started. The "provisional on S-3 decision" commits on the merged engine lane (VS-01, VS-03 to VS-09
from `413229f` on) are no longer provisional.

Conditions (tracked as SP-S3E, not blocking the vertical slice):
1. Linux x86-64 `make ci` reproduces the S-3 digests before **SP-GATE**.
2. The 20-stream lockstep is rerun with the real cycle table loaded, before **VS-02 closes**.
3. Shim clock and idle tests (emulated-time PIC/LFC tick rate, scaling with speed, `sim_idle` consuming
   the slice) before **VS-02 closes**; CNF-03 nightly running before **M3**.

### Contract changes adopted (ARCHITECTURE updated to match)

| Was (ARCHITECTURE 0.1) | Now | Where |
|---|---|---|
| `int sx_snapshot(sx_engine *, sx_snapshot *out)` | `int sx_snapshot_read(sx_engine *, sx_snapshot *out)`: C cannot give a typedef and a function the same name | §4.3, `seastones.h` |
| Four patches 0001–0004 | **Two patches**: `0001-cycle-cost`, `0004-devices`. 0002 (emulated RTC) and 0003 (idle in engine) are not needed: `id_uvc.c` calibrates only through `sim_rtcn_init`/`sim_rtcn_calb`, and the wait state only calls `sim_idle`; the shim implements all three on emulated time. Numbers 0002/0003 are retired, not reused | §4.2, §12 |
| Four vendored `.c` files | **Five**: `id16_cpu.c id_io.c id_uvc.c id16_sys.c id_fp.c`. The CPU calls the FP routines, so `id_fp.c` must link even though the subset excludes FP. CT-12's licence audit and RIGHTS-7 list it | §2.2, §4.2, PRD MACH-1 |
| Shim "~300 lines" | 430 lines (ceiling stays 600) | §2.2 |

Numbering note: FB-01 in the backlog says its fallback would be recorded "as ADR-009". FB-01 is now
not started, and ADR-009 is the scan-loop budget. If the fallback is ever revived it takes the next
free number.

## Consequences

- Positive: the engine route is proven against SIMH on the instruction set the program can use; the
  oracle harness is in CI and becomes the regression gate (PO-07); the vertical slice continues on the
  merged branch without rework; the shim is smaller than its ceiling.
- Negative: the shim now carries clock and idle semantics that a patch would otherwise have made
  visible in the diff, so it needs its own tests (condition 3). Evidence is single-platform until
  condition 1. The code view inherits SIMH's disassembly quirks.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **GO** | evidence meets every criterion with margin; gaps are cheap follow-ups | three follow-ups to track |
| Amber (hold until Linux and the cycle-table rerun) | removes the two cheap gaps first | blocks ~50 points of merged, passing work for checks that cannot change instruction semantics; DEV-PLAN reserves amber for shim size or partial subset, neither of which happened |
| No-go, route B (own core) | none; no trigger fired | ~20 points of rework for no measured reason |
