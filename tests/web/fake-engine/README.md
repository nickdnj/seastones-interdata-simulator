# The fake engine (VS-28)

A deterministic stand-in for `rigd` that speaks protocol v1, so the page can be developed and
tested without the engine, audio or MIDI. A supported artefact, not a throwaway (QA request 5).
It makes no sound.

| File | What |
|---|---|
| `schema/protocol-v1.json` | The protocol v1 message schemas. **Proposed**: `src/rigd/schema/` does not exist yet (VS-14). Move this file there when rigd lands and point `schema.mjs` at it, so one file validates both. Fields marked "extension" are additions to ARCHITECTURE 4.4 and 4.6 the page needs. |
| `schema.mjs` | A small validator for that schema (no dependency). |
| `cpu.mjs` | A tiny interpreter that runs the real program image (`build/program/rig.img.json`) with the real KEYS, DAC and GATE semantics. `tests/web/test_fake_cpu_conformance.py` checks it against the real CPU (`build/engine/sx-cpu`) instruction by instruction. An opcode it does not know stops it with `program_stalled`. |
| `engine.mjs` | `FakeEngine`: the server, the machine model (speed detents, lamp duty cycles, `pc_hist`, `scan_hz`, patch reachability, held-key rule, HOME) and the control API the tests use. |
| `ws.mjs` | A minimal WebSocket server (RFC 6455 text frames). |
| `cli.mjs` | Run it on its own: `node tests/web/fake-engine/cli.mjs --port 7690`. |
| `cpu-trace.mjs` | Prints the interpreter's state per instruction, for the conformance test. |
| `engine.test.mjs` | Its own tests: byte-identical scripted runs, schema validity, PLAY-3 freeze, STEP, held key, patch reachability. |

## Control API (tests)

`freeze(on)` (HALT), `midiKeys(bits)` (the physical keyboard), `override(fields)` and
`play(frames, {loop})` (scripted states), `fault(code)` / `clearFault(code)`, `setHealth({audio_ok,
midi_present})`, `setStages({...})`, `kill()` / `revive()` (rigd dies and restarts), `recorded({dedupe})`
(every client message as received), `advance(ms)` with `clock: "manual"`.

## Staff protocol (KP-07 to KP-09, proposed)

`staff.auth` with the fake's test PIN (`FAKE_STAFF_PIN`, or `SX_FAKE_STAFF_PIN`; never the station's
PIN, which rigd keeps hashed on `/data`), five tries then a 30 s lockout, then the session's
settings and actions. `settings` goes to every connection at connect and on change (idle timeout,
reduced motion, review mode, attract sound); `staff` goes only to the connection concerned.
`staffLog` records what staff did; `staffPin` is the PIN in use. The schema entries are marked
"extension (KP-07 to KP-09, CT-07), PROPOSED"; the host lane's `src/rigd/schema/` decides.

## What is modelled, and what is not

- **Real:** PC, registers, CC, key rows read (`keys_seen`), D/A codes after the 12-bit converter, gate
  latch, which voice holds which note (the mono program's R6 and gate 0), disassembly (from `sx-cpu`).
- **Estimated:** instructions per second at RUN (360,000, the S-4b `ESTIMATE`), the detent ratios
  (UX 6.2 placeholders, `calibrated: false` until PR-03), so `scan_hz` and lateness are estimates.
- **Pictures, not sound:** the scope is a deterministic saw from gate 0 and D/A 0, present only when the
  patch reaches the speaker. The patch graph is a cable list and a reachability check (PM-05 is the real one).
