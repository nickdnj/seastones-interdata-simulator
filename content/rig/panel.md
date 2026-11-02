title: Front panel
status: ready
note: Slots: label-panel-inferred. Which engine field each drawn lamp shows (PANEL-1, PR-04). The layout is inferred: the bitsavers search (docs/research/bitsavers-716-report.md) found the 7/16 shipped with a binary or a hex display panel and which one Lagin had is unknown, so this panel is drawn from Interdata documentation, not traced. Brightness is the duty cycle the engine reports (UX 6.3).

| Lamps | Field | Meaning |
|---|---|---|
| Address 0-15 | pc | the address of the instruction now running |
| Data 0-15 | the instruction word at pc | the word the computer is holding |
| Running or waiting | halted, waiting, speed | whether the computer is running or waiting for STEP |
