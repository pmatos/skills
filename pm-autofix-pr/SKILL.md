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

- `gh` CLI installed and authenticated with `repo` scope (read/write access to pull requests)

## Configuration

Override via prompt arguments (e.g., `/pm-autofix-pr 10 --ci-timeout 30 --monitor 0`).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MONITOR_DURATION` | 10 | Minutes to watch for new issues after convergence. 0 to skip. |
| `CI_TIMEOUT` | 20 | Minutes to wait for CI before prompting user. |
| `LOG_TAIL_LINES` | 500 | Lines of CI failure log to inspect. |

There is no iteration limit. The loop runs until a fixed point or until a stale-loop is detected.

## Bundled Scripts

All API interaction is handled by scripts in `scripts/`. Execute them directly — read them only if patching is needed.

| Script | Purpose |
|--------|---------|
| `scripts/fetch-pr-state.sh <owner> <repo> <pr> <gh_user> [log_lines]` | Fetch CI failures, unresolved review threads, review summaries, PR comments. Outputs JSON. |
| `scripts/reply-and-resolve.sh <owner> <repo> <pr> <comment_db_id> <thread_node_id> <message>` | Post reply to a review thread and resolve it. Rate-limit aware. |
| `scripts/reject-comment.sh <owner> <repo> <pr> <comment_db_id> <category> <reason>` | Post rejection reply (does NOT resolve — lets reviewer respond). |
| `scripts/wait-for-ci.sh <pr> [timeout_minutes]` | Wait for CI. Exit 0=pass, 1=fail, 2=timeout. |

## Workflow

### Step 1: Identify the PR

Run `gh repo view --json nameWithOwner -q '.nameWithOwner'` to get `{owner}/{repo}`. If this fails, stop — the user needs `gh auth login`.

If a PR number was provided as argument, use it. Otherwise auto-detect: `gh pr view --json number,title,headRefName,url,body`. Validate the local branch matches `headRefName`. Get the current gh user: `gh api user -q '.login'`.

### Step 2: Read Project Pre-commit Requirements

Find CLAUDE.md (or AGENTS.md) by walking from working directory to repo root. Extract **only explicitly stated** pre-commit commands: format, lint, type-check, test, build. If none are stated, skip pre-commit checks entirely.

### Step 3: Fetch PR State

Run `scripts/fetch-pr-state.sh {owner} {repo} {pr_number} {gh_user} {LOG_TAIL_LINES}`. Parse the JSON output to get: CI failures (fixable vs non-fixable), unresolved review threads, review summaries, PR conversation comments, and resolved thread IDs.

Initialize `ADDRESSED_IDS` with the resolved thread IDs from the output. Initialize `REJECTED_THREADS` as an empty map `{thread_id → latest_comment_db_id_at_rejection}`.

Present the initial assessment and ask: **"Found N CI failures and M unresolved review comments. Begin fixing?"**

If nothing to fix, report the PR is clean and stop.

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

**5a. Reject invalid comments.** For each comment evaluated as INVALID, run `scripts/reject-comment.sh` with the appropriate category and a clear reason derived from the evaluators' reasoning. Record the thread in `REJECTED_THREADS` as `thread_id → current_latest_comment_db_id`. Do **not** add to `ADDRESSED_IDS` — rejected threads are intentionally left unresolved so the reviewer can push back, and Step 5g must re-surface the thread when they do.

**5b. Fix valid comments and CI failures.** Apply fixes one issue at a time:
- CI failures: read error logs, identify failing file/line, read source, fix.
- Review comments: read the referenced file, understand context, apply the requested change.
- Review summaries / PR comments: parse for specific asks, locate files, apply changes.

After handling each review summary or PR conversation comment, add its ID to `ADDRESSED_IDS`.

**5c. Run pre-commit checks** (from Step 2) in order: format → lint → type-check → test → build. If a formatter modifies files, stage them. If a check fails, attempt one sub-fix (does not count as an iteration). If the sub-fix also fails, ask the user.

**5d. Commit and push.** If `git status --porcelain` shows no changes, skip to 5f. Otherwise: stage files by name (not `git add -A`), commit with a descriptive message, push. On rejected push, stop and tell user to `git pull --rebase`. On network error, retry with exponential backoff (2s, 4s, 8s, 16s).

**5e. Reply to every addressed comment.** For each review thread fixed in this iteration, run `scripts/reply-and-resolve.sh` with message `"Fixed in \`<short-sha>\`"`. If the script exits 0, add to `ADDRESSED_IDS`. If it exits non-zero (resolve failed), do **not** suppress the thread — it will reappear on re-fetch and be retried. This step is **mandatory** — never skip it.

**5f. Wait for CI.** Run `scripts/wait-for-ci.sh {pr_number} {CI_TIMEOUT}`. On timeout (exit 2), ask the user whether to keep waiting or abort.

**5g. Re-fetch state and check for fixed point.** Run `scripts/fetch-pr-state.sh` again. Filter out threads whose ID is in `ADDRESSED_IDS`. For each thread in `REJECTED_THREADS`, suppress it **only if** its newest comment databaseId still matches the value recorded at rejection; if a later comment exists, the reviewer has replied — remove the thread from `REJECTED_THREADS` and treat it as fresh feedback to re-evaluate in Step 4. If the output contains a non-empty `errors` array, do **not** declare a fixed point — report the fetch failures to the user and retry after 30 seconds.

**Fixed point reached** if:
- All CI checks pass (no `fail` bucket — `cancel` is informational, doesn't block)
- No new unresolved feedback exists

→ Proceed to Step 6.

**Stale loop detected** if the same CI checks are failing with similar error patterns as the previous iteration → report to user, ask whether to continue or stop.

**New issues found** → run Step 4 (evaluate new comments) and continue the loop.

### Step 6: Monitoring Phase

Skip if `MONITOR_DURATION` is 0 or if there are unresolved issues.

Report: **"All issues resolved. Monitoring for {MONITOR_DURATION} minutes..."**

Every 60 seconds, run `scripts/fetch-pr-state.sh`. If new issues appear, re-enter the evaluate + fix loop (Step 4 → Step 5) with a fresh sub-loop. After fixing, resume monitoring with remaining time.

### Step 7: Final Summary

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

- **`references/api-patterns.md`** — GraphQL queries, REST endpoints, supersession logic, push handling
- **`references/comment-evaluation.md`** — Full evaluation prompt templates, decision matrix, rejection taxonomy, ambiguity handling
