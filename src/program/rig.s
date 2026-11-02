* rig.s: The 1974 Seastones Rig, the program the emulated 7/16 runs (PO-03, PO-04, PO-13).
*
* Over and over, for ever: read the keyboard, notice which keys changed, give each new key a
* voice of its own, and send that voice its note and its gate. When every voice is busy, a new
* key takes the voice that has been playing longest. Nothing else in the exhibit can make a
* sound: every note comes from this loop.
*
* Switches 0-3 pick play (0), the score (1: the tape loaded at X'2000' plays by itself) or both
* (2: the tape keeps its voices and the keyboard has the rest); score.s. The operator's switches
* pick a routine (switches 8-11) and its variant (12-15):
*   0 play     every key gets a voice (the default)
*   1 rhythm   hold a key: the computer plays a sixteen-step pattern from it
*   2 steps    play as usual while the computer steps the filter and the tuning, slowly
*   3 arpeggio hold a chord: the computer plays its notes one at a time
* Switches 4-7 transpose the keyboard (signed semitones).
*
* Polled input and output only, no interrupts, so the same program can run on a real Model 74
* (MACH-6). The loop handles at most K key changes each time round (scan.s, ADR-009). Which
* D/A channel or gate line each voice uses is data, not code: the channel-map table is built
* from the rig data at assembly (TABLE channel-map). The three synth devices are our design,
* not Lagin's (ARCHITECTURE 5, ADR-003). Assembled by sxasm with rig.s, scan.s, voices.s,
* routines.s and tables.s, in that order.
*
KEYS     EQU   X'20'                    the keyboard: eight rows of eight keys
DAC      EQU   X'21'                    the D/A converter: 16 output channels
GATE     EQU   X'22'                    the gate latch: 16 on/off lines
PANEL    EQU   X'01'                    the front panel: its switches
PIC      EQU   X'6C'                    the interval clock
PICCOUNT EQU   4000                     the clock counts down from this, once a millisecond
NROUTINE EQU   4                        routines 0-3
*
* The channel map's fields (the table is at MAP, tables.s; sxasm tables.py has the layout).
NVOICES  EQU   MAP                      how many voices
GMODE    EQU   MAP+2                    0: gates on the gate latch, 1: gates on D/A channels
PCH      EQU   MAP+4                    per voice: its pitch channel (D/A command byte)
GCH      EQU   MAP+20                   per voice: its gate (latch mask or D/A command byte)
GATEHI   EQU   MAP+36                   the D/A code for a gate that is on
LANES    EQU   MAP+38                   the eight lanes' D/A command bytes
GINV     EQU   MAP+54                   per voice: its latch bit inverted, to clear it
CUTCH    EQU   LANES                    lane: filter cutoff
DETCH    EQU   LANES+10                 lane: detune
*
         ORG   X'0080'
*@block start-up
* Remember the devices' numbers, start the interval clock, silence every gate and make every
* voice free.
START    LHI   R10,KEYS                 R10: the keyboard
         LHI   R11,DAC                  R11: the D/A converter
         LHI   R12,GATE                 R12: the gate latch
         LHI   R6,PIC                   the interval clock
         LHI   R4,X'8000'+PICCOUNT      count milliseconds, from PICCOUNT down to 1
         WHR   R6,R4
         OC    R6,PICGO                 start it
         LHI   R4,PICCOUNT
         STH   R4,MSLAST
         LHI   R4,0
         STH   R4,ROUTINE               play
         STH   R4,SMODE                 the keyboard alone: no score
         STH   R4,SGEN                  no tape seen yet
         STH   R4,VARIANT
         STH   R4,SRLAST
         STH   R4,TRANSP
         STH   R4,NOW
         LH    R4,BASENOTE
         AHR   R4,R4
         STH   R4,NOTEOFF               (base note + transposition) x 2: no transposition yet
         LH    R4,NVOICES
         AHR   R4,R4
         STH   R4,NV2                   voices x 2: voices are counted in twos (halfwords)
         BAL   R15,SILENCE
         BAL   R15,ROUTINIT
         B     LOOP
*
*@block silence
* Every gate off, every lane to 0 V, every voice free, and no key known to be down, so a key
* still held is played again as a new key. Used at start-up and when the switches pick a
* different routine.
SILENCE  LHI   R4,0
         WHR   R12,R4                   every gate-latch line off
         LHR   R7,R4                    R7: gate lines 0-7 wanted
         LHR   R8,R4                    R8: gate lines 0-7 last sent
         STH   R4,HELD
         STH   R4,HELD+2
         STH   R4,HELD+4
         STH   R4,ROWS+4                the unused sixth row byte stays 0
         LHI   R5,16                    the eight lanes, last first
SILLANE  SIS   R5,2
         BM    SILVOX
         LH    R6,LANES(R5)
         OCR   R11,R6
         WHR   R11,R4                   0 V
         B     SILLANE
SILVOX   LH    R5,NV2                  R5: a voice (x 2), counting down
SILV     SIS   R5,2
         BM    SILKEYS
         BAL   R14,GATEOFF              its gate off
         LHI   R6,X'FF'
         STB   R6,VKEY(R5)              it holds no key
         LHI   R6,0
         STB   R6,VON(R5)               it is playing nothing
         B     SILV
SILKEYS  CHR   R7,R8                    the latch's gates, if they changed
         BE    SILMAP
         WDR   R12,R7
         LHR   R8,R7
* The key map needs no clearing: a key coming up checks that its voice still plays it, and
* every voice now plays nothing.
SILMAP   LHI   R4,X'FF'
         STB   R4,AHEAD                 the age ring is empty
         LHI   R4,0
         STB   R4,FHEAD
         STH   R4,TRIGS                 no score trigger is up
         BAL   R14,SPLIT                which voices the keyboard has (the rest are the score's)
         LH    R5,KVFIRST               the keyboard's voices wait in the free queue, in order
         LHI   R6,0
SILFREE  CH    R5,NV2
         BNL   SILFDONE
         STB   R5,FREEQ(R6)
         AIS   R5,2
         AIS   R6,1
         B     SILFREE
SILFDONE STH   R6,FCOUNT                every keyboard voice is free
         BR    R15
*
*@block constants
* Small values the loop reads.
PICGO    DC    X'E000'                  clock command X'E0': start, no interrupts
SRSTEP   DC    X'4000'                  panel command X'40': read both switch bytes in turn
FROMROW0 DC    X'4000'                  keyboard command X'40': row 0, step after each read
BASENOTE DC    48                       the lowest key plays note 48 (C3); data (VS-29)
ZERO     DC    0                        nothing: a gate that is off
BITMASK  DC    X'8040',X'2010',X'0804',X'0201'  each key's bit in a row, first key first
ROWKEY   DC    X'0008',X'1018',X'2000'  each row's first key number
MASKGE   DC    X'FF7F',X'3F1F',X'0F07',X'0301'  a row's keys from place n on
MASKLE   DC    X'80C0',X'E0F0',X'F8FC',X'FEFF'  a row's keys up to place n
*