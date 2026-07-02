#!/usr/bin/env bash
#
# push-branch.sh — Phase 6 push for the investigate skill.
#
# Push the current branch, honoring any existing upstream instead of hardcoding
# `origin`, using the SAME remote resolver as the Phase 5 guard
# (git-safety-lib.sh). This matters for fork workflows (the branch may already
# track `upstream` or a fork-named remote) and for repos whose only remote is
# not `origin`.
#
# Usage:
#   push-branch.sh
#
# Exit status: propagates git's exit status (0 on success). Exits 1 without
# pushing if HEAD is detached.
#
# See ../references/git-safety.md for the rationale.

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=git-safety-lib.sh
. "$here/git-safety-lib.sh"

branch="$(git branch --show-current 2>/dev/null)"
if [[ -z "$branch" ]]; then
  printf 'investigate: cannot push from a detached HEAD.\n' >&2
  exit 1
fi

remote="$(resolve_push_remote "$branch")"

# `branch.<name>.merge` is set iff the branch already has an upstream, so it is
# a cheap, parse-free proxy for "has this branch been pushed before?".
if git config --get "branch.$branch.merge" >/dev/null 2>&1; then
  # Upstream already configured — bare push uses the existing tracking, no -u.
  # (Never `git push -u origin HEAD`: -u would move the upstream to origin even
  # if the branch tracks a different remote.)
  git push
else
  # First push of this branch — set the upstream explicitly via -u.
  git push -u "$remote" "$branch"
fi
