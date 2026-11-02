* scan.s: the main loop (ADR-009 scan design; PO-03, PO-13). Part of rig.s.
*
K        EQU   3                        at most this many key changes in one pass
*
*@block read-the-keys
* Ask the keyboard for row 0, then read five rows in a row: the keyboard steps to the next
* row by itself after each read. Five rows of eight cover all 37 keys.
LOOP     OC    R10,FROMROW0             start at row 0
         RD    R10,ROWS                 keys 0-7
         RD    R10,ROWS+1               keys 8-15
         RD    R10,ROWS+2               keys 16-23
         RD    R10,ROWS+3               keys 24-31
         RD    R10,ROWS+4               keys 32-36
*
*@block what-changed
* Compare the rows just read with the keys the program already knows are down, two rows at a
* time. Almost always nothing has changed, and then this costs three quick checks. The
* first pair that differs is where the next block starts looking.
         LHI   R1,0                     R1: the first row that may have changed
         LH    R2,ROWS                  rows 0 and 1 now
         XH    R2,HELD                  any difference from what we know?
         BNZ   CHANGED
         LIS   R1,2
         LH    R2,ROWS+2                rows 2 and 3
         XH    R2,HELD+2
         BNZ   CHANGED
         LIS   R1,4
         LH    R2,ROWS+4                row 4
         XH    R2,HELD+4
         BZ    IDLE                     nothing changed
*
*@block one-key-at-a-time
* Something changed. In each changed row, the first-key table names one changed key at a
* time; the program notes it, clears it from the changes, and gives it a voice or lets its
* voice go. It handles at most K keys in one pass. Any others are still different next time
* round, so none is ever lost, and no single pass can take long.
CHANGED  LIS   R9,K                     R9: changes still allowed this pass
         LH    R13,ONPRESS              R13: what this routine does with a key going down
         LH    R14,ONLETGO              R14: and with a key coming up
ROWNEXT  LB    R2,ROWS(R1)              R2: the row now (R1: which row, 0-4)
         LB    R3,HELD(R1)              R3: the row as the program knows it
         XHR   R2,R3                    R2: the keys in this row that changed
         BZ    ROWDONE                  none: next row
KEYNEXT  LB    R4,FIRSTKEY(R2)          R4: position of the first changed key
         LB    R5,BITMASK(R4)           R5: that key's bit in the row
         XHR   R3,R5                    the program now knows this key's new state
         XHR   R2,R5                    and it is no longer a change
         LB    R6,ROWKEY(R1)
         AHR   R4,R6                    R4: the key number, the row's first key + position
         NHR   R5,R3                    is the key down now?
         BZ    KEYUP
         BALR  R15,R13                  a key went down
KEYDONE  SIS   R9,1                     one fewer change allowed this pass
         BZ    KLAST                    K handled: play what we know, read again
         LHR   R2,R2                    more changes in this row?
         BNZ   KEYNEXT
         STB   R3,HELD(R1)              the row as the program now knows it
ROWDONE  AIS   R1,1                     next row
         CHI   R1,5
         BL    ROWNEXT                  until all five rows are checked
         B     KEYSEND
KLAST    STB   R3,HELD(R1)
*
*@block keys-sent
* A pass that handled keys sends the gates and goes straight round again: the routine's own
* work waits for the next pass, so no pass grows long.
KEYSEND  CHR   R7,R8                    the same gates as last time?
         BE    LOOP
         WDR   R12,R7                   gates 0-7 to the gate latch
         LHR   R8,R7
         B     LOOP
KEYUP    BALR  R15,R14                  a key came up
         B     KEYDONE
*
*@block read-the-switches
* With no key changing, look at the operator's switches. Only when they change does anything
* happen.
IDLE     LHI   R9,PANEL
         OC    R9,SRSTEP                read the two switch bytes in turn
         RD    R9,SRNOW+1               switches 8-15
         RD    R9,SRNOW                 switches 0-7
         LH    R4,SRNOW
         CH    R4,SRLAST
         BNE   NEWSR
*
*@block write-the-gates
* Gate lines 0-7 change together with one byte write, and only when they changed. (With the
* four-voice map the gates are D/A channels, written as each note starts and stops.)
PASSEND  CHR   R7,R8                    the same gates as last time?
         BE    TICK
         WDR   R12,R7                   gates 0-7 to the gate latch
         LHR   R8,R7                    remember them
*
*@block go-round-again
* In the play routine that is the whole loop. The other routines also have work to do each
* time round, by the clock.
TICK     LH    R6,ONTICK
         BR    R6
*
*@block switch-register
* The switches changed. Switches 4-7 transpose the keyboard: 0-7 up, 8-15 down 8 to down 1.
* Switches 8-11 pick the routine and 12-15 its variant. A new routine starts from silence.
NEWSR    STH   R4,SRLAST
         LHR   R5,R4
         SRLS  R5,8                     switches 0-7
         NHI   R5,X'0F'                 switches 4-7
         CHI   R5,8
         BL    NSUP
         SHI   R5,16                    8-15 mean down 8 to down 1
NSUP     STH   R5,TRANSP
         AH    R5,BASENOTE
         AHR   R5,R5
         STH   R5,NOTEOFF               (base note + transposition) x 2
         LHR   R5,R4
         NHI   R5,X'0F'
         STH   R5,VARIANT               switches 12-15
         LHR   R5,R4
         SRLS  R5,4
         NHI   R5,X'0F'                 switches 8-11
         CHI   R5,NROUTINE
         BL    NSOK
         LHI   R5,0                     no such routine: play
NSOK     LHR   R6,R4
         SRLS  R6,12                    switches 0-3: play, score, or both
         CHI   R6,3
         BL    NSMODE
         LHI   R6,0                     no such mode: play
NSMODE   CH    R6,SMODE
         BNE   NSNEW
         CH    R5,ROUTINE
         BE    NSSAME
NSNEW    STH   R5,ROUTINE
         STH   R6,SMODE
         LHI   R6,0
         STH   R6,SGEN                  the tape starts again from its beginning
         BAL   R15,SILENCE              a different routine or mode: from silence
NSSAME   BAL   R15,ROUTINIT             its settings, from the variant
         B     LOOP
