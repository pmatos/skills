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
| Resolve the PR for the current branch | `gh pr list -R "$PR_REPO" --head <branch> --state open --json number,headRefName,headRepository,headRepositoryOwner,baseRefName,url` |
| Read PR head/base/mergeability | `gh pr view <n> -R "$PR_REPO" --json number,headRefName,baseRefName,mergeable,headRepository,headRepositoryOwner,url,title` |
| Report what was rebased | `gh pr comment <n> -R "$PR_REPO" --body-file <tmpfile>` |
| Wait for post-push CI (opt-in) | `gh pr checks <n> -R "$PR_REPO" --watch --interval <POLL_INTERVAL>` |

Every call passes `-R "$PR_REPO"` explicitly (resolved in Step 1) rather than relying on `gh`'s
ambient repo resolution. On a checkout with several GitHub remotes and no `gh repo set-default`,
ambient resolution can **prompt** for the base repository — and this skill has no way to answer a
prompt. `pm-autofix-pr` Step 1 documents the same hazard at greater length.

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

1. `BRANCH=$(git rev-parse --abbrev-ref HEAD)`. A detached HEAD stops the run. Also capture the
   **tracked** head name, which is what GitHub knows the branch as:
   `TRACKED=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)` → strip the
   leading `<remote>/`. The two differ whenever the local branch was renamed (`review-42` tracking
   `origin/feature`), a configuration Step 2 explicitly supports.
2. Parse `git remote get-url origin` into `ORIGIN_OWNER` / `ORIGIN_REPO` (strip `git@github.com:`,
   `https://github.com/`, and a trailing `.git`). If an `upstream` remote exists, parse it the same
   way into `UPSTREAM_OWNER` / `UPSTREAM_REPO`.
3. **If a PR number was given**, resolve which repository it belongs to before reading it. A PR
   number is scoped to the repository the PR was opened against — the **base** repository, which in
   a fork checkout is `upstream`, not `origin`. Try candidates in order, taking the first that
   returns the PR, and set `PR_REPO` to whichever answered: `<UPSTREAM_OWNER>/<UPSTREAM_REPO>` (if an
   `upstream` remote exists), then `<ORIGIN_OWNER>/<ORIGIN_REPO>`. Querying the fork first is not
   merely a miss: if the fork carries its own PR of that number, `gh` returns that unrelated PR and
   every later step binds to *its* `HEAD_REF` / `BASE_REF`. The argument may also be given as
   `owner/repo#N` or a full PR URL, which names the repository outright and skips the candidate
   order — prefer it when in doubt. Read the PR with
   `gh pr view <n> -R "$PR_REPO" --json number,headRefName,baseRefName,mergeable,headRepository,headRepositoryOwner,url,title`,
   then validate that `headRepository.nameWithOwner` matches a local remote (item 5); if it matches
   none, stop rather than pushing somewhere unverified.

   **Otherwise** look it up. Query **both** candidate repositories and require exactly one match
   across their combined results — do **not** stop at the first that answers. A fork branch can carry
   a PR against the fork *and* a PR against upstream at the same time; `-R` scopes each query to one
   repository, so an origin-first-and-stop order silently selects the fork-local PR, takes `BASE_REF`
   from it, and then Step 7 force-pushes the shared head branch — rewriting the upstream PR onto the
   wrong base, with the lease raising no objection because the head branch never moved. Combining
   costs nothing when the two candidates are distinct repositories — a PR appears only in its own
   base repository's list — and the ordinary upstream-only fork still yields exactly one match. Two
   matches from *distinct* base repositories means genuine
   ambiguity — stop and say so, as below.

   **Deduplicate the candidates before querying.** `origin` and `upstream` frequently name the *same*
   repository — a maintainer who cloned the base repo directly and also added an `upstream` alias for
   it. Both queries would then return the identical PR, the combined count would be two, and
   discovery would stop as falsely ambiguous on the most ordinary setup there is. Compare the two
   `owner/repo` pairs (case-insensitively — GitHub owner and repository names are not
   case-sensitive) and query the second only if it differs. As a belt-and-braces measure, deduplicate
   the combined matches by `(base repository, PR number)` before applying the exactly-one rule — that
   same dedupe also absorbs the case where `$BRANCH` and `$TRACKED` both match the one real PR.
   **Query both branch names, too.** `gh pr list --head` filters on the PR's *head branch* and does
   not translate a local alias, so a renamed checkout searched by `$BRANCH` alone finds nothing and
   the run stops — even though the skill supports that configuration. Query `$BRANCH` **and**
   `$TRACKED` when they differ, and let the same dedupe and exactly-one rule adjudicate. Union rather
   than replace: `git checkout -b foo origin/main` leaves `@{u}` pointing at `main`, and querying
   `--head main` *instead of* `foo` could match a stranger's PR against the default branch. The
   `headRepository.nameWithOwner` filter below still applies to every result.
   - **Origin.** Set `PR_REPO = <ORIGIN_OWNER>/<ORIGIN_REPO>`, then
     `gh pr list -R "$PR_REPO" --head <name> --state open --json number,headRefName,headRepository,headRepositoryOwner,baseRefName,url`
     for each of `$BRANCH` / `$TRACKED`,
     then **keep only PRs whose `headRepository.nameWithOwner` equals `PR_REPO`** (compose it from
     `headRepositoryOwner.login` + `headRepository.name` if your `gh` predates `nameWithOwner`). That
     filter is load-bearing, not belt-and-braces: `--head` matches on branch name alone (`gh` rejects
     the `owner:branch` qualifier), and a base repository's PR list includes every cross-repository PR
     opened from a fork — so an unfiltered lookup can return a stranger's PR whose head branch merely
     shares a name with yours. Rebasing and force-pushing someone else's PR is not a recoverable
     mistake. Match the full `owner/repo` pair, not the owner alone: one account can own several
     repositories with the same branch name, and the owner-only test cannot tell them apart.
   - **Upstream (fork checkout).** If an `upstream` remote exists **and names a different repository
     than `origin`**, run this query too — regardless of whether the origin lookup matched. Set `PR_REPO = <UPSTREAM_OWNER>/<UPSTREAM_REPO>` and repeat
     the query — but now filter `headRepository.nameWithOwner` against the **origin** pair
     (`ORIGIN_OWNER/ORIGIN_REPO`), since the head branch lives in your fork, not in the base
     repository `PR_REPO` now names.

   Zero matches across both queries, or more than one, → stop and say so; never guess. On exactly one
   match, set `PR_REPO` to the repository whose query produced it.
4. Capture `PR_NUMBER`, `HEAD_REF` (`headRefName`), and **`BASE_REF` (`baseRefName`) — the base branch
   is whatever the PR says it is, not a hardcoded `main`.**
5. Resolve the two remotes by matching `git remote -v` URLs (strip `git@github.com:`,
   `https://github.com/`, and a trailing `.git`):
   - `PUSH_REMOTE` — the remote **every** endpoint of which resolves to
     `headRepository.nameWithOwner`, the **full owner/repo pair** of the head repository. Check both
     sides, and enumerate each — `git remote get-url --all <r>` (fetch) and
     `git remote get-url --push --all <r>` (push): a remote may have several `remote.<r>.url` or
     `remote.<r>.pushurl` entries, `git push` writes to **all** of the effective ones, and without
     `--all` git prints only the first, so a single-URL check inspects one of N destinations while
     claiming to have validated the remote. Require every listed URL to match, or reject the remote
     outright. Getting this wrong is not a clean failure: `safe-force-push.sh` pushes by remote name,
     so the intended repository is rewritten and the *second* destination rejects — Step 7 then
     reports exit 5 "push rejected" over a rewrite that already published. `git remote -v` prints a `(fetch)` and a `(push)` row per remote, and with
     `remote.<r>.pushurl` set they name *different* repositories; matching either row alone can
     select a remote that pushes to the fork but fetches from upstream. The two endpoints are used by
     different halves of the lease: the scripts fetch the branch through the fetch URL to capture and
     compare the anchor, while the rewrite goes out through the push URL. A split remote is
     fail-safe rather than destructive — a missing branch exits 2, a foreign same-named upstream
     branch exits 3 or 4, and git's own `--force-with-lease=<branch>:<sha>` check rejects a
     tag-or-stranger-derived anchor as stale info — but the diagnosis is misleading, so validate up
     front. `BASE_REMOTE` below is fetch-only, so only its normal URL needs to resolve to the base
     repository. This is where the force-push goes; for a fork PR it is
     the fork, not the base repository. Matching on the owner alone is not enough: the same account
     may have several remotes here, and if two of their repositories carry a branch of this name the
     lease would be captured against — and the push aimed at — the wrong one, safely overwriting a
     branch that has nothing to do with this PR. If no remote matches the pair, stop rather than
     guessing; a lease is only as meaningful as the ref it is armed against.
   - `BASE_REMOTE` — the remote holding the base repository. For a same-repo PR both are `origin`.
     If no local remote points at the base repository, use its clone URL
     `https://github.com/<base_owner>/<base_repo>.git`; `git fetch` accepts a URL in place of a name.
6. The local branch **name** need not match `HEAD_REF` — a fork checkout often names it differently,
   and Step 7 targets `HEAD_REF` on `PUSH_REMOTE` explicitly. What must be established is that this
   checkout **is** the PR branch, which Step 2 verifies: descending from the PR head is not proof of
   being it. A follow-up branch cut from the PR tip descends from it too, and force-pushing that HEAD
   would publish commits the PR never contained — with the lease raising no objection, since the
   remote has not moved.

### Step 2: Capture the lease anchor, then fetch the base

```bash
scripts/capture-lease.sh "$PUSH_REMOTE" "$HEAD_REF"
```

stdout is `EXPECTED_REMOTE_SHA`. Act on the exit code:

- **0** — the local tip equals the remote head. Proceed.
- **3** — the local branch is strictly ahead (unpushed local commits) **and** tracks
  `<PUSH_REMOTE>/<HEAD_REF>`, so it really is the PR branch. Proceed, and say in Step 7's comment
  that the push also published those commits.
- **5** — HEAD is ahead of the PR head but this checkout does not track it: it is a different branch
  that merely descends from the PR tip. **Stop** with `exit reason: branch-mismatch`. Check out the
  PR head first (`gh pr checkout <n>`) and re-run; do not push a HEAD whose identity as the PR branch
  was never established.
- **4** — the local branch is behind or has diverged: another writer pushed to this branch. **Stand
  down.** Report their commits (the script prints the range) and stop. Do not reset, do not
  fast-forward silently — reconciling someone else's commits with the local ones is the user's call.
- **2** — usage error, missing remote branch, or an unreachable remote. Relay stderr and stop.

Record `EXPECTED_REMOTE_SHA` and `ORIGINAL_HEAD=$(git rev-parse HEAD)`. Then fetch the base:

```bash
git fetch "$BASE_REMOTE" "refs/heads/$BASE_REF"
BASE_SHA=$(git rev-parse FETCH_HEAD)
```

**`refs/heads/` is not optional.** A bare `"$BASE_REF"` is a refspec, and git's ref-resolution rules
try `refs/tags/` **before** `refs/heads/` — so in a repo carrying a tag named like the base branch,
`git fetch <remote> main` writes the *tag's* commit to `FETCH_HEAD` (`* tag main -> FETCH_HEAD`;
reproduced on git 2.55). `BASE_SHA` would then be the tag, Step 4 would rebase the PR onto it, and
Step 7's lease would raise no objection — the head branch never moved. The PR gets silently rewritten
onto the wrong history, which is also what would break Step 4's claim that rebasing `$BASE_SHA` pins
the operation to what Step 2 fetched. Both bundled scripts fetch `refs/heads/<branch>` for the same
reason.

### Step 3: Discover the quality gate

Read the project's own instructions first — `CLAUDE.md` / `AGENTS.md`. Collect them from **two**
directions, because either alone misses real rules:

- **Baseline:** walk from the working directory up to the repo root.
- **Scoped:** list the paths this PR actually changes,
  `git diff --name-only "$BASE_SHA"...HEAD`, and for each one walk *its* directory up to the repo
  root, collecting every `CLAUDE.md` / `AGENTS.md` on the way. Deduplicate (symlink-aware —
  `AGENTS.md` is frequently a symlink to `CLAUDE.md`).

The upward-only baseline is what misses a monorepo: run from the repo root, it never descends into
`packages/foo/AGENTS.md`, so a PR touching only that package would be gated by root-level checks
while the package's own mandated checks never run — and then force-pushed. The changed-path walk is
what finds them.

Merge with **closest-wins** precedence: the repo-root file is the baseline, a nearer file overrides
it on conflict and may add checks the baseline omits. When a scoped file changes or adds a command,
surface a one-line divergence note — which file, which command — so the gate stays auditable rather
than silently flattened. Use exactly the commands these files state. Only if they state none, infer
from the manifests:

| Manifest | Gate commands (run in this order, separately) |
|----------|-----------------------------------------------|
| `package.json` | the `format`/`lint`/`typecheck`/`test`/`build` scripts that exist, via the lockfile's package manager (`npm run`, `pnpm`, `yarn`) |
| `pyproject.toml` | `uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check`, `uv run pytest` — or the `hatch`/bare-`pytest` equivalents when `uv.lock` is absent |
| `Cargo.toml` | `cargo fmt --check`, `cargo clippy`, `cargo test`, `cargo build` |
| `go.mod` | `gofmt -l .`, `go vet ./...`, `go test ./...`, `go build ./...` — `gofmt -l` recurses, but exits **0** even when it lists unformatted files, so judge that step by its output, not its exit status |
| `Makefile` | whichever of `make fmt`, `make lint`, `make test`, `make check`, `make ci` exist |
| `.pre-commit-config.yaml` | `pre-commit run --all-files` |

**Re-run this discovery after Step 4's rebase** whenever the replayed base brought in a new or
changed `CLAUDE.md` / `AGENTS.md` (`git diff --name-only "$ORIGINAL_HEAD" HEAD -- '*CLAUDE.md' '*AGENTS.md'`
is enough to tell). This walk reads the *checked-out* tree, which at Step 3 is still the pre-rebase
PR branch — so a package's instruction file that the **base** added after the PR diverged is
invisible here, and the gate would run without the checks that file mandates before the branch is
force-pushed. That is the same failure the paragraph above argues against, arriving from the other
direction. Post-rebase discovery is a strict superset: it sees base-added *and* PR-added instruction
files, which reading them from `BASE_SHA` alone would not.

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
   - `git grep -nE '^(<{7}|\|{7}|={7}|>{7})( |$)' -- <resolved paths>` — no hits. The `|||||||`
     alternative matters: under `merge.conflictStyle = diff3` or `zdiff3` git emits a base section
     delimited by it, and a pattern covering only the other three markers passes a resolution that
     still carries the base text.
   If any fails, go back to item 1 rather than continuing over a half-resolved tree.
6. `GIT_EDITOR=true git rebase --continue`. The override is mandatory: a real editor has nothing to
   attach to in a headless run and the command would hang. **No git invocation in this skill may open
   an editor** — bare `git rebase -i` is therefore forbidden, and the one place a todo list is needed
   (Step 6's autosquash) stubs both `GIT_EDITOR` and `GIT_SEQUENCE_EDITOR`.
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

- **REGRESSION** — the rebase caused it. Fix it and `git add` the fix. If it belongs to the branch
  tip, `git commit --amend --no-edit`. If it belongs to an **earlier** commit, do not reach for
  `git rebase -i` — it opens an editor and hangs. Use the non-interactive equivalent:

  ```bash
  git commit --fixup=<sha>
  GIT_SEQUENCE_EDITOR=true GIT_EDITOR=true git rebase --autosquash "$BASE_SHA"
  ```

  (On git older than 2.45, `--autosquash` needs `--interactive` alongside it; with
  `GIT_SEQUENCE_EDITOR=true` accepting the already-reordered todo list, that stays non-interactive.)
  Squashing into an earlier commit replays the branch, so re-run the failing gate command afterwards
  — and if it conflicts, Step 4's conflict rules apply unchanged. Adding a plain follow-up commit is
  always an acceptable alternative when the fix does not belong to any single commit.
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
`gh pr comment "$PR_NUMBER" -R "$PR_REPO" --body-file <tmpfile>`, then `rm -f` it. The body covers: the base SHA
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
   `TIMEOUT_BIN <chunk>s gh pr checks "$PR_NUMBER" -R "$PR_REPO" --watch --interval <POLL_INTERVAL>`
   where `<chunk>` is `min(CI_BUDGET_REMAINING in seconds, 300)`. Classify **every** exit status —
   `timeout` passes the child's status through unchanged, and here the status *is* the signal:

   | Exit | Meaning | Action |
   |------|---------|--------|
   | `0` | every check finished successfully | terminal — done |
   | `124` | the chunk elapsed with checks still pending | keep waiting if budget remains |
   | `8` | checks still pending (the non-watch read in item 3 reports this) | keep waiting if budget remains |
   | any other nonzero | **unknown — do not guess** | terminal for the wait: re-read `gh pr checks "$PR_NUMBER" -R "$PR_REPO" --json name,state,bucket,link` and let *that* decide (see below) |

   The nonzero row deliberately does not name a cause, because the status alone cannot distinguish
   one. `gh help exit-codes` gives `1` for *any* failure and `4` for "authentication required"; `2`
   is a cancelled command; and since the call is wrapped in `TIMEOUT_BIN`, that binary's own `125` /
   `126` / `127` surface here too. A repo with no CI at all exits `1` ("no checks reported on the …
   branch"). So decide from the re-read, not from the number.
   Classify on the `bucket` field, which `gh` documents as categorizing `state` into `pass`, `fail`,
   `pending`, `skipping`, or `cancel` — `state` alone carries no pending discriminator, and throwing
   that signal away is what would let the wait end before CI ran:

   - Any check in `bucket: fail` → **`exit reason: ci-failed`**, naming them.
   - No failures but any check in `bucket: pending` → **not terminal.** Keep waiting while budget
     remains; only on exhaustion is this `ci-timeout`. (The exit-`8` row above already treats pending
     this way; the re-read must agree with it.)
   - Every check terminal (`pass` / `skipping` / `cancel`) and none failing → terminal success.
     `cancel` groups here deliberately: `gh` exits nonzero only on failed or pending counts, so a
     cancel-only rollup already exits `0` and ends the wait via the table's exit-`0` row without ever
     reaching this re-read — classifying it as unsuccessful here would make the two paths contradict
     each other. It also matches `pm-autofix-pr`, where `cancelled` is the one non-success conclusion
     treated as informational. This wait decides terminality, not merge-readiness.
   - No checks reported at all → **not yet conclusive.** This is the ordinary push-to-registration
     race: `gh` exits 1 with "no checks reported" until the workflows register. Allow a bounded grace
     period — `min(2 × POLL_INTERVAL, CI_BUDGET_REMAINING)` — re-reading across it, and only declare
     **`exit reason: no-checks`** if the set is still empty when it elapses. The rebase and push have
     already succeeded either way; there is simply nothing to wait for.
   - The re-read itself fails (auth expired, API unreachable, `gh` broken) → **`exit reason:
     gh-unavailable`**, quoting `gh`'s stderr. Never report failing checks the re-read did not show.

   Distinguishing pending is also what keeps this aligned with `pm-autofix-pr`, which gates on a
   terminal `.conclusion` per check run rather than on the absence of failures.

   What must not happen is the wait treating a red CI run as "still pending" and reporting a budget
   timeout instead. (`pm-autofix-pr` can ignore the exit status because it treats the watch as a pure
   sleep replacement and always re-fetches authoritative state afterwards; Step 8's re-read plays the
   same role here — the status only decides *when* to stop waiting, never *what happened*.)

   Subtract each wait's actual elapsed time from `CI_BUDGET_REMAINING`.
3. Without the blocking watch, fall back to one `sleep` per pass plus a
   `gh pr checks "$PR_NUMBER" -R "$PR_REPO"` re-read, applying the same exit classification as the
   table above. Sleep `min(POLL_INTERVAL, CI_BUDGET_REMAINING)`, not a flat `POLL_INTERVAL` — an
   unclamped final sleep overshoots the advertised ceiling by up to one interval.
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
| HEAD descends from the PR head but is not the PR branch | Step 2, exit 5 | `branch-mismatch` |
| Conflict cannot be resolved confidently | Step 4 | `rebase-conflict` (after `git rebase --abort`) |
| Gate red from a regression that resists fixing | Step 6 | `gate-failure` (no push) |
| Remote head moved while the rebase ran | Step 7, exit 4 | `concurrent-writer` |
| Push rejected despite a valid lease | Step 7, exit 5 | `push-failure` |
| CI red on the rebased branch | Step 8 | `ci-failed` (failing checks named) |
| The branch has no CI checks at all | Step 8 | `no-checks` (rebase and push already succeeded) |
| `gh` cannot report check state (auth, API, broken CLI) | Step 8 | `gh-unavailable` (stderr quoted) |
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
