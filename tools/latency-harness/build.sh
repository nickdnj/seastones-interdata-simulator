#!/bin/sh
# Build sxlat (SP-S1A). macOS: CoreAudio backend. Linux: ALSA backend (needs libasound2-dev).
# Output goes to build/ (git-ignored). Usage: tools/latency-harness/build.sh [outdir]
# CC and CFLAGS are word-split on purpose (flag lists).
# shellcheck disable=SC2086
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-"$here/../../build/latency-harness"}
mkdir -p "$out"
CC=${CC:-cc}
CFLAGS="-std=c17 -O2 -Wall -Wextra -Wpedantic -Werror"
case "$(uname -s)" in
Darwin)
  $CC $CFLAGS -o "$out/sxlat" "$here/sxlat.c" "$here/backend_coreaudio.c" \
    -framework AudioToolbox -framework CoreAudio -framework CoreFoundation -lm -lpthread ;;
Linux)
  $CC $CFLAGS -o "$out/sxlat" "$here/sxlat.c" "$here/backend_alsa.c" -lasound -lm -lpthread ;;
*) echo "unsupported OS" >&2; exit 1 ;;
esac
echo "$out/sxlat"
