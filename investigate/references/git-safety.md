# Git Safety — Remote and Default-Branch Resolution

Detailed reference for Phases 5 and 6 of the investigate skill. The deterministic
logic lives in `scripts/git-safety-lib.sh` (shared resolvers),
`scripts/check-branch.sh` (the guard), and `scripts/push-branch.sh` (the push).
This file explains *why*.

## The core requirement: guard and push must agree

The Phase 5 branch-safety guard and the Phase 6 push **must** resolve the same
remote. If they diverge, the guard can pass on local `main` against remote A's
default while the push then lands on remote B — defeating the protection. That is
why both source a single `git-safety-lib.sh` and call the same
`resolve_push_remote` instead of each computing the remote its own way.

## `resolve_push_remote <branch>`

Picks the remote Phase 6 will push to. Tried in order; first non-empty wins:

1. **The branch's existing upstream** (set by a prior `git push -u`), read via
   `git rev-parse --abbrev-ref --symbolic-full-name <branch>@{u}` and taking the
   part before the first `/`.
2. **`branch.<name>.remote`** in git config.
3. **`git remote | head -1`** — the alphabetically-first configured remote.
   Deterministic only when there is exactly one remote (the common fork-only
   case, e.g. only `upstream`); on multi-remote checkouts it picks whatever sorts
   first, which may or may not be what the user intends. Used as a best-effort
   guess.
4. **Literal `origin`** — final fallback when `git remote` is empty.

## `resolve_default_branch <remote>`

Echoes the default branch on `<remote>`, or empty if it cannot be determined:

1. **Local symref** `refs/remotes/<remote>/HEAD` — present after `git clone`, but
   *missing* after `git remote add` + manual fetch unless `git remote set-head`
   was run afterwards.
2. **Remote-aware `gh repo view --json defaultBranchRef`** — authoritative for a
   GitHub repo, and the way the `trunk`/`develop` case is handled when the local
   symref is absent. Tolerates `gh` not being authenticated by quietly returning
   empty. The repo is derived from `<remote>`'s URL (not from the current
   directory) so `gh` queries the same repo the push will target. URL forms
   handled:
   - `git@github.com:OWNER/REPO[.git]`
   - `https://github.com/OWNER/REPO[.git]`
   - `ssh://git@github.com/OWNER/REPO[.git]`
3. **Local heuristic** `main` or `master` if they exist as heads. A last resort
   that intentionally does **not** include `trunk`/`develop` — with no remote
   signal, leave the default unresolved rather than guess.

## The guard (`check-branch.sh`)

Refuses to commit/push when the current branch is the resolved default branch
(whatever its name — `main`, `master`, `trunk`, `develop`, …) or when HEAD is
detached.

If `resolve_default_branch` returns empty (no `<remote>/HEAD`, no `gh` answer, no
local `main`/`master`), the guard still refuses a detached HEAD but **allows**
other branches through: there is no reliable default to compare against, and
forcing the user to set one would block legitimate first-commit scenarios.

This protects against the common case of `/investigate` being invoked while the
user is still on the default branch after the last PR merged — without it,
Phases 5 and 6 would commit and push straight to the default branch.

## The push (`push-branch.sh`)

Never hardcode `git push -u origin HEAD`. The `-u` flag overrides any existing
upstream, so if the branch already tracks a different remote, that push silently
moves the upstream pointer to `origin`. Instead:

- If `branch.<name>.merge` is set (a cheap, parse-free proxy for "the branch has
  an upstream"), do a bare `git push` — it uses the existing tracking.
- Otherwise this is the branch's first push: `git push -u <remote> <branch>`,
  where `<remote>` comes from the same `resolve_push_remote` the guard used.
