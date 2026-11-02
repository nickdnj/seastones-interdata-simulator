#!/bin/bash
# The engine on Linux with the station's compilers (Debian 13: gcc 14, clang 19), warning-clean
# (-Werror is in OUR_CFLAGS), make test-engine, and golden hashes against the pins. Run from the
# repo root with docker (add --platform linux/amd64 for x86-64; SX_ARCH names the build tree):
#   docker run --rm -v "$PWD":/work debian:trixie bash /work/tools/compilers/linux-check.sh
#   docker run --rm --platform linux/amd64 -e SX_ARCH=-amd64 -v "$PWD":/work debian:trixie \
#     bash /work/tools/compilers/linux-check.sh
# Needs `make program` and build/presets/ (tools/presets.py) on the host first.
set -u
cd /work || exit 1
export DEBIAN_FRONTEND=noninteractive
if ! command -v gcc >/dev/null || ! command -v clang >/dev/null; then
  apt-get update -qq >/dev/null && apt-get install -y -qq gcc clang make patch python3 python3-numpy >/dev/null 2>&1
fi
gcc --version | head -1
clang --version | head -1
rc=0
for cc in gcc clang; do
  b=build/linux-$cc${SX_ARCH:-}
  echo "=== $cc"
  if make -s engine CC=$cc BUILD="$b" > /tmp/$cc.log 2>&1 && make -s test-engine CC=$cc BUILD="$b" >> /tmp/$cc.log 2>&1; then
    grep -E "warning|checks" /tmp/$cc.log
    echo "$cc: build and test-engine OK"
  else
    grep -E "error|warning|CHECK" /tmp/$cc.log | head -40
    echo "$cc: FAILED"
    rc=1
  fi
done
cd /work || exit 1
for cc in gcc clang; do
  r="build/linux-$cc${SX_ARCH:-}/engine/sx-render"
  echo "$cc phrase $("$r" --image build/program/rig.img.json --script tests/engine/scripts/mono-phrase.txt --seconds 2.2 | cut -d' ' -f2)"
  echo "$cc bell   $("$r" --image build/program/rig.img.json --graph build/presets/bell.graph --script tests/engine/scripts/presets/bell.txt --seconds 9 | cut -d' ' -f2)"
done
echo "pinned phrase $(grep -o '"sha256": "[0-9a-f]*' tests/engine/golden/render-poly-phrase.json | cut -d'"' -f4)"
echo "pinned bell   $(grep -o '"sha256": "[0-9a-f]*' tests/engine/golden/preset-bell.json | cut -d'"' -f4)"
exit $rc
