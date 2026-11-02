title: Channel map
status: ready
note: Slots: label-channel-map, label-gate-latch. The floor's map, all-da-4 (DEV-PLAN D-PLAN-2, adopted; src/program/rig/channel-map.md is the copy the program is assembled with): four voices, their pitches on D/A 0-3 and their gates on D/A 4-7, eight lanes on D/A 8-15. The patch wall's rail shows these names. Ours, not Lagin's (PATCH-7, RETRO-1). A change to which line does what needs the image rebuilt; a change to a name here is words only. The Line column is the jack id; Name is the jack's label on the rail.

| Line | Name | Use |
|---|---|---|
| dac.0 | Pitch 1 | voice 1 pitch, 1 V per octave |
| dac.1 | Pitch 2 | voice 2 pitch |
| dac.2 | Pitch 3 | voice 3 pitch |
| dac.3 | Pitch 4 | voice 4 pitch |
| dac.4 | Gate 1 | voice 1 gate, on above 2.5 V |
| dac.5 | Gate 2 | voice 2 gate |
| dac.6 | Gate 3 | voice 3 gate |
| dac.7 | Gate 4 | voice 4 gate |
| dac.8 | Cutoff | lane: filter cutoff |
| dac.9 | Resonance | lane: filter resonance |
| dac.10 | Rate | lane: modulation rate |
| dac.11 | Depth | lane: modulation depth |
| dac.12 | Width | lane: pulse width |
| dac.13 | Detune | lane: detune |
| dac.14 | Level | lane: level |
| dac.15 | Spare | lane: spare |
