# ADR-002: Engine host — a native real-time audio process, not a browser AudioWorklet

**Status:** Proposed · **Date:** 2026-10-31

## Context

ADR-001 puts CPU, devices and synthesizer in one render call. That call can run in the browser (a
WASM AudioWorklet, with the page owning sound) or in a native process with the page as a display
only. The station is a fully offline x86 mini-PC with a USB-MIDI keyboard. NFR-1 allows 25 ms p95
end to end. MACH-7 requires silence within 100 ms of any fault. AUDIO-4 forbids thumps on reloads.

## Decision

`rigd`: a Python host process (control, WebSocket, staff, counters, supervision, all ported from the
Model 4 bridge) that loads the C engine through `cffi`. C threads own the real-time work: a
`SCHED_FIFO` audio thread on ALSA `hw:` direct (miniaudio, 48 kHz, 128-frame periods, 2-period ring,
no PipeWire/PulseAudio on the image) and an ALSA-sequencer MIDI thread subscribed to the announce
port for immediate unplug notice. No Python runs on a real-time thread. Chromium draws, and it makes
no sound.

## Consequences

- Positive: an output path we control (≈5 ms ring), on budget with ~9 ms margin (ARCHITECTURE
  §6.6); MIDI never crosses the browser's main thread; page reloads and Chromium crashes cannot thump
  or glitch audio; autoplay and Web MIDI permission policies are moot; `kill -9` closes the PCM
  (immediate silence); systemd `WatchdogSec` supervises one process; dev parity on the Mac with the
  CoreAudio/CoreMIDI backends.
- Negative: native audio/MIDI code (two small backends); the page needs a loopback WebSocket for
  every lamp (60 Hz, fine); a dead page leaves sound running unless `rigd` mutes, so it mutes after
  10 s with no UI client.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **Native `rigd`** | lowest, most predictable latency; fate-sharing of CPU and sound; Model 4 supervision reused | native code to maintain |
| AudioWorklet (WASM) in Chromium | one runtime; KIOSK-9 mirror for free | Chromium's Linux output latency is an unmeasured term on the critical path; Web MIDI is main-thread only; reloads restart audio (thumps); needs a kiosk permission policy for MIDI |
| Electron with native modules | native MIDI | a second browser runtime + update surface for what `rigd` already does |

## Risk note

Real-time C in a long-running kiosk process: a memory bug crashes the exhibit. Mitigations are an
RT-safety lint on the render path, ASan/UBSan in CI, fuzzing the patch and score loaders, and the
10 h soak. The crash itself fails silent and self-recovers (≤ 10 s). The engine stays OS-free so a
WASM build remains possible (KIOSK-9).
