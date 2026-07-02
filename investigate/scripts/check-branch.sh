#!/usr/bin/env bash
#
# check-branch.sh — Phase 5.0 guard for the investigate skill.
#
# Refuse to commit/push from the repo's default branch (whatever its name) or a
# detached HEAD. The remote used to resolve the default branch is the SAME one
# push-branch.sh pushes to (shared git-safety-lib.sh), so the guard and the push
# cannot disagree about which remote is canonical.
#
# Usage:
#   check-branch.sh
#
# Exit codes:
#   0  Safe. On a topic branch (branch name printed to stdout), OR the default
#      branch could not be resolved but HEAD is not detached (best effort).
#   5  Refuse. On the default branch or detached HEAD. The offending branch name
#      (or the literal "detached HEAD") is printed to stdout for the caller's
#      message.
#
# See ../references/git-safety.md for the rationale.

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=git-safety-lib.sh
. "$here/git-safety-lib.sh"

branch="$(git branch --show-current 2>/dev/null)"

if [[ -z "$branch" ]]; then
  printf 'detached HEAD\n'
  exit 5
fi

remote="$(resolve_push_remote "$branch")"
default_branch="$(resolve_default_branch "$remote")"

# Refuse only when the default resolved AND equals the current branch. If it
# could not be resolved at all, allow the branch through (HEAD is not detached,
# checked above) rather than block a legitimate first-commit scenario.
if [[ -n "$default_branch" && "$branch" == "$default_branch" ]]; then
  printf '%s\n' "$branch"
  exit 5
fi

printf '%s\n' "$branch"
exit 0
