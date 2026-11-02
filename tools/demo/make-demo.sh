#!/usr/bin/env bash
# make-demo.sh: the narrated demo video of the rig (for Nick; no media is ever committed).
#
#   tools/demo/make-demo.sh            -> build/demo/seastones-rig-demo.mp4
#
# A real rigd on the null audio device (paced in real time, nothing audible) captures its
# output; the page is served on a free port; Playwright drives the real page (video);
# macOS `say` narrates; tools/demo/mix.py aligns, ducks, normalises and muxes. Needs macOS,
# ffmpeg, Node with tests/web's Playwright, numpy. Kills only the processes it started.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/build/demo"
WORK="$OUT/work"
mkdir -p "$WORK"
rm -f "$WORK/rig.f32" "$WORK/video.webm" "$WORK"/*.webm "$WORK/timeline.json" "$WORK/mix.f32"

cd "$ROOT"
make --no-print-directory program engine host >/dev/null
[ -d tests/web/node_modules/@playwright/test ] || (cd tests/web && npm ci --no-audit --no-fund)

free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'; }
RIG_PORT="$(free_port)"
WEB_PORT="$(free_port)"
DATA="$(mktemp -d)"
INDEX="$(mktemp -d)"
RUN="$(mktemp -d)"
PIDS=()
cleanup() {
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$DATA" "$INDEX" "$RUN"
}
trap cleanup EXIT

echo "narration"
node tools/demo/narrate.mjs "$WORK"

echo "rigd on $RIG_PORT (null audio, capture), page on $WEB_PORT"
PYTHONPATH="$ROOT/src" PYTHONUNBUFFERED=1 python3 -m rigd --port "$RIG_PORT" --audio null --rate 48000 --no-midi \
  --content "$ROOT/content" --data "$DATA" --capture "$WORK/rig.f32" >"$WORK/rigd.log" 2>&1 &
PIDS+=($!)
python3 src/web/serve.py --port "$WEB_PORT" --content "$ROOT/content" --index-dir "$INDEX" \
  --program "$ROOT/build/program" --run "$RUN" >"$WORK/serve.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 100); do
  grep -q "listening on" "$WORK/rigd.log" 2>/dev/null && grep -q "serve.py: http" "$WORK/serve.log" 2>/dev/null && break
  sleep 0.2
done
grep -q "listening on" "$WORK/rigd.log" || { echo "rigd did not start"; cat "$WORK/rigd.log"; exit 1; }

echo "driving the page"
node tools/demo/drive.mjs "$WORK" "http://127.0.0.1:$WEB_PORT" "ws://127.0.0.1:$RIG_PORT"

kill "${PIDS[0]}" 2>/dev/null || true # stop rigd so the capture is flushed
sleep 1

echo "mixing"
python3 tools/demo/mix.py "$WORK" "$WORK/rig.f32" "$OUT/seastones-rig-demo.mp4"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/seastones-rig-demo.mp4"
