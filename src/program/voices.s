* voices.s: voice allocation in 7/16 code (PO-03, PO-04; ADR-009 rule 3). Part of rig.s.
*
* Voices are counted in twos (0, 2, 4 ...), because each voice's channel numbers are
* halfwords in the channel map. Three small structures make every step take the same short
* time, however many voices are busy:
*   the free queue   voices nobody is playing, the one that has rested longest first
*   the age ring     voices being played, in the order their keys went down, joined in a
*                    ring: each voice names the one pressed before it and the one after it.
*                    AHEAD is the oldest; the newest is the one just before it.
*   the key map      for each of the 64 key places, the voice it last got: a key coming up
*                    lets that voice go only if the voice still plays it
* So a new key never searches. It takes the free queue's first voice, or else steals the
* oldest: then the ring simply turns one place, and the stolen voice, now playing the new key,
* is the newest. The documented steal order is "the oldest note goes first" (PRG-04).
*
*@block find-a-voice
* A key went down (R4: its number). Take the free voice that has rested longest. If every
* voice is busy, take the one that has been playing longest; the ring turns one place.
PRESS    LH    R0,FCOUNT                any voice free?
         BZ    STEAL
         LB    R6,FHEAD                 R6: the free queue's front
         LB    R5,FREEQ(R6)             R5: the voice that has rested longest
         AIS   R6,1
         NHI   R6,7
         STB   R6,FHEAD
         SIS   R0,1
         STH   R0,FCOUNT
         LB    R6,AHEAD                 it joins the ring as the newest, before the oldest
         CHI   R6,X'FF'
         BE    PRALONE
         LB    R0,APREV(R6)             R0: the newest voice until now
         STB   R5,APREV(R6)
         STB   R0,APREV(R5)
         STB   R6,ANEXT(R5)
         LHR   R6,R0
         STB   R5,ANEXT(R6)
PRKEY    STB   R4,VKEY(R5)              the voice plays this key
         STB   R5,KVOICE(R4)            and the key knows its voice
         AHR   R4,R4                    two bytes per pitch-table entry
         AH    R4,NOTEOFF               plus the base note and transposition, x 2
         LH    R0,GMODE
         BNZ   FREEDAC
         B     LATCUT                   (its line may not have been sent low yet this pass)
PRALONE  STB   R5,AHEAD                 the only voice playing: oldest and newest
         STB   R5,APREV(R5)
         STB   R5,ANEXT(R5)
         B     PRKEY
STEAL    LB    R5,AHEAD                 R5: the voice playing longest
         LB    R6,ANEXT(R5)
         STB   R6,AHEAD                 the ring turns: the next voice is now the oldest
         STB   R4,VKEY(R5)              the voice plays this key now (its old key, when it
         STB   R5,KVOICE(R4)            comes up, finds the voice is no longer its own)
         AHR   R4,R4
         AH    R4,NOTEOFF
         LH    R0,GMODE
         BNZ   STEALDAC
*
*@block write-to-the-synth
* Send the voice the number that plays its note, then raise its gate. A stolen voice's gate
* drops first, so its envelope starts over.
LATCUT   NH    R7,GINV(R5)              the gate latch: this voice's line off
         WDR   R12,R7                   at once
         LHR   R8,R7
         OC    R11,PCH+1(R5)            the voice's pitch channel
         WH    R11,PITCH(R4)            the number that plays the note
         OH    R7,GCH(R5)               its line on, sent at the end of the pass
         BR    R15
STEALDAC OC    R11,GCH+1(R5)            the D/A converter: the voice's gate channel
         WH    R11,ZERO                 off
FREEDAC  OC    R11,PCH+1(R5)            the voice's pitch channel
         WH    R11,PITCH(R4)            the number that plays the note
         OC    R11,GCH+1(R5)            the gate channel
         WH    R11,GATEHI               on
         BR    R15
*
*@block let-a-voice-go
* A key came up (R4: its number). If its voice is still its own, the voice lowers its gate,
* leaves the ring and joins the end of the free queue, where it rests while its note fades.
RELEASE  LB    R5,KVOICE(R4)            R5: the voice this key last got
         CLB   R4,VKEY(R5)              still playing this key?
         BNE   RLDONE                   no: a newer key took it, nothing to do
         LHI   R0,X'FF'
         STB   R0,VKEY(R5)
         LB    R6,ANEXT(R5)             out of the ring. R6: the voice after it
         CLB   R5,ANEXT(R5)             the only voice playing?
         BE    RLEMPTY
         LB    R0,APREV(R5)             R0: the voice before it
         STB   R0,APREV(R6)
         CLB   R5,AHEAD
         BNE   RLMID
         STB   R6,AHEAD                 it was the oldest: the next one is now
RLMID    LHR   R6,R0
         LB    R0,ANEXT(R5)
         STB   R0,ANEXT(R6)             the voices either side now name each other
RLFREE   LB    R6,FHEAD                 the free queue's end: front + count
         LH    R0,FCOUNT
         AHR   R6,R0
         NHI   R6,7
         STB   R5,FREEQ(R6)
         AIS   R0,1
         STH   R0,FCOUNT
         LH    R0,GMODE
         BNZ   RELDAC
         NH    R7,GINV(R5)              the gate latch: off, sent at the end of the pass
         BR    R15
RELDAC   OC    R11,GCH+1(R5)            the D/A converter: the gate channel off
         WH    R11,ZERO
RLDONE   BR    R15
RLEMPTY  LHI   R0,X'FF'
         STB   R0,AHEAD                 the ring is empty
         B     RLFREE
*
*@block send-a-note
* For the routines: send voice R5 the number that plays note R4.
SENDNOTE LHR   R6,R4
         AHR   R6,R6                    two bytes per table entry
         OC    R11,PCH+1(R5)            the voice's pitch channel
         WH    R11,PITCH(R6)            pitch to the converter
         BR    R14
*
*@block gates-on-and-off
* For the routines: raise or lower voice R5's gate. On the gate latch a gate is a bit, sent
* with the others at the end of the pass (or at once, when a gate must drop before it rises
* again); on the D/A converter it is a voltage, sent at once.
GATEON   LH    R0,GMODE
         BNZ   GONDAC
         OH    R7,GCH(R5)               on, sent at the end of the pass
         BR    R14
GONDAC   OC    R11,GCH+1(R5)
         WH    R11,GATEHI               on
         BR    R14
GATECUT  LH    R0,GMODE
         BNZ   GOFFDAC
         NH    R7,GINV(R5)              off
         WDR   R12,R7                   at once, so the envelope will start again
         LHR   R8,R7
         BR    R14
GATEOFF  LH    R0,GMODE
         BNZ   GOFFDAC
         NH    R7,GINV(R5)              off, sent at the end of the pass
         BR    R14
GOFFDAC  OC    R11,GCH+1(R5)
         WH    R11,ZERO                 off
         BR    R14
