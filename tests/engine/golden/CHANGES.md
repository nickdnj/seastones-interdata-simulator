# Golden render changes

Every change to a pinned hash in this directory gets a line here: date, files, reason, and who
re-blessed (DEV-PLAN 7.2). Re-bless commands are in the test that owns each file.

| Date | File | Reason | By |
|---|---|---|---|
| 2026-11-01 | `vco-saw-37.sha256` | first bless: VS-30 VCO (ADR-010 kernel tables) | engine lane, overnight |
| 2026-11-01 | `render-mono-phrase.json` | first bless: VS-12 render of the mono program v0 (ADR-009 scan), VS-10 voice, VS-11 safety chain | engine lane, overnight |
| 2026-11-02 | `render-mono-phrase.json` -> `render-poly-phrase.json` | the program is polyphonic (PO-03: four voices on the all-D/A map) and the engine renders through the patch graph (PM-05, built-in four-voice patch); same script. The graph was first checked equal, sample for sample, to the VS-10 voice it replaces (`tests/engine/test_graph.c`) | engine lane, overnight round 3 |
| 2026-11-02 | `render-poly-phrase.json` | the scan loop sends a key pass's gates and goes straight round (routines commit): the program's writes move by a few instructions | engine lane, overnight round 3 |
| 2026-11-02 | `preset-*.json` (10) | first bless: the presets (PM-16) and the routines' presets, each rendered from its key script in tests/engine/scripts/presets/ through the program, the patch graph and the safety chain | engine lane, overnight round 3 |
| 2026-10-31 | golden renders | VS-21: the score player joins the program (score.s; START and SILENCE gain a few instructions), so the program's writes move by microseconds | make bless |
