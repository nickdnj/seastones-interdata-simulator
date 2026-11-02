# deploy/

Station deployment (ADR-006, KP-11), ported from the Model 4 kiosk's `deploy/`. Installed by
`scripts/install-station.sh` (a dry run unless `--apply`; idempotent) and removed by
`scripts/uninstall-station.sh`. The docent's page is `docs/OPERATIONS.md`.

| Path | What |
|---|---|
| `simh.pin` | the one open-simh build this project is tested against (`scripts/build-oracle.sh`) |
| `station.conf` | tunables (watchdog times, nightly restart, log rotation, boot budget); no secrets |
| `systemd/` | Linux: `seastones-station.target` = `seastones-rigd` (Restart=always, WatchdogSec=5 from rigd's heartbeat) + `seastones-web` + page watchdog and nightly-reset timers + `seastones-playable` (boot-to-playable record) |
| `launchd/` | macOS: the same as LaunchAgent templates, each process under `supervise.py` |
| `supervise.py` | restart, rigd-heartbeat watchdog, log rotation and orphan reaping where systemd is absent |
| `kiosk.sh` | opens the page in a Chromium kiosk window (Linux: from the `.xinitrc` loop) |
| `watchdog.py`, `restart-browser.sh` | page-heartbeat watchdog (monotonic clock) and the browser restart |
| `reset.sh` | the nightly clean restart |
| `playable.py` | is the station playable? (boot-to-playable probe, kiosk.sh's page check) |
| `boot-wait.html` | the dark holding page shown instead of Chromium's error page |
| `logrotate/`, `nftables/` | Linux log rotation; default-deny firewall (input, forward and output) |

Not here yet (KP-11/KP-12): the overlayfs read-only root, the golden-image build, the box's
acceptance script, microphone disabled at the OS level.
