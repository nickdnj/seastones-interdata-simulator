# src/

Application code. Layout follows `docs/DEV-PLAN.md` section 6 and `docs/ARCHITECTURE.md` section 12.

- `engine/`: the rig engine in C17. `include/seastones.h` is the contract. `simh/` holds vendored
  open-simh files, byte-identical to the pin, changed only by numbered patches in `simh/patches/`.
  `shim/scp_shim.c` is the minimal SCP that lets the vendored CPU run inside the engine.
- `oracle/`: the `id16-seastones` device-trace oracle (VS-06).
- `toolchain/`: `sxasm` and `sxscore`.
- `program/`: the 7/16 program and the portable-subset file.

Nothing here is ever a Seastones-derived file, an Interdata binary or tape, a manual scan, or audio.
