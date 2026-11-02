# ADR-004: Toolchain — our own assembler and a plain-text score format

**Status:** Proposed · **Date:** 2026-10-31

## Context

MACH-4 requires our program in Interdata assembly, assembled reproducibly by one command into a
byte-identical image. MACH-6 requires a check that fails on instructions outside the portable
subset. CODE-1/2 need a real listing with named blocks. RE-5/MACH-8 need a score format that analysis
tools emit, people edit and the 7/16 program consumes. The surviving Interdata assembler exists only
as a paper-tape image run under BOSS.

## Decision

- **`sxasm`** (Python, in `src/toolchain/sxasm/`): Interdata CAL syntax; mnemonics taken from SIMH's
  `id16_sys.c` table (a test parses it); `*@block <slug>` comment markers for CODE-2 (valid CAL
  comments); `--subset` enforcement; `TABLE` directives that generate the pitch and channel-map tables
  from `content/rig/` data. Deterministic outputs: `rig.img.json`, `rig.lst.json`, `rig.sym`,
  `rig.dep.sim` (oracle deposit script). Every instruction form is tested by round trip through stock
  `id16`'s `ex -m`.
- **`seastones.score/1`**: line-based text (`@t note v0 C3`, `cv d8 2.50V`, `ramp … steps 20 over
  500`, `trig`, `loop`, `end`) with `status:` and `ledger:` headers. `sxscore` compiles it to
  3-halfword records loaded at X'2000' as "a tape". Notes compile to note numbers so the program's
  pitch table and the D/A model stay in force. Ramps are expanded **by the program**, so the stepping
  is the computer's.

## Consequences

- Positive: one command, reproducible; listings and blocks for the code view; subset enforced at
  assembly; scores stay readable and diffable; the same score plays on the floor and in `sx-render`.
- Negative: we maintain an assembler (small: one subset, no macros, no relocation); the period
  assembler's authenticity is given up in the build.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **Own Python assembler** | listings, blocks, subset check, determinism | ours to maintain |
| Interdata assembler under SIMH | period-authentic | BOSS + tapes + expect in the build; object tape needs a loader; no listing JSON or blocks; RIGHTS-6 check before any publication. Kept as a Could provenance check |
| Hand-assembled hex | none | violates MACH-4 |
| Scores as MIDI files | tooling exists | cannot express D/A voltages, ramps-as-steps, gate lines or ledger refs; binary, not human-editable |

## Risk note

An assembler bug would put the wrong word in memory with the listing claiming otherwise, which would
be a CODE-1 honesty failure. The `ex -m` round trip on every word of the shipped image is a release
gate for exactly this reason.
