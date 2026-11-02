# ADR-005: Audio engine — C DSP in the engine, frame-accurate D/A, selectable authenticity

**Status:** Proposed · **Date:** 2026-10-31

> **Amended by ADR-010 (2026-10-31).** The VCO's band-limiting is table-driven minBLEP/minBLAMP,
> not PolyBLEP, which measured −35 dBc at the top key against DSP-08's −60 dBc.

## Context

The synthesizer must sound beautiful (DES-3), be band-limited with zero dropouts (NFR-6), reproduce
D/A steps as steps, with smoothing only by choice (NFR-2), use 1 V/oct pitch from a configurable D/A
model (MACH-3), and pass a safety chain no patch can bypass (AUDIO-2). The PRD asks that jitter and
control-rate/zipper behaviour be deliberate and selectable.

## Decision

- All modules (VCO PolyBLEP, noise, ZDF ladder VCF 2× oversampled with tanh, VCA with 0.5 ms
  declick on its CV, ADSR/AR envelope, LFO, slew, mixer, FDN reverb) are C in `src/engine/dsp/`,
  rendered in the same call as the CPU. The registry is exported as `build/modules.json`.
- **D/A → CV:** truncate to N bits, scale to volts, then pitch `f = f0·2^V`, cutoff 1 V/oct, gate
  threshold 2.5 V. The program's pitch table assumes an ideal 16-bit converter, so word-size changes
  quantise without code changes.
- **Authenticity modes** per patch: `authentic` (default: instantaneous steps at the exact frame; the
  control rate and jitter are the program's own), `analog` (converter output low-pass), `strobed`
  (writes transferred on a D/A update clock), and a **research-only** `jitter`. Never on the floor.
- **Safety chain**, fixed and last: DC block → 25 Hz HPF → soft clip → look-ahead brick-wall limiter
  at `min(staff ceiling, quiet hours, −1 dBFS)` → visitor volume → supervisor mute ramp. The hardware
  gain caps sit after it.

## Consequences

- Positive: sample-accurate, deterministic, testable offline (golden hashes); the zipper heard is the
  program's; one clock for computer and synth; no browser audio policy issues.
- Negative: we write and tune our own DSP (the listening gate is the judge); the 0.5 ms VCA declick
  is a deliberate exception to "no smoothing" and must be stated in the honest labels.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **C DSP in the engine** | determinism, quality, safety placement | ours to build |
| Web Audio native graph | free band-limited oscillators | no gate envelopes; weak filter character; main-thread scheduling jitter; browser output latency |
| AudioWorklet DSP | sample-accurate | ties sound to the renderer (see ADR-002) |
| Faust-generated C | proven DSP primitives | another toolchain to pin; may still be used offline to prototype a filter, emitting C we vendor |

## Risk note

"Beautiful" is subjective and late-binding. Build the default patch and listening rig early (build
step 4). The DSP must also fit the real-time budget at 8 voices with 2× filter oversampling on a
fanless box; S-1/S-8 measure it, and the fallback is 1× oversampling with a gentler resonance curve.
