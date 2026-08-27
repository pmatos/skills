---
name: pm-autofix-pr
description: This skill should be used when the user asks to "autofix pr", "fix pr locally", "fix ci failures", "fix review comments", "iterate on pr", "fix failing checks", "fix pr comments", "make ci green", "fix the build", "address reviewer feedback", or wants to iteratively fix CI failures and review comments on a GitHub PR from the local CLI.
user-invocable: true
---

# Autofix PR

Iteratively fix CI failures and address reviewer feedback on a GitHub PR until a true fixed point is reached — all CI green, the PR free of merge conflicts with its base branch, every feedback item triaged into one of three outcomes (FIX, DEFER, REJECT), and every feedback item has a reply documenting the outcome. A single invocation handles everything end-to-end without user input.

## Core Principle: Three Outcomes per Feedback Item

Not every review comment deserves a code change in this PR, and not every rejected comment is worthless. Before touching code, evaluate every review thread, review summary, and PR conversation comment on its merits with two independent AI reviewers — the **local host model** (whichever harness you are running in) and a **cross-harness model** (Claude ↔ Codex; whichever one you are not). Each item is triaged into exactly one of:

- **FIX** — correct **and** in scope for this PR → change the code in this PR, reply with the commit.
- **DEFER** — correct but out of scope, or a minor/diminishing-returns nit not worth churn in this PR → file a tracking issue, reply on the PR with a link to the new issue.
- **REJECT** — wrong, unrelated, already-handled, or pure style preference with no project backing → reply with a rationale, no code change, no issue.

DEFER is the safety valve that lets the skill say "not now" to legitimate-but-low-value feedback without losing it. Use it for: pickiness on naming/style where the current code is reasonable, micro-optimizations, refactor requests for working code, doc requests for internal helpers, and anything correct but outside the PR's stated scope.

## Core Principle: Always Reply

Every reviewer feedback item must get an explicit reply before the skill can converge. FIX gets a reply that says what was fixed, where it was fixed, and the commit that contains it. DEFER gets a reply with the rejection rationale plus a link to the filed tracking issue. REJECT gets a reply that says no code change was made and why. A missing reply is still unfinished work, even if the code and CI are already green.

## Core Principle: Never Prompt the User

This skill runs end-to-end without asking the user anything once invoked. There is no "begin fixing?" confirmation, no "ambiguous feedback, how should I handle it?", no "pre-commit failed, retry?", no "merge conflict, resolve it?", no "stale loop, continue?", no "CI timeout, keep waiting?". Every decision point has a deterministic auto-action defined below; uncertain feedback defaults to DEFER (file an issue and let humans resolve later); merge conflicts with the base branch are auto-resolved by merging the base in (Step 5h); unrecoverable conditions exit cleanly with a final summary. The only way the skill stops mid-flight is by reaching the fixed point, hitting a hard precondition failure (missing/unauthenticated `gh`, missing cross-harness CLI, no PR for the branch), or hitting an unrecoverable error (unresolvable merge conflict, rebase conflict, persistent push failure). Each exit goes through Step 7's summary.

## Prerequisites

- **`gh` CLI** must be installed and authenticated (`gh auth status`). This is now the primary path for all GitHub interaction, including fetching failed-job log tails (`gh run view --job <id> --log-failed`, still the only way to get raw Actions log output). The skill stops at preflight if `gh` is missing or unauthenticated.
- **GitHub MCP server** is optional. If one happens to be connected in the host session, use it opportunistically for thread resolution — the one operation where it's a genuinely better fit than `gh` (see "GitHub CLI Commands Used" below). Its absence never blocks the skill. (Comment/reply posting always goes through `gh` — see the note under "GitHub CLI Commands Used" for why.)
- **Both harness CLIs** must be installed: `claude` (Claude Code, `npm install -g @anthropic-ai/claude-code`) and `codex` (Codex CLI, `npm install -g @openai/codex`). The dual-evaluator step calls whichever one is *not* the host. The skill stops at preflight if the cross-harness CLI is missing.

## Configuration

Override via prompt arguments (e.g., `/pm-autofix-pr 10 --ci-timeout 30 --monitor 0`).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `TOTAL_CI_BUDGET` | 15 | Overall wall-clock ceiling (minutes) on **all** CI-wait (Step 5f) + monitoring (Step 6) time for the whole run, initialized once at run start (Step 0b) — not reset by later pushes or monitoring cycles. `CI_TIMEOUT` and `MONITOR_DURATION` below remain the per-phase bounds, but each wait is clamped to whichever of `TOTAL_CI_BUDGET` or the per-phase bound remains, whichever is smaller. Once it reaches zero, the run aborts through Step 7 with `ci-timeout` (which also posts a resume-pointer PR comment — see Step 7) regardless of how recently the last commit was pushed or how many fix/push cycles happened inside it. |
| `MONITOR_DURATION` | 10 | Minutes to watch for new issues after convergence. 0 to skip. Also bounded by whatever of `TOTAL_CI_BUDGET` remains. |
| `CI_TIMEOUT` | 20 | Minutes to wait for CI before aborting (no user prompt — exits through Step 7 with `ci-timeout`). Also bounded by whatever of `TOTAL_CI_BUDGET` remains — with the defaults above, `TOTAL_CI_BUDGET` (15) binds first. |
| `POLL_INTERVAL` | 30 | Seconds between PR-state re-fetches while waiting for CI or monitoring; also the `--interval` passed to `gh pr checks --watch` where supported (see Step 5f). |
| `LOG_TAIL_LINES` | 500 | Lines of CI failure log to inspect. |

There is no iteration limit. The loop runs until one of: fixed point reached, stale loop detected, CI timeout (per-push or total budget exhausted), unresolvable merge conflict, rebase conflict, persistent push failure, or monitoring window elapsed. Every exit goes through Step 7. The skill never prompts the user.

## GitHub CLI Commands Used

`gh` / `gh api` is the primary path for all GitHub interaction — no bundled scripts. A GitHub MCP server, if already connected in the session, may be used as an opportunistic fast path for the one operation marked below; never wait for or require one. All comment/reply posting always goes through `gh`, even when an MCP is connected — see the note below the table for why.

`<tmpfile>` and `<titlefile>` below always mean a file allocated via `mktemp` for that specific write (e.g. `mktemp /tmp/reply-body-XXXXXX`) — never a fixed literal path. Two concurrent `/pm-autofix-pr` invocations on the same host would otherwise race on a shared filename, letting one invocation's generated body or title get overwritten by the other's before `gh` reads it. Capture the exact path `mktemp` returns, reuse it across the write and the `gh` call, then `rm -f` it afterward — the same discipline Step 0a already uses for evaluator prompt files.

| Operation | Primary (`gh`) | Opportunistic MCP fast path |
|------|-----------------|------------------------------|
| Preflight / current user | `gh auth status`; `gh api user -q .login` for `GH_USER` | — |
| Auto-detect the PR for the current branch | `gh pr list -R {owner}/{repo} --json number,headRefName,url --head <branch>` (see Step 1) | — |
| Fetch PR details and mergeability | `gh api repos/{owner}/{repo}/pulls/{n}` (`mergeable`, `mergeable_state`, `head.sha`, `base.ref`, …) | — |
| Fetch CI check runs | `gh api repos/{owner}/{repo}/commits/{sha}/check-runs` | — |
| Fetch review threads (with resolution state) | `gh api graphql` — REST has no `isResolved` field, so this one needs GraphQL regardless of MCP (see `references/api-patterns.md`) | — |
| Fetch review summaries | `gh api repos/{owner}/{repo}/pulls/{n}/reviews` | — |
| Fetch PR conversation comments | `gh api repos/{owner}/{repo}/issues/{n}/comments` | — |
| Reply on an inline review thread | `gh api repos/{owner}/{repo}/pulls/{n}/comments/{id}/replies -F body=@<tmpfile>` (body written to a temp file first, so no shell-escaping of the reviewer-authored text is needed — no `jq` or other extra binary required) | — |
| Reply on a review summary / PR conversation comment | `gh pr comment <n> -R {owner}/{repo} --body-file <tmpfile>` / `gh issue comment <n> -R {owner}/{repo} --body-file <tmpfile>` | — |
| Resolve a review thread after a fix | `gh api graphql` — `resolveReviewThread` mutation (GraphQL-only; no REST equivalent) | MCP's thread-resolve method, if connected — same GraphQL mutation under the hood |
| File a tracking issue (DEFER outcome) | `gh issue create -R {owner}/{repo} --title "$(cat <titlefile>)" --body-file <tmpfile>` | — |

**Why posting never uses MCP, even opportunistically:** `GH_USER` (used for all self-authored-comment filtering) is captured from `gh api user`. If a connected MCP server posts a comment under a *different* authenticated identity, that reply would never be recognized as self-authored on a later re-fetch — the skill could then evaluate and reply to its own past outcome messages indefinitely, breaking convergence. Since `gh api -F body=@<tmpfile>` / `gh pr comment --body-file <tmpfile>` already avoid the shell-escaping problem MCP's typed body field solved, MCP's only remaining advantage for posting was skipping a temp file — not enough to justify the risk. Thread resolution has no such coupling (it authors no content attributable to an identity), so it keeps the MCP fast path.

See `references/api-patterns.md` for exact commands, JSON shapes, and pagination/vocabulary notes.

## Workflow

### Step 0a: Detect the host harness

This skill runs under either Claude Code or Codex CLI. The orchestrator (you) is the **local host**; the dual-evaluator step delegates the second opinion to the **cross-harness** CLI.

Self-identify before doing anything else:

- If you are Claude (Opus / Sonnet / Haiku) → host is **`claude`**, cross-harness is **`codex`**.
- If you are Codex (GPT-5.x) → host is **`codex`**, cross-harness is **`claude`**.

Verify the cross-harness CLI is installed: run `command -v <cross-harness-binary>` via Bash. If it's missing, **stop immediately** with:

> **`<cross-harness>` CLI not installed.** This skill needs both harnesses to run the dual-evaluator step. Install it with `npm install -g @anthropic-ai/claude-code` (Claude) or `npm install -g @openai/codex` (Codex), then re-run.

Capture for use in evaluator prompts and rejection bodies:

- `LOCAL_LABEL` — e.g. `"Claude Opus 4.6"` or `"Codex GPT-5.4"`. Use the most specific identifier you know about yourself; fall back to the family name (`"Claude"`, `"Codex GPT-5.x"`) if unsure.
- `REMOTE_LABEL` — the cross-harness model label. Same precision rule.

Per-host invocation table (referenced by Step 4):

| Host | Local Evaluator (clean-context spawn of own model) | Cross-harness Evaluator |
|------|---------------------------------------------------|-------------------------|
| `claude` | Agent tool with `model="opus"` | Skill tool with `skill="codex-2nd-opinion"` |
| `codex` | Bash: `codex exec --sandbox read-only --ephemeral - < /tmp/eval-XXXX` (10-min timeout) | Bash: `claude -p --permission-mode auto --output-format text < /tmp/eval-XXXX` (10-min timeout) |

For Bash-based evaluator spawns, write the prompt to a `mktemp /tmp/eval-XXXXXX` file, run the command with stdin redirection, capture stdout, then `rm -f` the temp file.

### Step 0b: Preflight — verify `gh`

Run `gh auth status`. If it exits non-zero (not installed, not authenticated, or unreachable), **stop immediately** with this message:

> **`gh` CLI not available.** This skill requires the GitHub CLI (`gh`), authenticated. Install it from <https://cli.github.com/> and run `gh auth login`, then re-run.

Then capture `GH_USER` via `gh api user -q .login` (used to filter out self-authored comments later — see the `[bot]`-suffix note in `references/api-patterns.md` when comparing this login against GraphQL-sourced `author.login` values).

Also initialize `TOTAL_CI_BUDGET_REMAINING` to `TOTAL_CI_BUDGET` minutes here — run-scoped state captured once at the start of the run, like `GH_USER`, not on first entry into Step 5f. This matters because some runs never enter Step 5f at all: Step 3's "nothing to fix" path goes straight to Step 6, and Step 5d's "no commits this iteration" path skips to Step 5g and from there can also reach Step 6 — both would reference an uninitialized counter if the budget were only set up inside Step 5f's own prose.

For the same reason, also probe here — once, not per-iteration and not inside Step 5f's own prose — whether Step 5f's waiting primitive (item 1) can use a blocking watch: run `gh pr checks --help 2>&1 | grep -q -- '--watch'` **and** check for a `timeout`-equivalent binary (`command -v timeout` first, falling back to `command -v gtimeout`, the name Homebrew's coreutils installs on stock macOS). Record the result as `WATCH_USABLE` (true only if both checks pass) and, when true, the resolved binary name as `TIMEOUT_BIN`. Both Step 5f and Step 6 read these once-per-run values; neither re-probes, including on the Step 3 → Step 6 direct path that never visits Step 5f.

Also initialize `ALL_COMMITTED_ITEMS = []` here, for the same reason `TOTAL_CI_BUDGET_REMAINING` lives here rather than in Step 3: it is a run-wide accumulator (one entry per successful FIX commit across every iteration, appended to in Step 5b, consumed by Step 7's budget-exhaustion comment) that must persist and only grow for the whole run — unlike the other lists Step 3 (re)initializes below, which are safely re-derived from each fetch.

If a GitHub MCP server happens to be connected in this session, note it for opportunistic use later (thread resolution only — see "GitHub CLI Commands Used" below); its absence is not a preflight failure and no check for it is needed here.

### Step 1: Identify the PR

`gh`'s own ambient repo resolution (bare `gh pr view`, no `-R`) can be ambiguous on a checkout with multiple GitHub remotes and no `gh repo set-default` — in the worst case `gh` prompts for the base repository, which this skill can never do (Never Prompt the User). So every tier below except the deliberate last-resort (3c) resolves and passes an explicit `-R {owner}/{repo}` rather than relying on ambient resolution.

1. Get the current branch: `git rev-parse --abbrev-ref HEAD`.
2. If a PR number was provided as argument, resolve its repo the same way as 3a (derive `{owner}/{repo}` from `origin`), then call `gh api repos/{owner}/{repo}/pulls/<n>` (if the resolved PR's `head.ref` doesn't match the local branch, warn and continue with the user's explicit number). Then **skip the auto-detect in step 3 and go straight to step 4** so the same validation and base capture (`base.ref`, `base.repo`, `BASE_REMOTE`) runs — otherwise Step 5h's `git fetch <BASE_REMOTE> <base.ref>` would run with `BASE_REMOTE` unset even for a same-repo PR.
3. Auto-detect the PR. Try the following resolution strategies in order and stop at the first that yields exactly one open PR whose `head.ref` matches the local branch:
   - **3a. Origin lookup.** Parse `git remote get-url origin` to `{owner}/{repo}` (strip `git@github.com:`, `https://github.com/`, trailing `.git`). Run `gh pr list -R {owner}/{repo} --head <branch> --state open --json number,url,headRefName,baseRefName,headRepositoryOwner`, then **keep only PRs whose `headRepositoryOwner.login` equals `{owner}`** (the owner just parsed from `origin`). This filter is load-bearing, not belt-and-braces: `gh pr list`'s `--head` filter matches on branch name only — it does not support the `owner:branch` qualifier (`gh pr list --help`: `"<owner>:<branch>" syntax not supported`) — and `-R` only scopes *which repo's* PR list is searched, not which fork owns each result's head. It is needed at 3a and not only at 3b because `origin` is frequently the base repository itself: a maintainer or push-access contributor who cloned it directly has no `upstream` remote at all, so 3b never runs and 3a is the only tier that fires. A base repository's PR list includes every cross-repository PR opened from a fork, so an unfiltered lookup can return a stranger's PR whose head branch merely happens to share the same name (verified empirically: a single `gh pr list -R <owner>/<repo> --head <branch>` against a busy public repo returned open PRs from several distinct fork owners, all cross-repository). Since Step 4 validates only `head.ref`, an unfiltered match would let the skill fetch, comment on, and triage that stranger's PR whenever the local branch's own PR is absent or closed. A deleted or inaccessible head repository yields an empty/missing `login`, which correctly fails the comparison. If the filter leaves no PRs, treat 3a as "no PR found" and fall through — including the uncommon case where the branch's own PR head lives in a fork registered under some remote name other than `origin`/`upstream`, which 3c exists to catch.
   - **3b. Upstream lookup (fork workflow).** If step 3a returned no PRs *after its owner filter* and `git remote get-url upstream` exists, parse it the same way to `{upstream_owner}/{upstream_repo}` and run `gh pr list -R {upstream_owner}/{upstream_repo} --head <branch> --state open --json number,url,headRefName,baseRefName,headRepositoryOwner`, then **keep only PRs whose `headRepositoryOwner.login` equals `{origin_owner}`** (the owner parsed from `origin` in 3a) — the same filter as 3a, load-bearing for the same reasons stated there. If the filter leaves no PRs, treat 3b as "no PR found" and fall through to 3c.
   - **3c. Ambient `gh pr view` fallback.** If both explicit-remote lookups return nothing (uncommon remote naming, or the base repo isn't reachable via `origin`/`upstream`), run bare `gh pr view --json number,url,headRefName,baseRefName` and let `gh`'s own resolution find it. Parse `{base_owner}/{base_repo}` directly out of the returned `url` (`https://github.com/{owner}/{repo}/pull/{number}`) rather than depending on version-specific JSON field names for the base repository. Treat any non-zero exit (including `gh` being unable to resolve a single unambiguous repo) as "no PR found" — stop and tell the user there is no open PR for the current branch.
4. Validate — **this runs for both the explicit-number path (step 2) and the auto-detected path (step 3)** — by calling `gh api repos/{owner}/{repo}/pulls/<pullNumber>` on the resolved `{owner, repo, pullNumber}` to retrieve `title`, `body`, `head.ref`, `head.sha`, `base.ref`, and `html_url` (the base repository's `full_name` is `{owner}/{repo}`, the same pair just queried). Confirm `head.ref` matches the local branch. Capture `base.ref` for Step 5d's first-push fallback and Step 5h's base-branch merge, and capture **`BASE_REMOTE`** — the fetch source for the *base* repository, which is **not** always `origin`. Resolve it by matching `git remote -v` URLs to `{base_owner}/{base_repo}` (apply the same `git@github.com:` / `https://github.com/` / trailing-`.git` stripping as 3a): `origin` on the 3a origin path, `upstream` on the 3b fork path, and on the 3c path the remote matching the `{base_owner}/{base_repo}` parsed from `url`. If no local remote points at the base repository (common for a fork checkout with no `upstream`), set `BASE_REMOTE` to the base repo's clone URL `https://github.com/{base_owner}/{base_repo}.git` — `git fetch` accepts a URL in place of a remote name, so Step 5h works either way.

### Step 2: Read Project Pre-commit Requirements

Find CLAUDE.md (or AGENTS.md) by walking from working directory to repo root. Extract **only explicitly stated** pre-commit commands: format, lint, type-check, test, build. If none are stated, skip pre-commit checks entirely.

### Step 3: Fetch PR State

Issue these `gh`/`gh api` calls (paginate where applicable) and merge into a single state object. All REST calls below use the `{owner}/{repo}` and `pullNumber` captured in Step 1:

| State field | Source |
|---|---|
| `head_sha`, `base.ref` | `gh api repos/{owner}/{repo}/pulls/<n>` → `.head.sha`, `.base.ref` |
| `has_merge_conflict` | Same call → `.mergeable` (bool or `null`) and `.mergeable_state` (string) — this is the REST vocabulary, distinct from the uppercase `MERGEABLE`/`CONFLICTING` values `gh pr view --json mergeable` returns via GraphQL; use the REST call so this table's vocabulary and the retry logic below stay correct. If `mergeable` is `null`, GitHub is still computing mergeability in the background — re-fetch up to 3 times with a 3-second sleep between tries, and only treat a definitive `true`/`false` as authoritative. Set `has_merge_conflict = true` when `mergeable == false` **or** `mergeable_state == "dirty"` (the PR conflicts with its base branch). Any other terminal state (`clean`, `blocked`, `behind`, `unstable`, `has_hooks`, `unknown`) sets `has_merge_conflict = false` — those don't indicate a content conflict and don't block the fixed point. If `mergeable` is still `null` after the re-fetches, leave `has_merge_conflict = false` but record the indeterminate state in `errors` so Step 5g re-fetches instead of declaring a false fixed point. |
| `ci_failures` | `gh api repos/{owner}/{repo}/commits/<head_sha>/check-runs` → keep entries whose `.conclusion ∈ {failure, timed_out, cancelled, startup_failure, action_required}`. For each `failure` whose `.app.slug == "github-actions"`, mark `fixable=true` and fetch the log tail with the `Bash` command shown just below this table (kept out of the cell so the shell pipe stays a real pipe) — the check run's `.id` here is the job id `gh run view --job` expects. Other failure types are non-fixable — report them. |
| `review_threads` | `gh api graphql` with a `reviewThreads` query (see below and `references/api-patterns.md`) — REST's `pulls/<n>/comments` endpoint has no thread-resolution concept at all (`isResolved` only exists in the GraphQL schema), so this is the one piece of PR state that requires GraphQL regardless of whether an MCP is connected. Paginate `reviewThreads(first: 100, after: $cursor)`. Split into `unresolved = [t for t in threads if not t.isResolved]` and `resolved_thread_ids = [t.id for t in threads if t.isResolved]`. For each unresolved thread, take the last non-self element of `comments(last: 20)` (not `first:` — the goal is the *latest* reviewer comment, and GraphQL connections default to oldest-first; `last: 20` also bounds the query since nested pagination of comments-within-threads isn't practical in one `gh api graphql` call) as `latestReviewerComment`, sorting by `createdAt` if order is not guaranteed and excluding `author.login == GH_USER`. Drop self-only threads whose `latestReviewerComment` is absent from `feedback_items`; they are author notes, not reviewer feedback, and must not be dereferenced later. |
| `review_summaries` | `gh api repos/{owner}/{repo}/pulls/<n>/reviews`. Apply supersession (see below). |
| `pr_comments` | `gh api repos/{owner}/{repo}/issues/<n>/comments`. Drop entries where `.user.login == GH_USER`. |

REST and GraphQL disagree on bot logins: for the same comment, REST's `user.login` carries a `[bot]` suffix (e.g. `"chatgpt-codex-connector[bot]"`) while GraphQL's `author.login` for the identical comment (matched by `databaseId`) omits it (`"chatgpt-codex-connector"`) — verified on a live PR in this repo. `GH_USER` is captured via REST (`gh api user -q .login` in Step 0b) and self-filtering compares it against both REST-sourced logins (`review_summaries`, `pr_comments`) and GraphQL-sourced logins (`review_threads`). Rather than reasoning about which side is which, strip a trailing `[bot]` from **both** `GH_USER` and the login being compared before every self-authorship check — this is cheap, always correct, and avoids depending on which identity type (personal account, GitHub App, Actions bot) `gh` happens to be authenticated as in a given run.

The `ci_failures` log-tail fetch lives here rather than inside the table cell
above: an escaped `\|` renders correctly on GitHub but is a literal argument, not
a pipe operator, when this raw Markdown is executed — so the command is kept in a
fenced block where the pipe stays a real shell pipe.

```bash
gh run view --job <check_run.id> --log-failed 2>&1 | tail -<LOG_TAIL_LINES>
```

**Supersession algorithm for reviews:** group reviews by `user.login`. Within each group, sort by `submitted_at` ascending. Find the index of the latest `APPROVED` or `DISMISSED` review (or -1 if none). Discard everything at or before that index. From the remainder, keep only `CHANGES_REQUESTED` or `COMMENTED` reviews with non-empty `body` and `user.login != GH_USER`. The result is the actionable summary list.

**Errors:** if any `gh`/`gh api` call fails, accumulate the error message into an `errors` list. Do not abort — downstream steps tolerate partial state and re-fetch.

Build `feedback_items` from:
- unresolved review threads with a non-null `latestReviewerComment`, keyed as `thread:<thread.id>`
- `review_summaries`, keyed as `review:<review.id>`
- `pr_comments`, keyed as `comment:<comment.id>`

Initialize `ADDRESSED_THREAD_IDS` with `resolved_thread_ids`. Initialize `REPLIED_ITEM_KEYS = {}` for review summaries and PR conversation comments that already received an outcome reply during this invocation. Initialize `OUTCOME_MARKERS = {}` (`item_key → latest_reviewer_marker_at_outcome`) covering both REJECTED and DEFERRED items so a later reviewer edit re-enters evaluation. Initialize `DEFERRED_ITEMS = []` (one entry per filed tracking issue, used by Step 7's summary). (`ALL_COMMITTED_ITEMS` is initialized once in Step 0b, not here — see that step for why: unlike this paragraph's other lists, which are safely re-derived every time "Step 3's calls" are re-run from Step 5f/5g/6, `ALL_COMMITTED_ITEMS` must persist and only grow across the whole run.) This is distinct from the per-iteration `COMMITTED_ITEMS` Step 5b/5d/5e use to isolate each iteration's own push and replies — do not widen `COMMITTED_ITEMS` itself to run scope, or 5d's empty-iteration short-circuit and 5e's reply-once guarantee both break.

Print the initial assessment as a status line — `Found N CI failures, M reviewer feedback items, and merge conflicts: yes/no. Begin processing.` — and proceed unconditionally. **Never** wait for a confirmation: the skill is fully automatic from this point on.

If there is nothing to fix (no CI failures, no unanswered feedback), `has_merge_conflict` is false, **and the `errors` list is empty**, report the PR is clean and proceed to Step 6 (monitoring). If `has_merge_conflict` is true, go to Step 5h even when there is no other work. If `errors` is non-empty — including an indeterminate `mergeable == null` recorded in Step 3, or any failed Step 3 fetch — do **not** declare the PR clean and do **not** enter monitoring; fall through to Step 5g's retry path (report the fetch failures and retry after 30 seconds) so the ambiguous state resolves before any success exit. A false "clean" here would otherwise skip Step 5g's error gate entirely under `--monitor 0`.

### Step 4: Evaluate Every Feedback Item

**This is the most important step.** Every time PR state is fetched, evaluate reviewer feedback before waiting on CI. Do not defer review handling until checks finish.

For each feedback item not already answered, gather context, then spawn **two subagents in parallel**. Inline threads are already answered when `thread.id ∈ ADDRESSED_THREAD_IDS`; review summaries and PR conversation comments are already answered when `item_key ∈ REPLIED_ITEM_KEYS`; previously rejected or deferred feedback is already answered when `item_key ∈ OUTCOME_MARKERS` and its reviewer marker has not changed.

- Inline review threads: use `latestReviewerComment`, then read the referenced file and code context.
- Review summaries: parse the body into concrete asks; read the PR diff, PR description, and any files mentioned by the review.
- PR conversation comments: parse the body into concrete asks; read referenced files, logs, or diff context as needed.

1. **Local Evaluator** — runs the host model in a clean context. Use the row from Step 0a's per-host invocation table that matches your host:
   - **Claude host:** Agent tool with `model="opus"`.
   - **Codex host:** Bash with `codex exec --sandbox read-only --ephemeral - < /tmp/eval-XXXXXX` (10-minute timeout). Write the prompt via `mktemp` first; `rm -f` after.

   Provide the comment, code context, PR title/description, and changed files summary. Ask for a **FIX / DEFER / REJECT** verdict with category, confidence, and reasoning. See `references/comment-evaluation.md` for the full prompt template.

2. **Cross-harness Evaluator** — runs the *other* model. Use the matching row from Step 0a's invocation table:
   - **Claude host:** Skill tool with `skill="codex-2nd-opinion"` (the user-level skill in this repo, frontmatter `name: codex-2nd-opinion`).
   - **Codex host:** Bash with `claude -p --permission-mode auto --output-format text < /tmp/eval-XXXXXX` (10-minute timeout; `--permission-mode auto` keeps `claude` from prompting when run headless inside the loop). Same `mktemp` / `rm -f` discipline as above.

   Pass the same evaluation prompt as the Local Evaluator. Ask for the same verdict format.

   **Claude host — DO NOT** invoke any of the following — they look superficially related but are the wrong tool and will produce different output:
   - `codex:rescue` / Skill tool with `skill="codex:rescue"` — this delegates rescue/fix work, not opinion-gathering.
   - `codex:codex-rescue` — the rescue subagent in the Agent tool, same problem.
   - `codex:setup`, `codex:codex-cli-runtime`, `codex:gpt-5-4-prompting`, `codex:codex-result-handling` — internal helpers, not user-facing review tools.

   The only correct invocation is the Skill tool with `skill="codex-2nd-opinion"`. If `codex-2nd-opinion` is not in the available-skills list, **stop and report** — do not substitute another skill.

   **Codex host — DO NOT** call `codex exec` again as the cross-harness evaluator (that is the Local Evaluator). The cross-harness step must be `claude -p`, never another `codex exec`.

**Decision logic** (from `references/comment-evaluation.md`):

| Local | Cross-harness | Action |
|-------|---------------|--------|
| FIX | FIX | **FIX** — apply code change in this PR |
| FIX + DEFER | (either order) | **FIX** — both agree the feedback is valid; apply it now instead of filing an issue |
| REJECT | REJECT | **REJECT** — reply with rationale, no code change, no issue |
| DEFER | DEFER | **DEFER** — file tracking issue, reply with link |
| any other combination | | **DEFER** — file tracking issue (any remaining disagreement, all involving a REJECT vote, defaults to DEFER) |

The rule leans toward action without being reckless: fix when both evaluators agree the change belongs in this PR, and also when one votes FIX and the other DEFER — both consider the feedback valid, so the disagreement is only about timing and fixing now avoids issue churn. Only reject when both agree there is no concern worth tracking. Every remaining disagreement (any combination with a REJECT vote) files an issue so nothing is silently dropped. This matches the "Three Outcomes" core principle.

**Ambiguous feedback** (open questions, architectural suggestions with multiple alternatives, requests that depend on undocumented context) is auto-classified as **DEFER** without consulting the user. The filed issue is the durable artifact a human can resolve later; the PR reply tells the reviewer where the discussion has moved. Do not block the loop on user input.

### Step 5: The Triage and Fix Loop

Loop until fixed point or unrecoverable abort. Process each feedback item exactly once per fetch cycle through the outcome flow that matches its Step 4 verdict.

**5a. REJECT flow** (verdict = REJECT). Compose a rejection body using the prefix table below and reply through the right channel (see "GitHub CLI Commands Used" and `references/api-patterns.md` for exact commands):
- Inline review thread: reply to `commentId = latestReviewerComment.databaseId` via `gh api repos/{owner}/{repo}/pulls/<n>/comments/<commentId>/replies -F body=@<tmpfile>` with the body written to a temp file first (no `jq` or other JSON-building tool needed — `gh api -F key=@path` reads and correctly encodes the file's raw contents). Always post through `gh`, even if a GitHub MCP is connected — see "GitHub CLI Commands Used" for why.
- Review summary or PR conversation comment: `gh pr comment <n> -R {owner}/{repo} --body-file <tmpfile>` (or `gh issue comment`) with the body written to a temp file first. Start the body with `@reviewer Regarding your <review/comment> (<short identifier>):` and quote or summarize the specific ask being rejected.

Do **not** resolve rejected inline threads — they stay unresolved so the reviewer can push back. Record the item in `OUTCOME_MARKERS` as `item_key → latest_reviewer_marker_at_outcome` using a mutable marker: `latestReviewerComment.databaseId + updatedAt` for inline threads, `review.id + body_hash(body)` for review summaries (REST reviews have no `updated_at`, and `submitted_at` doesn't change on a body edit — see `references/api-patterns.md`), and `comment.id + updated_at` for PR conversation comments. Do **not** add it to `ADDRESSED_THREAD_IDS`; suppression depends on the recorded reviewer marker staying current.

Rejection body format:

```
{prefix} {reason}

_This assessment was made by two independent AI reviewers ({LOCAL_LABEL} and {REMOTE_LABEL}). If you disagree, please reply and we'll re-evaluate._
```

Substitute `{LOCAL_LABEL}` / `{REMOTE_LABEL}` with the values captured in Step 0a (e.g. `"Claude Opus 4.6"` and `"Codex GPT-5.4"`, in either order depending on the host).

Prefixes by REJECT category:

| Category | Prefix |
|---|---|
| `not-an-issue` | `**Not an issue** —` |
| `unrelated` | `**Unrelated to this PR** —` |
| `not-relevant` | `**Not applicable** —` |
| `style-preference` | `**Style preference (no change)** —` |
| `already-handled` | `**Already handled (no change)** —` |
| (default) | `**No action taken** —` |

**5a'. DEFER flow** (verdict = DEFER). The feedback is legitimate but does not belong in this PR — file a tracking issue, then reply with a link.

1. Build the issue title from the feedback's primary ask: a short imperative phrase, e.g. `Refactor extractTokens() to share parser state` or `Add retry logic to HTTP client`.
2. Build the issue body:

   ```
   Deferred from #{pullNumber}: {one-line summary}.

   Original feedback by @{reviewer} on PR #{pullNumber} ({pr_url}):

   > {quoted feedback, blockquoted}

   **Context:** {file path:line, or short note on where this applies}.

   **Why deferred:** {scope-creep | diminishing-returns | ambiguous} — {one-sentence rationale from the evaluators}.

   _Filed automatically by `pm-autofix-pr` after dual-evaluator triage by {LOCAL_LABEL} and {REMOTE_LABEL}._
   ```

3. Write the title to its own temp file first, as a single non-empty line — the title, like the body, is derived from untrusted reviewer feedback, and interpolating it directly into `--title "<title>"` lets shell metacharacters in the feedback (backticks, `$(...)`, quotes) execute as commands or simply break the invocation. Run `gh issue create -R {owner}/{repo} --title "$(cat <titlefile>)" --body-file <tmpfile> [--label deferred-from-pr]` — write `$(cat <titlefile>)` **verbatim** into the command text; never splice the title text itself into the command string. The file's content becomes inert command-substitution output inside a double-quoted argument, not re-parsed shell syntax. If the repo has no `deferred-from-pr` label, drop `--label` and retry rather than pre-creating it. Capture the returned issue number and URL by parsing `gh issue create`'s stdout (it prints the new issue's URL, from which the number is the trailing path segment).
4. Compose the PR reply with the matching prefix below, ending with `Tracked as #{new_issue_number} ({issue_html_url}).`

   Prefixes by DEFER category:

   | Category | Prefix |
   |---|---|
   | `scope-creep` | `**Out of scope for this PR** —` |
   | `diminishing-returns` | `**Deferred (diminishing returns)** —` |
   | `ambiguous` | `**Deferred for separate discussion** —` |
   | `automated-fix-failed` | `**Deferred (automated fix failed pre-commit)** —` |
   | (default) | `**Deferred** —` |

5. Reply through the same channel as REJECT (inline thread → the `.../replies` endpoint; review summary / PR comment → `gh pr comment`/`gh issue comment`). Do **not** resolve inline threads — the reviewer can push back if the deferral is wrong.
6. Record the item in `OUTCOME_MARKERS` (same marker scheme as REJECT). Append `{item_key, issue_number, issue_url, category, title}` to `DEFERRED_ITEMS` for the Step 7 summary.

**Issue-creation failure fallback.** If `gh issue create` fails (rate limit, permissions, transient error) — retry once after 60 seconds. If the retry also fails, **do not block the loop**: post the DEFER reply with `TODO: file as a separate issue — automated issue creation failed (<error summary>).` instead of the tracked-issue link, and append `{item_key, issue_number=null, ...}` to `DEFERRED_ITEMS` so the final summary surfaces the gap. The reviewer's concern is still acknowledged in writing.

**5b. FIX flow** (verdict = FIX) and CI failures. Process each FIX item individually — apply, check, commit — before moving to the next. This isolates each item in its own commit so a pre-commit failure can be reverted cleanly without touching earlier successful fixes (the revert combines `git restore` for tracked changes and `git clean -fd` for untracked files the FIX created — both are safe because only the in-flight item's changes are in the worktree).

**Precondition** before entering 5b: the worktree must be clean (`git status --porcelain` empty). If it is not, fail loudly and jump to Step 7 with `exit reason: dirty-worktree` — there is no safe way to attribute the existing changes to a specific FIX item.

For each FIX item in `feedback_items` whose verdict is FIX (CI failures included), in sequence:

1. **Snapshot the worktree.** Run `git status --porcelain` and record it as `pre_fix_status` — at this point it must be empty (the 5b precondition).
2. **Apply the change.** Read the relevant source/error context and edit files:
   - CI failures: read the failed-job log tail, identify failing file/line, fix.
   - Inline review threads: read the referenced file, apply the requested change.
   - Review summaries / PR conversation comments: locate files, apply the parsed asks.
3. **Categorize what this FIX touched.** Run `git status --porcelain` again. Capture:
   - `modified_paths` — entries with status codes `M`, `A`, `D`, `R`, `T` (tracked changes/renames/deletes).
   - `untracked_paths` — entries with status code `??` (new files this FIX created).
4. **Run pre-commit checks** for this item (Step 5c).
5. **On pre-commit success:** stage the touched files by name (never `git add -A`) — staging both `modified_paths` and `untracked_paths`. Commit with a descriptive message that names the feedback item (e.g. `Fix null check in extractTokens (review thread #PRRT_xxx)`), capture the resulting short-sha, and add the FIX item to `COMMITTED_ITEMS = []` with `{item_key, sha, files, validation}` — also append the same entry to the run-wide `ALL_COMMITTED_ITEMS` (initialized in Step 0b) so Step 7's exhaustion comment can report every commit landed this run, not just this iteration's.
6. **On pre-commit failure** (5c returned a hard fail after the sub-fix attempt): revert this item completely so the next FIX starts from a clean worktree:
   - `git restore --source=HEAD --staged --worktree -- <modified_paths>` to undo tracked modifications/renames/deletions (also unstages anything pre-commit staged).
   - `git clean -fd -- <untracked_paths>` to delete files this FIX created (`-fd` so newly-created subdirectories are removed too).
   - Verify with `git status --porcelain` that the worktree is once again empty; if it is not, abort the entire loop with `exit reason: dirty-worktree` rather than risk contaminating later FIXes.

   Record the item under `BLOCKED_ITEMS = []` with `{item_key, files, pre_commit_error_tail}`. Continue with the next FIX item; blocked items will be turned into `automated-fix-failed` DEFER entries (with their own tracking issues) at the end of the loop iteration.

After all FIX items have been processed, the worktree is clean and `COMMITTED_ITEMS` lists every successful fix with its own sha. Each entry's sha is what 5e quotes in the corresponding "Fixed in `<sha>`" reply.

**Convert each blocked FIX into an `automated-fix-failed` DEFER before leaving 5b.** For every entry in `BLOCKED_ITEMS` (the items 5b reverted because pre-commit refused them), run the Step 5a' DEFER flow with `category="automated-fix-failed"`:

- Title: `Auto-fix failed pre-commit: <one-line summary of the original feedback>`.
- Issue body: include the reviewer's original feedback (quoted), the file paths the FIX touched, and the `pre_commit_error_tail` captured in 5b. Set the `**Why deferred:**` line to `automated-fix-failed — <one-line of the pre-commit error>`.
- File the tracking issue with `gh issue create` (as in Step 5a'), post the DEFER reply on the original thread / review summary / PR conversation comment using the `automated-fix-failed` prefix from Step 5a' and ending with `Tracked as #<issue_number> (<issue_html_url>).`, then record the item in `OUTCOME_MARKERS` and append it to `DEFERRED_ITEMS` — exactly like an evaluator-driven DEFER. Apply the same retry + `TODO: file as a separate issue` fallback if issue creation fails.

After this conversion, every blocked item has an explicit PR reply and (best-effort) a tracking issue, so the "Always Reply" core principle holds for blocked FIXes too. Clear `BLOCKED_ITEMS` for the iteration; do not include their entries in 5e (which only iterates `COMMITTED_ITEMS`).

**5c. Pre-commit checks** (from Step 2) — invoked by 5b for the current in-flight item only. Run in order: format → lint → type-check → test → build. If a formatter modifies files, stage them. If a check fails, attempt one sub-fix (does not count as a loop iteration). If the sub-fix also fails, **do not ask the user** — return a hard fail to 5b, which handles the revert and continues with the next FIX item. The check is bounded to this single item because earlier successful items are already committed and out of the worktree.

**5d. Push the iteration's commits.** After 5b finishes, decide whether there is anything to push without depending on undefined refs:

- If `COMMITTED_ITEMS` is empty for this iteration (no FIX produced a commit), there is nothing to push — **skip directly to Step 5g** (re-fetch and check fixed point), **not** 5f. An iteration that only emits REJECT replies, DEFER replies, or `automated-fix-failed` DEFER conversions creates no new commits and therefore no new CI events, so waiting for CI in 5f would just spin until `CI_TIMEOUT` and exit as a failure even when we have actually reached the fixed point.
- Otherwise, push:
  - If the branch has an upstream (`git rev-parse --abbrev-ref --symbolic-full-name @{u}` exits 0), run `git push`.
  - If the branch has no upstream yet (first push of this branch — common for a freshly-created PR), run `git push -u origin <head.ref>` using the branch name captured in Step 1. Do **not** consult any base-branch ref; the upstream gets set during this push.
  - On a successful push (either case above), reset the per-push `CI_TIMEOUT` clock (Step 5f) back to `CI_TIMEOUT` minutes — it is scoped to "time since the most recent push," so it re-arms on every push. `TOTAL_CI_BUDGET_REMAINING` is a separate, run-wide counter and is never reset here.

On **rejected push** (upstream has new commits), auto-recover without prompting:
1. Run `git pull --rebase`.
2. If the rebase succeeds, re-run pre-commit checks for each rebased commit (using `git rebase --exec` is acceptable, or by replaying 5b's checks on the rebased tree), then push again.
3. If the rebase fails (conflicts), run `git rebase --abort` to leave the worktree clean, record the abort in the final summary, jump straight to Step 7. Exit with summary; the user must resolve the divergence manually.

On **network error** during push, retry with exponential backoff (2s, 4s, 8s, 16s). After the fourth failure, jump to Step 7 with the failure recorded — do not prompt.

**5e. Reply to every addressed feedback item.** For each entry in `COMMITTED_ITEMS` (the per-item commits 5b/5d produced this iteration), post an outcome reply that quotes that item's own short-sha — never a different item's sha, since each FIX has its own commit. An item only counts as addressed once its reply is posted.

Reply body format:

```
Fixed in `<short-sha>`.

Changed: <file/function/behavior summary>.
Validation: <pre-commit check, targeted test, or reason validation was not run>.
```

Use the right channel:
- Inline review thread: reply to `commentId = latestReviewerComment.databaseId` (the numeric REST ID of the thread's most recent reviewer comment — **not** the thread's GraphQL `id`) via `gh api repos/{owner}/{repo}/pulls/<n>/comments/<commentId>/replies -F body=@<tmpfile>` — always through `gh`, even if a GitHub MCP is connected (see "GitHub CLI Commands Used"). After the reply succeeds, resolve the thread: primary path `gh api graphql` with the `resolveReviewThread` mutation and `threadId = <thread.id>` (the GraphQL node ID from the `review_threads` query in Step 3); if a GitHub MCP is already connected, its thread-resolve method may be used instead — it performs the same mutation. If both the reply and the resolve succeed, add the thread to `ADDRESSED_THREAD_IDS`.
- Review summary or PR conversation comment: `gh pr comment <n> -R {owner}/{repo} --body-file <tmpfile>` (or `gh issue comment`). Start the body with `@reviewer Regarding your <review/comment> (<short identifier>):`, then include the fixed outcome. If the reply succeeds, add the item key to `REPLIED_ITEM_KEYS`.

This step is **mandatory** — never skip it. If a reply or resolve call fails with 403/429, wait 60s and retry once. After a failed retry, continue the code loop if needed, but do not count that feedback item as addressed and do not declare convergence; it must reappear on the next fetch/retry cycle until a reply is posted.

**5f. Wait for CI only after feedback is answered.** If any fetched feedback item still lacks an evaluation decision and an outcome reply, re-enter Step 4 immediately instead of waiting. Once feedback is answered, wait for CI to change:

`TOTAL_CI_BUDGET_REMAINING` was already initialized once in Step 0b, at run start — not here. It is never reset by a later push or by a monitoring cycle (Step 6); every wait anywhere in the run, in either step, draws down the same counter, which is what closes the "resets per push" and "monitoring windows chain unboundedly" gaps described in the issue this behavior was added for.

At the top of each wait, compute `budget_this_wait = min(minutes remaining on the per-push CI_TIMEOUT clock, TOTAL_CI_BUDGET_REMAINING)`. If that is `<= 0`, skip straight to the timeout check below without waiting.

1. **Waiting primitive** — prefer a blocking watch over a manual sleep loop:
   - `WATCH_USABLE` and `TIMEOUT_BIN` were already probed once, in Step 0b — not here, not per iteration. Reuse those values. If `WATCH_USABLE`, wait with `TIMEOUT_BIN <chunk>s gh pr checks <n> -R {owner}/{repo} --watch --interval <POLL_INTERVAL>`, where `<chunk>` is `min(budget_this_wait in seconds, 300)` — capping every watch invocation at 5 minutes even when more budget remains, so control returns periodically to check the four channels `--watch` never looks at (review threads, review summaries, PR conversation comments, mergeability). `TIMEOUT_BIN` exits 124 when the chunk elapses with checks still pending; treat that the same as "nothing changed this wait" below. A clean exit (`0`) from `gh pr checks --watch` means the checks reached a terminal state — re-fetch immediately rather than waiting out the rest of the chunk.
   - If `WATCH_USABLE` is false, fall back to the original loop: sleep `POLL_INTERVAL` seconds **once** (via `Bash` with `sleep <n>`), then continue to item 2 below — the same single-sleep-per-pass shape every other iteration of this wait loop already has. `budget_this_wait` bounds the fallback the same way it bounds the watch path: by the outer loop (items 2-5) repeatedly re-entering item 1 and sleeping again until the timeout check fires — item 1 itself never sleeps for the full `budget_this_wait` in one call. A `--watch`-capable `gh` without a timeout binary must use this fallback — invoking `gh pr checks --watch` unbounded, with nothing to cap it, would block past `budget_this_wait` and defeat the run-wide budget just as surely as a command-not-found failure would.
   - **`gh pr checks --watch` is a sleep replacement only, never a state source.** Its own status output uses the GraphQL `CheckConclusionState` vocabulary (uppercase — see `references/api-patterns.md`'s "CI check runs" section), not the REST vocabulary the rest of this skill relies on. Whichever waiting path was used, always re-run Step 3's five calls next to rebuild authoritative state — do not parse `gh pr checks`' own output.
2. Re-run Step 3's calls to rebuild PR state.
3. Compare against the previous snapshot. Treat any of the following as a "change event" worth re-entering Step 4 / Step 5:
   - `head_sha` changed (new push from another contributor).
   - `has_merge_conflict` flipped from false to true (the base branch advanced and now conflicts with the PR) — re-enter to run Step 5h.
   - Any check run's `conclusion` transitioned from null/`in_progress` to a terminal value, or any check run was added/removed.
   - Review thread count, review summary count, or PR conversation comment count changed.
   - Any review thread's latest comment `updatedAt`, or any PR conversation comment's `updated_at`, advanced past the previous snapshot. These fields are real and reliable on their respective endpoints.
   - Any review summary's `hash(body)` differs from the previous snapshot's — **not** `updated_at`: the REST `pulls/{n}/reviews` response has no `updated_at` field at all (only `submitted_at`, which does not change when a review body is edited), so a body-edited review would never be detected otherwise. This mirrors the `OUTCOME_MARKERS` scheme already used for edited reviews after a REJECT/DEFER outcome.
4. Subtract this wait's actual elapsed wall-clock time from both `TOTAL_CI_BUDGET_REMAINING` and the per-push `CI_TIMEOUT` clock.
5. If nothing changed and CI is still in flight, loop back to step 1 — unless the timeout check below now fires. **Exception:** if this wait exited via a clean (`0`) `--watch` return (checks were already in a terminal state when the wait started) and step 3 found no change event, sleep the remainder of `POLL_INTERVAL` before looping back to step 1's watch call, rather than re-entering `--watch` immediately — then subtract *this sleep's* duration from both `TOTAL_CI_BUDGET_REMAINING` and the per-push `CI_TIMEOUT` clock too, the same way step 4 already does for the wait itself. Without this floor and its own deduction, an already-terminal check set makes `--watch` return almost instantly every time, turning "loop back to step 1" into a tight spin of Step 3's five API calls with no actual wait between them, *and* — if the floor sleep's own time weren't separately charged — into wall-clock time the run-wide budget never sees, since step 4's deduction already ran before this exception fires. This is not a rare edge case: Step 6 hits it on *every* iteration, since it is only ever entered once checks are already terminal (see Step 6) — Step 5f itself can also hit it in the narrower push-to-check-creation race window, where `--watch` sees the previous commit's already-terminal checks before GitHub creates new ones for the latest push.

**Timeout check.** Abort the loop if **either**: the per-push `CI_TIMEOUT` minutes have elapsed with no terminal CI conclusion for at least one previously-pending check, **or** `TOTAL_CI_BUDGET_REMAINING` has reached zero, regardless of how recently the last commit was pushed. Record which of the two conditions actually fired as `TIMEOUT_TRIGGER` — `total-budget` if `TOTAL_CI_BUDGET_REMAINING` reached zero (checked first, since that's the harder deadline once it's hit), otherwise `per-push` — so Step 7's PR comment can report the real cause instead of always blaming the total budget. Record `ci-timeout` in the final summary and jump to Step 7 (which posts a resume-pointer PR comment before exiting). Do not prompt the user.

This wait-and-refetch path is the only mechanism the skill uses to detect new state. It does not depend on `<github-webhook-activity>` envelopes or any subscription tool; those are not available in the standard Claude Code CLI or Codex CLI sessions this skill targets. `gh pr checks --watch` changes how the wait is spent, not how state is detected.

**5g. Re-fetch state and check for fixed point.** Re-run Step 3's calls. Filter out threads whose ID is in `ADDRESSED_THREAD_IDS` and PR-level feedback whose key is in `REPLIED_ITEM_KEYS`. For each item in `OUTCOME_MARKERS`, suppress it **only if** its latest reviewer marker still matches the value recorded at the prior REJECT/DEFER outcome; if a later reviewer reply exists, remove the item from `OUTCOME_MARKERS` and treat it as fresh feedback to re-evaluate in Step 4. If the merged state has a non-empty `errors` list (including an indeterminate `mergeable == null`), do **not** declare a fixed point — report the fetch failures and retry after 30 seconds.

**Fixed point reached** if **all** of:
- `ci_failures` is empty after filtering out `cancelled` (the only non-success conclusion treated as informational). Any remaining entry — including `timed_out`, `startup_failure`, `action_required`, and non-`github-actions` `failure` — blocks convergence and is reported to the user.
- No reviewer feedback item remains without an evaluation decision and an outcome reply.
- `has_merge_conflict` is false — the PR has no merge conflicts with its base branch. **This is a hard gate: never declare a fixed point while the PR is conflicted.** If `has_merge_conflict` is true, do not converge — run Step 5h to resolve the conflict, then continue the loop. (A `null`/indeterminate `mergeable` is not "false"; it was recorded in `errors` above, so this branch retries rather than converging.)

→ Proceed to Step 6.

**Merge conflict present** (`has_merge_conflict` true) → run Step 5h, then continue the loop.

**Stale loop detected** if the same CI checks are failing with similar error patterns as the previous iteration, **or** two consecutive iterations resolved base-branch conflicts yet the PR is still reported non-mergeable → record `stale_loop` in the final summary and jump to Step 7. Do not prompt the user. (`BLOCKED_ITEMS` cannot accumulate across iterations because Step 5b now converts each blocked FIX into an `automated-fix-failed` DEFER and clears the list.)

**New issues found** → run Step 4 (evaluate new feedback) and continue the loop.

**5h. Resolve merge conflicts with the base branch.** Runs whenever the fetched state has `has_merge_conflict == true`. The PR branch has diverged from its base (`base.ref`, captured in Step 1) in a way GitHub can't auto-merge; left alone the PR is unmergeable and must never be reported as a fixed point. Resolve by merging the base branch **into** the PR branch — merge, not rebase, because the PR branch is already published and a merge avoids a force-push and preserves the reviewer-visible commit history.

**Precondition:** the worktree must be clean (`git status --porcelain` empty). Step 5b leaves it clean; if it is not, jump to Step 7 with `exit reason: dirty-worktree`.

1. **Fetch the base.** `git fetch <BASE_REMOTE> <base.ref>`, using the `BASE_REMOTE` captured in Step 1 — the base repository's remote or clone URL, **not** necessarily `origin`. For a fork PR the base lives on `upstream` (or a direct URL), and fetching `origin/<base.ref>` would merge the fork's stale copy of the branch — or fail outright — leaving GitHub's conflict unresolved and dead-ending the loop.
2. **Merge the base in.** `git merge --no-edit FETCH_HEAD` — `FETCH_HEAD` is exactly what step 1 just fetched, so this merges the correct base branch whether `BASE_REMOTE` is a named remote or a URL. (Equivalently `git merge --no-edit <BASE_REMOTE>/<base.ref>` when `BASE_REMOTE` is a named remote.)
3. **If the merge is clean** (exit 0 — the branch was merely behind, or the divergent changes auto-merged): `git merge` has **already created the merge commit**. Now run the Step 5c pre-commit checks on the merged tree.
   - On success → if Step 5c staged or modified any files (a formatter run or the one allowed sub-fix), fold them into the merge commit with `git add -- <changed paths>` then `git commit --amend --no-edit`, so the tree you push is exactly the tree that passed validation and no stray changes are left to trip the next iteration's clean-worktree precondition. Confirm `git status --porcelain` is empty, then go to step 6 (push).
   - On a pre-commit failure that a single sub-fix can't clear, undo the merge with `git reset --hard ORIG_HEAD` (`git merge` sets `ORIG_HEAD` to the pre-merge commit) and jump to Step 7 with `exit reason: merge-conflict`, noting that merging the base broke the pre-commit checks. Do not push a broken merge.
4. **If the merge conflicts** (non-zero exit; `git diff --name-only --diff-filter=U` lists the conflicted files): resolve each conflicted file, preserving this PR's intent while incorporating the base's changes.
   - Read **every** conflicted file, reason about both sides (`ours` = this PR, `theirs` = the base), and edit to a coherent resolution that keeps both the PR's change and any independent base change. Never blindly keep one side, and never leave a conflict marker (`<<<<<<<`, `=======`, `>>>>>>>`) behind.
   - When every file is resolved, `git add` the resolved paths and run the Step 5c pre-commit checks. On success, complete the merge with `git commit --no-edit`.
   - If resolution can't be done confidently — a semantic conflict the skill can't reason about, markers it can't cleanly remove, or pre-commit still failing after one sub-fix — run `git merge --abort` to restore the clean pre-merge worktree and jump to Step 7 with `exit reason: merge-conflict`. Do not leave a half-resolved merge in place and do not prompt the user.
5. **Push the merge.** Push with the same handling as Step 5d (upstream check, `git pull --rebase` recovery on a rejected push, exponential backoff on network error) — including resetting the per-push `CI_TIMEOUT` clock on success, exactly as Step 5d does. This publishes the merge commit and triggers a fresh CI run.
6. **Record it.** Append `{sha, base_ref, conflicted_files}` to `MERGE_COMMITS = []` for the Step 7 summary, then continue the loop (return to Step 5f to wait for the new CI run, or Step 5g to re-check the fixed point).

**Bounded attempt.** Successful merges count toward stale-loop detection (Step 5g): if two consecutive iterations resolve base conflicts but the PR is still reported non-mergeable — e.g. the base keeps advancing and re-conflicting faster than the loop can converge — stop with `exit reason: stale-loop` rather than merging forever.

### Step 6: Monitoring Phase

Skip if `MONITOR_DURATION` is 0 or if there are CI failures, unanswered feedback items, or a merge conflict (`has_merge_conflict` true). Monitoring is only entered from a true fixed point.

The effective monitor window is `min(MONITOR_DURATION, TOTAL_CI_BUDGET_REMAINING)` — the same shared counter Step 5f draws down, initialized once in Step 0b and never reset by convergence (this holds even when Step 6 is entered directly from Step 3's "nothing to fix" exit, without ever passing through Step 5f). If that effective window is `<= 0` (the run reached a fixed point but exhausted the total budget getting there), skip monitoring entirely and proceed straight to Step 7 as `monitoring-timeout`: the PR genuinely has no open work, there is just no budget left to keep watching it — still a success exit, and no resume-pointer comment is needed since nothing is pending.

Report: **"All issues resolved. Monitoring for {effective window} minutes..."**

Wait for change for up to the effective window using Step 5f's waiting *primitive only* — the probe/chunk/watch-or-sleep selection (item 1), the re-fetch (item 2), and the change comparison (item 3) — but never Step 5f's **Timeout check** paragraph, which is scoped to the `ci-timeout` exit reason and does not apply here. Compare counts, `updated_at` markers, review-summary body hashes (and `head_sha`, and `has_merge_conflict`) against the previous snapshot — same signals as Step 5f's "change event" list. Track a dedicated `MONITOR_DURATION_REMAINING` clock, initialized to the effective window at Step 6 entry; subtract each wait's elapsed time from both it and `TOTAL_CI_BUDGET_REMAINING`, the same way Step 5f item 4 subtracts from both `TOTAL_CI_BUDGET_REMAINING` and the per-push `CI_TIMEOUT` clock. If either reaches `<= 0` during one of these direct Step 6 waits, that is `monitoring-timeout` — a success exit, per the paragraph above — never `ci-timeout`. If a change is detected within the window — including the base advancing to introduce a new merge conflict — re-enter the evaluate + fix loop (Step 4 → Step 5, with Step 5h handling any new conflict) with a fresh sub-loop. Because that sub-loop runs Step 5f, it draws on `TOTAL_CI_BUDGET_REMAINING` and can itself hit Step 5f's own `ci-timeout` Timeout check if the total budget runs out before the sub-loop reconverges — this is what stops flapping monitor-detect-fix cycles from chaining forever. The sub-loop's duration is charged only to `TOTAL_CI_BUDGET_REMAINING`, not to `MONITOR_DURATION_REMAINING` — a fix detour narrows the shared run-wide budget but does not by itself consume the leftover monitor window. After fixing, resume monitoring with `min(MONITOR_DURATION_REMAINING, TOTAL_CI_BUDGET_REMAINING)`, not a fresh `MONITOR_DURATION`.

A non-empty `errors` list (Step 3's error accumulation, including an indeterminate `mergeable == null`) is never itself evidence of "no change": counts, timestamps, `head_sha`, and `has_merge_conflict` can look identical to the previous snapshot even though mergeability was never actually confirmed. If the window elapses while the most recent fetch's `errors` list is non-empty, do not declare `monitoring-timeout` success yet — perform one more Step 3 re-fetch, mirroring Step 5g's gate. If that re-fetch's `errors` list comes back empty and no other change is detected, the window has genuinely elapsed clean — proceed to Step 7 as `monitoring-timeout`. If `errors` is still non-empty, treat it as a change event and re-enter the evaluate + fix loop (Step 4 → Step 5g), so Step 5g's own retry-after-30-seconds gate resolves the ambiguous state instead of the window silently expiring into a false success.

If the window elapses without a change and the most recent fetch's `errors` list is empty, proceed to Step 7.

### Step 7: Final Summary

**Budget-exhaustion PR comment.** If the exit reason is `ci-timeout`, post a PR comment *before* printing the local summary below, so the state and the resume path are visible on GitHub without anyone needing to re-run the skill just to read local output. Write the body to a `mktemp`'d temp file first (the same discipline as every other reply in this skill — see "GitHub CLI Commands Used") and post with `gh pr comment <n> -R {owner}/{repo} --body-file <tmpfile>`. Branch on `TIMEOUT_TRIGGER`'s value (recorded by Step 5f's timeout check) to pick the matching branch of the `{if TIMEOUT_TRIGGER == ...}` conditional below, so the comment names whichever bound actually fired, rather than always blaming the total budget:

```
Autofix paused: {if TIMEOUT_TRIGGER == total-budget: total CI budget exhausted (`TOTAL_CI_BUDGET` = {TOTAL_CI_BUDGET} min) | if TIMEOUT_TRIGGER == per-push: CI check wait exceeded `CI_TIMEOUT` ({CI_TIMEOUT} min) for this push}.

**Fixes landed this run:** {ALL_COMMITTED_ITEMS shas + one-line summaries, or "none"}
**Feedback resolved:** {count of threads resolved / DEFER issues filed this run, or "none"}.
**Still pending:** {check runs from the most recent Step 3 fetch without a terminal `.conclusion` yet, and/or entries in `ci_failures` that never resolved, and/or unresolved feedback items, and/or merge conflicts, whichever apply}.

Resume with `/pm-autofix-pr {pullNumber}`.
```

`ALL_COMMITTED_ITEMS` is the run-wide accumulator (Step 0b/Step 5b), not the current iteration's `COMMITTED_ITEMS`, so the "Fixes landed this run" line above reports every commit the run made before exhausting the budget, not just the final iteration's.

This comment is authored by `GH_USER` — the same identity every other reply in this skill already posts under — so Step 3's existing `pr_comments` self-filter (drops entries where `.user.login == GH_USER`, `[bot]`-suffix stripped on both sides per the note under Step 3) already keeps a later, resumed run from misreading its own exhaustion comment as reviewer feedback; no new filtering logic is needed. If the comment post itself fails, do not retry indefinitely or block the exit — log the failure and proceed to print the local summary regardless.

Print:

```
## Autofix PR Summary

### PR: #<number> — <title>
### Iterations: N
### Exit reason: fixed-point | stale-loop | ci-timeout | merge-conflict | rebase-conflict | push-failure | dirty-worktree | monitoring-timeout

### Changes Made (FIX outcomes)
| Iteration | Commit | Fixes Applied | Replies Posted |
|-----------|--------|---------------|----------------|
| 1 | abc123 | Fixed lint error in foo.ts, addressed review on bar.ts | @reviewer fixed thread in bar.ts via abc123 |
| 2 | def456 | Fixed test failure in baz_test.py | n/a |

### Merge Conflict Resolutions (base merged in — Step 5h)
| Iteration | Merge Commit | Base | Conflicted Files Resolved |
|-----------|--------------|------|---------------------------|
| 2 | 9f8e7d6 | main | src/parser.ts, src/index.ts |

### Deferred Feedback (DEFER outcomes — issue filed)
| Feedback | Category | Tracking Issue | Reply |
|----------|----------|----------------|-------|
| @reviewer on file.ts:42 | scope-creep | #123 | Posted DEFER reply with link |
| @reviewer (review summary) | diminishing-returns | #124 | Posted DEFER reply with link |
| @reviewer on util.ts:88 | scope-creep | _none — issue creation failed_ | Posted DEFER reply with TODO note |

### Rejected Feedback (REJECT outcomes — no change, no issue)
| Feedback | Category | Reason | Reply |
|----------|----------|--------|-------|
| @reviewer on file.ts:42 | not-an-issue | Code is correct as-is | Posted no-change rationale |

### Blocked Items (FIX attempted but pre-commit failed)
| Item | Pre-commit failure | Tracking Issue |
|------|--------------------|----------------|
| @reviewer on parser.ts:201 | type-check: tsc TS2322 | #125 |

### Current Status
- CI: All passing / N failures remaining (list each: name, conclusion, log link)
- Mergeable: yes / no — merge conflicts with `<base.ref>` remaining (list conflicted files if the run exited on `merge-conflict`)
- Reviewer feedback: All answered / M items still missing replies (list each)
- Issue creation failures: 0 / K (each requires manual filing — see Deferred table)
```

Do **not** ask the user anything at the end. The skill exits unconditionally after printing the summary:

- **Success exits** — `fixed-point` (CI green, no merge conflicts, all feedback answered) or `monitoring-timeout` (reached only by passing through the same green-CI / no-conflict / answered-feedback gate before entering Step 6, so a clean window-elapse is also success): print **"PR is ready for re-review."**
- **Failure exits** — `stale-loop`, `ci-timeout` (also posts the budget-exhaustion PR comment above), `merge-conflict`, `rebase-conflict`, `push-failure`, `dirty-worktree`: print **"Autofix exited without converging — see summary above for required follow-up."** For a `merge-conflict` exit, add: **"Merge conflicts with `<base.ref>` could not be resolved automatically — resolve them manually, then re-run."** Do not loop again, do not prompt.

## References

- **`references/api-patterns.md`** — `gh`/`gh api` command signatures, expected response shapes, polling-loop semantics, supersession algorithm, push and rebase handling, issue-creation flow, the opportunistic-MCP thread-resolution fast path
- **`references/comment-evaluation.md`** — Full evaluation prompt templates, FIX/DEFER/REJECT decision matrix, DEFER and REJECT taxonomies, ambiguity-to-DEFER policy
