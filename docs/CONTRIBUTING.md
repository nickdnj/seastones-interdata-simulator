# Contributing to the Seastones Rig

Thanks for helping. This applies to people and to AI assistants alike.

## First time

```
scripts/dev-setup.sh      # checks the toolchain, installs the pre-commit hook
make ci                   # the same list CI runs; must pass before anything is merged
```

`make ci` runs lint, the private-material check, every test target that exists, and the S-3
conformance lockstep (`make conformance`). The stock `id16` oracle is built from `deploy/simh.pin`
by `make oracle`; the pinned open-simh source is cloned once into `~/.cache/seastones/open-simh`.

## Pull requests

- Fork, branch (`issue/<slug>`), and open a pull request against `main`.
- `make ci` must pass. `main` is always green.
- Keep a change focused, and commit only the files you meant to change. Never commit with
  `--no-verify`: the pre-commit hook is the rights guard.
- Message: `<type>(<scope>): <summary>`. Types: `feat fix test docs chore spike`. Say what
  test or measurement proves the change.

## What never enters the repo

- **Audio** of any kind, including our own renders (RE-1). The hook rejects audio by extension and by
  magic bytes. Golden renders are hashes plus feature JSON.
- **Any Seastones recording, waveform, spectrogram or derived score** (LEGAL-REVIEW 2.3).
- **Interdata binaries, paper tapes or manual scans** (RIGHTS-6). Period programs used as test
  fixtures are read through `SX_FIXTURES_DIR` at test time and never copied in.
- Notebooks (they live in `$SEASTONES_NOTEBOOK_DIR`, outside git).

## Vendored SIMH

`src/engine/simh/` holds open-simh files byte-identical to the pinned tag. They are **never edited
in place**. Every change is a numbered patch in `src/engine/simh/patches/`, applied at build time,
listed in `src/engine/simh/PROVENANCE.md`, and limited to clocking, timing, idle and device
registration. `tests/conformance/test_vendor_hashes.py` enforces this.

## Standards

- C17 for our C, with `-Wall -Wextra -Wpedantic -Wconversion -Werror`. Vendored files are built with
  their own upstream flags (`-DIFP_IN_MEM`) and warnings off, because they are not ours to change.
  `clang-format` (`.clang-format`) for our C only.
- Python 3.12 (compatible with 3.13), `ruff` (`ruff.toml`), `pytest`. Tests print their seeds and use
  no network.
- Fixtures are synthetic and seeded; planted violations are generated at run time in a temp dir.
