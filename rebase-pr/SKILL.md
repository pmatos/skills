---
name: rebase-pr
description: This skill should be used when the user asks to "rebase pr", "rebase onto main", "rebase this branch", "rebase and force push", "resolve rebase conflicts", "update the branch from main", "my PR has conflicts", "bring the PR up to date with main", or wants a PR branch rebased onto its base branch with conflicts resolved by hand, the project's quality gate re-run, and a safe force-push. Also triggered by the /rebase-pr command.
argument-hint: "[pr-number]"
user-invocable: true
---

# Rebase PR

Rebase a GitHub PR branch onto its base branch, resolve every conflict by hand, re-run the
project's quality gate, and force-push without clobbering a concurrent writer. One invocation,
`gh` CLI only, no GitHub MCP dependency.

## Core Principle: Never Bulk-Resolve a Conflict

A rebase conflict is resolved **file by file**, by reading both sides and writing a coherent
result. Never run `git checkout ORIG_HEAD -- .`, `git checkout --ours .`, `git checkout --theirs .`,
`git restore --source=... .`, or any other bulk path operation while a rebase is in progress — each
one silently discards resolutions already made for the other files in the same conflict.

## Core Principle: The Lease Is Taken Before the Rebase

`--force-with-lease` only protects a concurrent writer if the value it is armed with predates that
writer's push. Fetching the branch and *then* computing the lease anchor arms the lease with the
other writer's commit, so the push succeeds and destroys their work — the exact failure the lease
exists to prevent. Capture `EXPECTED_REMOTE_SHA` **before** the rebase (Step 2); every later fetch
of that branch is for **inspection only**. See `references/force-push-safety.md`.

## Core Principle: Gate Steps Never Chain

Quality-gate commands run as **separate** invocations, never `&&`-chained. A flaky test must not
silently skip the build step that follows it — each step's own exit status has to be observed.

## Prerequisites

- **`gh` CLI**, installed and authenticated (`gh auth status`). This is the only GitHub dependency;
  the skill stops at preflight if it is missing. A GitHub MCP server is never required and never
  waited for (same posture as `pm-autofix-pr`).
- **A clean worktree.** The skill refuses to start with uncommitted tracked changes — a rebase over
  a dirty tree is how resolutions get lost.

## Configuration

Override via prompt arguments (e.g. `/rebase-pr 42 --watch-ci --ci-budget 20`).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `WATCH_CI` | off | Whether to wait for post-push CI (Step 8) instead of exiting immediately after the push. Enable with `--watch-ci`. |
| `CI_BUDGET` | 15 | Wall-clock ceiling (minutes) on the whole Step 8 wait, initialized once when Step 8 is entered. Only meaningful with `--watch-ci`. |
| `POLL_INTERVAL` | 30 | Seconds between check re-fetches; also the `--interval` passed to `gh pr checks --watch`. |

## GitHub CLI Commands Used

| Operation | Command |
|-----------|---------|
| Preflight | `gh auth status` |
| Resolve the PR for the current branch | `gh pr list --head <branch> --state open --json number,headRefName,headRepositoryOwner,baseRefName,url` |
| Read PR head/base/mergeability | `gh pr view <n> --json number,headRefName,baseRefName,mergeable,headRepositoryOwner,url,title` |
| Report what was rebased | `gh pr comment <n> --body-file <tmpfile>` |
| Wait for post-push CI (opt-in) | `gh pr checks <n> --watch --interval <POLL_INTERVAL>` |

`gh pr view --json mergeable` returns the GraphQL vocabulary — `MERGEABLE`, `CONFLICTING`,
`UNKNOWN` (uppercase) — **not** REST's `mergeable`/`mergeable_state` pair. Treat it as a hint about
whether a rebase is needed, never as the authority on whether one succeeded; `git rebase`'s own exit
status is the authority.

`<tmpfile>` always means a path from `mktemp` (e.g. `mktemp /tmp/rebase-pr-body-XXXXXX`), never a
fixed literal, so two concurrent invocations cannot race on the same filename. `rm -f` it after.

## Bundled Scripts

Invoke by absolute path. When loaded as a plugin that prefix is
`${CLAUDE_PLUGIN_ROOT}/rebase-pr/scripts/`; if `${CLAUDE_PLUGIN_ROOT}` is unset (skill installed
standalone), resolve `scripts/` relative to this SKILL.md. Both scripts are self-contained — this
skill installs on its own, so they share no library with any other skill in the repo.

- **`scripts/capture-lease.sh <remote> <branch>`** — Step 2. Fetches the branch, prints the lease
  anchor, and classifies local-vs-remote divergence.
- **`scripts/safe-force-push.sh <remote> <branch> <expected-sha>`** — Step 7. Re-inspects the remote,
  stands down if it moved, otherwise pushes with the lease armed to `<expected-sha>`.

## Workflow

### Step 0: Preflight

1. `gh auth status`. On non-zero exit, stop with:
   > **`gh` CLI not available.** This skill requires the GitHub CLI (`gh`), authenticated. Install it
   > from <https://cli.github.com/> and run `gh auth login`, then re-run.
2. `git status --porcelain --untracked-files=no`. If non-empty, stop and report the dirty paths —
   commit or set them aside first. Do not stash on the user's behalf: the stash stack is shared
   across worktrees and another session may pop it.
3. Confirm no rebase is already in progress: both `git rev-parse --git-path rebase-merge` and
   `git rev-parse --git-path rebase-apply` must name a path that does not exist. If one does, stop —
   finish or `git rebase --abort` that rebase first.

### Step 1: Identify the PR

1. `BRANCH=$(git rev-parse --abbrev-ref HEAD)`. A detached HEAD stops the run.
2. If a PR number was given, `gh pr view <n> --json number,headRefName,baseRefName,mergeable,headRepositoryOwner,url,title`.
   Otherwise `gh pr list --head "$BRANCH" --state open --json number,headRefName,headRepositoryOwner,baseRefName,url`
   and require exactly one open PR whose `headRefName` matches `$BRANCH`. Zero or several → stop and
   say so; never guess.
3. Capture `PR_NUMBER`, `HEAD_REF` (`headRefName`), and **`BASE_REF` (`baseRefName`) — the base branch
   is whatever the PR says it is, not a hardcoded `main`.**
4. Resolve the two remotes by matching `git remote -v` URLs (strip `git@github.com:`,
   `https://github.com/`, and a trailing `.git`):
   - `PUSH_REMOTE` — the remote holding `headRepositoryOwner.login`'s copy of the head branch. This
     is where the force-push goes. For a fork PR it is the fork, not the base repository.
   - `BASE_REMOTE` — the remote holding the base repository. For a same-repo PR both are `origin`.
     If no local remote points at the base repository, use its clone URL
     `https://github.com/<base_owner>/<base_repo>.git`; `git fetch` accepts a URL in place of a name.
5. If `git rev-parse --abbrev-ref HEAD` differs from `HEAD_REF` (a fork checkout may name the local
   branch differently), note it — the push in Step 7 targets `HEAD_REF` on `PUSH_REMOTE` explicitly,
   so the local name never has to match.

### Step 2: Capture the lease anchor, then fetch the base

```bash
scripts/capture-lease.sh "$PUSH_REMOTE" "$HEAD_REF"
```

stdout is `EXPECTED_REMOTE_SHA`. Act on the exit code:

- **0** — the local tip equals the remote head. Proceed.
- **3** — the local branch is strictly ahead (unpushed local commits). Proceed, and say in Step 7's
  comment that the push also published those commits.
- **4** — the local branch is behind or has diverged: another writer pushed to this branch. **Stand
  down.** Report their commits (the script prints the range) and stop. Do not reset, do not
  fast-forward silently — reconciling someone else's commits with the local ones is the user's call.
- **2** — usage error, missing remote branch, or an unreachable remote. Relay stderr and stop.

Record `EXPECTED_REMOTE_SHA` and `ORIGINAL_HEAD=$(git rev-parse HEAD)`. Then fetch the base:
`git fetch "$BASE_REMOTE" "$BASE_REF"` and record `BASE_SHA=$(git rev-parse FETCH_HEAD)`.

### Step 3: Discover the quality gate

Read the project's own instructions first — `CLAUDE.md` / `AGENTS.md`, walking from the working
directory to the repo root, closest file winning on conflict. Use exactly the commands they state.
Only if they state none, infer from the manifests:

| Manifest | Gate commands (run in this order, separately) |
|----------|-----------------------------------------------|
| `package.json` | the `format`/`lint`/`typecheck`/`test`/`build` scripts that exist, via the lockfile's package manager (`npm run`, `pnpm`, `yarn`) |
| `pyproject.toml` | `uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check`, `uv run pytest` — or the `hatch`/bare-`pytest` equivalents when `uv.lock` is absent |
| `Cargo.toml` | `cargo fmt --check`, `cargo clippy`, `cargo test`, `cargo build` |
| `go.mod` | `gofmt -l .`, `go vet ./...`, `go test ./...`, `go build ./...` |
| `Makefile` | whichever of `make fmt`, `make lint`, `make test`, `make check`, `make ci` exist |
| `.pre-commit-config.yaml` | `pre-commit run --all-files` |

Record the resulting list as `GATE`. Never assume `npm run *`. Also note any known-failure list the
project's instructions record — see `references/quality-gate.md` for why that list belongs in the
repo rather than in this skill.

### Step 4: Rebase

```bash
git rebase "$BASE_SHA"
```

Rebasing onto the fetched SHA (not `<remote>/<branch>`) pins the operation to exactly what Step 2
fetched. On exit 0 with no conflicts, go to Step 5.

On a conflict, loop until the rebase completes:

1. `git diff --name-only --diff-filter=U` lists the conflicted files. Read **every** one.
2. Resolve each by hand. **In a rebase the sides are inverted relative to a merge:** `--ours` is the
   base branch being replayed onto, `--theirs` is your own commit. Reason about content, not about
   which label sounds like "mine". Keep the PR's intent and the base's independent change; never
   discard a side wholesale, and never leave a `<<<<<<<`, `=======`, or `>>>>>>>` marker behind.
3. Bulk operations are forbidden here — see the first Core Principle.
4. `git add -- <resolved paths>` (name the paths; not `git add -A`).
5. **Verify before continuing.** All three must hold:
   - `git diff --name-only --diff-filter=U` — empty (nothing unmerged left).
   - `git diff --name-only` — empty (nothing resolved-but-unstaged).
   - `git grep -nE '^(<<<<<<< |=======$|>>>>>>> )' -- <resolved paths>` — no hits.
   If any fails, go back to item 1 rather than continuing over a half-resolved tree.
6. `GIT_EDITOR=true git rebase --continue`. The editor override is mandatory: an interactive editor
   has nothing to attach to here and the command would hang. Never use `git rebase -i`.
7. If a replayed commit becomes empty because the base already contains it,
   `GIT_EDITOR=true git rebase --skip`, and record it for the Step 7 comment.

If a conflict cannot be resolved confidently — a semantic conflict whose correct outcome is
genuinely unclear, or markers that cannot be cleanly removed — run `git rebase --abort`, confirm
`git rev-parse HEAD` is back at `ORIGINAL_HEAD`, and stop with `exit reason: rebase-conflict`,
naming the file and what was ambiguous. A half-rebased branch is never left behind and never pushed.

### Step 5: Re-run the quality gate

Run each `GATE` command from Step 3 as its own invocation, in order, observing each exit status.
Never `&&`-chain them, and do not stop at the first failure — a full picture is what makes the next
step's classification possible.

### Step 6: Classify failures, fix only regressions

For each failing command, classify it once (see `references/quality-gate.md`):

- **REGRESSION** — the rebase caused it. Fix it, `git add` the fix, and amend it into the commit it
  belongs to (or add a follow-up commit if it does not belong to one commit). Re-run that gate
  command.
- **PRE-EXISTING** — it fails on the base branch too. Do not chase it. Verify **once**, with
  evidence: on a clean worktree `git switch --detach "$BASE_SHA"`, run only the failing command,
  then `git switch -` back to the branch. Record the evidence (command, exit status, one-line
  symptom) for Step 7's comment.

If the gate cannot be made green because a genuine regression resists fixing, stop with
`exit reason: gate-failure` — do not force-push a branch whose gate you know is broken.

### Step 7: Force-push safely

```bash
scripts/safe-force-push.sh "$PUSH_REMOTE" "$HEAD_REF" "$EXPECTED_REMOTE_SHA"
```

The script re-fetches the branch, compares the remote head against the anchor from Step 2, and only
then pushes with `--force-with-lease=<branch>:<expected-sha>`. Exit codes:

- **0** — pushed.
- **4** — the remote head moved off the anchor while the rebase ran. **Stand down.** The script
  prints the intervening commits; diff their change against yours and report both to the user. Do
  not re-run with a refreshed anchor: that is precisely the mistake this ordering prevents.
- **5** — the push was rejected anyway (branch protection, or a writer racing inside the push
  window). Report the rejection verbatim; do not retry with `--force`.
- **2 / 3** — usage error, or the worktree went dirty / a rebase is still in progress. Fix and re-run.

Then comment on the PR with what actually happened — write the body to a `mktemp` file and post with
`gh pr comment "$PR_NUMBER" --body-file <tmpfile>`, then `rm -f` it. The body covers: the base SHA
rebased onto, each conflicted file and the resolution taken, any skipped-as-empty commits, the gate
results, and each PRE-EXISTING failure with its evidence.

### Step 8: Wait for CI (opt-in)

Skipped unless `--watch-ci` was passed; by default the run ends at Step 7 with the PR URL and a
summary. When enabled, reuse the pattern `pm-autofix-pr` already implements rather than inventing a
second one:

1. Probe once: `gh pr checks --help 2>&1 | grep -q -- '--watch'`, and `command -v timeout` falling
   back to `command -v gtimeout` (the name Homebrew's coreutils installs on macOS). Both must
   succeed to use the blocking watch; record the binary as `TIMEOUT_BIN`.
2. Initialize `CI_BUDGET_REMAINING = CI_BUDGET` once, here. Each wait is
   `TIMEOUT_BIN <chunk>s gh pr checks "$PR_NUMBER" --watch --interval <POLL_INTERVAL>` where
   `<chunk>` is `min(CI_BUDGET_REMAINING in seconds, 300)`. Exit 124 means the chunk elapsed with
   checks still pending; exit 0 means they reached a terminal state. Subtract each wait's actual
   elapsed time from `CI_BUDGET_REMAINING`.
3. Without the blocking watch, fall back to `sleep <POLL_INTERVAL>` once per pass plus a
   `gh pr checks "$PR_NUMBER"` re-read, bounded by the same budget.
4. **On budget exhaustion, exit degraded, not silently:** post a PR comment naming what was rebased,
   which checks are still pending, and the exact resume command (`/rebase-pr <n> --watch-ci`), then
   stop with `exit reason: ci-timeout`.

## Failure Modes

| Situation | Handled in | Exit reason |
|-----------|------------|-------------|
| `gh` missing or unauthenticated | Step 0 | stop at preflight |
| Dirty worktree, or a rebase already in progress | Step 0 | `dirty-worktree` |
| No open PR for the branch, or several | Step 1 | stop, no guess |
| Another writer pushed before the rebase started | Step 2, exit 4 | `concurrent-writer` |
| Conflict cannot be resolved confidently | Step 4 | `rebase-conflict` (after `git rebase --abort`) |
| Gate red from a regression that resists fixing | Step 6 | `gate-failure` (no push) |
| Remote head moved while the rebase ran | Step 7, exit 4 | `concurrent-writer` |
| Push rejected despite a valid lease | Step 7, exit 5 | `push-failure` |
| CI still pending when the budget runs out | Step 8 | `ci-timeout` (degraded comment posted) |

## Consistency With the Sibling PR Skills

Two conventions are shared with `pm-autofix-pr` so the three PR workflows do not drift; when either
changes there, change it here too.

- **`gh`-first, MCP-optional** (issue #44): the command table above is `gh` only, and a GitHub MCP
  server is never a precondition. `pm-autofix-pr`'s "GitHub CLI Commands Used" section is the
  reference implementation.
- **Bounded CI waiting** (issue #45): Step 8's probe, 5-minute watch chunks, single run-wide budget,
  and degraded-exit comment mirror `pm-autofix-pr` Step 0b / Step 5f / Step 7. This skill keeps the
  wait opt-in and single-phase — it has no fix loop to re-enter, so it needs no per-push clock.

`pm-autofix-pr` resolves base-branch conflicts by **merging the base in** (no force-push, history
preserved for reviewers). This skill rebases and force-pushes. Pick by what the PR needs: merge when
review is in flight and the history is being read, rebase when a linear history is wanted and the
branch is safe to rewrite.
