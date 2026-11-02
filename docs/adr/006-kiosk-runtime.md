# ADR-006: Kiosk runtime — reuse the Model 4 kiosk platform

**Status:** Proposed · **Date:** 2026-10-31

## Context

KIOSK-1–8 and NFR-3/4/7/12/13 ask for boot-to-exhibit, supervised restart, a three-layer watchdog,
power-cut safety, offline operation, content updates without re-imaging, a reproducible image, and a
museum that runs it without Nick (OPS-*). The museum's Model 4 kiosk (a separate project)
has built exactly this platform (its ARCHITECTURE §3, §7, §9; `deploy/`), and the museum's staff
will meet both exhibits.

## Decision

Port it, and change only what sound requires:

- Debian 13 x86-64, X11, no desktop; BIOS restore-on-AC → `agetty` autologin → `startx` →
  `.xinitrc` loop → `kiosk.sh` → `chromium --kiosk` (verbatim).
- systemd units `seastones-content` (oneshot), `seastones-web` (static server + counters +
  heartbeat), **`seastones-rigd`** (`Restart=always`, `RestartSec=1`, `WatchdogSec=5`,
  `LimitRTPRIO`), watchdog and nightly-reset timers, `RuntimeWatchdogSec=60`.
- overlayfs read-only root; `/data` (`SXDATA`) for logs, counters, staff settings, saved presets;
  content stick `SEASTONES` with baked fallback; nftables default-deny; radios off in prod.
- **New for sound:** ALSA `hw:` direct (no sound server), CPU governor `performance`, hardware gain
  caps sealed at install, amplifier with turn-on/off mute.
- **Update path:** software by golden image on a spare disk (swap; the old disk becomes the
  fallback); content by stick swap + power cycle. No network path.

## Consequences

- Positive: proven pieces, one runbook vocabulary across exhibits, and a fault table extended rather
  than rewritten (ARCHITECTURE §8).
- Negative: inherits the Model 4 platform's unverified-on-box items (its `deploy/README.md`
  UNVERIFIED table). Those must be verified here too, not assumed.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **Chromium kiosk (Model 4 platform)** | proven, minimal | X11 (Wayland rotation story avoided on purpose, M4-ARCH §4.2) |
| Electron | native APIs in one app | `rigd` already provides them; second update/attack surface |
| Tauri | small | WebKitGTK on Linux: weak AudioWorklet history, no Web MIDI |
| Wayland kiosk compositor (cage) | modern | touch/rotation mapping differs from the proven path |

## Risk note

The Model 4 kiosk has **not yet run on its own target box**. Treat its runtime as a strong starting
point, not a verified one: this exhibit's acceptance script must exercise every inherited claim on
the Seastones station (boot timing, watchdogs, read-only root, loopback-only listeners).
