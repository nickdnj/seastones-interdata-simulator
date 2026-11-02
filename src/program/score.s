* score.s: the score player (VS-21; MACH-8; ARCHITECTURE 9.3). Part of rig.s.
*
* A score is a tape: the operator loads its table at X'2000' (the engine's sx_score_load,
* compiled by sxscore.compile) and sets switches 0-3 to 1 (the score alone) or 2 (the score
* and the keyboard together). The table is records of three halfwords: how many ticks to wait
* after the record before, what to do, and a value. The interval clock keeps the time. The
* score's notes are note numbers, so the pitch table and the converter still decide how they
* sound. Ramps are played by the computer, one step at a time: their zipper is the program's.
*
TAPE     EQU   X'2000'                  the table: generation, voices, tick, then records
TAPEV    EQU   TAPE+2
TAPET    EQU   TAPE+4
RECS     EQU   TAPE+6
SMAXREC  EQU   4                        at most this many records in one pass
TAPEEND  EQU   X'7FF8'                  the last record that fits the score area (32 KB machine)
TAPEMAX  EQU   4092                     records that fit: (TAPEEND - RECS) / 6
*
*@block whose-voices
* With the score and the keyboard together, the tape keeps voices 1 up to its own count and the
* keyboard has the rest. KVFIRST is the keyboard's first voice, counted in twos.
SPLIT    LHI   R0,0
         STH   R0,SVOICES
         LH    R6,SMODE
         BZ    SPDONE                   the keyboard alone: every voice is its own
         LH    R6,TAPE
         BZ    SPDONE                   no tape loaded yet
         LH    R6,TAPEV                 the tape's voices,
         CH    R6,NVOICES               no more than there are
         BNP   SPOK
         LH    R6,NVOICES
SPOK     STH   R6,SVOICES
         AHR   R6,R6
         LH    R0,SMODE
         CHI   R0,2
         BE    SPKEEP
         LH    R6,NV2                   the score alone: the keyboard has none
SPKEEP   STH   R6,KVFIRST
         BR    R14
SPDONE   STH   R0,KVFIRST
         BR    R14
*
*@block read-the-tape
* Each time round: if a new tape has been loaded, start it from the top; else play every record
* that is due, a few at most, and step any ramp that is running.
SCORE    BAL   R14,CLOCK
         LH    R0,TAPE                  the tape's generation
         CH    R0,SGEN
         BE    SCSAME
         STH   R0,SGEN                  a new tape (or a new mode): from its first record
         BAL   R15,SILENCE
         LH    R0,TAPET
         STH   R0,STICK
         LHI   R1,RECS
         STH   R1,SPTR
         LHI   R0,0
         STH   R0,SDONE
         STH   R0,RCH
         LHI   R6,32                    the score's record of each D/A channel: 0 V, as
SCCV     SIS   R6,2                     silence left them
         STH   R0,CVNOW(R6)
         BNZ   SCCV
         STH   R0,CVNOW
         LH    R6,0(R1)                 the first record's wait
         BAL   R14,MSOF
         AH    R6,NOW
         STH   R6,SNEXT
         B     LOOP
SCSAME   LH    R0,TAPE
         BZ    LOOP                     no tape: nothing to play
         BAL   R15,TRIGDOWN
         BAL   R15,RAMPSTEP
         LH    R0,SDONE
         BNZ   LOOP
         LIS   R9,SMAXREC
SCDUE    LH    R6,NOW
         SH    R6,SNEXT
         BM    LOOP                     not yet
         LH    R1,SPTR
         LH    R2,2(R1)                 what to do
         LH    R3,4(R1)                 its value
         LHR   R6,R2
         SRLS  R6,11
         NHI   R6,X'1E'                 the op, x 2
         LH    R6,SOPS(R6)
         BALR  R15,R6
         SIS   R9,1
         BNZ   SCDUE
         B     LOOP
*
*@block next-record
* After a record: on to the next one, due its wait (in ticks) after this one.
SNEXTREC LH    R1,SPTR
         AIS   R1,6
         CLHI  R1,TAPEEND               past the end of the score area: a damaged tape
         BNL   SEND                     stops there
SNEXTAT  STH   R1,SPTR
         LH    R6,0(R1)
         BAL   R14,MSOF
         AH    R6,SNEXT
         STH   R6,SNEXT
         BR    R15
*
*@block ticks-to-milliseconds
* R6 ticks to milliseconds: a tick is 1 ms or 10 ms (the tape says which).
MSOF     LH    R0,STICK
         CHI   R0,10
         BNE   MSDONE
         LHR   R0,R6
         SLLS  R6,3
         AHR   R6,R0
         AHR   R6,R0                    x 10
MSDONE   BR    R14
*
*@block score-notes
* NOTE: voice (the low byte of the op word) plays note R3. OFF: the voice lets go. Only the
* tape's own voices answer it.
SNOTE    LHR   R5,R2
         NHI   R5,X'FF'
         CH    R5,SVOICES
         BNL   SNEXTREC                 not one of the tape's voices
         AHR   R5,R5
         LHR   R4,R3
         BAL   R14,GATECUT              its gate drops, so the envelope starts again
         BAL   R14,SENDNOTE
         BAL   R14,GATEON
         B     SNEXTREC
SOFF     LHR   R5,R2
         NHI   R5,X'FF'
         CH    R5,SVOICES
         BNL   SNEXTREC
         AHR   R5,R5
         BAL   R14,GATEOFF
         B     SNEXTREC
*
*@block score-voltages
* CV: D/A channel (the low byte) to code R3, at once.
SCV      LHR   R5,R2
         NHI   R5,X'0F'
         LHR   R6,R5
         AHR   R6,R6
         STH   R3,CVNOW(R6)             remembered, for a ramp from here
         OHI   R5,X'80'
         OCR   R11,R5
         WHR   R11,R3
         B     SNEXTREC
*
*@block score-ramps
* RAMP: from the channel's code now to code R3 in a number of equal steps across a number of
* ticks (the next record holds both). The steps are worked out once, by a division, in half
* codes so the difference fits a halfword; then RAMPSTEP sends one step each time it is due.
SRAMP    LHR   R5,R2
         NHI   R5,X'0F'
         LHR   R6,R5
         AHR   R6,R6
         LH    R13,CVNOW(R6)            R13: where the ramp starts
         STH   R3,CVNOW(R6)             and where it ends
         STH   R3,RTARGET
         OHI   R5,X'80'
         STH   R5,RCH
         SRLS  R13,1
         STH   R13,RCUR
         LH    R1,SPTR
         LH    R4,10(R1)                R4: the steps
         STH   R4,RLEFT
         LHR   R3,R3
         SRLS  R3,1                     the target, in half codes
         SHR   R3,R13                   the whole move
         LHI   R2,0
         LHR   R3,R3
         BNM   SRPOS
         LCS   R2,1                     a move down: the high half is all ones
SRPOS    DHR   R2,R4                    R3: the move per step
         STH   R3,RSTEP
         LHI   R2,0
         LH    R3,6(R1)                 the ticks it takes
         DHR   R2,R4
         LHR   R6,R3                    ticks per step
         BAL   R14,MSOF
         LHR   R6,R6
         BNZ   SRDT
         LIS   R6,1                     at least a millisecond a step
SRDT     STH   R6,RDT
         AH    R6,NOW
         STH   R6,RNEXT
         AIS   R1,6                     past the second record, which the ramp used
         STH   R1,SPTR
         B     SNEXTREC
*
*@block ramp-step
* A ramp that is running sends its next step when due; the last step is the exact target.
RAMPSTEP LH    R5,RCH
         BZ    RSDONE
         LH    R6,NOW
         SH    R6,RNEXT
         BM    RSDONE
         LH    R6,RNEXT
         AH    R6,RDT
         STH   R6,RNEXT
         LH    R6,RLEFT
         SIS   R6,1
         STH   R6,RLEFT
         BNZ   RSMID
         LH    R6,RTARGET               the last step: exactly the target
         LHI   R0,0
         STH   R0,RCH                   the ramp is over
         B     RSSEND
RSMID    LH    R6,RCUR
         AH    R6,RSTEP
         STH   R6,RCUR
         AHR   R6,R6                    back to a whole code
RSSEND   OCR   R11,R5
         WHR   R11,R6
RSDONE   BR    R15
*
*@block score-triggers
* TRIG: gate line 8-15 (the low byte) up for one tick, then down; lines 0-7 are the voices'.
STRIG    LHR   R5,R2
         NHI   R5,X'0F'
         CHI   R5,8
         BL    SNEXTREC
         SHI   R5,8
         LB    R5,LINEBIT(R5)
         OH    R5,TRIGS
         STH   R5,TRIGS
         BAL   R14,GATE16
         LH    R6,STICK
         AH    R6,NOW
         STH   R6,TRIGAT                down a tick later
         B     SNEXTREC
TRIGDOWN LH    R0,TRIGS
         BZ    TDDONE
         LH    R6,NOW
         SH    R6,TRIGAT
         BM    TDDONE
         LHI   R0,0
         STH   R0,TRIGS
         BAL   R14,GATE16
TDDONE   BR    R15
* All sixteen gate lines at once: the voices' lines 0-7 as they are, the triggers 8-15.
GATE16   LHR   R6,R7
         SLLS  R6,8
         OH    R6,TRIGS
         WHR   R12,R6
         LHR   R8,R7
         BR    R14
*
*@block score-flow
* LOOP: play on from record R3, with no wait. END: stop; the tape's voices let go. WAIT: nothing.
SLOOP    CLHI  R3,TAPEMAX               a loop to a record past the area: stop instead
         BNL   SEND
         LHR   R1,R3
         AHR   R1,R1
         AHR   R1,R3
         AHR   R1,R1                    R3 x 6
         AHI   R1,RECS
         STH   R1,SPTR
         BR    R15
SEND     LIS   R0,1
         STH   R0,SDONE
         LH    R5,SVOICES
SENDV    SIS   R5,1
         BM    SENDX
         LHR   R6,R5
         AHR   R5,R5
         BAL   R14,GATEOFF
         LHR   R5,R6
         B     SENDV
SENDX    BR    R15
SWAIT    B     SNEXTREC
*
*@block score-tables
* What each op does (0 END, 1 NOTE, 2 OFF, 3 CV, 4 RAMP, 5 TRIG, 6 LOOP, 7 WAIT), and each
* trigger line's bit.
SOPS     DC    SEND,SNOTE,SOFF,SCV,SRAMP,STRIG,SLOOP,SWAIT
         DC    SEND,SEND,SEND,SEND,SEND,SEND,SEND,SEND
LINEBIT  DC    X'8040',X'2010',X'0804',X'0201'
