#!/usr/bin/env bash
#
# Build stock `id16`, the S-3 conformance oracle (ADR-001), from deploy/simh.pin.
# Ported from the Model 4 kiosk's scripts/build-simh.sh.
#
#   scripts/build-oracle.sh               build (or reuse) the cached oracle, print its path
#   scripts/build-oracle.sh --print-pin   read deploy/simh.pin and stop
#   scripts/build-oracle.sh --source      make sure the pinned source is present, print its path
#
# Cache layout (outside the repo; CI caches it on the hash of the pin):
#
#   $SX_CACHE/open-simh/                  a clone of the repo, checked out at the pin
#   $SX_CACHE/oracle/<commit>/src/        a clean export of the pinned tree (git archive)
#   $SX_CACHE/oracle/<commit>/bin/id16    the built oracle, with .pinned-at beside it
#
# SX_CACHE defaults to ~/.cache/seastones. Network is touched only when the clone is
# missing or lacks the pinned commit (DEV-PLAN 10.1: one git clone).
#
# The last line printed is the absolute path of the requested artefact, so:
#   export SX_ORACLE="$(scripts/build-oracle.sh | tail -1)"

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pin_file="$here/deploy/simh.pin"
cache="${SX_CACHE:-$HOME/.cache/seastones}"

pin() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$pin_file" | head -1 \
    | sed 's/[[:space:]]*$//'
}

[ -f "$pin_file" ] || { echo "no $pin_file: nothing to pin to" >&2; exit 1; }
REPO="$(pin repo)"
COMMIT="$(pin commit)"
TARGET="$(pin target)"
FLAGS="$(pin flags)"
BANNER="$(pin banner)"
[ -n "$COMMIT" ] && [ -n "$TARGET" ] || { echo "$pin_file names no commit/target" >&2; exit 1; }

if [ "${1:-}" = "--print-pin" ]; then
  printf 'repo=%s\ncommit=%s\ntarget=%s\nflags=%s\nbanner=%s\n' \
    "$REPO" "$COMMIT" "$TARGET" "$FLAGS" "$BANNER"
  exit 0
fi

# --- the pinned source ------------------------------------------------------
clone="$cache/open-simh"
if ! git -C "$clone" cat-file -e "$COMMIT^{commit}" 2>/dev/null; then
  echo "fetching $REPO at $COMMIT into $clone" >&2
  mkdir -p "$cache"
  if [ ! -d "$clone/.git" ]; then
    rm -rf "$clone"
    git clone -q "$REPO" "$clone"
  else
    git -C "$clone" fetch -q origin "$COMMIT"
  fi
fi
git -C "$clone" cat-file -e "$COMMIT^{commit}" \
  || { echo "$clone does not contain $COMMIT: refusing to build" >&2; exit 1; }

if [ "${1:-}" = "--source" ]; then
  echo "$clone"
  exit 0
fi

# --seastones: id16-seastones (VS-06), the pinned tag plus src/engine/devices/id_seastones.c
# (copied in byte for byte) and src/oracle/0001-id16-seastones.patch. Cached on the hash
# of those two files, so a device change rebuilds it.
extra=""
if [ "${1:-}" = "--seastones" ]; then
  dev="$here/src/engine/devices/id_seastones.c"
  opatch="$here/src/oracle/0001-id16-seastones.patch"
  key="$(cat "$dev" "$opatch" | shasum -a 256 | cut -c1-16)"
  extra="seastones-$key"
fi

out="$cache/oracle/$COMMIT${extra:+/$extra}"
bin="$out/bin/$TARGET"
stamp="$out/bin/.pinned-at"

if [ -x "$bin" ] && [ "$(cat "$stamp" 2>/dev/null || true)" = "$COMMIT" ]; then
  echo "stock $TARGET already built at $COMMIT (cached)" >&2
  echo "$bin"
  exit 0
fi

# A clean export of exactly the pinned tree: the clone's work tree may be on
# another commit, and building in it would leave BIN/ behind in the cache clone.
rm -rf "$out/src"
mkdir -p "$out/src" "$out/bin"
git -C "$clone" archive "$COMMIT" | tar -x -C "$out/src"
if [ -n "$extra" ]; then
  cp "$dev" "$out/src/Interdata/id_seastones.c"
  patch -d "$out/src" -p1 -s --no-backup-if-mismatch -i "$opatch"
fi

echo "building $TARGET ($FLAGS)" >&2
# shellcheck disable=SC2086
make -C "$out/src" $FLAGS "$TARGET" >"$out/build.log" 2>&1 \
  || { tail -30 "$out/build.log" >&2; echo "oracle build failed: $out/build.log" >&2; exit 1; }

built="$out/src/BIN/$TARGET"
[ -x "$built" ] || { echo "make finished but $built is not there" >&2; exit 1; }
cp "$built" "$bin"
printf '%s\n' "$COMMIT" > "$stamp"

got="$("$bin" </dev/null 2>&1 | awk 'NF {print; exit}')"
echo "built: $got" >&2
if [ -n "$BANNER" ] && [ "$got" != "$BANNER" ]; then
  echo "banner mismatch: expected '$BANNER'" >&2
  exit 1
fi
echo "$bin"
