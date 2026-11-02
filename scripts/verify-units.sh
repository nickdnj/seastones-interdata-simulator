#!/usr/bin/env bash
# verify-units.sh: `systemd-analyze verify` on every unit in deploy/systemd/ in a Debian 13 container
# (VS-17 AC 2). systemd-analyze is Linux-only, so the Mac runs it through Docker; on a Linux
# CI runner with systemd it runs directly (SX_VERIFY_LOCAL=1).
#
#   scripts/verify-units.sh
#
# Any warning counts as a failure: systemd only warns about a misplaced setting and then
# ignores it, which is exactly how the Model 4 kiosk's restart limit went missing.
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
image=${SX_LINUX_IMAGE:-debian:trixie}

run_verify() {
  # the paths and accounts the units name, as an installed station would have them
  id seastones >/dev/null 2>&1 || useradd --system --no-create-home --user-group --groups audio seastones
  mkdir -p /opt/seastones/deploy /data/log /etc/systemd/system
  # the scripts the units run must exist and be executable for verify to pass
  for f in kiosk.sh restart-browser.sh reset.sh supervise.py watchdog.py playable.py; do
    install -m 0755 "$1/deploy/$f" /opt/seastones/deploy/
  done
  cp "$1"/deploy/systemd/seastones-* /etc/systemd/system/
  out=$(cd /etc/systemd/system && systemd-analyze verify seastones-*.service seastones-*.timer \
          seastones-*.target 2>&1 || true)
  # systemd-analyze names units it cannot find among the dependencies; ours are not all here
  out=$(printf '%s\n' "$out" | grep -v "seastones-content.service" || true)
  if [ -n "$out" ]; then
    printf '%s\n' "$out"
    echo "verify-units: FAIL"
    return 1
  fi
  echo "verify-units: PASS ($(systemd-analyze --version | head -1))"
}

if [ "${SX_VERIFY_LOCAL:-0}" = 1 ]; then
  run_verify "$here"
  exit
fi
if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
  echo "verify-units: SKIPPED, no Docker and not asked to run locally (UNVERIFIED)"
  exit 0
fi
docker run --rm -v "$here":/src:ro "$image" bash -euo pipefail -c "
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null
  apt-get install -y -qq systemd python3 >/dev/null
  $(declare -f run_verify)
  run_verify /src
"
