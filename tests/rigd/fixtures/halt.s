* halt.s: a test program that halts (FLT-03; VS-17). Never shipped: tests/rigd only.
*
* It sounds note 60 with no key held (pitch on D/A 0, gate line 0 high), keeps reading the
* keyboard for about 0.3 s of emulated time so the supervisor's liveness check is happy, then
* loads a PSW with the wait bit set and interrupts off: the machine can never leave, which is
* program_stalled (ARCHITECTURE 8.1). rigd must fall silent within 100 ms, send HOME, and the
* program starts again (and halts again).
*
KEYS     EQU   X'20'
DAC      EQU   X'21'
GATE     EQU   X'22'
*
         ORG   X'0080'
*@block start-up
START    LHI   R10,KEYS
         LHI   R11,DAC
         LHI   R12,GATE
         OC    R11,CHANNEL0             converter: channel 0
         WH    R11,NOTE60               voice 0's pitch: note 60
         OC    R11,CHANNEL4             converter: channel 4, voice 0's gate on the
         WH    R11,FIVEVOLT             all-D/A map: 5 V, so it sounds with no key
         WH    R12,GATEON               gate line 0 too (the latch map's voice 0)
         LHI   R3,25000                 about 0.3 s of the loop below
*@block keep-reading
WAIT     OC    R10,FROMROW0
         RD    R10,ROW
         SIS   R3,1
         BNZ   WAIT
*@block stop
         LPSW  STOPPSW                  wait state, interrupts off: halted for good
*@block constants
CHANNEL0 DC    X'8000'
CHANNEL4 DC    X'8400'
FIVEVOLT DC    X'7D00'
FROMROW0 DC    X'4000'
NOTE60   DC    X'6400'
GATEON   DC    X'8000'
ROW      DC    X'0000'
STOPPSW  DC    X'8000',X'0080'
         END   START
