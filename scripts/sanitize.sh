#!/usr/bin/env bash
#
# VS-01 / CNF-12 short form: the engine unit tests and a short lockstep, built with
# AddressSanitizer and UndefinedBehaviorSanitizer in their own tree (build/san).
#
# ASan needs a working runtime. Apple clang 16 on macOS 26 aborts in ASan's own init
# (even on an empty program), so this script probes first: it tries $SX_SAN_CC, then cc,
# then Homebrew LLVM. If no compiler gives a working ASan it runs UBSan alone and says,
# loudly, that ASan is UNVERIFIED on this machine (Linux CI runs both).

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build="${BUILD:-build}/san"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

printf '#include <stdlib.h>\nint main(void){char *p = malloc(8); p[0] = 1; free(p); return 0;}\n' \
  > "$tmp/probe.c"

works() { # $1 compiler, $2 sanitizer list
  "$1" -fsanitize="$2" "$tmp/probe.c" -o "$tmp/probe" 2>/dev/null && "$tmp/probe" 2>/dev/null
}

cc_used=""
list=""
for c in ${SX_SAN_CC:-} clang cc /opt/homebrew/opt/llvm/bin/clang; do
  command -v "$c" >/dev/null 2>&1 || continue
  if works "$c" address,undefined; then cc_used="$c"; list="address,undefined"; break; fi
done
if [ -z "$cc_used" ]; then
  cc_used="cc"
  if works cc undefined; then
    list="undefined"
    echo "sanitize: ASan UNAVAILABLE on this toolchain ($(cc --version | head -1)):" \
         "running UBSan only. ASan is UNVERIFIED here; verify with 'make sanitize' on Linux." >&2
  else
    echo "sanitize: no working sanitizer runtime on this machine: UNVERIFIED" >&2
    exit 0
  fi
fi
# The one upstream UBSan site (tests/engine/ubsan-vendored.ignorelist) is ignored for the
# vendored objects only, by function, where the compiler supports ignore lists (clang);
# otherwise (gcc) only that check is turned off for the vendored objects, and we say so.
ignorelist="$here/tests/engine/ubsan-vendored.ignorelist"
if "$cc_used" -fsanitize=undefined -fsanitize-ignorelist="$ignorelist" "$tmp/probe.c" \
     -o "$tmp/probe" 2>/dev/null; then
  vendor_extra="-fsanitize-ignorelist=$ignorelist"
else
  vendor_extra="-fno-sanitize=shift-base"
  echo "sanitize: $cc_used has no ignore lists: shift-base off for vendored SIMH objects only" >&2
fi
echo "sanitize: $cc_used -fsanitize=$list (vendored: $vendor_extra)"

rm -rf "${here:?}/$build" # objects from another compiler must not be reused
make -C "$here" --no-print-directory engine \
  BUILD="$build" CC="$cc_used" SX_SAN=1 SAN_LIST="$list" SAN_VENDOR_EXTRA="$vendor_extra" >/dev/null
make -C "$here" --no-print-directory test-engine \
  BUILD="$build" CC="$cc_used" SX_SAN=1 SAN_LIST="$list" SAN_VENDOR_EXTRA="$vendor_extra"

SX_ENGINE="$build/engine/sx-cpu" python3 "$here/tests/conformance/lockstep.py" \
  --streams 2 --instructions 200000 --fine 200 --jobs 2
echo "sanitize: clean under -fsanitize=$list"
