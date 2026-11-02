map: all-da-4
voices: 4
gates: dac                 # each voice's gate is a D/A channel, on above 2.5 V
pitch: 0 1 2 3             # PITCH 1 to 4
gate: 4 5 6 7              # GATE 1 to 4
gate_high_v: 5.0
cutoff: 8
resonance: 9
rate: 10
depth: 11
width: 12
detune: 13
level: 14
spare: 15

The floor's default channel map (DEV-PLAN D-PLAN-2, adopted: four voices on the all-D/A map).
Sixteen D/A channels carry everything, as Lagin described his rig: four pitches, four gates read
through a 2.5 V threshold, and eight lanes the program uses for tone and movement. The lane names
match the patch panel's D/A rail (UX 5.5). This is our choice, not Lagin's (PATCH-7, ADR-003).

Developer note, not visitor copy. ARCHITECTURE 11.2 puts this file at content/rig/channel-map.md;
it lives in src/program/rig/ until the content lane moves it (one `git mv` and a Makefile path).
sxasm reads it for `TABLE channel-map` (src/toolchain/sxasm/tables.py).
