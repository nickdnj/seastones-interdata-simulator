# tests/

`make test` runs the pytest suites here; `make conformance` runs the S-3 lockstep against stock `id16`.

- `conformance/`: lockstep vs stock `id16`, disassembly vs `ex -m`, vendored-file hashes (CNF-*).
- `safety/`: the private-material hook tests. Fixtures (audio-like files) are generated at run time
  in a temp dir and never committed.
- `engine/`, `toolchain/`: C unit tests and assembler tests (Wave 3 onward).

Every randomised test prints its seed. Failing conformance seeds go into `conformance/seeds.txt`.
