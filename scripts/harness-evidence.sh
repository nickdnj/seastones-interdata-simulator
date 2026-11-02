#!/bin/sh
# Lane C and D acceptance evidence (SP-S1A, SP-S2A, SP-S8A; SP-S4B, SP-S5), until SP-01/SP-03 land a Makefile and
# `make ci`; then these steps become make targets and this script can go.
#
# Builds the harnesses into build/ (git-ignored), runs the unit tests and the Mac smoke runs, and
# writes the raw JSON records to docs/qa/results/M1/. The audio smoke run is SILENT (zeros), so
# nothing plays through the machine's speakers. Re-running overwrites the committed JSON records
# with fresh measurements; the .md records quote the committed run.
#
#   scripts/harness-evidence.sh            all steps
#   SX_PLAYWRIGHT_DIR=<node_modules/playwright> scripts/harness-evidence.sh
#                                          when tests/web has no `npm ci` install
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
out="$root/docs/qa/results/M1"
mkdir -p "$out"
fail=0
step() { printf '\n== %s\n' "$1"; }

step "S-1a: build sxlat"
"$root/tools/latency-harness/build.sh" >/dev/null || fail=1
step "S-1a: silent smoke run, 128-frame periods, 10 s"
if "$root/build/latency-harness/sxlat" --mode silent --period 128 --seconds 10 >"$out/S1A-smoke-128.json"; then
  cat "$out/S1A-smoke-128.json"
else fail=1; fi
step "S-1a: silent smoke run, 64-frame periods, 10 s"
"$root/build/latency-harness/sxlat" --mode silent --period 64 --seconds 10 >"$out/S1A-smoke-64.json" || fail=1

step "S-1a / S-2a: analysis unit tests"
python3 -m pytest -q -p no:cacheprovider "$root/tests/latency" || fail=1

step "S-2a: build sxmidi"
"$root/tools/midi-harness/build.sh" >/dev/null || fail=1
step "S-2a: self-test (virtual source, 1000 events, simulated unplug)"
if "$root/build/midi-harness/sxmidi" selftest --events 1000 --spacing-ms 2 --seed 1974 >"$out/S2A-selftest.json"; then
  cat "$out/S2A-selftest.json"
else cat "$out/S2A-selftest.json"; fail=1; fi

step "S-8a: fixture isolation tests"
node --test "$root/tests/web/fixture-isolation.test.mjs" || fail=1
node "$root/tests/web/check-fixture-isolation.mjs" || fail=1
step "S-8a: headless fps run, 1920x1080, 8 voices, 20 cables, 10 s"
if node "$root/tests/web/s8-render-budget/measure.mjs" --seconds 10 --warmup 2 --min-fps 50 >"$out/S8A-headless.json"; then
  cat "$out/S8A-headless.json"
else fail=1; fi

step "S-4b / S-5: cycle table, cycle-calc and subset file tests"
python3 -m pytest -q -p no:cacheprovider "$root/tests/tools" || fail=1
step "S-4b: scan-loop cases"
python3 "$root/tools/cycles/scan-cases.py" >"$out/S4-scan-cases.json" || fail=1

printf '\n== lane C and D evidence: %s\n' "$([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit $fail
