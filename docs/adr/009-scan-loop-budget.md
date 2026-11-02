# ADR-009: Scan-loop budget — restate it as key-to-write latency, and make the scan smarter

**Status:** Accepted (architecture owner) · **Date:** 2026-10-31 · **Changes:** ARCHITECTURE §5.5,
§5.6, §6.6; QA PRG-01 and LAT-01 (QA to edit TEST-PLAN, issue QA-01); backlog VS-09 and PO-04 ACs
(superseded by PO-13)
**Evidence:** `docs/qa/results/M1/S4.md`, `S4-scan-cases.json`, `tools/cycles/cycles-716.tsv`
(`STATUS: ESTIMATE`, Model 74 table 29-261R01 App. 5 as proxy), `tools/cycles/sketches/scan-37.txt`

## Context

ARCHITECTURE 0.1 §5.6 set a design constraint: *worst-case scan-loop period ≤ 1.0 ms of emulated time,
all 37 keys changing, score active*, and §6.6 gave the scan 1.0 ms of the 25 ms NFR-1 budget. The
harness lane costed a straightforward draft loop against the S-4B cycle table:

| Case (draft loop, RUN) | Instructions | Period |
|---|---|---|
| idle, no score | 25 | 67 µs |
| idle, score tick | 35 | 100 µs |
| one key, 4 voices busy | 114 | 328 µs |
| one key, 8 voices busy | 146 | 409 µs |
| 4-note chord, 2 rows, 4 voices | 283 | 801 µs |
| **8-note chord, 3 rows, 8 voices** | 753 | **2.04 ms** |
| **all 37 keys, 4 voices** | 1,870 | **5.15 ms** |
| **all 37 keys, 8 voices** | 3,054 | **8.15 ms** |

The mix runs at 2.75–2.9 µs per instruction (350–375 k instructions/s), inside §2.1's independent
250–450 k estimate, so the result does not hinge on the proxy table. About 350 instructions fit in
1 ms. The worst case misses the limit by 5× to 8×. 70% of it is the linear voice search, repeated
for every changed key; most of the rest is walking all 8 bits of every changed row.

Two things were wrong with the original constraint:
1. **It measured the wrong quantity.** What a visitor feels is how long after a key goes down its
   pitch and gate are written. Loop period is a proxy for that only when one key changes per lap.
2. **The program design was naive**, and the speed is not ours to change (MACH-5 fixes it).

## Options considered

| Option | What it does | Numbers | Verdict |
|---|---|---|---|
| A. Relax only | Keep the draft loop; raise the limit to ~8 ms | 8-voice smash: 15.2 + 8.15 = 23.4 ms against 25 ms, so 1.6 ms of margin left for every p95 tail. One pass can last 8 ms, so the 1 ms score tick slips by up to 8 ticks and the code view's "loop" becomes erratic | Rejected alone: it spends the margin on a design flaw |
| B1. Changed-row skip | XOR each row with its previous value; unchanged rows cost one branch | Already in the draft | Keep |
| B2. First-set-bit table | Replace the 8-step bit walk of a changed row with a 256-byte table lookup (`LB` indexed by the change byte) and a clear of that bit, looped once per changed **key** rather than per bit | ~5 instructions per changed key instead of ~32 per changed row | **Adopt** |
| B3. O(1) voice allocation | Free list plus an age queue (oldest at the head) plus a key→voice map (64 bytes). Press: pop the free list, else steal the head of the age queue. Release: look up the voice by key, push it free. No search | ~8 instructions per press, ~6 per release, independent of voice count | **Adopt** |
| B4. Bounded work per pass | Handle at most `K` key changes per pass (assembled constant, `K = 4`); the rest wait for the next pass. The score block runs once per pass after the keys | One pass is bounded whatever the hands do; a smash spreads over a few passes in key order | **Adopt** |
| C. Hardware scan-latch / change FIFO in KEYS | The device reports changed rows (a mask) or queues key events | Saves most of "what-changed" (~25% of a key's cost) | Rejected for v1: it moves the teaching logic (the computer noticing a key) out of the program, adds invented hardware beyond ADR-003's minimal protocol, and complicates the Phase 2 board. A one-halfword "changed rows" mask is the fallback if B misses its numbers |
| D. Keyboard interrupt | Interrupt on key change | — | Rejected: MACH-6 and §5.7 keep the program polled-only |
| E. Faster CPU constant | Assume 750 ns core | — | Rejected: MACH-5 sets the speed from the cycle table, not from what the program needs |

## Decision

**Both: restate the constraint in latency terms, and adopt B1–B4 in the program.**

### The constraint (replaces ARCHITECTURE 0.1 §5.6's single 1.0 ms period)

Measured in **emulated time at RUN**, from the instant the KEYS device's bitmap changes (the period-start
latch) to the completion of that key's pitch write **and** gate write (for a release: the gate write).
Asserted by PRG-01 from the engine's device-event timestamps, not wall time, with the score active and
every voice busy:

| ID | Case | Limit | Design estimate (B1–B4, ESTIMATE table) | Draft loop (for comparison) |
|---|---|---|---|---|
| **L1** | one key changes | **≤ 1.0 ms** | ≈ 0.25 ms | 0.33–0.41 ms |
| **L8** | up to 8 keys change at once (a chord) | every key **≤ 2.0 ms** | ≈ 0.95 ms (two passes) | 2.04 ms |
| **L37** | all 37 keys change at once | every key **≤ 6.0 ms**, none lost, first key ≤ 1.0 ms | ≈ 4.0 ms (10 passes) | 5.15–8.15 ms |
| **P** | any single pass | **≤ 0.5 ms**; idle pass ≤ 0.15 ms | ≈ 0.42 ms max (4 keys + score); 67–100 µs idle | unbounded |

Basis of the estimate (per item, at the S-4B mean of ~2.8 µs per instruction): base pass 25–35
instructions (67–100 µs); each changed row ~4 instructions (~11 µs); each changed key: first-set-bit
lookup and clear ~5 (~14 µs), allocation ~8 (~24 µs), pitch and gate writes ~10 (~33 µs), so ~71 µs per
key. With `K = 4`, a full pass is ≤ 100 + 3 × 11 + 4 × 71 ≈ 417 µs. These are estimates against an
`ESTIMATE` table; PO-13 replaces them with `cycle-calc` output on the revised sketch, then with engine
measurements.

**Why these limits.** NFR-1 is 25 ms p95 / 40 ms p99 per key press. ARCHITECTURE §6.6 spends
15.2 ms on everything that is not the program (keyboard, USB, period wait, envelope onset, ALSA ring,
interface). Then:
- L1 keeps §6.6's 1.0 ms line, so the **p95 single-key budget stays 16.2 ms** (8.8 ms margin).
- L8: the last note of a chord at **≤ 17.2 ms**, and the chord's spread (≤ 2 ms, ≈ 1 ms by design) is
  below the few milliseconds at which simultaneous notes start to sound strummed.
- L37: even a forearm on the keyboard has every key sounding by **≤ 21.2 ms**, inside 25 ms.
- P keeps the score player's 1 ms tick jitter to under one tick, keeps the liveness check meaningful,
  and keeps "one lap of the loop" a stable thing the code view and the loop ring can show.

### Program design rules (for VS-09, PO-03, PO-04)

1. Rows: one auto-advance `OC` then 5 × `RD` (or 2 × `RH` + `RD`), XOR with the previous rows held in
   registers or low memory; unchanged rows cost one branch.
2. Changed key: `LB` from a 256-byte first-set-bit table indexed by the row's change byte; clear that
   bit; handle the key; loop while the change byte is non-zero **and** the per-pass count is below `K`.
   Unhandled changes stay in the change byte (the previous-row image is updated per key, not per row),
   so the next pass picks them up and nothing is lost.
3. Voices: free list, age queue and key→voice map in the voice table area; steal = head of the age
   queue (the documented order PRG-04 tests); a stolen voice's gate drops and re-rises.
4. Gates: keep a gate image in a register and write it once per pass with `WD` (voice gates are lines
   0–7, the high byte, §5.3) when it changed; rhythm triggers with `WH`.
5. `K` is an `EQU` in `scan.s`, shown in the code view; changing it is a rebuild, not a code change.

### Memory map

The first-set-bit table takes X'1200'–X'12FF'; variables, the attract pattern and the built-in rhythm
tables move to X'1300'–X'1FFF' (ARCHITECTURE §5.5).

## Consequences

- Positive: every NFR-1 case fits with margin; the single-key budget in §6.6 is unchanged; LAT-01's
  4.7 ms tripwire remains valid for one key; pass time is bounded, so score timing and liveness are
  well defined. The arpeggiated smash is also how a polled 1974 program would behave, and the slowed
  detents make it audible (PLAY-7's "chords arpeggiate").
- Negative: the program is a little cleverer than the "obvious" loop the code view was going to show,
  so the code notes (PR-10) need to explain the table lookup and the free list in plain words; two
  more tables in memory; PRG-01 measures four quantities instead of one; QA must edit PRG-01 and add a
  chord variant of LAT-01 (QA-01).
- Neutral: on a Model 74 (Phase 2) the same source and numbers apply, since the 7/16 table is the 74's.

## What would reopen this

PO-13's `cycle-calc` or engine measurement misses L8 or L37 by more than 10% (then try option C's
one-halfword change mask), or a cited 7/16 table (SP-S4A sign-off, document 29-350) moves the mean
instruction time by more than 20%.
