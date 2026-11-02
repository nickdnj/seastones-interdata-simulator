#!/usr/bin/env bash
# station-lib.sh: the shared parts of install-station.sh and uninstall-station.sh (KP-11).
# Sourced, never run. bash 3.2 compatible (macOS's /bin/bash).
#
# Every change goes through one of the do_* functions, which:
#   - do nothing and say nothing when the target is already right (idempotent: a second run
#     reports 0 changes),
#   - in a dry run (the default) print what they WOULD do and change nothing,
#   - with --root DIR write under DIR instead of / (staging: tests, the release gate) and
#     never run a service manager, create a user or chown,
#   - with --apply and no --root, change the machine.

CHANGES=0
APPLY=0
ROOT=""
PRINT_PATHS=0

say() { [ "$PRINT_PATHS" = 1 ] || printf '\n== %s\n' "$*"; }
note() { [ "$PRINT_PATHS" = 1 ] || printf '   %s\n' "$*"; }
warn() { printf '   !! %s\n' "$*" >&2; }
die() { printf '%s: %s\n' "${PROG:-station}" "$*" >&2; exit 1; }

R() { printf '%s%s' "$ROOT" "$1"; }

# Real changes to this machine: --apply, no --root.
live() { [ "$APPLY" = 1 ] && [ -z "$ROOT" ]; }
can_chown() { live && [ "$(id -u)" -eq 0 ]; }

file_mode() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }
norm_mode() { local m="${1#0}"; echo "${m:-0}"; }

changed() {  # $1 = verb, $2 = path
  CHANGES=$((CHANGES + 1))
  if [ "$APPLY" = 1 ]; then printf '   + %s %s\n' "$1" "$2"; else printf '   would %s %s\n' "$1" "$2"; fi
}

do_dir() {  # path mode [owner[:group]]
  if [ "$PRINT_PATHS" = 1 ]; then echo "$1"; return 0; fi
  local t; t="$(R "$1")"
  if [ -d "$t" ]; then return 0; fi
  changed "create dir" "$1"
  if [ "$APPLY" = 1 ]; then
    mkdir -p "$t"
    chmod "$2" "$t"
    if [ -n "${3:-}" ] && can_chown; then chown "$3" "$t"; fi
  fi
}

do_file() {  # src dst mode [owner[:group]]
  MANIFEST_NEW="${MANIFEST_NEW:-}"
  if [ -n "$MANIFEST_NEW" ] && [ "${NO_MANIFEST:-0}" != 1 ]; then echo "$2" >> "$MANIFEST_NEW"; fi
  if [ "$PRINT_PATHS" = 1 ]; then echo "$2"; return 0; fi
  local t; t="$(R "$2")"
  if [ -f "$t" ] && cmp -s "$1" "$t" \
     && [ "$(norm_mode "$(file_mode "$t")")" = "$(norm_mode "$3")" ]; then
    return 0
  fi
  if [ -e "$t" ]; then changed "update" "$2"; else changed "install" "$2"; fi
  if [ "$APPLY" = 1 ]; then
    mkdir -p "$(dirname "$t")"
    cp "$1" "$t.sx-new"
    chmod "$3" "$t.sx-new"
    if [ -n "${4:-}" ] && can_chown; then chown "$4" "$t.sx-new"; fi
    mv -f "$t.sx-new" "$t"
  fi
}

do_text() {  # dst mode [owner] < content
  local tmp; tmp="$(mktemp "${TMPDIR:-/tmp}/sx-station.XXXXXX")"
  cat > "$tmp"
  do_file "$tmp" "$@"
  rm -f "$tmp"
}

do_remove() {  # path
  if [ "$PRINT_PATHS" = 1 ]; then return 0; fi
  local t; t="$(R "$1")"
  if [ ! -e "$t" ] && [ ! -L "$t" ]; then return 0; fi
  changed "remove" "$1"
  if [ "$APPLY" = 1 ]; then rm -f "$t"; fi
}

do_rmdir_empty() {  # path: remove empty directories under and including it
  if [ "$PRINT_PATHS" = 1 ]; then return 0; fi
  local t; t="$(R "$1")"
  [ -d "$t" ] || return 0
  if [ "$APPLY" = 1 ]; then
    find "$t" -depth -type d -empty -exec rmdir {} \; 2>/dev/null || true
    [ -d "$t" ] || printf '   + remove empty dirs %s\n' "$1"
  elif [ -z "$(find "$t" -type f 2>/dev/null | head -1)" ]; then
    printf '   would remove empty dirs %s\n' "$1"
  fi
}

do_run() {  # command... : run on a live install; otherwise only say so
  if [ "$PRINT_PATHS" = 1 ]; then return 0; fi
  if live; then
    printf '   run: %s\n' "$*"
    "$@" || warn "failed (continuing): $*"
  else
    printf '   would run: %s\n' "$*"
  fi
}

do_line() {  # file line : make sure the file contains the line (appended once)
  if [ "$PRINT_PATHS" = 1 ]; then echo "$1"; return 0; fi
  local t; t="$(R "$1")"
  if [ -f "$t" ] && grep -qxF -- "$2" "$t"; then return 0; fi
  changed "add a line to" "$1"
  if [ "$APPLY" = 1 ]; then mkdir -p "$(dirname "$t")"; printf '%s\n' "$2" >> "$t"; fi
}

undo_line() {  # file line : remove the line if present
  if [ "$PRINT_PATHS" = 1 ]; then return 0; fi
  local t; t="$(R "$1")"
  [ -f "$t" ] && grep -qxF -- "$2" "$t" || return 0
  changed "remove a line from" "$1"
  if [ "$APPLY" = 1 ]; then
    grep -vxF -- "$2" "$t" > "$t.sx-new" || true
    cat "$t.sx-new" > "$t"
    rm -f "$t.sx-new"
  fi
}

# NAME=value lines of a station.conf, without a shell (the value of $2, or $3 if absent).
conf_get() {  # file name default
  local v
  v="$(sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -1 | sed 's/^"//; s/"$//')"
  echo "${v:-$3}"
}

finish() {  # $1 = what was done ("install" | "uninstall")
  if [ "$PRINT_PATHS" = 1 ]; then return 0; fi
  echo
  if [ "$APPLY" = 1 ]; then
    echo "$1: $CHANGES change(s) made${ROOT:+ under $ROOT}."
  else
    echo "$1: dry run, $CHANGES change(s) would be made; nothing was changed."
    echo "Run again with --apply to do it."
  fi
}
