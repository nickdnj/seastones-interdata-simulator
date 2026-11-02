# ADR-007: Content, patch, gated-layer and research data model

**Status:** Proposed · **Date:** 2026-10-31 · **Changes PRD:** PATCH-5 AC (file pair), CONT-2 (two status axes)

## Context

Patches and presets must be data (PATCH-5, G8). Every visitor-facing word must live in plain-text
content files a non-developer edits (CONT-1, OPS-4). The Seastones layer must ship disabled and be
switched on by a content edit (SEA-3). Labels must follow the research ledger (RETRO-2). Recordings
must never enter git or the build (RE-1, RE-2). The Model 4 kiosk's content system (flat
`key: value` header + Markdown body, Python indexer at boot, validator, stick with baked fallback)
already serves the same museum staff.

## Decision

- **Reuse the Model 4 content system** and extend it with `presets/`, `passages/`, `code/`, `rig/`.
  Keep its **two status axes**: `status` (ready | draft-hidden) for shipping, `claim` (confirmed |
  unconfirmed | withheld) for facts.
- **Preset = `<slug>.md`** (title, status, description, ledger refs: the words) **+
  `<slug>.patch.json`** (`seastones.patch/1`: modules, cables, voice template, auth mode: the
  graph). Staff saves write the pair atomically to `/data/presets/`, with an export-to-stick action.
- **Passage = `<slug>.md` + `<slug>.score`**, shipped `draft-hidden`. The gate is enforced **twice**:
  the indexer leaves hidden passages out of the visitor order, and `rigd` refuses `passage.start`
  unless the passage is `ready` or review mode is on. The validator requires ledger refs and the
  hypothesis-label slot for any `ready` passage.
- **Ledger** = `research/ledger/H-NNN.md` in the same header format. The validator resolves every
  `ledger:` reference, and the label wording slot is chosen by ledger status.
- **Recordings outside git, four layers:** `.gitignore`; a pre-commit check (extensions, magic bytes,
  >2 MB under `research/`, notebook outputs/audio MIME); the same check in CI over the PR's commits;
  indexer and image build refuse audio-magic files. `SEASTONES_AUDIO_DIR` must be outside every git
  work tree, checked at notebook start.

## Consequences

- Positive: staff edit words without touching JSON; the graph stays machine-validated; one parser;
  the gate cannot be opened by a UI bug alone; RETRO edits are data.
- Negative: two files per preset or passage; the validator must pair them and report orphans in plain
  English.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **File pairs** | words where staff expect them; strict graph schema | pairing to validate |
| One JSON per preset with name/description inside | PATCH-5's literal "one file" | visitor words in a syntax with teeth (Model 4 A-11 rejected this for staff) |
| Patches in a SQLite DB on `/data` | atomic | opaque to staff; not diffable; not on the stick |

## Risk note

A content editor could flip a passage to `ready` before clearance. This is accepted and documented:
enabling layer 6 is Doug's decision (OPS-1) and needs no code. The runbook and content guide state
that the switch is a rights decision, and the validator prints a reminder whenever a passage is
`ready`.
