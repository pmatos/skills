#!/usr/bin/env bash
#
# git-safety-lib.sh — shared remote / default-branch resolvers for the
# investigate skill's commit (Phase 5) and push (Phase 6) steps.
#
# Source this file; do not execute it. Defining the resolvers in one place
# guarantees the branch guard and the push pick the SAME remote — otherwise the
# guard could pass on local `main` against remote A while the push lands on
# remote B, defeating the protection.
#
# See ../references/git-safety.md for the resolution order and rationale.

# resolve_push_remote <branch>
# Echo the remote Phase 6 will push to. First non-empty wins:
#   1. the branch's existing upstream (set by a prior `git push -u`)
#   2. branch.<name>.remote in git config
#   3. `git remote | head -1` — the alphabetically-first configured remote
#      (deterministic only with a single remote; a best-effort guess otherwise)
#   4. literal "origin" (final fallback when `git remote` is empty)
resolve_push_remote() {
  local branch="$1" upstream remote
  if upstream=$(git rev-parse --abbrev-ref --symbolic-full-name "$branch@{u}" 2>/dev/null) &&
    [[ -n "$upstream" ]]; then
    printf '%s' "${upstream%%/*}"
    return
  fi
  if remote=$(git config --get "branch.$branch.remote" 2>/dev/null) && [[ -n "$remote" ]]; then
    printf '%s' "$remote"
    return
  fi
  if remote=$(git remote | head -1) && [[ -n "$remote" ]]; then
    printf '%s' "$remote"
    return
  fi
  printf '%s' "origin"
}

# resolve_default_branch <remote>
# Echo the default branch on <remote>, or empty if it cannot be determined.
#   1. Local symref refs/remotes/<remote>/HEAD (present after `git clone`,
#      absent after `git remote add` + fetch unless `git remote set-head` ran)
#   2. `gh repo view <owner/repo>` on the repo derived from <remote>'s URL —
#      authoritative for a GitHub repo; handles trunk/develop; tolerates `gh`
#      being unauthenticated by returning empty
#   3. Local heuristic: `main` or `master` if they exist as heads. Deliberately
#      excludes trunk/develop — with no remote signal, leave it unresolved
#      rather than guess.
resolve_default_branch() {
  local remote="$1" default remote_url remote_repo
  default=$(git symbolic-ref "refs/remotes/$remote/HEAD" 2>/dev/null |
    sed "s|refs/remotes/$remote/||")
  if [[ -z "$default" ]]; then
    remote_url=$(git remote get-url "$remote" 2>/dev/null)
    if [[ -n "$remote_url" ]]; then
      # Derive owner/repo from the remote URL so `gh` queries the same repo the
      # push will target. Handles:
      #   git@github.com:OWNER/REPO[.git]
      #   https://github.com/OWNER/REPO[.git]
      #   ssh://git@github.com/OWNER/REPO[.git]
      remote_repo=$(printf '%s' "$remote_url" | sed -E \
        -e 's|^git@[^:]+:||' \
        -e 's|^ssh://[^@]+@[^/]+/||' \
        -e 's|^https?://[^/]+/||' \
        -e 's|\.git/*$||')
      default=$(gh repo view "$remote_repo" --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null)
    fi
  fi
  if [[ -z "$default" ]]; then
    if git show-ref --verify --quiet refs/heads/main 2>/dev/null; then
      default=main
    elif git show-ref --verify --quiet refs/heads/master 2>/dev/null; then
      default=master
    fi
  fi
  printf '%s' "$default"
}
