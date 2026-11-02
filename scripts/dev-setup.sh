#!/usr/bin/env bash
#
# Developer setup (SP-01, SP-02).
#
#   scripts/dev-setup.sh            check the toolchain, install the pre-commit hook
#   scripts/dev-setup.sh --check    check the toolchain only
#
# The hook runs scripts/check-private.py over the staged files (RE-1 layer 2,
# RIGHTS-6, RIGHTS-10). It is installed into this clone's hooks directory.
# Note for git worktrees: all worktrees of one clone share a hooks directory, so
# run this from a checkout whose branch contains scripts/check-private.py.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
missing=0

need() {
  if command -v "$1" >/dev/null 2>&1; then
    printf '  ok       %-14s %s\n' "$1" "$(command -v "$1")"
  else
    printf '  MISSING  %-14s %s\n' "$1" "$2"
    missing=1
  fi
}

want() {
  if command -v "$1" >/dev/null 2>&1; then
    printf '  ok       %-14s %s\n' "$1" "$(command -v "$1")"
  else
    printf '  optional %-14s %s (lint step is skipped without it)\n' "$1" "$2"
  fi
}

echo "toolchain:"
need cc "a C17 compiler (clang or gcc)"
need make "GNU make"
need git "git"
need patch "patch(1), applies the numbered SIMH patches at build time"
need python3 "Python 3.12 or 3.13"
need ruff "pip install ruff"
if python3 -c 'import pytest' 2>/dev/null; then
  echo "  ok       pytest"
else
  echo "  MISSING  pytest         pip install pytest"
  missing=1
fi
want shellcheck "brew install shellcheck / apt install shellcheck"
want clang-format "brew install clang-format / apt install clang-format"
want actionlint "brew install actionlint (falls back to a YAML parse)"

[ "$missing" -eq 0 ] || { echo "install the missing tools above, then re-run" >&2; exit 1; }

if [ "${1:-}" = "--check" ]; then
  exit 0
fi

hooks="$(git -C "$here" rev-parse --git-path hooks)"
case "$hooks" in /*) ;; *) hooks="$here/$hooks" ;; esac
mkdir -p "$hooks"
cat > "$hooks/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# Installed by scripts/dev-setup.sh. RE-1 layer 2: reject audio, oversized
# research files, notebooks with outputs, and Interdata binaries or tapes.
top="$(git rev-parse --show-toplevel)"
exec python3 "$top/scripts/check-private.py" --staged
HOOK
chmod +x "$hooks/pre-commit"
echo "pre-commit hook installed: $hooks/pre-commit"
