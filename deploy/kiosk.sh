#!/usr/bin/env bash
# kiosk.sh: open the exhibit's page in a Chromium kiosk window (ADR-006; ported from the Model 4
# kiosk's deploy/kiosk.sh).
#
# Started by the .xinitrc loop on Linux (agetty autologin -> startx -> .xinitrc -> this) and by
# deploy/supervise.py under launchd on macOS, never by hand. When it exits for any reason the
# loop or the supervisor runs it again a few seconds later; that relaunch is the browser's
# recovery path, and the reason the browser is a foreground `exec` at the end.
#
#   1. wait for OUR page server: not just an open port, the server's own security header,
#      so a different program squatting on :8080 never gets shown (KIOSK-4)
#   2. on Linux: no blanking, no screensaver, no DPMS; touch mapped onto the screen
#   3. clear Chromium's "didn't shut down correctly" flag (a power cut is normal here)
#   4. exec Chromium with the lockdown flags
#
# If the page is not up in 30 s, a dark holding page (deploy/boot-wait.html: no words, no
# network) is shown instead of Chromium's own error page, and this exits when the page answers.
#
#   SX_DEST (/opt/seastones)  SX_DATA (/data)  SX_CONF (<dest>/deploy/station.conf)
#   SX_BROWSER (auto)  SX_PYTHON (python3)  SX_PAGE_WAIT_S (30)
set -euo pipefail

DEST="${SX_DEST:-/opt/seastones}"
DATA="${SX_DATA:-/data}"
CONF="${SX_CONF:-$DEST/deploy/station.conf}"
PY="${SX_PYTHON:-python3}"
KIOSK_URL=http://127.0.0.1:8080/
CHROMIUM_EXTRA=
# shellcheck disable=SC1090,SC1091  # NAME=value lines only
if [ -f "$CONF" ]; then . "$CONF"; fi
URL="${SX_URL:-$KIOSK_URL}"
CHROME_PROFILE="$DATA/chrome"
HOLD_PAGE="$DEST/deploy/boot-wait.html"

log() { printf '%s kiosk: %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*"; }

page_up() {
  "$PY" "$DEST/deploy/playable.py" --check page --http "$URL" --timeout "${1:-0}" >/dev/null 2>&1
}

find_browser() {
  if [ -n "${SX_BROWSER:-}" ]; then echo "$SX_BROWSER"; return; fi
  local c
  for c in chromium chromium-browser google-chrome; do
    if command -v "$c" >/dev/null 2>&1; then command -v "$c"; return; fi
  done
  for c in "/Applications/Chromium.app/Contents/MacOS/Chromium" \
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
    if [ -x "$c" ]; then echo "$c"; return; fi
  done
}

# --- 2. the screen (Linux, X11) ------------------------------------------------------------
if [ "$(uname -s)" = Linux ]; then
  export DISPLAY="${DISPLAY:-:0}"
  xset s off 2>/dev/null || true
  xset s noblank 2>/dev/null || true
  xset -dpms 2>/dev/null || true
  if command -v unclutter >/dev/null 2>&1; then (unclutter -idle 0 -root &) ; fi
  # The display and the digitizer are separate devices; map every touch device onto the
  # connected output each start (Model 4 lesson: an unmapped panel looks like broken hardware).
  if command -v xrandr >/dev/null 2>&1 && command -v xinput >/dev/null 2>&1; then
    out="$(xrandr --query 2>/dev/null | awk '/ connected/{print $1; exit}')"
    if [ -n "$out" ]; then
      for id in $(xinput list --id-only 2>/dev/null); do
        if xinput list-props "$id" 2>/dev/null | grep -q "libinput Calibration Matrix"; then
          xinput --map-to-output "$id" "$out" 2>/dev/null || log "could not map touch device $id"
        fi
      done
    fi
  fi
fi

# --- 3. the stale exit flag ----------------------------------------------------------------
prefs="$CHROME_PROFILE/Default/Preferences"
if [ -f "$prefs" ]; then
  tmp="$prefs.sx-tmp"
  if sed -e 's/"exit_type":"[^"]*"/"exit_type":"Normal"/' \
         -e 's/"exited_cleanly":false/"exited_cleanly":true/' "$prefs" > "$tmp" 2>/dev/null; then
    mv -f "$tmp" "$prefs"
  else
    rm -f "$tmp"
  fi
fi

BROWSER="$(find_browser)"
if [ -z "$BROWSER" ]; then
  log "no Chromium or Chrome found: nothing can be shown (install the chromium package)"
  sleep 30
  exit 1
fi

# shellcheck disable=SC2054  # the commas belong to --disable-features' value
flags=(
  --kiosk --start-fullscreen --user-data-dir="$CHROME_PROFILE"
  --noerrdialogs --disable-infobars --disable-session-crashed-bubble
  --disable-features=TranslateUI,Translate,ChromeWhatsNewUI,InfiniteSessionRestore
  --disable-component-update --disable-background-networking --disable-sync
  --check-for-update-interval=31536000 --no-first-run --no-default-browser-check
  --password-store=basic --touch-events=enabled --disable-pinch
  --overscroll-history-navigation=0 --hide-scrollbars --disable-translate
  --disable-notifications --deny-permission-prompts
)

# --- 1 and 4 -------------------------------------------------------------------------------
if page_up "${SX_PAGE_WAIT_S:-30}"; then
  log "page is up at $URL"
  # shellcheck disable=SC2086  # CHROMIUM_EXTRA is a list of flags by design
  exec "$BROWSER" "${flags[@]}" ${CHROMIUM_EXTRA:-} "$URL"
fi

log "the page did not answer in ${SX_PAGE_WAIT_S:-30} s: showing the dark holding page"
"$BROWSER" "${flags[@]}" "file://$HOLD_PAGE" &
hold=$!
while ! page_up 0; do
  kill -0 "$hold" 2>/dev/null || break
  sleep 5
done
log "page came up: restarting into it"
kill "$hold" 2>/dev/null || true
wait "$hold" 2>/dev/null || true
exit 0
