#!/usr/bin/env bash
# reset.sh: the nightly clean restart (KIOSK-3, SYS-05; ported from the Model 4 kiosk's
# model4-reset.service). Not a reboot: rigd starts from cold (a fresh engine, the default patch,
# staff settings kept in <data>/staff.conf), then the browser is taken down so its loop opens a
# fresh page. The station is silent in between and playable again within about 10 s.
#
# Linux: run by seastones-reset.timer (03:30 with RandomizedDelaySec; SX_RESET_NO_DELAY=1).
# macOS: run by the local.seastones.reset launchd job at 03:30; it adds its own random delay.
#
#   SX_DEST (/opt/seastones)  SX_DATA (/data)  SX_CONF  SX_RESET_NO_DELAY  SX_DRY_RUN=1 (print)
set -euo pipefail

DEST="${SX_DEST:-/opt/seastones}"
DATA="${SX_DATA:-/data}"
CONF="${SX_CONF:-$DEST/deploy/station.conf}"
RESET_RANDOM_DELAY_S=300
# shellcheck disable=SC1090,SC1091  # NAME=value lines only
if [ -f "$CONF" ]; then . "$CONF"; fi

log() { printf '%s reset: %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*"; }
run() {
  if [ "${SX_DRY_RUN:-0}" = 1 ]; then echo "would run: $*"; else "$@"; fi
}

if [ "${SX_RESET_NO_DELAY:-0}" != 1 ] && [ "${RESET_RANDOM_DELAY_S:-0}" -gt 0 ]; then
  delay=$((RANDOM % RESET_RANDOM_DELAY_S))
  log "waiting ${delay} s (spread, so a hall of exhibits does not restart at once)"
  run sleep "$delay"
fi

log "nightly restart: rigd, then the browser"
case "$(uname -s)" in
  Linux) run systemctl restart seastones-rigd.service ;;
  Darwin) run launchctl kickstart -k "gui/$(id -u)/local.seastones.rigd" ;;
  *) log "unknown platform $(uname -s)"; exit 1 ;;
esac
SX_DATA="$DATA" run "$DEST/deploy/restart-browser.sh"
log "done"
