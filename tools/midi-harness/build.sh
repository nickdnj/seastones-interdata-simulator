#!/bin/sh
# Build sxmidi (SP-S2A). macOS: CoreMIDI backend. Linux: ALSA sequencer (needs libasound2-dev).
# Output goes to build/ (git-ignored). Usage: tools/midi-harness/build.sh [outdir]
# CC and CFLAGS are word-split on purpose (flag lists).
# shellcheck disable=SC2086
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-"$here/../../build/midi-harness"}
mkdir -p "$out"
CC=${CC:-cc}
CFLAGS="-std=c17 -O2 -Wall -Wextra -Werror"
case "$(uname -s)" in
Darwin)
  # Blocks (CoreMIDI's block API) are a clang extension, so no -Wpedantic here.
  $CC $CFLAGS -fblocks -o "$out/sxmidi" "$here/sxmidi_common.c" "$here/sxmidi_coremidi.c" \
    -framework CoreMIDI -framework CoreFoundation ;;
Linux)
  $CC $CFLAGS -Wpedantic -o "$out/sxmidi" "$here/sxmidi_common.c" "$here/sxmidi_alsa.c" -lasound -lpthread ;;
*) echo "unsupported OS" >&2; exit 1 ;;
esac
echo "$out/sxmidi"
