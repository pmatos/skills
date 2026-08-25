#!/usr/bin/env bash
# Force-push a rebased branch without clobbering a concurrent writer.
#
# <expected-sha> must be the anchor captured by capture-lease.sh BEFORE the
# rebase — never a value re-derived from the remote at push time, which would arm
# the lease with the other writer's own commit and defeat it entirely.
#
# Usage: safe-force-push.sh <remote> <branch> <expected-sha>
#
# Exit codes:
#   0  pushed
#   2  usage error, not a repository, or the remote could not be fetched
#   3  worktree dirty, or a rebase is still in progress
#   4  the remote head moved off <expected-sha>: another writer is active
#   5  the push itself was rejected

set -euo pipefail

usage() {
  echo "usage: safe-force-push.sh <remote> <branch> <expected-sha>" >&2
  exit 2
}

[ "$#" -eq 3 ] || usage
remote=$1
branch=$2
expected=$3
[ -n "$remote" ] && [ -n "$branch" ] && [ -n "$expected" ] || usage

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "safe-force-push: not inside a git repository" >&2
  exit 2
fi

for state in rebase-merge rebase-apply; do
  if [ -e "$(git rev-parse --git-path "$state")" ]; then
    echo "safe-force-push: a rebase is still in progress — finish it or 'git rebase --abort' first" >&2
    exit 3
  fi
done

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "safe-force-push: worktree has uncommitted tracked changes; refusing to push" >&2
  git --no-pager status --short --untracked-files=no >&2
  exit 3
fi

if ! git rev-parse --verify --quiet "$expected^{commit}" >/dev/null; then
  echo "safe-force-push: '$expected' is not a commit in this repository" >&2
  exit 2
fi

if ! git fetch --quiet "$remote" "$branch"; then
  echo "safe-force-push: cannot fetch '$branch' from '$remote' — branch missing or remote unreachable" >&2
  exit 2
fi

actual=$(git rev-parse FETCH_HEAD)
if [ "$actual" != "$expected" ]; then
  echo "safe-force-push: $remote/$branch moved from $expected to $actual — another writer is active." >&2
  echo "safe-force-push: stand down and diff their change against yours. Their commits:" >&2
  git --no-pager log --oneline "$expected..$actual" >&2
  exit 4
fi

if ! git push --force-with-lease="$branch:$expected" "$remote" "HEAD:refs/heads/$branch"; then
  echo "safe-force-push: push rejected — do not retry with --force" >&2
  exit 5
fi
