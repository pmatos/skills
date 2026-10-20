#!/usr/bin/env bash
#
# capped.sh — run a heavy command in its own memory-capped systemd scope.
#
# A runaway build, test suite or solver started from an agent session lives in the
# terminal's cgroup; when it exhausts RAM and swap the OOM killer takes the terminal
# and every agent with it. This wrapper gives the command its own transient scope under
# one shared slice (vibe.slice, capped at 70% of RAM in total) with a hard per-job memory
# cap, no swap, a task limit and an optional wall-clock limit, so the kernel kills only
# that job. Exclusive jobs (timing runs, full builds, whole suites) can be serialised
# behind one shared lock.
#
# Usage:
#   capped.sh [-n] [-m GB] [-t SECONDS] [-w SECONDS] [-l LOCKFILE] [--] cmd [args...]
#
#   -n          do not take the shared lock (small runs); default cap drops to 12 GB
#   -m GB       RAM cap in whole GB (default 24 with the lock, 12 without, never above
#               70% of RAM; refused above VIBE_MAX_MEM_GB (default 32) or total RAM)
#   -t SECONDS  kill the command after this wall-clock time, counted after the lock is held
#   -w SECONDS  give up waiting for the lock after this long (exit 75)
#   -l LOCKFILE lock path (default $VIBE_LOCK, else $XDG_RUNTIME_DIR/vibe-heavy.lock,
#               else /tmp/vibe-heavy.lock)
#   -h          print this help
#
# Exit codes: the command's own; 124 timeout; 137 or 143 mean a signal killed the command
# (the memory cap or the timeout's kill; check `journalctl --user -k | grep -i oom` and
# report it as a finding, never raise the cap); 2 usage error; 3 user scopes unavailable
# (set VIBE_ALLOW_UNCAPPED=1 to run uncapped, without the memory cap); 75 lock wait timed out.
#
# The lock is not inherited by processes the command leaves behind (flock -o).

set -euo pipefail

usage() {
  local code="${1:-2}"
  if [[ "$code" == 0 ]]; then
    sed -n '3,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  else
    sed -n '3,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  fi
  exit "$code"
}

die() {
  echo "capped.sh: $1" >&2
  exit "${2:-2}"
}

use_lock=1
mem=""
tmo=""
lock_wait=""
max_mem="${VIBE_MAX_MEM_GB:-32}"
lockfile="${VIBE_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/vibe-heavy.lock}"

while getopts ":nm:t:w:l:h" opt; do
  case "$opt" in
    n) use_lock=0 ;;
    m) mem="$OPTARG" ;;
    t) tmo="$OPTARG" ;;
    w) lock_wait="$OPTARG" ;;
    l) lockfile="$OPTARG" ;;
    h) usage 0 ;;
    *) usage 2 ;;
  esac
done
shift $((OPTIND - 1))
[[ $# -gt 0 ]] || usage 2

positive_int() { [[ "$1" =~ ^[1-9][0-9]*$ ]]; }

total_gb=0
if [[ -r /proc/meminfo ]]; then
  total_gb=$(awk '/^MemTotal:/ { print int($2 / 1048576) }' /proc/meminfo)
fi
limit_gb=$((total_gb * 7 / 10))
((limit_gb >= 1)) || limit_gb=$max_mem

if [[ -z "$mem" ]]; then
  if [[ "$use_lock" == 1 ]]; then mem=24; else mem=12; fi
  ((mem <= limit_gb)) || mem=$limit_gb
else
  positive_int "$mem" || die "-m wants a positive whole number of GB, got '$mem'"
fi
if [[ -n "$tmo" ]]; then positive_int "$tmo" || die "-t wants a positive whole number of seconds, got '$tmo'"; fi
if [[ -n "$lock_wait" ]]; then positive_int "$lock_wait" || die "-w wants a positive whole number of seconds, got '$lock_wait'"; fi
if ((mem > max_mem)); then
  die "refusing a cap above ${max_mem} GB (raise VIBE_MAX_MEM_GB deliberately)"
fi
if ((total_gb > 0 && mem > total_gb)); then
  die "refusing a cap of ${mem} GB on a host with ${total_gb} GB of RAM"
fi
high=$((mem * 9 / 10))
((high >= 1)) || high=1

cmd=("$@")
if [[ -n "$tmo" ]]; then
  cmd=(timeout -k 20 "$tmo" "$@")
fi

lock=()
if [[ "$use_lock" == 1 ]]; then
  lock=(flock -o)
  if [[ -n "$lock_wait" ]]; then lock+=(-w "$lock_wait" -E 75); fi
  lock+=("$lockfile")
fi

run_uncapped() {
  [[ "${VIBE_ALLOW_UNCAPPED:-}" == 1 ]] || die "$1; refusing to run uncapped (VIBE_ALLOW_UNCAPPED=1 overrides, without the memory cap)" 3
  echo "capped.sh: warning: running WITHOUT a memory cap ($1)" >&2
  "${lock[@]}" "${cmd[@]}"
}

stamp="${XDG_RUNTIME_DIR:-/tmp}/vibe-capped.ok"
if ! command -v systemd-run >/dev/null 2>&1; then
  rc=0
  run_uncapped "systemd-run not found" || rc=$?
  exit "$rc"
fi
if [[ ! -e "$stamp" ]]; then
  if systemd-run --user --scope --quiet --collect -p MemoryMax=64M true >/dev/null 2>&1; then
    : >"$stamp" 2>/dev/null || true
  else
    rc=0
    run_uncapped "systemd-run --user scopes are unavailable (no user bus or no memory controller)" || rc=$?
    exit "$rc"
  fi
fi

# One shared slice caps the sum of all jobs; best effort, the per-job caps still apply.
if ((total_gb > 0)); then
  systemctl --user set-property --runtime vibe.slice "MemoryMax=${limit_gb}G" MemorySwapMax=0 >/dev/null 2>&1 || true
fi

scope=(systemd-run --user --scope --quiet --collect --slice=vibe.slice
  -p "MemoryMax=${mem}G" -p "MemoryHigh=${high}G" -p MemorySwapMax=0 -p TasksMax=4096 --)

rc=0
"${lock[@]}" "${scope[@]}" "${cmd[@]}" || rc=$?
if [[ "$rc" == 137 || "$rc" == 143 ]]; then
  echo "capped.sh: exit $rc: killed by a signal (memory cap, or the timeout's kill); check 'journalctl --user -k | grep -i oom' and report it" >&2
fi
exit "$rc"
