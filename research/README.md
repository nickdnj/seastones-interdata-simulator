# research/: the Seastones research workstream (tooling only)

PRD section 6, ADR-007, LEGAL-REVIEW section 2. **No audio, ever.** Nothing in this folder is a
recording, an excerpt, a spectrogram or waveform image of a recording, or a transcription of one.
This folder is never copied into the station image (RE-2, SEA-3).

| Path | What it holds |
|---|---|
| `tools/env.py` | The environment guard. Every notebook calls `env.check()` first (RS-01). |
| `tools/ledger.py` | Hypothesis ledger validator and lister (RS-02). |
| `ledger/H-NNN.md` | Ledger entries (RE-4). `H-900` and up are synthetic fixtures, clearly fictional. |
| `notes/` | "What the machine seems to be doing" notes (RE-8) and workstream decisions. |
| `scores/` | **Original and synthetic scores only** (`seastones.score/1`, see `docs/score-format.md`). |
| `notebook-templates/` | Notebook templates with outputs stripped. Real notebooks live outside git. |
| `provenance.md` | Acquisition log without audio (RE-3). Written by Nick in RS-06. |

## Where the private material lives

Outside this repo, on an encrypted disk, outside iCloud, Dropbox, Google Drive and OneDrive:

| Variable | Folder | Default |
|---|---|---|
| `SEASTONES_AUDIO_DIR` | the recordings and the provenance log with audio details | none: must be set |
| `SEASTONES_NOTEBOOK_DIR` | the analysis notebooks (decision D-PLAN-1) | `seastones-notebooks` beside the audio folder |
| `SEASTONES_NOTEBOOKS_IN_REPO=1` | flips notebooks back to `research/notebooks/` in this repo (PRD RE-6 layout) | off |

Seastones-derived scores (transcriptions) are kept in the private folder too. The release guard
(`scripts/derived_guard.py`, RS-05) fails if one appears under `content/`, `src/`, `deploy/` or an
image directory.

Check the setup:

```
python -m research.tools.env
```

It exits 0 with the two paths, or 2 with a plain message saying what to fix. It never lists or reads
anything inside the folders.

## Rules for agents

AI agents never receive the recordings, any image of them, or any Seastones-derived transcription
(LEGAL-REVIEW 2.3). Every tool here is built and tested on generated synthetic signals and synthetic
scores. Agents run with `SEASTONES_AUDIO_DIR` unset.

## Analysis toolkit (RS-04)

`tools/analysis.py` (pitch track, steps and update rate, onsets, loop length, zipper) and
`tools/synth.py` (the generated test signals). Set up a local venv once; it is git-ignored by its
own `.gitignore`:

```
python3.12 -m venv .venv-research
printf '*\n' > .venv-research/.gitignore
.venv-research/bin/pip install -r research/requirements.txt
.venv-research/bin/nbstripout --install      # activates research/.gitattributes
```

The default pitch tracker (`method="peak"`) follows one strong partial and is sub-cent on a clean
tone; it is meant for monophonic stretches with the band set around one voice. `method="yin"`
(librosa) copes better with a weak fundamental but jitters by several cents, too coarse for D/A
step sizes. Measured on generated signals: 3-cent steps recovered within 2 percent at 30 dB SNR
or better (about 10 percent at 20 dB), and a 25 Hz update rate within 3 percent. Real recordings are mixed, processed and noisy;
treat every number as a hypothesis for the ledger.

## Tests

```
.venv-research/bin/python -m pytest tests/research tests/toolchain   # everything
python3 -m pytest tests/research tests/toolchain                       # librosa tests skip
```
