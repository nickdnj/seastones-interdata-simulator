# ADR-003: Device contract — keys X'20', D/A X'21', gates X'22'

**Status:** Proposed · **Date:** 2026-10-31 · **Changes PRD:** MACH-2 (adds the gate latch)
· **Amended:** 2026-10-31, gate-latch bit numbering

## Context

SIMH has no synth I/O. MACH-2 asks for a key-matrix input port and a 16-channel D/A at documented
addresses, reached with standard Interdata I/O instructions and labelled as our choice. P2-2 asks
that the contract be implementable in hardware on a Model 74. PLAY-4 wants 8 voices (Should). The
only evidence is Lagin's statement that 16 D/A channels controlled all of the E-mu's functions. The
word size, channel map and gate scheme are unknown.

## Decision

Full spec in ARCHITECTURE §5. Summary:

- **KEYS X'20':** 8×8 matrix; OC selects the row (`0x40` auto-advance); RD returns a row byte, RH two
  rows; no interrupts; MIDI and touch are separate bitmaps ORed; the device records what the program
  actually read (`keys_seen`).
- **DAC X'21':** OC selects channel 0–15 (`0x40` auto-increment); WH writes a **16-bit unsigned,
  MSB-justified** code; the converter keeps the top *N* bits (`dac.word_bits`, default 12); range
  default 0 to +10.24 V (12-bit LSB = 2.5 mV = 3 cents at 1 V/oct). Both are hypotheses for RE-7.
- **GATE X'22':** a 16-bit digital latch, one bit per gate line. **Bit numbering is Interdata's,
  as for KEYS: bit 0 is the most significant bit.** Gate line *i* is mask `0x8000 >> i`. `WH` writes
  all 16 lines; `WD` writes lines 0–7 from its byte (byte mask `0x80 >> i`, the high byte of the
  latch) and leaves lines 8–15 alone, matching the DAC, where `WD` also lands in the high byte. So
  the eight voice gates (lines 0–7, ARCHITECTURE §5.4) are one `WD`. (Amended 2026-10-31: ARCHITECTURE §5.3 was silent; the
  engine lane built it this way in `src/engine/devices/id_seastones.c`, and this confirms it.)
- Polled I/O only. X'20'–X'22' are free in `id16`'s default configuration (PAS ends at X'1F').
- Channel map is data (`content/rig/channel-map.md`). Default: 8 voices' pitch on D/A 0–7, gates on
  the latch, modulation and score lanes on D/A 8–15. An **all-D/A 4-voice map** (gates from D/A
  channels through a 2.5 V threshold) ships as an alternative so the evidence-aligned hypothesis can be
  heard.

## Consequences

- Positive: a real board can implement it (parallel input with row drive, 16-channel D/A with channel
  select, 16-bit latch); word-size changes need no code (MACH-3); a confirmed map is a data edit.
- Negative: the gate latch is an invention beyond the "16 D/A channels" story, and must be labelled
  as one; two maps to keep working.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **3 devices incl. gate latch** | 8 voices + modulation | an extra invented device |
| D/A-only (gates from D/A) | closest to Lagin's description | 16 channels cap at ~4 voices with modulation; fails PLAY-4 Should |
| Reuse display device X'01' | zero C | stopgap only (PRD MACH-2) |

## Risk note

If the people who built the original later describe a different interface, programs written against this contract still
run, because the map is data. A different *protocol* (for example a multiplexed single-channel
converter) would mean a new device file and a program change. The protocol is kept minimal to make
that change small.
