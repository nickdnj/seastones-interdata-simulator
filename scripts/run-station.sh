#!/usr/bin/env bash
# run-station.sh: the live station on this machine, one command (VS-14; `make run`).
#
# Starts rigd (the emulated 7/16 and its synthesizer, on this machine's default audio output,
# with every MIDI keyboard connected) and, when the page is present, the page server. It opens
# nothing: it prints the URL. Ctrl-C stops both, and only them.
#
#   scripts/run-station.sh [rigd options...]       e.g. --device "MacBook Air Speakers"
#
#   SX_WEB_DIR   the page (default src/web; it comes with the UI lane's branch)
#   SX_CONTENT   the content set the page shows (default: content/ beside SX_WEB_DIR's tree)
#   SX_PORT_WS   rigd's port (7690)       SX_PORT_HTTP  the page's port (8080)
#
# Play: a USB MIDI keyboard (C3 = MIDI 48 is the lowest key; 37 keys), or the page's on-screen
# keys, or the QWERTY keys on the page with ?dev=1. Every sound comes from the emulated
# program writing the D/A converter: nothing here plays anything by itself.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
py=${PYTHON:-python3}
ws_port=${SX_PORT_WS:-7690}
http_port=${SX_PORT_HTTP:-8080}
web=${SX_WEB_DIR:-$root/src/web}
if [ -z "${SX_CONTENT:-}" ] && [ -d "$web/../../content" ]; then
  content=$(cd "$web/../../content" && pwd)
else
  content=${SX_CONTENT:-$root/content}
fi

case "$(uname -s)" in Darwin) lib=build/host/libsxhost.dylib ;; *) lib=build/host/libsxhost.so ;; esac
if [ ! -f "$lib" ] || [ ! -f build/program/rig.img.json ]; then
  echo "run-station: building the host and the program (make host program)"
  make --no-print-directory host program >/dev/null
fi

pids=()
# (bash 3.2 compatible: macOS's /bin/bash has no `wait -n`, and an empty array is unbound)
stop() {
  trap - INT TERM EXIT
  for p in ${pids[@]+"${pids[@]}"}; do kill "$p" 2>/dev/null || true; done
  for p in ${pids[@]+"${pids[@]}"}; do wait "$p" 2>/dev/null || true; done
}
trap stop INT TERM EXIT

rigd_args=(--port "$ws_port" --content "$content")
page=0
if [ -f "$web/index.html" ] && [ -f "$web/serve.py" ]; then
  page=1
else
  # With no page, the 10 s no-screen mute (ARCHITECTURE 4.5) would silence a MIDI-only
  # session; a developer may play without the page, so it is off here and only here.
  rigd_args+=(--no-ui-mute)
fi

PYTHONPATH="$root/src" "$py" -m rigd "${rigd_args[@]}" "$@" &
pids+=($!)

if [ "$page" = 1 ]; then
  "$py" "$web/serve.py" --port "$http_port" --content "$content" --program "$root/build/program" \
    --index-dir "$root/build/content" --run "$root/build/run" &
  pids+=($!)
fi

sleep 1
echo
echo "  The 1974 Seastones Rig is running on this machine."
echo "    rigd (engine + sound):  ws://127.0.0.1:$ws_port"
if [ "$page" = 1 ]; then
  echo "    the station page:       http://127.0.0.1:$http_port/"
  echo "    with QWERTY keys:       http://127.0.0.1:$http_port/?dev=1"
else
  echo "    the page is not in this tree ($web): play a MIDI keyboard,"
  echo "    or set SX_WEB_DIR to a checkout's src/web (the UI lane's branch)."
fi
echo "  Press Ctrl-C to stop."
echo
# until either process ends (rigd exiting is a fault to see, not to hide), then stop both
while :; do
  for p in "${pids[@]}"; do
    kill -0 "$p" 2>/dev/null || {
      echo "run-station: process $p ended; stopping"
      exit 1
    }
  done
  sleep 1
done
