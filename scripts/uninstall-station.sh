#!/usr/bin/env bash
# uninstall-station.sh: take the station software off a machine (the reverse of
# install-station.sh). KP-11.
#
#   scripts/uninstall-station.sh                     DRY RUN (the default): say what would go
#   sudo scripts/uninstall-station.sh --apply        do it, on this machine
#   scripts/uninstall-station.sh --apply --root DIR  the same for a staged install under DIR
#
# Options: --platform linux|macos  --dest DIR  --data DIR  --kiosk-user NAME
#          --purge-data   also delete <data> (staff settings, saved presets, logs, counters,
#                         the PIN). Off by default: the museum's state outlives a reinstall.
#
# It removes exactly what the install recorded in <dest>/.install-manifest (application files,
# units or launch agents, the kiosk user's .xinitrc and .bash_profile, the logrotate, journald,
# watchdog and firewall files), stops and disables the services first, and removes the
# firewall include line. It never deletes a user account (it prints how). Idempotent: on a
# machine with nothing installed it reports 0 changes.
set -euo pipefail

PROG=uninstall-station
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091  # sourced by path; linted on its own
. "$REPO/scripts/station-lib.sh"

PLATFORM=""
DEST=""
DATA=""
KIOSK_USER=""
PURGE=0

usage() { sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --dry-run) APPLY=0; shift ;;
    --root) ROOT="${2:?--root needs a directory}"; shift 2 ;;
    --platform) PLATFORM="${2:-}"; shift 2 ;;
    --dest) DEST="${2:-}"; shift 2 ;;
    --data) DATA="${2:-}"; shift 2 ;;
    --kiosk-user) KIOSK_USER="${2:-}"; shift 2 ;;
    --purge-data) PURGE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "$PROG: unknown argument $1" >&2; usage >&2; exit 2 ;;
  esac
done
if [ -z "$PLATFORM" ]; then
  case "$(uname -s)" in Darwin) PLATFORM=macos ;; Linux) PLATFORM=linux ;; *) die "unknown platform" ;; esac
fi
case "$PLATFORM" in
  linux) DEST="${DEST:-/opt/seastones}"; DATA="${DATA:-/data}"; KIOSK_USER="${KIOSK_USER:-kiosk}" ;;
  macos) DEST="${DEST:-/opt/seastones}"; DATA="${DATA:-/Users/Shared/Seastones/data}"
         KIOSK_USER="${KIOSK_USER:-${SUDO_USER:-$(id -un)}}" ;;
  *) die "--platform must be linux or macos" ;;
esac
if [ -n "$ROOT" ] && [ -d "$ROOT" ]; then ROOT="$(cd "$ROOT" && pwd)"; fi
if live && [ "$(id -u)" -ne 0 ]; then
  die "--apply changes this machine and needs root (sudo), or use --root DIR"
fi

say "removing the station from $DEST${ROOT:+ (staged under $ROOT)}"
[ "$APPLY" = 1 ] || note "dry run: nothing will be changed"

say "stopping the services (the station goes silent first: rigd ramps to silence on SIGTERM)"
if [ "$PLATFORM" = linux ]; then
  do_run systemctl disable --now seastones-station.target seastones-watchdog.timer \
    seastones-reset.timer seastones-playable.service seastones-web.service seastones-rigd.service
else
  if live; then
    uid="$(id -u "$KIOSK_USER" 2>/dev/null || echo "")"
    for j in kiosk watchdog reset playable web rigd; do
      [ -n "$uid" ] && do_run launchctl bootout "gui/$uid/local.seastones.$j"
    done
  else
    note "would stop the local.seastones.* launch agents (launchctl bootout)"
  fi
fi

say "files"
MANIFEST="$DEST/.install-manifest"
if [ -f "$(R "$MANIFEST")" ]; then
  while IFS= read -r f; do
    [ -n "$f" ] && do_remove "$f"
  done < "$(R "$MANIFEST")"
else
  note "no install manifest at $MANIFEST: nothing recorded to remove"
fi
if [ "$PLATFORM" = linux ]; then
  undo_line /etc/nftables.conf 'include "/etc/nftables.d/seastones.nft"'
  do_run systemctl daemon-reload
fi
do_rmdir_empty "$DEST"
for d in /etc/systemd/system/getty@tty1.service.d /etc/systemd/journald.conf.d \
         /etc/systemd/system.conf.d /etc/systemd/logind.conf.d /etc/nftables.d; do
  do_rmdir_empty "$d"
done

if [ "$PURGE" = 1 ]; then
  say "the station's state ($DATA): --purge-data"
  if [ -d "$(R "$DATA")" ]; then
    changed "delete everything under" "$DATA"
    [ "$APPLY" = 1 ] && rm -rf "$(R "$DATA")"
  fi
else
  note "kept: $DATA (staff settings, saved presets, logs, counters, the PIN); --purge-data deletes it"
fi
if [ "$PLATFORM" = linux ]; then
  note "user accounts kept. To remove them: sudo userdel -r $KIOSK_USER; sudo userdel seastones"
fi
finish uninstall
