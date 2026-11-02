title: Channel map, eight voices
status: ready
note: The ADR-003 eight-voice map, latch-8 (src/program/rig/channel-map-8.md; built and tested so it can be promoted, PO-04, PO-06): pitches on D/A 0-7, gates on gate-latch lines 0-7, lanes on D/A 8-15. The patch wall's rail shows these names when this map is loaded. Ours, not Lagin's (PATCH-7).

| Line | Name | Use |
|---|---|---|
| dac.0 | Pitch 1 | voice 1 pitch, 1 V per octave |
| dac.1 | Pitch 2 | voice 2 pitch |
| dac.2 | Pitch 3 | voice 3 pitch |
| dac.3 | Pitch 4 | voice 4 pitch |
| dac.4 | Pitch 5 | voice 5 pitch |
| dac.5 | Pitch 6 | voice 6 pitch |
| dac.6 | Pitch 7 | voice 7 pitch |
| dac.7 | Pitch 8 | voice 8 pitch |
| dac.8 | Cutoff | lane: filter cutoff |
| dac.9 | Resonance | lane: filter resonance |
| dac.10 | Rate | lane: modulation rate |
| dac.11 | Depth | lane: modulation depth |
| dac.12 | Width | lane: pulse width |
| dac.13 | Detune | lane: detune |
| dac.14 | Level | lane: level |
| dac.15 | Spare | lane: spare |
| gate.0 | Gate 1 | voice 1 gate, gate latch line 0 |
| gate.1 | Gate 2 | voice 2 gate |
| gate.2 | Gate 3 | voice 3 gate |
| gate.3 | Gate 4 | voice 4 gate |
| gate.4 | Gate 5 | voice 5 gate |
| gate.5 | Gate 6 | voice 6 gate |
| gate.6 | Gate 7 | voice 7 gate |
| gate.7 | Gate 8 | voice 8 gate |
