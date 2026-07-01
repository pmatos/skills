#!/usr/bin/env bash
#
# collect-instructions.sh — Phase 3.2 of the investigate skill.
#
# Given the paths the skill intends to change, print the scoped project
# instruction files (CLAUDE.md / AGENTS.md) that govern them. For each path it
# walks from that path's directory up to the repository root and collects every
# such file found along the way. Output is deduplicated (symlink-aware) and
# ordered from the repository root — the baseline — down to the deepest
# directory — the closest-wins layer — so a reader applies "closest wins"
# precedence simply by reading top to bottom, later lines overriding earlier.
#
# Deterministic: it discovers and orders the files; the caller reads and merges
# their contents and judges conflicts (see ../references/scoped-instructions.md).
#
# Usage:
#   collect-instructions.sh <changed-path> [<changed-path> ...]
#
# Paths may be files or directories and need not exist yet — a to-be-created
# file's nearest existing ancestor directory is walked. Relative paths are
# resolved against the current directory.
#
# Output:
#   Repo-relative paths of the instruction files, one per line, ordered
#   baseline (repo root) → closest (deepest directory). Empty output means no
#   CLAUDE.md / AGENTS.md governs any of the given paths, and the caller falls
#   back to the Phase 3.1 baseline alone.
#
# Exit codes:
#   0  Ran successfully. The (possibly empty) file list is on stdout.
#   1  Hard failure: no paths given, or not inside a git repository. A specific
#      message is on stderr.
#
# See ../references/scoped-instructions.md for the precedence and merge rules.

set -u

if (( $# == 0 )); then
  printf 'collect-instructions.sh: no paths given.\n' >&2
  exit 1
fi

root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [[ -z "$root" ]]; then
  printf 'collect-instructions.sh: not inside a git repository.\n' >&2
  exit 1
fi
root="$(cd "$root" && pwd -P)"     # canonical, symlink-resolved repo root

declare -a found_abs=()            # absolute paths already emitted (for -ef dedup)
declare -a out_lines=()            # "<depth>\t<repo-relative path>" pending sort
declare -A visited_dir=()          # directories already scanned

# Record a found instruction file unless an alias of it (same inode, e.g. an
# AGENTS.md symlinked to CLAUDE.md) was already recorded.
record() {
  local abs="$1" f rel depth
  for f in "${found_abs[@]:-}"; do
    [[ -n "$f" && "$abs" -ef "$f" ]] && return 0
  done
  found_abs+=("$abs")
  rel="${abs#"$root"/}"
  depth="$(printf '%s' "$rel" | tr -cd '/' | wc -c)"; depth=$((depth))
  out_lines+=("$depth"$'\t'"$rel")
}

# Scan one directory for CLAUDE.md then AGENTS.md (CLAUDE.md wins the dedup when
# the two are the same file).
scan_dir() {
  local d="$1"
  [[ -n "${visited_dir[$d]:-}" ]] && return 0
  visited_dir[$d]=1
  [[ -f "$d/CLAUDE.md" ]] && record "$d/CLAUDE.md"
  [[ -f "$d/AGENTS.md" ]] && record "$d/AGENTS.md"
}

# Walk one input path's directory up to (and including) the repo root.
walk_up() {
  local start="$1" d existing i
  local -a chain=()
  case "$start" in
    /*) : ;;
    *)  start="$(pwd -P)/$start" ;;
  esac
  if [[ -d "$start" ]]; then
    existing="$start"
  else
    existing="$(dirname -- "$start")"
  fi
  while [[ ! -d "$existing" && "$existing" != "/" ]]; do
    existing="$(dirname -- "$existing")"
  done
  [[ -d "$existing" ]] || return 0
  d="$(cd "$existing" && pwd -P)"
  if [[ "$d" != "$root" && "$d" != "$root"/* ]]; then
    printf 'collect-instructions.sh: %s is outside the repo root; skipping.\n' "$1" >&2
    return 0
  fi
  # Collect the directory chain closest→root, then scan it root→closest so an
  # aliased file (a symlink to a shallower one) dedups to the baseline label,
  # not the deeper occurrence.
  while :; do
    chain+=("$d")
    [[ "$d" == "$root" ]] && break
    d="$(dirname -- "$d")"
  done
  for (( i=${#chain[@]}-1; i>=0; i-- )); do
    scan_dir "${chain[i]}"
  done
}

for p in "$@"; do
  walk_up "$p"
done

if (( ${#out_lines[@]} > 0 )); then
  printf '%s\n' "${out_lines[@]}" | sort -s -t"$(printf '\t')" -k1,1n -k2,2 | cut -f2-
fi
exit 0
