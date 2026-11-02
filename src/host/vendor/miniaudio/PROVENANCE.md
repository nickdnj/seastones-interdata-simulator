# miniaudio: provenance (VS-13; ARCHITECTURE 1.3, ADR-002; CT-12 and HO-04 read this)

| Field | Value |
|---|---|
| Project | miniaudio, by David Reid: <https://github.com/mackron/miniaudio> |
| Tag | `0.11.26` (`MA_VERSION_MAJOR 0`, `MINOR 11`, `REVISION 26` in the header) |
| Commit | `877ea4a7c2601c7b0f2a44e83dfac42e6470fea6` |
| Fetched | 2026-10-31, `raw.githubusercontent.com/mackron/miniaudio/<commit>/miniaudio.h` and `/LICENSE`, by the host lane's overnight run |
| `miniaudio.h` SHA-256 | `6b376c7fbb1352ba1e0e432ab66069b335ea9405e45cb6c30b97ef0f3c9c3e0e` (4,161,918 bytes) |
| `LICENSE` SHA-256 | `457f1b500e0adf6bc059edddfa78a2f62012e7c3bb43476c20e0bd23b25ba0eb` |
| Licence | Choice of **public domain (Unlicense)** or **MIT No Attribution**. Neither requires a notice in the product; CT-12 should still credit it in `THIRD-PARTY-NOTICES` as a courtesy and for the audit trail. |

## Rules

- The files here are **byte-identical to the commit above** and are never edited. A test
  (`tests/host/test_vendor_miniaudio.py`) checks both hashes.
- To update: fetch the new tag's two files, update this table and the test's hashes in one commit,
  run `make ci` and `scripts/host-linux-check.sh`, and note the change for the release record.
- Build options live in our own `src/host/ma_config.h` (device I/O only: no decoding, encoding,
  generation, resource manager, node graph or engine; only CoreAudio, ALSA and the null device).
  `src/host/miniaudio_impl.c` is the one translation unit that compiles it, with warnings off like
  the vendored SIMH files.
