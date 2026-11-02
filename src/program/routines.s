* routines.s: the routines the switches pick, and the interval clock they keep time by.
* Part of rig.s. Original material, written for this exhibit (SEA-4): in the spirit of a 1974
* computer-controlled synthesizer, not derived from any recording.
*
*@block pick-a-routine
* Set what the loop does with each key and each time round, and the routine's settings from
* the variant switches: bits 12-13 pick a pattern, direction or step size, bits 14-15 a speed.
ROUTINIT LH    R4,ROUTINE
         AHR   R4,R4
         LH    R0,PRESSTAB(R4)
         STH   R0,ONPRESS               what a key going down does
         LH    R0,LETGOTAB(R4)
         STH   R0,ONLETGO               what a key coming up does
         LH    R0,TICKTAB(R4)
         STH   R0,ONTICK                what happens each time round
         LH    R4,SMODE                 with the score: the score's tick, and the keyboard
         BZ    RIPLAY                   plays (mode 2) or not (mode 1)
         LHI   R0,SCORE
         STH   R0,ONTICK
         CHI   R4,2
         BE    RIPLAY
         LHI   R0,IGNORE
         STH   R0,ONPRESS
         STH   R0,ONLETGO
RIPLAY   LH    R4,ROUTINE
         LH    R0,NOW
         STH   R0,NEXTAT                the first step is due at once
         LHI   R0,0
         STH   R0,STEP
         STH   R0,RVOICE
         STH   R0,ARPDIR
         STH   R0,ARPOCT
         STH   R0,DET
         LHI   R0,X'FF'
         STH   R0,LASTK
         LH    R0,CUTLO
         STH   R0,CUT
         LH    R5,VARIANT
         LHR   R6,R5
         NHI   R6,3                     bits 12-13
         STH   R6,ARPMODE
         LHR   R0,R6
         SLLS  R0,5
         STH   R0,PATBASE               32 bytes per pattern
         AHR   R6,R6
         LH    R0,STEPTAB(R6)
         STH   R0,STEPSZ
         STH   R0,CDIR
         STH   R0,DDIR
         LHR   R6,R5
         SRLS  R6,2                     bits 14-15
         AHR   R6,R6
         LH    R0,TEMPOTAB(R6)
         STH   R0,STEPMS
         LH    R0,ARPLENS(R6)
         STH   R0,ARPLEN
         LH    R0,UPDTAB(R6)
         STH   R0,UPDMS
         BR    R15
*
*@block keys-for-the-routines
* In the routines that play by themselves, a key going down or up gives no voice: the
* routine reads the keys held down when it is time for its next note.
IGNORE   BR    R15
*
*@block the-clock
* The interval clock counts down once a millisecond, from 4000 to 1, over and over. The
* loop reads it as it comes round and adds the milliseconds that have passed to NOW. Nothing
* ever waits for the clock.
CLOCK    LHI   R6,PIC
         RHR   R6,R0                    R0: the clock's count now
         LH    R6,MSLAST
         STH   R0,MSLAST
         SHR   R6,R0                    R6: milliseconds since the last look
         BNM   CLKADD
         AHI   R6,PICCOUNT              the count started again in between
CLKADD   AH    R6,NOW
         STH   R6,NOW
         BR    R14
*
*@block step-due
* Is the next step due? R6 comes back negative if not. If the loop fell more than a step
* behind, the timing starts again from now rather than rushing to catch up.
DUE      LH    R6,NOW
         SH    R6,NEXTAT                R6: how late the step is
         BM    DUENOT
         CH    R6,STEPMS
         BL    DUEON
         LH    R0,NOW
         STH   R0,NEXTAT
DUEON    LH    R0,NEXTAT
         AH    R0,STEPMS
         STH   R0,NEXTAT
DUENOT   BR    R14
*
*@block notes-that-are-done
* Each note a routine plays has a time to stop. Any note whose time has come gets its gate
* turned off. A pass that starts a note does not also do this: it waits for the next pass,
* a fraction of a millisecond later, so no pass grows long.
NOTESOFF BAL   R15,DUEOFF
         B     LOOP
DUEOFF   LH    R5,NV2
DONEXT   SIS   R5,2
         BM    DODONE
         LB    R0,VON(R5)
         LHR   R0,R0
         BZ    DONEXT                   not sounding
         LH    R6,NOW
         SH    R6,OFFAT(R5)             now minus its stop time
         BM    DONEXT                   not yet
         LHI   R0,0
         STB   R0,VON(R5)
         BAL   R14,GATEOFF
         B     DONEXT
DODONE   BR    R15
*
*@block play-a-note
* Play note R4 for R3 milliseconds on the next voice in turn. Its gate drops first, so the
* envelope starts again even if the voice was still sounding.
PLAYNOTE LH    R5,RVOICE                R5: the next voice in turn
         LHR   R0,R5
         AIS   R0,2
         CH    R0,NV2
         BL    PNNEXT
         LHI   R0,0
PNNEXT   STH   R0,RVOICE
         BAL   R14,GATECUT
         BAL   R14,SENDNOTE
         BAL   R14,GATEON
         LIS   R0,1
         STB   R0,VON(R5)
         LH    R0,NOW
         AHR   R0,R3
         STH   R0,OFFAT(R5)             when it stops
         BR    R15
*
*@block lowest-key
* R4: the lowest key held down, or X'FF' if none.
LOWEST   LHI   R6,0                     R6: which row
LWNEXT   LB    R4,HELD(R6)
         LHR   R4,R4
         BNZ   LWFOUND
         AIS   R6,1
         CHI   R6,5
         BL    LWNEXT
         LHI   R4,X'FF'
         BR    R14
LWFOUND  LB    R4,FIRSTKEY(R4)
         SLLS  R6,3
         AHR   R4,R6
         BR    R14
*
*@block next-key-up
* R4: the next key held down above key R4 (X'FF' in R4: the lowest), or X'FF' if none.
NEXTUP   CHI   R4,X'FF'
         BNE   NUFROM
         LCS   R4,1                     start below key 0
NUFROM   AIS   R4,1                     the first key that could come next
         CHI   R4,40
         BNL   NUNONE
         LHR   R6,R4
         SRLS  R6,3                     R6: its row
         NHI   R4,7                     R4: its place in the row
         LB    R0,HELD(R6)
         LB    R4,MASKGE(R4)            the row's keys from that place on
         NHR   R4,R0
         BNZ   NUFOUND
NUROW    AIS   R6,1
         CHI   R6,5
         BNL   NUNONE
         LB    R4,HELD(R6)
         LHR   R4,R4
         BZ    NUROW
NUFOUND  LB    R4,FIRSTKEY(R4)
         SLLS  R6,3
         AHR   R4,R6
         BR    R14
NUNONE   LHI   R4,X'FF'
         BR    R14
*
*@block next-key-down
* R4: the next key held down below key R4 (X'FF' in R4: the highest), or X'FF' if none.
NEXTDN   CHI   R4,X'FF'
         BNE   NDFROM
         LHI   R4,40                    start above the last key
NDFROM   SIS   R4,1                     the first key that could come next
         BM    NDNONE
         LHR   R6,R4
         SRLS  R6,3
         NHI   R4,7
         LB    R0,HELD(R6)
         LB    R4,MASKLE(R4)            the row's keys up to that place
         NHR   R4,R0
         BNZ   NDFOUND
NDROW    SIS   R6,1
         BM    NDNONE
         LB    R4,HELD(R6)
         LHR   R4,R4
         BZ    NDROW
NDFOUND  LB    R4,LASTKEY(R4)
         SLLS  R6,3
         AHR   R4,R6
         BR    R14
NDNONE   LHI   R4,X'FF'
         BR    R14
*
*@block computer-rhythm
* Hold a key and the computer plays a pattern from it by itself: sixteen steps, each a note
* above or below the lowest key held, or a rest. Each note goes to the next voice in turn,
* so the notes ring on into each other. Accented steps also open the filter: the cutoff lane
* jumps up for that step and back down on the next, one stepped voltage per step.
RHYTHM   BAL   R14,CLOCK
         BAL   R14,LOWEST               R4: the lowest key held
         CHI   R4,X'FF'
         BNE   RHHELD
         LH    R0,NOW                   nothing held: the next key starts the pattern at once
         STH   R0,NEXTAT
         LHI   R0,0
         STH   R0,STEP
         B     NOTESOFF
RHHELD   BAL   R14,DUE
         LHR   R6,R6
         BM    NOTESOFF                 not time yet: stop any note that is done
         LH    R6,STEP
         LHR   R0,R6
         AIS   R0,1
         NHI   R0,15
         STH   R0,STEP                  the step after this one
         AHR   R6,R6                    two bytes a step
         AH    R6,PATBASE
         LB    R0,PATTERNS(R6)          the step's interval
         CHI   R0,X'80'
         BE    LOOP                     a rest
         BL    RHUP
         SHI   R0,256                   X'81'-X'FF' are below the key
RHUP     AHR   R4,R0
         AH    R4,BASENOTE
         AH    R4,TRANSP                R4: the note
         LB    R3,PATTERNS+1(R6)        R3: its length, and its accent
         OC    R11,CUTCH+1              the cutoff lane
         THI   R3,X'80'
         BZ    RHSOFT
         WH    R11,ACCENTV              an accent: open the filter
         B     RHLEN
RHSOFT   WH    R11,SOFTV
RHLEN    NHI   R3,X'7F'
         SLLS  R3,2                     length in milliseconds
         BAL   R15,PLAYNOTE
         B     LOOP
*
*@block stepped-voltages
* The keys play as usual. Meanwhile the computer moves two lanes, the filter cutoff and the
* detune, one step at a time: up to the top, then back down. Each step adds a fixed number to
* the lane's code. The converter shows a step only as fine as its word size allows, so the
* converter and the step rate together set the zipper you hear.
STEPS    BAL   R14,CLOCK
         LH    R6,NOW
         SH    R6,NEXTAT
         BM    LOOP                     not time yet
         LH    R0,NEXTAT
         AH    R0,UPDMS
         STH   R0,NEXTAT
         LH    R6,CUT
         AH    R6,CDIR                  one step on
         CH    R6,CUTHI
         BNP   STCLO
         LH    R6,CUTHI                 past the top: turn round
         B     STCREV
STCLO    CH    R6,CUTLO
         BNM   STCOUT
         LH    R6,CUTLO                 past the bottom: turn round
STCREV   LH    R0,CDIR
         XHI   R0,X'FFFF'
         AIS   R0,1
         STH   R0,CDIR
STCOUT   STH   R6,CUT
         OC    R11,CUTCH+1
         WHR   R11,R6                   the cutoff lane
         LH    R6,DET
         AH    R6,DDIR
         CH    R6,DETHI
         BNP   STDLO
         LH    R6,DETHI
         B     STDREV
STDLO    LHR   R6,R6
         BNM   STDOUT
         LHI   R6,0
STDREV   LH    R0,DDIR
         XHI   R0,X'FFFF'
         AIS   R0,1
         STH   R0,DDIR
STDOUT   STH   R6,DET
         OC    R11,DETCH+1
         WHR   R11,R6                   the detune lane
         B     LOOP
*
*@block arpeggio
* Hold a chord and the computer plays its notes one at a time, round and round: up, down,
* up and down, or up over two octaves.
ARP      BAL   R14,CLOCK
         BAL   R14,LOWEST
         CHI   R4,X'FF'
         BNE   ARHELD
         LH    R0,NOW                   nothing held: start again at once on the next chord
         STH   R0,NEXTAT
         LHI   R0,X'FF'
         STH   R0,LASTK
         LHI   R0,0
         STH   R0,ARPOCT
         STH   R0,ARPDIR
         B     NOTESOFF
ARHELD   BAL   R14,DUE
         LHR   R6,R6
         BM    NOTESOFF                 not time yet: stop any note that is done
         LH    R0,ARPMODE
         CHI   R0,1
         BE    ARDOWN
         CHI   R0,2
         BE    ARBOUNCE
ARUP     LH    R4,LASTK
         BAL   R14,NEXTUP
         CHI   R4,X'FF'
         BNE   ARPLAY
         LH    R0,ARPMODE
         CHI   R0,3
         BNE   ARUPW
         LH    R0,ARPOCT                two octaves: every other time round, an octave up
         XHI   R0,12
         STH   R0,ARPOCT
ARUPW    LHI   R4,X'FF'
         BAL   R14,NEXTUP               back to the lowest key
         B     ARPLAY
ARDOWN   LH    R4,LASTK
         BAL   R14,NEXTDN
         CHI   R4,X'FF'
         BNE   ARPLAY
         LHI   R4,X'FF'
         BAL   R14,NEXTDN               back to the highest key
         B     ARPLAY
ARBOUNCE LH    R0,ARPDIR
         LHR   R0,R0
         BNZ   ARBDN
         LH    R4,LASTK
         BAL   R14,NEXTUP
         CHI   R4,X'FF'
         BNE   ARPLAY
         LIS   R0,1
         STH   R0,ARPDIR                the top: turn round
         LH    R4,LASTK
         BAL   R14,NEXTDN
         B     ARBCHK
ARBDN    LH    R4,LASTK
         BAL   R14,NEXTDN
         CHI   R4,X'FF'
         BNE   ARPLAY
         LIS   R0,0
         STH   R0,ARPDIR                the bottom: turn round
         LH    R4,LASTK
         BAL   R14,NEXTUP
ARBCHK   CHI   R4,X'FF'
         BNE   ARPLAY
         LHI   R4,X'FF'                 only one key: play it again
         BAL   R14,NEXTUP
ARPLAY   STH   R4,LASTK
         AH    R4,BASENOTE
         AH    R4,TRANSP
         AH    R4,ARPOCT                R4: the note
         LH    R3,ARPLEN
         BAL   R15,PLAYNOTE
         B     LOOP
*
*@block routine-tables
* For each routine: what a key going down does, what a key coming up does, and what happens
* each time round the loop.
PRESSTAB DC    PRESS,IGNORE,PRESS,IGNORE
LETGOTAB DC    RELEASE,IGNORE,RELEASE,IGNORE
TICKTAB  DC    LOOP,RHYTHM,STEPS,ARP
ONPRESS  DC    PRESS
ONLETGO  DC    RELEASE
ONTICK   DC    LOOP
*
*@block routine-settings
* Speeds (bits 14-15 of the switches), step sizes (bits 12-13) and the lanes' ranges. A step
* of 16 is one step of a 12-bit converter (3 cents on a pitch lane); 256 is one step of an
* 8-bit converter.
TEMPOTAB DC    125,100,160,200          milliseconds per step: rhythm and arpeggio
ARPLENS  DC    94,75,120,150            how long each arpeggio note sounds
UPDTAB   DC    4,15,60,250              milliseconds per step: steps
STEPTAB  DC    16,64,256,1024           code added per step: steps
CUTLO    DC    X'1000'                  the cutoff lane's range, 0.64 V
CUTHI    DC    X'7000'                  to 4.48 V
DETHI    DC    X'0400'                  the detune lane's range, 0 to 0.16 V
ACCENTV  DC    X'5000'                  rhythm: the cutoff lane on an accent, 3.2 V
SOFTV    DC    X'1800'                  and on other steps, 0.96 V
*
*@block rhythm-patterns
* Four patterns of sixteen steps. Each step is two bytes: the interval from the lowest key
* held, in semitones (X'80' is a rest; X'F4' is 12 below), then the note's length in units
* of 4 ms, plus X'80' for an accent.
PATTERNS DC    X'0099',X'8000',X'0C0F',X'070F',X'0019',X'8000',X'0A0F',X'8000'
         DC    X'0099',X'030C',X'070C',X'8000',X'0594',X'8000',X'FB1E',X'8000'
         DC    X'00BC',X'8000',X'8000',X'8000',X'0728',X'8000',X'8000',X'0E1E'
         DC    X'8000',X'0CB2',X'8000',X'8000',X'131E',X'8000',X'0528',X'8000'
         DC    X'0090',X'000F',X'0C0F',X'008F',X'000F',X'0C0F',X'008F',X'070F'
         DC    X'000F',X'0C0F',X'008F',X'000F',X'0C0F',X'0F8F',X'000F',X'0A0F'
         DC    X'00A8',X'0714',X'8000',X'0C14',X'8000',X'F4A8',X'0014',X'8000'
         DC    X'0714',X'8000',X'03A0',X'0A14',X'8000',X'0514',X'8000',X'1114'
