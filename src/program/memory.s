* memory.s: where the program keeps its working values (ARCHITECTURE 5.5). Part of rig.s.
* Nothing here is code: DS only reserves room, so these blocks hold no instructions.
*
*@block the-loop-memory
* Where the loop keeps the rows it reads, the keys it knows are down, and its clocks and
* settings. Rows take one byte each; the sixth byte is never used, so the rows can be
* compared two at a time.
         ORG   X'1300'
ROWS     DS    6                        the five rows just read
HELD     DS    6                        the five rows as the program knows them
SRNOW    DS    2                        the switches as just read
SRLAST   DS    2                        the switches as last acted on
ROUTINE  DS    2                        the routine (0-3)
VARIANT  DS    2                        its variant (0-15)
TRANSP   DS    2                        transposition, semitones
NOTEOFF  DS    2                        (base note + transposition) x 2
ALLOC    DS    2                        1: each key gets a voice of its own
NV2      DS    2                        voices x 2
NOW      DS    2                        milliseconds, counted from the interval clock
MSLAST   DS    2                        the clock's count at the last look
NEXTAT   DS    2                        when the next step is due (NOW time)
STEPMS   DS    2                        milliseconds per step
STEP     DS    2                        the step of the pattern (0-15)
PATBASE  DS    2                        where the variant's pattern starts
RVOICE   DS    2                        the next voice in turn (x 2)
LASTK    DS    2                        the arpeggio's last key (X'FF': none)
ARPMODE  DS    2                        up, down, up and down, up two octaves
ARPDIR   DS    2                        up and down: 0 going up, 1 going down
ARPOCT   DS    2                        up two octaves: 0 or 12
ARPLEN   DS    2                        how long each arpeggio note sounds
STEPSZ   DS    2                        steps: how much each step adds to a lane's code
UPDMS    DS    2                        steps: milliseconds between steps
CUT      DS    2                        steps: the cutoff lane's code
CDIR     DS    2                        steps: the cutoff's step, up (+) or down (-)
DET      DS    2                        steps: the detune lane's code
DDIR     DS    2                        steps: the detune's step
SMODE    DS    2                        switches 0-3: 0 play, 1 score, 2 both
SGEN     DS    2                        the tape's generation as last seen (0: none)
SPTR     DS    2                        the score's next record (an address)
SNEXT    DS    2                        when it is due (NOW time)
SDONE    DS    2                        1 after END
SVOICES  DS    2                        voices the tape keeps
KVFIRST  DS    2                        the keyboard's first voice (x 2)
STICK    DS    2                        milliseconds per score tick
TRIGS    DS    2                        score trigger lines up (lines 8-15, low byte)
TRIGAT   DS    2                        when they come down
RCH      DS    2                        the ramp's channel (D/A command byte); 0: no ramp
RCUR     DS    2                        the ramp's value now, in half codes
RSTEP    DS    2                        its step, in half codes
RLEFT    DS    2                        steps still to come
RTARGET  DS    2                        its last value, the exact code
RDT      DS    2                        milliseconds per step
RNEXT    DS    2                        when the next step is due
CVNOW    DS    32                       the code last sent to each D/A channel by the score
*
*@block the-voice-tables
* One entry per voice, two bytes apart (voices count in twos), and the key map.
         ORG   X'1140'
VKEY     DS    16                       the key each voice plays (X'FF': none)
APREV    DS    16                       the ring: the voice pressed just before it
ANEXT    DS    16                       the ring: the voice pressed just after it
VON      DS    16                       routines: 1 while its note sounds
OFFAT    DS    16                       routines: when its note stops (NOW time)
FREEQ    DS    8                        the free queue (a ring of eight)
AHEAD    DS    1                        the oldest voice playing (X'FF': none)
FHEAD    DS    1                        the free queue's front
FCOUNT   DS    2                        how many voices are free
         ORG   X'11C0'
KVOICE   DS    64                       for each key place, the voice it last got
