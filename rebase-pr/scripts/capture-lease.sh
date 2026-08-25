#!/usr/bin/env bash
# Capture the --force-with-lease anchor BEFORE a rebase rewrites the branch.
#
# The lease only protects a concurrent writer if the value it is armed with
# predates that writer's push. Fetching the branch and then computing the anchor
# arms the lease with their commit, so the later push succeeds and destroys their
# work. This script is therefore run once, before the rebase; every later fetch of
# the same branch is for inspection only (see safe-force-push.sh).
#
# Usage: capture-lease.sh <remote> <branch>
#
# Prints the remote head SHA (the lease anchor) on stdout for exit codes 0 and 3.
#
# Exit codes:
#   0  local tip == remote head; safe to rebase
#   2  usage error, not a repository, missing remote branch, or remote unreachable
#   3  local is strictly ahead of the remote (unpushed local commits); safe to
#      rebase, but the eventual force-push will also publish those commits
#   4  local is behind, or has diverged from, the remote: another writer is active

set -euo pipefail

usage() {
  echo "usage: capture-lease.sh <remote> <branch>" >&2
  exit 2
}

[ "$#" -eq 2 ] || usage
remote=$1
branch=$2
[ -n "$remote" ] && [ -n "$branch" ] || usage

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "capture-lease: not inside a git repository" >&2
  exit 2
fi

if ! git fetch --quiet "$remote" "$branch"; then
  echo "capture-lease: cannot fetch '$branch' from '$remote' — branch missing or remote unreachable" >&2
  exit 2
fi

remote_sha=$(git rev-parse FETCH_HEAD)
local_sha=$(git rev-parse HEAD)

# The anchor is printed before any divergence verdict, so a caller acting on
# exit 3 still has it.
echo "$remote_sha"

if [ "$remote_sha" = "$local_sha" ]; then
  exit 0
fi

if git merge-base --is-ancestor "$remote_sha" "$local_sha"; then
  ahead=$(git rev-list --count "$remote_sha..$local_sha")
  echo "capture-lease: local branch is ahead of $remote/$branch by $ahead commit(s); the force-push will publish them" >&2
  exit 3
fi

if git merge-base --is-ancestor "$local_sha" "$remote_sha"; then
  behind=$(git rev-list --count "$local_sha..$remote_sha")
  echo "capture-lease: local branch is BEHIND $remote/$branch by $behind commit(s) — another writer pushed." >&2
else
  echo "capture-lease: local branch has DIVERGED from $remote/$branch — another writer pushed." >&2
fi
echo "capture-lease: stand down and reconcile before rebasing. Their commits:" >&2
git --no-pager log --oneline "$local_sha..$remote_sha" >&2
exit 4
