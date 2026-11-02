# ADR-010: VCO band-limiting — table-driven minBLEP/minBLAMP at the output rate

**Status:** Accepted (architecture owner) · **Date:** 2026-10-31 · **Amends:** ADR-005 (VCO
"PolyBLEP/PolyBLAMP"), ARCHITECTURE §6.2 · **Supersedes:** VS-10's "PolyBLEP saw and pulse" (new
issue VS-30) · **Confirms:** DSP-08's −60 dBc, with its measurement band defined (QA-01)
**Evidence:** `docs/qa/results/overnight-2026-10-31-engine.md`, "VS-10 spec conflict"

## Context

NFR-6 asks for band-limited oscillators with no audible aliasing on the default patch and presets up
to the top of the keyboard. QA turned that into DSP-08: every waveform at every key, plus a glissando,
with every non-harmonic line at or below **−60 dBc**. The engine lane measured the ARCHITECTURE 0.1
choice (2-sample PolyBLEP) at 48 kHz, Blackman-Harris FFT, worst non-harmonic line:

| Note | Naive saw | PolyBLEP saw |
|---|---|---|
| C4 (262 Hz) | −39.3 dBc | −47.5 dBc |
| C6 (1047 Hz, top key) | −27.2 dBc | **−35.1 dBc** |
| C7 (2093 Hz) | −21.4 dBc | −30.1 dBc |

PolyBLEP is 25 dB short at the top key and gets worse by ~6 dB per octave. The switch register can
transpose up to +7 semitones, so the real top is G6 (1568 Hz).

Constraints the method must meet:
- **Determinism.** Golden renders are hash-pinned (§14.1) and must be bit-identical on the Mac (arm64)
  and the station (x86-64). The build already sets `-ffp-contract=off -fno-fast-math`. Nothing in the
  render path may depend on `libm` results that differ between platforms.
- **Frame-exact D/A steps** (NFR-2, §6.4): a pitch write changes frequency at an exact frame, with no
  smoothing the patch did not ask for.
- **Real-time budget** on a fanless x86-64 mini-PC (KIOSK-8; an Intel N100/N305-class box is the
  working assumption until SP-BUY), 8 voices, 128-frame periods, alongside a 2× oversampled ladder VCF
  and the reverb.
- **Pulse-width modulation and linear FM** (`pw`, `fm` inputs, §6.2).

**The authenticity angle.** The E-mu modular is analog. Its VCOs produce continuous-time waveforms;
harmonics above hearing are simply inaudible and never fold back. Aliasing is therefore an artefact the
1974 rig **did not have**, unlike D/A steps, zipper and loop timing, which it did have and which the
engine reproduces on purpose. Removing aliasing is fidelity, not polish. (A real saw core's finite
reset time and pitch drift are not modelled in v1: the first only removes content above 20 kHz, and the
second would cost determinism; both are candidates for a seeded `analog` character later.)

## Options considered

| Option | Expected aliasing (audible band) | CPU, 8 voices at 48 kHz (estimate) | Determinism | Other | Verdict |
|---|---|---|---|---|---|
| PolyBLEP, 1× (as built) | −35 dBc at the top key (measured) | lowest | fine | — | Fails |
| PolyBLEP, 2× or 4× oversampled + decimator | Unmeasured. 4× moves the fold to 96 kHz, so in-band aliases come from very high harmonics and are probably below −60 dBc, but the decimator's stopband sets the result | ~4–6× the 1× oscillator cost plus a half-band FIR per voice: ~80 MFLOP/s | fine | a linear-phase decimator adds ~0.3 ms; an IIR one adds phase distortion | Rejected: costs the most for an unproven number |
| **minBLEP / minBLAMP, table-driven, 1×** | Designed from a kernel with ≥ 90 dB stopband: in-band aliases are expected near −80 dBc or lower | per-sample work is a phase step and a ring read; per-edge work is 32 multiply-adds. ~15 MFLOP/s at the top key, ~72 MFLOP/s at the CV maximum: **a few percent of one core at worst** | the kernel is a checked-in constant table: no `libm` at run time | minimum phase, so **no added latency**; handles PWM, FM and frame-exact pitch steps naturally because edges are placed by the running phase | **Chosen** |
| Wavetable, band-limited mip-maps (⅓-octave, 2048–4096 points, cubic interpolation) | −70 to −80 dBc with large tables | cheapest per sample (~25 MFLOP/s), but ~0.7 MB of tables and cache traffic | needs tables generated without platform `libm` (checked in or own sine) | PWM needs two offset saws; a D/A pitch step across a band edge switches harmonic content abruptly, a timbre step the analog VCO does not have; crossfades add state | Runner-up |
| BLIT / additive | very clean | additive: hundreds of partials per voice at low notes | fine | BLIT integrators drift and need DC care | Rejected |

## Decision

**Table-driven minimum-phase band-limited step (minBLEP) for saw and pulse, minimum-phase band-limited
ramp (minBLAMP) for triangle, and a deterministic polynomial sine, all at the 48 kHz output rate, with
no oversampling.**

### Specification (for VS-30, then PM-01)

**Kernel generation** (offline, `tools/dsp/gen-minblep.py`, numpy, run by hand; its output is the
source of truth):
1. Windowed sinc at an oversampling factor of **64**, **32 zero-crossing spans** at the output rate
   (so the kernel spans 32 output samples), cutoff **0.875 × Nyquist (21.0 kHz at 48 kHz)**, 4-term
   Blackman-Harris window (sidelobes about −92 dB).
2. Minimum phase by the real-cepstrum method (FFT size ≥ 16,384 at the oversampled rate).
3. Integrate and normalise so the step ends at exactly 1.0: that is the minBLEP. Subtract the unit
   step to get the **residual** table. Integrate the minBLEP once more (minus the unit ramp) for the
   **minBLAMP residual**.
4. Store each as `float[32 + 1][64 + 1]` (sample × phase, with guard entries) in a generated
   `src/engine/dsp/minblep_tables.c` with a header line naming the generator, its parameters and the
   SHA-256 of the numbers. About 8.5 KB per table.
5. CI regenerates the table and requires byte equality with the committed file, so the table cannot
   drift silently. Re-generation is a deliberate golden-render re-bless.

**Oscillator core** (`src/engine/dsp/vco.c`):
- Phase is a **double** in [0, 1); the increment is `f / fs`, recomputed only when the pitch, `tune`,
  `fine` or `fm` input changes (pitch changes arrive as D/A steps at exact frames). FM is applied per
  sample when the `fm` input is connected.
- `f = f0 × 2^V` uses **our own `sx_exp2`** (range reduction plus a fixed minimax polynomial, at least
  0.01-cent accuracy over the CV range), never `exp2f`/`powf`, so pitch is bit-identical on both
  platforms. The sine output uses our own polynomial sine (at least −100 dB THD against a true sine).
- Each discontinuity is placed at its sub-sample position `t = overshoot / increment` from the running
  phase: saw at the wrap (step −1, scaled to output amplitude), pulse at the wrap and at the width
  crossing (two steps per period, width read per sample and clamped to [0.02, 0.98]), triangle at the
  two slope corners (BLAMP scaled by the slope change × increment).
- The residual is added into a per-voice **32-sample ring** with linear interpolation between adjacent
  phase columns; overlapping edges simply add. Each output sample = naive waveform + ring value, and the
  ring cell is then cleared.
- Fundamental clamped to **≤ 20 kHz**. Unconnected outputs are not computed.
- No allocation, no locks, no branches on uninitialised data: RT-lint applies.

**Cost check (estimate).** Per voice, per sample: a shared phase step plus a naive value and one ring
read and clear per connected output (≈ 22 flops with all four outputs). Per edge: 32 × (2 multiplies +
1 add) ≈ 100 flops; saw, pulse and triangle together have 5 edges per period. Worst realistic case, 8
voices with all four outputs connected at G6 (1.6 k periods/s): 8.4 + 6.4 ≈ **15 MFLOP/s**. At a 16 kHz
fundamental (CV at its maximum) it is ≈ 72 MFLOP/s. A single N100-class core sustains a few GFLOP/s
even in scalar code, so the VCO stays at a few percent of one core in the worst case and well under 1%
in normal play. VS-30 records the measured
cost per period on the Mac; S-8b/S-1b re-measure on the box with the full patch.

**What the oscillator does not promise.** Aliasing created *after* the oscillator by audio-rate FM,
hard waveshaping or the filter's saturation is not the VCO's; DSP-08 tests oscillators with `fm`
unconnected, and the VCF already runs 2× oversampled for its own nonlinearity.

### The test that proves −60 dBc (DSP-08 as specified here; QA-01 edits TEST-PLAN to match)

- **Signals:** sine, triangle, saw, pulse at widths 0.5 and 0.1. Every key from key 0 to key 36 at the
  default patch's tuning, **plus keys 37 to 48** (one octave above the top key, covering the +7
  semitone transpose with margin). Frequencies come from the 12-bit D/A codes of the program's pitch
  table, so they never land on FFT bin centres by construction.
- **Render:** `sx-render` or the DSP unit harness at 48 kHz, oscillator into the `out` module with
  the safety chain bypassed in the test profile; discard 0.1 s; analyse 65,536 samples (1.37 s).
- **Analysis:** 4-term Blackman-Harris window; magnitude spectrum in dB relative to the fundamental's
  peak (dBc). Mask ±8 bins around DC and around every harmonic `k × f0` below 24 kHz. The test value is
  the **highest remaining bin between 20 Hz and 20 kHz**. Aliases between 20 and 24 kHz are inaudible
  and lie in the kernel's transition band, so they are reported but do not count.
- **Pass:** every case **≤ −60 dBc**. Design margin is ~20 dB, so a result above −70 dBc is reported as a
  warning, which catches a degraded table before it fails.
- **Glissando:** an exponential sweep from key 0 to key 48 over 4 s, driven by 1-cent D/A steps (the
  program's ramp, authentic mode). STFT with 4,096-point Blackman-Harris frames, hop 1,024; mask
  harmonics of the known instantaneous `f0` widened by the sweep's spread within one frame; every frame's
  residual ≤ −60 dBc.
- **Self-check of the test:** the same analysis must report the PolyBLEP saw at C6 between −33 and
  −37 dBc (reproducing the lane's measurement) and a naive saw at C6 above −30 dBc, so the metric is
  known to see aliasing.
- **Determinism:** the 37 saw renders are hashed; the hashes are identical on Mac arm64 and Linux
  x86-64 (golden-render rule, PO-10).

### Fallback

If any case misses −60 dBc: kernel length 64 and 128 phases (cost about 2×, still small). If that
misses, the wavetable runner-up. Do not relax the threshold without Nick: the −60 dBc figure is a proxy
for "no audible aliasing", and QA-STRATEGY 16 item 7 asked for it to be confirmed, which this ADR does.

## Consequences

- Positive: meets the requirement by design rather than by tuning; no extra latency; no oversampling
  cost; PWM, FM and frame-exact D/A steps work without special cases; bit-reproducible across platforms;
  the honest label can say plainly that the VCO is band-limited because the analog original never
  aliased.
- Negative: a generator script and a 17 KB constant table to maintain; slightly more code than
  PolyBLEP; minimum phase gives the edges slightly asymmetric ringing (inaudible above 20 kHz, and not
  the analog VCO's exact edge shape either).
- Build order: VS-10 is rescoped (VCO by VS-30); VS-11 and VS-12 wait on VS-30, as they waited on
  VS-10. About 2 extra points on the vertical-slice path.
