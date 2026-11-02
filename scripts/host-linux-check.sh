#!/usr/bin/env bash
# host-linux-check.sh: build libsxhost and sxkeys for Linux (ALSA audio and sequencer) inside a
# Debian 13 container, from this checkout mounted read-only (VS-13 AC: "Linux build compiles
# with ALSA headers"). With --test it also loads the library from Python in the container and
# runs the null-device smoke (no sound card exists there).
#
#   scripts/host-linux-check.sh [--test]
#
# Needs Docker and network for the image and packages the first time. The build goes to
# /tmp inside the container; nothing in the checkout is written. This compiles and links the
# ALSA code; running it against real ALSA hardware is S-1b/S-2b on the station (UNVERIFIED here).
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
image=${SX_LINUX_IMAGE:-debian:trixie}
test=0
[ "${1:-}" = "--test" ] && test=1

if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
  echo "host-linux-check: SKIPPED, Docker not available (UNVERIFIED)"
  exit 0
fi

# CC: gcc (Debian's default) or clang. SX_LINUX_CC overrides.
cc=${SX_LINUX_CC:-gcc}

docker run --rm -v "$here":/src:ro -e SX_TEST="$test" -e CC="$cc" "$image" bash -euo pipefail -c '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null
  apt-get install -y -qq gcc clang make patch libasound2-dev python3 python3-cffi python3-numpy \
    python3-websockets >/dev/null
  cp -R /src /tmp/w
  cd /tmp/w
  rm -rf build
  echo "host-linux-check: CC=$CC ($($CC --version | head -1))"
  if ! make --no-print-directory -k host BUILD=/tmp/b CC="$CC" >/tmp/build.log 2>&1; then
    grep -E "error|Error" /tmp/build.log | head -40
    exit 1
  fi
  echo "host-linux-check: built $(ls /tmp/b/host/libsxhost.so /tmp/b/tools/sxkeys | tr "\n" " ")"
  grep -c "midi_alsa\|miniaudio" /tmp/build.log >/dev/null
  if [ "$SX_TEST" = 1 ]; then
    make --no-print-directory program BUILD=/tmp/b >/dev/null
    SX_HOST_LIB=/tmp/b/host/libsxhost.so PYTHONPATH=src python3 - <<EOF
from pathlib import Path
import time
from rigd.rig import Rig, RigConfig, AudioConfig
from rigd import engine as eng
r = Rig(RigConfig(lib=Path("/tmp/b/host/libsxhost.so"), image=Path("/tmp/b/program/rig.img.json"),
                  audio=AudioConfig(backend="null"), midi=False))
r.start()
r.keys_set(eng.KEYS_TOUCH, 1 << 12)
time.sleep(0.5)
s = r.snapshot()
gate = max(s.dac_volts[4:8])  # all-D/A map: voice gates are D/A 4-7, high above 2.5 V
print("host-linux-check: null device frames", s.frames, "voice gate", round(gate, 2), "V")
assert s.frames > 10000 and gate > 2.5
r.close()
EOF
  fi
'
echo "host-linux-check: PASS ($image)"
