title: Notebooks live outside git (D-PLAN-1)
status: adopted
date: 2026-10-31
decided_by: Nick's brief for the first overnight build (lane E)
conflicts_with: PRD RE-6 and ARCHITECTURE 11.5 (notebooks committed to the private repo with outputs cleared)

The research notebooks live in `$SEASTONES_NOTEBOOK_DIR`, beside the audio folder, outside every
git work tree. The repo keeps the tools, the ledger, the score format and validator, synthetic
fixtures and notebook templates with outputs stripped.

How the conflict is resolved: the brief wins. PRD RE-6 says notebooks are committed with outputs
cleared; DEV-PLAN D-PLAN-1 recommends the brief's way and leaves the final call to Nick. The lane E
build follows the brief. **The PRD was not edited.** If Nick confirms, RE-6 and the M0 Done line
("one transcription ... under `research/`") need amending in the PRD; if he chooses the PRD way,
`SEASTONES_NOTEBOOKS_IN_REPO=1` switches `research/tools/env.py` to `research/notebooks/` with no
code change.

What it changes in practice:
- `env.check()` validates the notebook folder with the same rules as the audio folder (exists,
  absolute, outside git, not in a sync folder).
- Seastones-derived scores also default to the private folder. `research/scores/` holds original
  and synthetic scores only.
- RSC-03 (notebook hygiene) still applies to the templates in `research/notebook-templates/`.
