# Score format `seastones.score/1`

**Version:** 1 · **Date:** 2026-10-31 · **Status:** Draft (RS-03), not reviewed by Nick
**Implements:** PRD RE-5, MACH-8, RE-4, SEA-3; ADR-004; ARCHITECTURE 9.3. **Tests:** SCR-01, SCR-02.
**Code:** `src/toolchain/sxscore/score.py` (parse, emit), `src/toolchain/sxscore/validate.py`
(validator). The compiler to table records is `VS-20`.

## 1. What it is

A small plain-text format for note events and D/A step tables that analysis tools emit, a person
can edit, and the 7/16 program plays (MACH-8). One event per line. A score is "a tape": `sxscore`
compiles it into records the program reads from the score area at X'2000'.

```
score: 1
title: Four step rhythm
status: ready
origin: original
kind: pattern
tick: 10ms
voices: 2
technique: a four-step sequence on two voices

@0     note  v0  A2          # voice 0 plays A2
@0     cv    d8  0x4000      # D/A channel 8 to a raw code
@25    trig  g8              # pulse gate line 8 for one tick
+25    off   v0              # 25 ticks after the previous event
@100   cv    d8  6.40V       # D/A channel 8 to a voltage
@100   ramp  d8  2.00V  steps 20  over 50   # the program writes 20 stepped values
@200   loop  @0              # or: end
```

## 2. Lexical rules

- UTF-8. A leading byte-order mark is ignored. LF, CRLF and CR line endings are all accepted.
- `#` starts a comment when it begins a line or follows a space or tab. A comment runs to the end
  of the line. (So a title cannot contain " #"; write "No. 2" instead.)
- Blank lines are ignored everywhere.
- Words are separated by any run of spaces or tabs; column alignment is free.

## 3. Header

`key: value` lines, before the first event. **`score: 1` must be the first line** that is not blank
or a comment. Unknown keys and repeated keys are errors (they are usually typos).

| Key | Required | Values | Meaning |
|---|---|---|---|
| `score` | yes | `1` | Format version. Any other value is "unknown score version". |
| `title` | yes | text | A short name. Never contains "Seastones" on the floor (RS-16, checked later by CT-13). |
| `status` | yes | `ready`, `draft-hidden` | The content rule (ADR-007). Passages ship `draft-hidden`. |
| `origin` | yes | `original`, `synthetic`, `seastones-derived` | Where the notes came from. `seastones-derived` **is the tag** the release guard looks for (RS-05, GAT-01). |
| `kind` | no (default `pattern`) | `pattern`, `passage`, `test` | `passage` is held to the 2-minute limit. |
| `grounding` | no (default `none`) | `none`, `recordings` | Whether the score claims its notes or timing are grounded in the recordings. |
| `ledger` | when grounded | `H-NNN, H-NNN` | Ledger ids (RE-4). Each must exist in `research/ledger/`. |
| `tick` | yes | `1ms`, `10ms` | The PIC tick the program steps by. All times are in ticks. |
| `voices` | yes | 1 to 8 | Voices the score reserves (v0 up); the rest stay with the keyboard. |
| `technique` | no | text | For original patterns: the technique used (SEA-4 technique note). |
| `note` | no | text | Anything else a reader should know. |

## 4. Events

Each event line is a time, an event word and its arguments.

**Time.** `@T` is absolute, `+T` is relative to the previous event (the first `+T` is relative to
0). T is a whole number of ticks. Several events may share a time; they play in file order.

| Event | Form | Meaning |
|---|---|---|
| `note` | `note vN PITCH` | Voice N plays PITCH. PITCH is a name (`C3`, `F#4`, `Bb2`, octaves -1 to 9) or a note number (`n60`). Numbers use MIDI numbering, C4 = 60; the program's pitch table turns them into D/A codes, so the D/A model stays in force (ADR-004). The table's own range is checked by the compiler. |
| `off` | `off vN` | Voice N releases. |
| `cv` | `cv dN VALUE` | D/A channel N (0 to 15) to VALUE. VALUE is a voltage (`2.50V`) or a raw 16-bit MSB-justified code (`0x4000`). |
| `ramp` | `ramp dN VALUE steps S over T` | From the channel's current value to VALUE in S equal steps across T ticks. The **program** expands it (ADR-004), so the zipper is the computer's. |
| `trig` | `trig gN` | Pulse gate line N (0 to 15) for one tick. |
| `loop` | `loop @T` | Jump back to tick T and play on from there. |
| `end` | `end` | Stop. |

Voltages map to codes as in ARCHITECTURE 6.3: `V = code × range / 65536`, default range
0 to +10.24 V, so the largest voltage is just below 10.24 V. The word-size truncation (default 12
bits) happens in the D/A device, not in the score.

## 5. Validation rules

`python -m toolchain.sxscore.validate [--ledger DIR] [--range-v 10.24] FILE...` (with `src/` on
`PYTHONPATH`). Every message has the form `file:line: what is wrong and what to write instead`.
Exit 0 when every file is valid, 1 otherwise.

| # | Rule | Error class (SCR-02) |
|---|---|---|
| V1 | First line is `score: 1` | unknown version |
| V2 | Required headers present; no unknown or repeated headers; header values from the lists above | header |
| V3 | `tick` is `1ms` or `10ms` | bad tick |
| V4 | `voices` is 1 to 8; every `vN` is below `voices` | voice out of range |
| V5 | Times never go backwards; no gap between two events over 65,535 ticks (one record's delta field) | non-monotonic time |
| V6 | D/A channel and gate line 0 to 15; voltage 0 up to just below the range; code 0x0000 to 0xFFFF; note number 0 to 127 | value out of range |
| V7 | `ramp`: 1 to 4,096 steps; at least one tick per step; at most 65,535 ticks; finishes no later than `end` or `loop` | ramp |
| V8 | The last event is `end` or `loop`; nothing follows it; a loop target is earlier than the loop | structure |
| V9 | A `kind: passage` lasts at most 2 minutes (SEA-1) | duration |
| V10 | The table fits the 24 KB (24,576-byte) score area: 6 bytes per record, one record per event and two per ramp (an upper bound; `VS-20` must stay within it) | table too large |
| V11 | `grounding: recordings` or `origin: seastones-derived` requires a `ledger:` line (RE-4), whatever the status | grounding without ledger |
| V12 | Every ledger id looks like `H-NNN` and exists in the ledger folder (the nearest `research/ledger/` above the score, or `--ledger`) | ledger |
| V13 | `origin: seastones-derived` requires `status: draft-hidden`; it cannot also say `grounding: none` | derived and ready (SEA-3) |
| V14 | `origin: synthetic` cannot claim `grounding: recordings` | contradiction |

## 6. Rights rules that sit outside the validator

- A `seastones-derived` score is a transcription of Lagin's composition (LEGAL-REVIEW 1.1). It lives
  in the private folder (`$SEASTONES_NOTEBOOK_DIR` or beside it), never under `content/`, `src/`,
  `deploy/` or in an image. `scripts/derived_guard.py` (RS-05) fails the build if one is found
  there; the full release gate (`CT-05`, G1) absorbs it.
- `research/scores/` in this repo holds **original and synthetic scores only**.
- Floor scores under `content/` carry `origin: original`, a `technique:` note and a recorded
  not-close result (PRG-14, RS-15, RS-16).

## 7. Canonical form

`emit` writes: headers in the order of section 3 (defaults written out), a blank line, then one
event per line with absolute times and single spaces, no comments, voltages as written, codes as
`0x` plus four upper-case hex digits, pitches as sharp names. Emitting, parsing and emitting again
gives identical text (SCR-01).

## 8. Changes to this format

The version is in the first line. A change that an old reader would misread bumps it to `score: 2`.
Adding an optional header with a default does not.
