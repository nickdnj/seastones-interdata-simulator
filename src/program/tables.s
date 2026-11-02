* tables.s: the program's data tables (PO-01, PO-05). The words come from the rig data at
* assembly (sxasm TABLE: src/toolchain/sxasm/tables.py), so a new channel map or converter is
* a data edit and a rebuild, never a code change.
*
*@block the-pitch-table
* One entry per note: the number the program sends the D/A converter to play it. Each step of
* 12 notes is one more volt: an octave up (1 volt per octave).
         ORG   X'1000'
PITCH    TABLE pitch
*
*@block the-channel-map
* Which D/A channel or gate line each voice and each lane uses. Our choice, not Lagin's.
         ORG   X'1100'
MAP      TABLE channel-map
*
*@block the-first-key-table
* For each pattern of eight keys in a row, which one comes first. The loop uses it to take
* changed keys one at a time, and to find the lowest key held down.
         ORG   X'1200'
FIRSTKEY TABLE first-set-bit
*
*@block the-last-key-table
* For each pattern of eight keys in a row, which one comes last (the arpeggio going down).
         ORG   X'1400'
LASTKEY  TABLE last-set-bit
*
* The program starts at START (rig.s).
         END   START
