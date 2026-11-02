# Slots (CONT-2, STORY-2, CT-02)
#
# Every claim a visitor can read is bound to a slot here. Two axes:
#   status: ready | draft-hidden    (does it ship)
#   claim:  confirmed | unconfirmed | withheld   (are its facts settled)
# A claim reaches the glass only when it is confirmed and cited (STORY-2). An item that
# names an unconfirmed or withheld slot must stay draft-hidden: tests/web/test_story_claims.py
# fails the build otherwise. tags: not-shippable marks the drafts kept for Doug's review.
# evidence_kind and tier (QA request 6) are written in the note until CT-02 adds the fields.

## claim-live-1974
kind: claim
status: ready
claim: confirmed
source: brief.md, Nedbase 1974 section (photographs and Lagin's accounts)
owner: Doug (DG-02)
note: evidence_kind dated-photo; tier 1. A computer and synthesizer were used live with the Dead in 1974.

## claim-tour-1974
kind: claim
status: ready
claim: confirmed
source: brief.md: 23 shows, 1974-06-23 to 1974-10-20 (public record)
owner: Doug (DG-02)
note: evidence_kind document; tier 1. "This one went on tour."

## claim-interdata-716
kind: claim
status: ready
claim: confirmed
source: Nedbase equipment list and the nameplate in photograph 1 (PRD A-10)
owner: Doug (DG-02)
note: evidence_kind dated-photo; tier 1. 7/16, not 7/17 and not a Model 70 or 74.

## claim-roosevelt-soundcheck
kind: claim
status: ready
claim: confirmed
source: Nedbase photograph captions, 1974-08-06 (cited, never shown: STORY-4)
owner: Doug (DG-02)
note: evidence_kind dated-photo; tier 1.

## claim-museum-relatives
kind: claim
status: ready
claim: confirmed
source: the Model 4 and Model 74 kiosks' own PRDs
owner: Doug (DG-02)
note: evidence_kind document; tier 1. Says "keeps", not "owns" (PRD R13).

## claim-seastones-name
kind: claim
status: ready
claim: confirmed
source: PRD 1.1 and D3 (the work and the exhibit name); Tier 1 citation to be logged in CT-11
owner: Nick (CT-11)
note: evidence_kind document; tier 1 once the citation is logged.

## claim-sixteen-channels
kind: claim
status: ready
claim: confirmed
source: PRD 1.1, Lagin's own description of the rig (brief.md); Tier 1 citation to be logged in CT-11
owner: Nick (CT-11)
note: evidence_kind on-record-statement; tier 1 once the citation is logged.

## disclosure
kind: claim
status: ready
claim: confirmed
source: UX 8.3 and LEGAL-REVIEW 5 (our statement about this exhibit; Doug and counsel approve the words)
owner: Doug and counsel (DG-02, CT-15)
note: The full disclosure, captions/disclosure.md. A screen that names this slot shows the disclosure card.

## claim-lesh-mid-show
kind: claim
status: draft-hidden
claim: unconfirmed
source: none yet (brief.md names only "Ned and Phil" sets)
owner: Nick (CT-11)
tags: not-shippable
note: STORY-2 claim 1. "He and Phil Lesh played it in the middle of the Dead's shows." Not on the floor until cited.

## claim-716-16bit-core
kind: claim
status: draft-hidden
claim: unconfirmed
source: none yet (only an uncited Wikipedia sentence; needs an Interdata manual)
owner: Nick (CT-11)
tags: not-shippable
note: STORY-2 claim 2. "A 16-bit minicomputer with magnetic core memory, from the early 1970s."

## claim-hour-from-here
kind: claim
status: draft-hidden
claim: unconfirmed
source: none yet (PRD 1.1 says "an hour up the road"; Doug to confirm, Q-M4)
owner: Doug (DG-02)
tags: not-shippable
note: STORY-2 claim 3. "Jersey City is about an hour from this room."

## claim-record-1975
kind: claim
status: draft-hidden
claim: unconfirmed
source: Round Records 1975 LP (PLAN.md); catalogue number not yet logged
owner: Nick (CT-11)
tags: not-shippable
note: "A record followed in 1975." Confirmed once the catalogue number is logged (UX 8.7).

## claim-photos-describe-rack
kind: claim
status: draft-hidden
claim: withheld
source: Nedbase 1974 section; describing the photographs needs Doug and counsel (Q-C2, RIGHTS-3)
owner: Doug and counsel
tags: not-shippable
note: "Photographs from that day show a rack holding the computer, with the synthesizer and its patch panel beside it."

## invite-tell-the-desk
kind: claim
status: draft-hidden
claim: withheld
source: an invitation, not a claim; it commits the museum to receive answers (Q-M3)
owner: Doug (DG-02)
tags: not-shippable
note: "If you know more about the original, tell the staff at the desk."

## media-lagin-photographs
kind: media
status: draft-hidden
claim: withheld
source: none yet (counsel, Q-C2)
owner: counsel
note: Lagin's photographs. Not shown, not described, until counsel answers.

## media-lagin-quotation
kind: claim
status: draft-hidden
claim: withheld
source: none yet
owner: Doug
note: A quotation from Ned Lagin, only with his agreement.

## credit-line
kind: claim
status: draft-hidden
claim: withheld
source: none yet
owner: Doug
note: A credit line for Ned Lagin or anyone else who helped, only with their agreement.

## field-engineer-account
kind: claim
status: draft-hidden
claim: withheld
source: an unverified oral recollection ("a Model 70 or 74"); not Tier 1
owner: Doug
note: Stays off the glass until it is Tier 1.

## corrected-channel-map
kind: claim
status: draft-hidden
claim: withheld
source: none yet (only people who worked on the original could give it)
owner: Doug
note: A confirmed channel map would replace ours (RETRO-1).

## label-channel-map
kind: claim
status: ready
claim: confirmed
source: ARCHITECTURE 5.4 (our design, ADR-003)
owner: Nick
note: The channel map is our choice, not Lagin's (PATCH-7).

## label-gate-latch
kind: claim
status: ready
claim: confirmed
source: ARCHITECTURE 5.3 (our design)
owner: Nick
note: The gate latch is our addition.

## label-dac-word-size
kind: claim
status: ready
claim: confirmed
source: ARCHITECTURE 5.2 (a hypothesis, labelled as such, MACH-3)
owner: Nick
note: A 12-bit D/A on 0 to 10.24 V is our guess.

## label-cycle-estimate
kind: claim
status: ready
claim: confirmed
source: docs/qa/results/M1/S4.md (ESTIMATE from the Model 74 table)
owner: Nick
note: The speed at RUN is an estimate until a 7/16 timing table is found.

## label-panel-inferred
kind: claim
status: ready
claim: confirmed
source: docs/research/bitsavers-716-report.md; DESIGN-SYSTEM 4.1
owner: Nick
note: The panel is drawn from Interdata documentation; which panel Lagin had is unknown (R7).
