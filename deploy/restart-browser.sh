#!/usr/bin/env bash
# restart-browser.sh: take the kiosk browser down; the .xinitrc loop (Linux) or deploy/supervise.py
# (macOS) brings it back in about 3 s. Used by the page watchdog and the nightly restart.
# Ported from the Model 4 kiosk.
#
# Only the kiosk's own browser is matched: the process whose command line carries our
# --user-data-dir. A bare `pkill chromium` would also close a browser somebody is reading the
# runbook in.
#
#   SX_DATA (/data)  SX_BROWSER_PATTERN (--user-data-dir=<data>/chrome)  SX_BROWSER_GRACE_S (5)
set -euo pipefail

DATA="${SX_DATA:-/data}"
GRACE="${SX_BROWSER_GRACE_S:-5}"
PATTERN="${SX_BROWSER_PATTERN:---user-data-dir=$DATA/chrome}"

log() { printf '%s restart-browser: %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*"; }

if ! pgrep -f -- "$PATTERN" >/dev/null 2>&1; then
  log "no kiosk browser running ($PATTERN); the loop starts one"
  exit 0
fi
log "asking the kiosk browser to exit ($PATTERN)"
pkill -f -- "$PATTERN" || true
for _ in $(seq 1 "$GRACE"); do
  if ! pgrep -f -- "$PATTERN" >/dev/null 2>&1; then
    log "browser exited; the loop restarts it"
    exit 0
  fi
  sleep 1
done
log "browser did not exit in ${GRACE} s: SIGKILL"
pkill -9 -f -- "$PATTERN" || true
exit 0
