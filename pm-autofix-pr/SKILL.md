---
name: pm-autofix-pr
description: This skill should be used when the user asks to "autofix pr", "fix pr locally", "fix ci failures", "fix review comments", "iterate on pr", "fix failing checks", "fix pr comments", "make ci green", "fix the build", "address reviewer feedback", or wants to iteratively fix CI failures and review comments on a GitHub PR from the local CLI.
user-invocable: true
---

# Autofix PR

Iteratively fix CI failures and address review comments on a GitHub PR until a true fixed point is reached — all CI green, all valid review comments addressed, all invalid comments rejected with reasons. A single invocation handles everything.

## Core Principle: Say NO

Not every review comment deserves a code change. Before touching code, evaluate every comment with two independent AI reviewers (Opus 4.6 + Codex/GPT-5.4). Reject comments that are wrong, out of scope, or unrelated. Post a clear explanation on the PR when rejecting. This prevents scope creep and unnecessary churn.

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
| `mcp__github__add_reply_to_pull_request_comment` | Post replies (both "fixed" replies and rejection replies). |
| `mcp__github__resolve_review_thread` | Resolve threads after a fix is pushed. |

## Workflow

### Step 0: Preflight — verify the GitHub MCP

Call `mcp__github__get_me`. If the tool is unavailable in the session or the call errors, **stop immediately** with this message:

> **GitHub MCP not available.** This skill requires the GitHub MCP server. Enable it in your Claude Code settings (`.mcp.json` or `~/.claude/settings.json`) and re-run. See https://github.com/github/github-mcp-server for setup.

Do not fall back to `gh` for the workflow. On success, capture `login` as `GH_USER` (used to filter out self-authored comments later).

### Step 1: Identify the PR

1. Get `{owner}/{repo}`: run `git remote get-url origin`, then parse to `owner/repo` (strip `git@github.com:`, `https://github.com/`, and trailing `.git`). If parsing fails, stop and ask the user for the repository.
2. Get the current branch: `git rev-parse --abbrev-ref HEAD`.
3. If a PR number was provided as argument, use it directly. Otherwise call `mcp__github__list_pull_requests` with `head={owner}:{branch}`, `state=open`, `perPage=1`. If no PR is returned, stop and tell the user there is no open PR for the current branch.
4. Validate by calling `mcp__github__pull_request_read` method=`get` to retrieve `title`, `body`, `head.ref`, `head.sha`, `url`. Confirm `head.ref` matches the local branch.
5. Subscribe to PR activity once: call `mcp__github__subscribe_pr_activity` with `{owner, repo, pullNumber}`. From this point on, CI completions, new reviews, and new comments will arrive as `<github-webhook-activity>` events in the conversation. The subscription is idempotent; do not call it again per iteration.

### Step 2: Read Project Pre-commit Requirements

Find CLAUDE.md (or AGENTS.md) by walking from working directory to repo root. Extract **only explicitly stated** pre-commit commands: format, lint, type-check, test, build. If none are stated, skip pre-commit checks entirely.

### Step 3: Fetch PR State

Issue these MCP calls (paginate where applicable) and merge into a single state object:

| State field | Source |
|---|---|
| `head_sha` | `pull_request_read method=get` → `head.sha` |
| `ci_failures` | `pull_request_read method=get_check_runs` → keep entries whose `conclusion ∈ {failure, timed_out, cancelled, startup_failure, action_required}`. For each `failure` whose `app.slug == "github-actions"`, mark `fixable=true` and fetch the log tail via `Bash`: `gh run view --job <check_run.id> --log-failed 2>&1 | tail -<LOG_TAIL_LINES>`. Other failure types are non-fixable — report them. |
| `review_threads` | `pull_request_read method=get_review_comments` (paginate via `perPage=100`, `after`). Split into `unresolved = [t for t in threads if not t.isResolved]` and `resolved_thread_ids = [t.id for t in threads if t.isResolved]`. For each thread, take the last element of `comments` (sorted by `createdAt` if order is not guaranteed) as `latestComment`. |
| `review_summaries` | `pull_request_read method=get_reviews`. Apply supersession (see below). |
| `pr_comments` | `pull_request_read method=get_comments`. Drop entries where `user.login == GH_USER`. |

**Supersession algorithm for reviews:** group reviews by `user.login`. Within each group, sort by `submitted_at` ascending. Find the index of the latest `APPROVED` or `DISMISSED` review (or -1 if none). Discard everything at or before that index. From the remainder, keep only `CHANGES_REQUESTED` or `COMMENTED` reviews with non-empty `body` and `user.login != GH_USER`. The result is the actionable summary list.

**Errors:** if any MCP call fails, accumulate the error message into an `errors` list. Do not abort — downstream steps tolerate partial state and re-fetch.

Initialize `ADDRESSED_IDS` with `resolved_thread_ids`. Initialize `REJECTED_THREADS = {}` (`thread_id → latest_comment_database_id_at_rejection`).

Present the initial assessment and ask: **"Found N CI failures and M unresolved review comments. Begin fixing?"**

If nothing to fix, report the PR is clean and proceed to Step 6 (monitoring).

### Step 4: Evaluate Every Review Comment

**This is the most important step.** For each unresolved review comment not in `ADDRESSED_IDS`, read the referenced file and code context, then spawn **two subagents in parallel**:

1. **Opus Evaluator** — Agent tool with `model="opus"`. Provide the comment, code context, PR title/description, and changed files summary. Ask for a VALID/INVALID verdict with category, confidence, and reasoning. See `references/comment-evaluation.md` for the full prompt template.

2. **Codex Evaluator** — Invoke `/codex-2nd-opinion` via the Skill tool with the same context. Ask for the same verdict format.

**Decision logic** (from `references/comment-evaluation.md`):

| Opus | Codex | Action |
|------|-------|--------|
| VALID | VALID | Address it |
| VALID | INVALID | Address it |
| INVALID | VALID | Address it |
| INVALID | INVALID | **Reject it** |

Exception: if one says INVALID with HIGH confidence and the other says VALID with LOW confidence, treat as INVALID.

For ambiguous comments (open questions, architectural suggestions, multiple alternatives), present to the user with both evaluators' reasoning and wait for guidance.

### Step 5: The Fix Loop

Loop until fixed point:

**5a. Reject invalid comments.** For each comment evaluated as INVALID, compose a rejection body using the prefix table below, then call `mcp__github__add_reply_to_pull_request_comment` with the comment's `databaseId` and the body. Do **not** call `resolve_review_thread` — the thread stays unresolved so the reviewer can push back. Record the thread in `REJECTED_THREADS` as `thread_id → current_latest_comment_database_id`. Do **not** add to `ADDRESSED_IDS`.

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
| (default) | `**No action taken** —` |

**5b. Fix valid comments and CI failures.** Apply fixes one issue at a time:
- CI failures: read error logs, identify failing file/line, read source, fix.
- Review comments: read the referenced file, understand context, apply the requested change.
- Review summaries / PR comments: parse for specific asks, locate files, apply changes.

After handling each review summary or PR conversation comment, add its ID to `ADDRESSED_IDS`.

**5c. Run pre-commit checks** (from Step 2) in order: format → lint → type-check → test → build. If a formatter modifies files, stage them. If a check fails, attempt one sub-fix (does not count as an iteration). If the sub-fix also fails, ask the user.

**5d. Commit and push.** If `git status --porcelain` shows no changes, skip to 5f. Otherwise: stage files by name (not `git add -A`), commit with a descriptive message, push. On rejected push, stop and tell user to `git pull --rebase`. On network error, retry with exponential backoff (2s, 4s, 8s, 16s).

**5e. Reply to every addressed comment.** For each review thread fixed in this iteration:
1. Call `mcp__github__add_reply_to_pull_request_comment` with the thread's `databaseId` and body `Fixed in \`<short-sha>\``. If it fails with 403/429, wait 60s and retry once. Reply failure is **non-fatal** — the code fix is already pushed.
2. Call `mcp__github__resolve_review_thread` with the thread's GraphQL `threadId`. Same 403/429 retry rule. If resolve succeeds, add the thread to `ADDRESSED_IDS`. If resolve fails, do **not** suppress the thread — it will reappear on re-fetch and be retried.

This step is **mandatory** — never skip it.

**5f. Wait for CI.** Wait passively for `<github-webhook-activity>` events from the active subscription. Treat these as the trigger to re-fetch:
- `check_run.completed` / `workflow_run.completed` — CI finished, re-fetch immediately.
- `pull_request_review.submitted` / `pull_request_review_comment.created` / `issue_comment.created` — new feedback, re-fetch immediately.

Track wall-clock elapsed time since the last commit was pushed. If `CI_TIMEOUT` minutes elapse with no terminal CI event, ask the user whether to keep waiting or abort. If the subscription appears dropped (no events for an extended period), re-call `mcp__github__subscribe_pr_activity` (idempotent) and continue.

**5g. Re-fetch state and check for fixed point.** Re-run Step 3's MCP calls. Filter out threads whose ID is in `ADDRESSED_IDS`. For each thread in `REJECTED_THREADS`, suppress it **only if** its newest comment `databaseId` still matches the value recorded at rejection; if a later comment exists, the reviewer has replied — remove the thread from `REJECTED_THREADS` and treat it as fresh feedback to re-evaluate in Step 4. If the merged state has a non-empty `errors` list, do **not** declare a fixed point — report the fetch failures and retry after 30 seconds.

**Fixed point reached** if:
- All CI checks pass (no `failure` bucket — `cancelled` is informational, doesn't block)
- No new unresolved feedback exists

→ Proceed to Step 6.

**Stale loop detected** if the same CI checks are failing with similar error patterns as the previous iteration → report to user, ask whether to continue or stop.

**New issues found** → run Step 4 (evaluate new comments) and continue the loop.

### Step 6: Monitoring Phase

Skip if `MONITOR_DURATION` is 0 or if there are unresolved issues.

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
| Iteration | Commit | Fixes Applied |
|-----------|--------|---------------|
| 1 | abc123 | Fixed lint error in foo.ts, addressed review on bar.ts |
| 2 | def456 | Fixed test failure in baz_test.py |

### Rejected Comments
| Comment | Category | Reason |
|---------|----------|--------|
| @reviewer on file.ts:42 | scope-creep | Retry logic is valid but out of scope |

### Current Status
- CI: All passing / N failures remaining
- Review comments: All addressed / M unresolved
```

If unresolved issues remain, ask if the user wants further attempts. If everything is resolved: **"PR is ready for re-review."**

## References

- **`references/api-patterns.md`** — MCP tool signatures, expected response shapes, supersession algorithm, push handling, log-fetching gap
- **`references/comment-evaluation.md`** — Full evaluation prompt templates, decision matrix, rejection taxonomy, ambiguity handling
