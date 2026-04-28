---
name: pm-autofix-pr
description: This skill should be used when the user asks to "autofix pr", "fix pr locally", "fix ci failures", "fix review comments", "iterate on pr", "fix failing checks", "fix pr comments", "make ci green", "fix the build", "address reviewer feedback", or wants to iteratively fix CI failures and review comments on a GitHub PR from the local CLI.
user-invocable: true
---

# Autofix PR

Iteratively fix CI failures and address reviewer feedback on a GitHub PR until a true fixed point is reached — all CI green, all valid feedback fixed, all invalid feedback rejected with reasons, and every feedback item has a reply documenting the outcome. A single invocation handles everything.

## Core Principle: Say NO

Not every review comment deserves a code change. Before touching code, evaluate every review thread, review summary, and PR conversation comment on its merits with two independent AI reviewers (Opus 4.6 + Codex/GPT-5.4). Reject comments that are wrong, out of scope, or unrelated. Post a clear explanation on the PR when rejecting. This prevents scope creep and unnecessary churn.

## Core Principle: Always Reply

Every reviewer feedback item must get an explicit reply before the skill can converge. Valid feedback gets a reply that says what was fixed, where it was fixed, and the commit that contains it. Invalid or out-of-scope feedback gets a reply that says no code change was made and why. Ambiguous feedback gets a reply after the user chooses the path. A missing reply is still unfinished work, even if the code and CI are already green.

## Prerequisites

- **GitHub MCP server** must be configured in the Claude Code session. The skill stops at preflight if it isn't available.
- **`gh` CLI** is still required for one thing only: fetching failed-job log tails (`gh run view --job <id> --log-failed`). The MCP has no equivalent. All other GitHub interaction goes through the MCP.

## Configuration

Override via prompt arguments (e.g., `/pm-autofix-pr 10 --ci-timeout 30 --monitor 0`).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MONITOR_DURATION` | 10 | Minutes to watch for new issues after convergence. 0 to skip. |
| `CI_TIMEOUT` | 20 | Minutes to wait for CI before prompting user. |
| `LOG_TAIL_LINES` | 500 | Lines of CI failure log to inspect. |

There is no iteration limit. The loop runs until a fixed point or until a stale-loop is detected.

## MCP Tools Used

All GitHub interaction is direct MCP tool calls — no bundled scripts.

| Tool | Purpose |
|------|---------|
| `mcp__github__get_me` | Preflight gate; also returns the current user's `login` for self-comment filtering. |
| `mcp__github__list_pull_requests` | Auto-detect the PR for the current branch. |
| `mcp__github__pull_request_read` | Fetch PR details, check runs, review comments/threads, reviews, conversation comments, status. |
| `mcp__github__subscribe_pr_activity` | One-time subscription so CI/review/comment events arrive as `<github-webhook-activity>` messages. |
| `mcp__github__unsubscribe_pr_activity` | Cleanup on exit. |
| `mcp__github__add_reply_to_pull_request_comment` | Post replies on inline review threads (both "fixed" replies and rejection replies). |
| `mcp__github__add_issue_comment` | Post PR-level replies for review summaries and PR conversation comments. |
| `mcp__github__pull_request_review_write` (`method="resolve_thread"`) | Resolve threads after a fix is pushed. |

## Workflow

### Step 0: Preflight — verify the GitHub MCP

Call `mcp__github__get_me`. If the tool is unavailable in the session or the call errors, **stop immediately** with this message:

> **GitHub MCP not available.** This skill requires the GitHub MCP server. Enable it in your Claude Code settings (`.mcp.json` or `~/.claude/settings.json`) and re-run. See https://github.com/github/github-mcp-server for setup.

Do not fall back to `gh` for the workflow. On success, capture `login` as `GH_USER` (used to filter out self-authored comments later).

### Step 1: Identify the PR

1. Get the current branch: `git rev-parse --abbrev-ref HEAD`.
2. If a PR number was provided as argument, resolve its repo via `mcp__github__pull_request_read` method=`get` (requires owner/repo — derive them from `origin` as in step 3a; if the resolved PR's `head.ref` doesn't match the local branch, warn and continue with the user's explicit number). Skip to step 5.
3. Auto-detect the PR. Try the following resolution strategies in order and stop at the first that yields exactly one open PR whose `head.ref` matches the local branch:
   - **3a. Origin lookup.** Parse `git remote get-url origin` to `{owner}/{repo}` (strip `git@github.com:`, `https://github.com/`, trailing `.git`). Call `mcp__github__list_pull_requests` with `head={owner}:{branch}`, `state=open`, `perPage=5`.
   - **3b. Upstream lookup (fork workflow).** If step 3a returned no PRs and `git remote get-url upstream` exists, parse it the same way to `{upstream_owner}/{upstream_repo}` and call `mcp__github__list_pull_requests` against that repo with `head={origin_owner}:{branch}` (PRs from a fork use the fork owner as the head prefix).
   - **3c. `gh pr view` fallback.** If both MCP lookups fail and `gh` is available, run `gh pr view --json number,headRepositoryOwner,headRepository,baseRepositoryOwner,baseRepository,url` to let `gh` resolve the base repo via `git config`. On success, treat the returned `baseRepositoryOwner.login` / `baseRepository.name` as the PR's owner/repo. If `gh` is not installed or returns nothing, stop and tell the user there is no open PR for the current branch.
4. Validate by calling `mcp__github__pull_request_read` method=`get` on the resolved `{owner, repo, pullNumber}` to retrieve `title`, `body`, `head.ref`, `head.sha`, `url`. Confirm `head.ref` matches the local branch.
5. Subscribe to PR activity once: call `mcp__github__subscribe_pr_activity` with `{owner, repo, pullNumber}`. From this point on, CI completions, new reviews, and new comments will arrive as `<github-webhook-activity>` events in the conversation. The subscription is idempotent; do not call it again per iteration.

### Step 2: Read Project Pre-commit Requirements

Find CLAUDE.md (or AGENTS.md) by walking from working directory to repo root. Extract **only explicitly stated** pre-commit commands: format, lint, type-check, test, build. If none are stated, skip pre-commit checks entirely.

### Step 3: Fetch PR State

Issue these MCP calls (paginate where applicable) and merge into a single state object:

| State field | Source |
|---|---|
| `head_sha` | `pull_request_read method=get` → `head.sha` |
| `ci_failures` | `pull_request_read method=get_check_runs` → keep entries whose `conclusion ∈ {failure, timed_out, cancelled, startup_failure, action_required}`. For each `failure` whose `app.slug == "github-actions"`, mark `fixable=true` and fetch the log tail via `Bash`: `gh run view --job <check_run.id> --log-failed 2>&1 | tail -<LOG_TAIL_LINES>`. Other failure types are non-fixable — report them. |
| `review_threads` | `pull_request_read method=get_review_comments` (paginate via `perPage=100`, `after`). Split into `unresolved = [t for t in threads if not t.isResolved]` and `resolved_thread_ids = [t.id for t in threads if t.isResolved]`. For each thread, take the last non-self element of `comments` (sorted by `createdAt` if order is not guaranteed and `author.login != GH_USER`) as `latestReviewerComment`. |
| `review_summaries` | `pull_request_read method=get_reviews`. Apply supersession (see below). |
| `pr_comments` | `pull_request_read method=get_comments`. Drop entries where `user.login == GH_USER`. |

**Supersession algorithm for reviews:** group reviews by `user.login`. Within each group, sort by `submitted_at` ascending. Find the index of the latest `APPROVED` or `DISMISSED` review (or -1 if none). Discard everything at or before that index. From the remainder, keep only `CHANGES_REQUESTED` or `COMMENTED` reviews with non-empty `body` and `user.login != GH_USER`. The result is the actionable summary list.

**Errors:** if any MCP call fails, accumulate the error message into an `errors` list. Do not abort — downstream steps tolerate partial state and re-fetch.

Build `feedback_items` from:
- `review_threads.unresolved`, keyed as `thread:<thread.id>`
- `review_summaries`, keyed as `review:<review.id>`
- `pr_comments`, keyed as `comment:<comment.id>`

Initialize `ADDRESSED_THREAD_IDS` with `resolved_thread_ids`. Initialize `REPLIED_ITEM_KEYS = {}` for review summaries and PR conversation comments that already received an outcome reply during this invocation. Initialize `REJECTED_ITEMS = {}` (`item_key → latest_reviewer_marker_at_outcome`) for rejected feedback.

Present the initial assessment and ask: **"Found N CI failures and M reviewer feedback items. Begin fixing?"**

If nothing to fix, report the PR is clean and proceed to Step 6 (monitoring).

### Step 4: Evaluate Every Feedback Item

**This is the most important step.** Every time PR state is fetched, evaluate reviewer feedback before waiting on CI. Do not defer review handling until checks finish.

For each feedback item not already answered, gather context, then spawn **two subagents in parallel**. Inline threads are already answered when `thread.id ∈ ADDRESSED_THREAD_IDS`; review summaries and PR conversation comments are already answered when `item_key ∈ REPLIED_ITEM_KEYS`; rejected feedback is already answered when `item_key ∈ REJECTED_ITEMS` and its reviewer marker has not changed.

- Inline review threads: use `latestReviewerComment`, then read the referenced file and code context.
- Review summaries: parse the body into concrete asks; read the PR diff, PR description, and any files mentioned by the review.
- PR conversation comments: parse the body into concrete asks; read referenced files, logs, or diff context as needed.

1. **Opus Evaluator** — Agent tool with `model="opus"`. Provide the comment, code context, PR title/description, and changed files summary. Ask for a VALID/INVALID verdict with category, confidence, and reasoning. See `references/comment-evaluation.md` for the full prompt template.

2. **Codex Evaluator** — Call the Skill tool with `skill="codex-2nd-opinion"` (the user-level skill in this repo, frontmatter `name: codex-2nd-opinion`). Pass the same evaluation prompt as the Opus Evaluator. Ask for the same verdict format.

   **DO NOT** invoke any of the following — they look superficially related but are the wrong tool and will produce different output:
   - `codex:rescue` / Skill tool with `skill="codex:rescue"` — this delegates rescue/fix work, not opinion-gathering.
   - `codex:codex-rescue` — the rescue subagent in the Agent tool, same problem.
   - `codex:setup`, `codex:codex-cli-runtime`, `codex:gpt-5-4-prompting`, `codex:codex-result-handling` — internal helpers, not user-facing review tools.

   The only correct invocation is the Skill tool with `skill="codex-2nd-opinion"`. If `codex-2nd-opinion` is not in the available-skills list, **stop and report** — do not substitute another skill.

**Decision logic** (from `references/comment-evaluation.md`):

| Opus | Codex | Action |
|------|-------|--------|
| VALID | VALID | Address it |
| VALID | INVALID | Address it |
| INVALID | VALID | Address it |
| INVALID | INVALID | **Reject it** |

Exception: if one says INVALID with HIGH confidence and the other says VALID with LOW confidence, treat as INVALID.

For ambiguous feedback (open questions, architectural suggestions, multiple alternatives), present to the user with both evaluators' reasoning and wait for guidance. After the user decides, treat it as either VALID or INVALID and reply with that decision and rationale.

### Step 5: The Fix Loop

Loop until fixed point:

**5a. Reject invalid feedback.** For each feedback item evaluated as INVALID, compose a rejection body using the prefix table below, then reply through the right channel:
- Inline review thread: call `mcp__github__add_reply_to_pull_request_comment` with `commentId = latestReviewerComment.databaseId`.
- Review summary or PR conversation comment: call `mcp__github__add_issue_comment` with `issue_number = pullNumber`. Start the body with `@reviewer Regarding your <review/comment> (<short identifier>):` and quote or summarize the specific ask being rejected.

Do **not** resolve rejected inline threads — they stay unresolved so the reviewer can push back. Record the item in `REJECTED_ITEMS` as `item_key → latest_reviewer_marker_at_outcome` (`latestReviewerComment.databaseId` for inline threads, `review.id` for summaries, `comment.id` for PR comments). Do **not** add it to `ADDRESSED_THREAD_IDS`; suppression depends on the recorded reviewer marker staying current.

Rejection body format:

```
{prefix} {reason}

_This assessment was made by two independent AI reviewers (Claude Opus 4.6 and GPT-5.4). If you disagree, please reply and we'll re-evaluate._
```

Prefixes by category:

| Category | Prefix |
|---|---|
| `not-an-issue` | `**Not an issue** —` |
| `scope-creep` | `**Out of scope for this PR** —` |
| `unrelated` | `**Unrelated to this PR** —` |
| `not-relevant` | `**Not applicable** —` |
| `style-preference` | `**Style preference (no change)** —` |
| `already-handled` | `**Already handled (no change)** —` |
| (default) | `**No action taken** —` |

**5b. Fix valid feedback and CI failures.** Apply fixes one issue at a time:
- CI failures: read error logs, identify failing file/line, read source, fix.
- Inline review threads: read the referenced file, understand context, apply the requested change.
- Review summaries / PR conversation comments: parse for specific asks, locate files, apply changes.

For each valid feedback item, record a reply plan before moving on: changed files, line/function names where useful, test/check evidence, and the commit SHA once available.

**5c. Run pre-commit checks** (from Step 2) in order: format → lint → type-check → test → build. If a formatter modifies files, stage them. If a check fails, attempt one sub-fix (does not count as an iteration). If the sub-fix also fails, ask the user.

**5d. Commit and push.** If `git status --porcelain` shows no changes, skip to 5f. Otherwise: stage files by name (not `git add -A`), commit with a descriptive message, push. On rejected push, stop and tell user to `git pull --rebase`. On network error, retry with exponential backoff (2s, 4s, 8s, 16s).

**5e. Reply to every addressed feedback item.** For each valid feedback item fixed in this iteration, post an outcome reply before it can count as addressed.

Reply body format:

```
Fixed in `<short-sha>`.

Changed: <file/function/behavior summary>.
Validation: <pre-commit check, targeted test, or reason validation was not run>.
```

Use the right channel:
- Inline review thread: call `mcp__github__add_reply_to_pull_request_comment` with `commentId = latestReviewerComment.databaseId` (the numeric REST ID of the thread's most recent reviewer comment — **not** the thread's GraphQL `id`). After the reply succeeds, call `mcp__github__pull_request_review_write` with `method="resolve_thread"` and `threadId = <thread.id>` (the GraphQL node ID from `get_review_comments`). If both calls succeed, add the thread to `ADDRESSED_THREAD_IDS`.
- Review summary or PR conversation comment: call `mcp__github__add_issue_comment` with `issue_number = pullNumber`. Start the body with `@reviewer Regarding your <review/comment> (<short identifier>):`, then include the fixed outcome. If the reply succeeds, add the item key to `REPLIED_ITEM_KEYS`.

This step is **mandatory** — never skip it. If a reply or resolve call fails with 403/429, wait 60s and retry once. After a failed retry, continue the code loop if needed, but do not count that feedback item as addressed and do not declare convergence; it must reappear on the next fetch/retry cycle until a reply is posted.

**5f. Wait for CI only after feedback is answered.** If any fetched feedback item still lacks an evaluation decision and an outcome reply, re-enter Step 4 immediately instead of waiting for CI. Once feedback is answered, wait passively for `<github-webhook-activity>` events from the active subscription. Treat these as the trigger to re-fetch:
- `check_run.completed` / `workflow_run.completed` — CI finished, re-fetch immediately.
- `pull_request_review.submitted` / `pull_request_review_comment.created` / `issue_comment.created` — new feedback, re-fetch immediately and process it before waiting for more CI events.

Track wall-clock elapsed time since the last commit was pushed. If `CI_TIMEOUT` minutes elapse with no terminal CI event, ask the user whether to keep waiting or abort. If the subscription appears dropped (no events for an extended period), re-call `mcp__github__subscribe_pr_activity` (idempotent) and continue.

**5g. Re-fetch state and check for fixed point.** Re-run Step 3's MCP calls. Filter out threads whose ID is in `ADDRESSED_THREAD_IDS` and PR-level feedback whose key is in `REPLIED_ITEM_KEYS`. For each item in `REJECTED_ITEMS`, suppress it **only if** its latest reviewer marker still matches the value recorded at rejection; if a later reviewer reply exists, remove the item from `REJECTED_ITEMS` and treat it as fresh feedback to re-evaluate in Step 4. If the merged state has a non-empty `errors` list, do **not** declare a fixed point — report the fetch failures and retry after 30 seconds.

**Fixed point reached** if:
- `ci_failures` is empty after filtering out `cancelled` (the only non-success conclusion treated as informational). Any remaining entry — including `timed_out`, `startup_failure`, `action_required`, and non-`github-actions` `failure` — blocks convergence and is reported to the user.
- No reviewer feedback item remains without an evaluation decision and an outcome reply.

→ Proceed to Step 6.

**Stale loop detected** if the same CI checks are failing with similar error patterns as the previous iteration → report to user, ask whether to continue or stop.

**New issues found** → run Step 4 (evaluate new feedback) and continue the loop.

### Step 6: Monitoring Phase

Skip if `MONITOR_DURATION` is 0 or if there are CI failures or unanswered feedback items.

Report: **"All issues resolved. Monitoring for {MONITOR_DURATION} minutes..."**

Wait for `<github-webhook-activity>` events from the still-active subscription. If a relevant event arrives within the window, re-fetch state and re-enter the evaluate + fix loop (Step 4 → Step 5) with a fresh sub-loop. After fixing, resume monitoring with the remaining time. If the window elapses with no events, proceed to Step 7.

### Step 7: Final Summary and Cleanup

Call `mcp__github__unsubscribe_pr_activity` with `{owner, repo, pullNumber}` to clean up the subscription, regardless of how the loop exited (fixed point, stale loop, user abort, monitoring timeout).

Then print:

```
## Autofix PR Summary

### PR: #<number> — <title>
### Iterations: N

### Changes Made
| Iteration | Commit | Fixes Applied | Replies Posted |
|-----------|--------|---------------|----------------|
| 1 | abc123 | Fixed lint error in foo.ts, addressed review on bar.ts | @reviewer fixed thread in bar.ts via abc123 |
| 2 | def456 | Fixed test failure in baz_test.py | n/a |

### Rejected Feedback
| Feedback | Category | Reason | Reply |
|----------|----------|--------|-------|
| @reviewer on file.ts:42 | scope-creep | Retry logic is valid but out of scope | Posted no-change rationale |

### Current Status
- CI: All passing / N failures remaining
- Reviewer feedback: All answered / M items still missing replies
```

If CI failures or unanswered feedback remain, ask if the user wants further attempts. If everything is resolved: **"PR is ready for re-review."**

## References

- **`references/api-patterns.md`** — MCP tool signatures, expected response shapes, supersession algorithm, push handling, log-fetching gap
- **`references/comment-evaluation.md`** — Full evaluation prompt templates, decision matrix, rejection taxonomy, ambiguity handling
