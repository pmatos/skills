---
name: pm-autofix-pr
description: This skill should be used when the user asks to "autofix pr", "fix pr locally", "fix ci failures", "fix review comments", "iterate on pr", "fix failing checks", "fix pr comments", "make ci green", "fix the build", "address reviewer feedback", or wants to iteratively fix CI failures and review comments on a GitHub PR from the local CLI.
user-invocable: true
---

# Autofix PR

Iteratively fix CI failures and address reviewer feedback on a GitHub PR until a true fixed point is reached — all CI green, every feedback item triaged into one of three outcomes (FIX, DEFER, REJECT), and every feedback item has a reply documenting the outcome. A single invocation handles everything end-to-end without user input.

## Core Principle: Three Outcomes per Feedback Item

Not every review comment deserves a code change in this PR, and not every rejected comment is worthless. Before touching code, evaluate every review thread, review summary, and PR conversation comment on its merits with two independent AI reviewers — the **local host model** (whichever harness you are running in) and a **cross-harness model** (Claude ↔ Codex; whichever one you are not). Each item is triaged into exactly one of:

- **FIX** — correct **and** in scope for this PR → change the code in this PR, reply with the commit.
- **DEFER** — correct but out of scope, or a minor/diminishing-returns nit not worth churn in this PR → file a tracking issue, reply on the PR with a link to the new issue.
- **REJECT** — wrong, unrelated, already-handled, or pure style preference with no project backing → reply with a rationale, no code change, no issue.

DEFER is the safety valve that lets the skill say "not now" to legitimate-but-low-value feedback without losing it. Use it for: pickiness on naming/style where the current code is reasonable, micro-optimizations, refactor requests for working code, doc requests for internal helpers, and anything correct but outside the PR's stated scope.

## Core Principle: Always Reply

Every reviewer feedback item must get an explicit reply before the skill can converge. FIX gets a reply that says what was fixed, where it was fixed, and the commit that contains it. DEFER gets a reply with the rejection rationale plus a link to the filed tracking issue. REJECT gets a reply that says no code change was made and why. A missing reply is still unfinished work, even if the code and CI are already green.

## Core Principle: Never Prompt the User

This skill runs end-to-end without asking the user anything once invoked. There is no "begin fixing?" confirmation, no "ambiguous feedback, how should I handle it?", no "pre-commit failed, retry?", no "stale loop, continue?", no "CI timeout, keep waiting?". Every decision point has a deterministic auto-action defined below; uncertain feedback defaults to DEFER (file an issue and let humans resolve later); unrecoverable conditions exit cleanly with a final summary. The only way the skill stops mid-flight is by reaching the fixed point, hitting a hard precondition failure (missing MCP, missing cross-harness CLI, no PR for the branch), or hitting an unrecoverable error (rebase conflict, persistent push failure). Each exit goes through Step 7's summary.

## Prerequisites

- **GitHub MCP server** must be configured in the host session (Claude Code or Codex CLI). The skill stops at preflight if it isn't available.
- **`gh` CLI** is still required for one thing only: fetching failed-job log tails (`gh run view --job <id> --log-failed`). The MCP has no equivalent. All other GitHub interaction goes through the MCP.
- **Both harness CLIs** must be installed: `claude` (Claude Code, `npm install -g @anthropic-ai/claude-code`) and `codex` (Codex CLI, `npm install -g @openai/codex`). The dual-evaluator step calls whichever one is *not* the host. The skill stops at preflight if the cross-harness CLI is missing.

## Configuration

Override via prompt arguments (e.g., `/pm-autofix-pr 10 --ci-timeout 30 --monitor 0`).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MONITOR_DURATION` | 10 | Minutes to watch for new issues after convergence. 0 to skip. |
| `CI_TIMEOUT` | 20 | Minutes to wait for CI before aborting (no user prompt — exits through Step 7 with `ci-timeout`). |
| `LOG_TAIL_LINES` | 500 | Lines of CI failure log to inspect. |

There is no iteration limit. The loop runs until one of: fixed point reached, stale loop detected, CI timeout, rebase conflict, persistent push failure, or monitoring window elapsed. Every exit goes through Step 7. The skill never prompts the user.

## MCP Tools Used

All GitHub interaction is direct MCP tool calls — no bundled scripts.

| Tool | Purpose |
|------|---------|
| `mcp__github__get_me` | Preflight gate; also returns the current user's `login` for self-comment filtering. |
| `mcp__github__list_pull_requests` | Auto-detect the PR for the current branch. |
| `mcp__github__pull_request_read` | Fetch PR details, check runs, review comments/threads, reviews, conversation comments, status. |
| `mcp__github__subscribe_pr_activity` | One-time subscription so CI/review/comment events arrive as `<github-webhook-activity>` messages. |
| `mcp__github__unsubscribe_pr_activity` | Cleanup on exit. |
| `mcp__github__add_reply_to_pull_request_comment` | Post replies on inline review threads (FIX, DEFER, and REJECT replies). |
| `mcp__github__add_issue_comment` | Post PR-level replies for review summaries and PR conversation comments. |
| `mcp__github__pull_request_review_write` (`method="resolve_thread"`) | Resolve threads after a fix is pushed. |
| `mcp__github__issue_write` (`method="create"`) | File a tracking issue for each DEFER outcome (out-of-scope, diminishing-returns, ambiguous, or automated-fix-failed). |

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
| `codex` | Bash: `codex exec --full-auto --sandbox read-only --ephemeral - < /tmp/eval-XXXX` (10-min timeout) | Bash: `claude -p --permission-mode auto --output-format text < /tmp/eval-XXXX` (10-min timeout) |

For Bash-based evaluator spawns, write the prompt to a `mktemp /tmp/eval-XXXXXX` file, run the command with stdin redirection, capture stdout, then `rm -f` the temp file.

### Step 0b: Preflight — verify the GitHub MCP

Call `mcp__github__get_me`. If the tool is unavailable in the session or the call errors, **stop immediately** with this message:

> **GitHub MCP not available.** This skill requires the GitHub MCP server. Enable it in your host's MCP settings (`.mcp.json`, `~/.claude/settings.json`, or the Codex equivalent) and re-run. See https://github.com/github/github-mcp-server for setup.

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
| `review_threads` | `pull_request_read method=get_review_comments` (paginate via `perPage=100`, `after`). Split into `unresolved = [t for t in threads if not t.isResolved]` and `resolved_thread_ids = [t.id for t in threads if t.isResolved]`. For each unresolved thread, take the last non-self element of `comments` (sorted by `createdAt` if order is not guaranteed and `author.login != GH_USER`) as `latestReviewerComment`. Drop self-only threads whose `latestReviewerComment` is absent from `feedback_items`; they are author notes, not reviewer feedback, and must not be dereferenced later. |
| `review_summaries` | `pull_request_read method=get_reviews`. Apply supersession (see below). |
| `pr_comments` | `pull_request_read method=get_comments`. Drop entries where `user.login == GH_USER`. |

**Supersession algorithm for reviews:** group reviews by `user.login`. Within each group, sort by `submitted_at` ascending. Find the index of the latest `APPROVED` or `DISMISSED` review (or -1 if none). Discard everything at or before that index. From the remainder, keep only `CHANGES_REQUESTED` or `COMMENTED` reviews with non-empty `body` and `user.login != GH_USER`. The result is the actionable summary list.

**Errors:** if any MCP call fails, accumulate the error message into an `errors` list. Do not abort — downstream steps tolerate partial state and re-fetch.

Build `feedback_items` from:
- unresolved review threads with a non-null `latestReviewerComment`, keyed as `thread:<thread.id>`
- `review_summaries`, keyed as `review:<review.id>`
- `pr_comments`, keyed as `comment:<comment.id>`

Initialize `ADDRESSED_THREAD_IDS` with `resolved_thread_ids`. Initialize `REPLIED_ITEM_KEYS = {}` for review summaries and PR conversation comments that already received an outcome reply during this invocation. Initialize `OUTCOME_MARKERS = {}` (`item_key → latest_reviewer_marker_at_outcome`) covering both REJECTED and DEFERRED items so a later reviewer edit re-enters evaluation. Initialize `DEFERRED_ITEMS = []` (one entry per filed tracking issue, used by Step 7's summary).

Print the initial assessment as a status line — `Found N CI failures and M reviewer feedback items. Begin processing.` — and proceed unconditionally. **Never** wait for a confirmation: the skill is fully automatic from this point on.

If nothing to fix, report the PR is clean and proceed to Step 6 (monitoring).

### Step 4: Evaluate Every Feedback Item

**This is the most important step.** Every time PR state is fetched, evaluate reviewer feedback before waiting on CI. Do not defer review handling until checks finish.

For each feedback item not already answered, gather context, then spawn **two subagents in parallel**. Inline threads are already answered when `thread.id ∈ ADDRESSED_THREAD_IDS`; review summaries and PR conversation comments are already answered when `item_key ∈ REPLIED_ITEM_KEYS`; previously rejected or deferred feedback is already answered when `item_key ∈ OUTCOME_MARKERS` and its reviewer marker has not changed.

- Inline review threads: use `latestReviewerComment`, then read the referenced file and code context.
- Review summaries: parse the body into concrete asks; read the PR diff, PR description, and any files mentioned by the review.
- PR conversation comments: parse the body into concrete asks; read referenced files, logs, or diff context as needed.

1. **Local Evaluator** — runs the host model in a clean context. Use the row from Step 0a's per-host invocation table that matches your host:
   - **Claude host:** Agent tool with `model="opus"`.
   - **Codex host:** Bash with `codex exec --full-auto --sandbox read-only --ephemeral - < /tmp/eval-XXXXXX` (10-minute timeout). Write the prompt via `mktemp` first; `rm -f` after.

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
| REJECT | REJECT | **REJECT** — reply with rationale, no code change, no issue |
| DEFER | DEFER | **DEFER** — file tracking issue, reply with link |
| any other combination | | **DEFER** — file tracking issue (any disagreement defaults to DEFER) |

The rule is conservative on purpose: only fix when both evaluators agree the change belongs in this PR; only reject when both agree there is no concern worth tracking; otherwise file an issue so nothing is silently dropped. This matches the "Three Outcomes" core principle.

**Ambiguous feedback** (open questions, architectural suggestions with multiple alternatives, requests that depend on undocumented context) is auto-classified as **DEFER** without consulting the user. The filed issue is the durable artifact a human can resolve later; the PR reply tells the reviewer where the discussion has moved. Do not block the loop on user input.

### Step 5: The Triage and Fix Loop

Loop until fixed point or unrecoverable abort. Process each feedback item exactly once per fetch cycle through the outcome flow that matches its Step 4 verdict.

**5a. REJECT flow** (verdict = REJECT). Compose a rejection body using the prefix table below and reply through the right channel:
- Inline review thread: call `mcp__github__add_reply_to_pull_request_comment` with `commentId = latestReviewerComment.databaseId`.
- Review summary or PR conversation comment: call `mcp__github__add_issue_comment` with `issue_number = pullNumber`. Start the body with `@reviewer Regarding your <review/comment> (<short identifier>):` and quote or summarize the specific ask being rejected.

Do **not** resolve rejected inline threads — they stay unresolved so the reviewer can push back. Record the item in `OUTCOME_MARKERS` as `item_key → latest_reviewer_marker_at_outcome` using a mutable marker: `latestReviewerComment.databaseId + updatedAt` for inline threads, `review.id + updated_at` for review summaries when available, `review.id + body_hash(body)` for review summaries when no update timestamp exists, and `comment.id + updated_at` for PR conversation comments. Do **not** add it to `ADDRESSED_THREAD_IDS`; suppression depends on the recorded reviewer marker staying current.

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

3. Call `mcp__github__issue_write` with `method="create"`, `owner`, `repo`, `title`, `body`, and (if applicable) `labels=["deferred-from-pr"]`. Capture the returned `number` and `html_url`.
4. Compose the PR reply with the matching prefix below, ending with `Tracked as #{new_issue_number} ({issue_html_url}).`

   Prefixes by DEFER category:

   | Category | Prefix |
   |---|---|
   | `scope-creep` | `**Out of scope for this PR** —` |
   | `diminishing-returns` | `**Deferred (diminishing returns)** —` |
   | `ambiguous` | `**Deferred for separate discussion** —` |
   | `automated-fix-failed` | `**Deferred (automated fix failed pre-commit)** —` |
   | (default) | `**Deferred** —` |

5. Reply through the same channel as REJECT (inline thread → `add_reply_to_pull_request_comment`; review summary / PR comment → `add_issue_comment`). Do **not** resolve inline threads — the reviewer can push back if the deferral is wrong.
6. Record the item in `OUTCOME_MARKERS` (same marker scheme as REJECT). Append `{item_key, issue_number, issue_url, category, title}` to `DEFERRED_ITEMS` for the Step 7 summary.

**Issue-creation failure fallback.** If `mcp__github__issue_write` fails (rate limit, permissions, transient error) — retry once after 60 seconds. If the retry also fails, **do not block the loop**: post the DEFER reply with `TODO: file as a separate issue — automated issue creation failed (<error summary>).` instead of the tracked-issue link, and append `{item_key, issue_number=null, ...}` to `DEFERRED_ITEMS` so the final summary surfaces the gap. The reviewer's concern is still acknowledged in writing.

**5b. FIX flow** (verdict = FIX) and CI failures. Process each FIX item individually — apply, check, commit — before moving to the next. This isolates each item in its own commit so a pre-commit failure can be reverted cleanly without touching earlier successful fixes (`git restore <files>` is safe because only the in-flight item's changes are in the worktree).

**Precondition** before entering 5b: the worktree must be clean (`git status --porcelain` empty). If it is not, fail loudly and jump to Step 7 with `exit reason: dirty-worktree` — there is no safe way to attribute the existing changes to a specific FIX item.

For each FIX item in `feedback_items` whose verdict is FIX (CI failures included), in sequence:

1. **Apply the change.** Read the relevant source/error context and edit files:
   - CI failures: read the failed-job log tail, identify failing file/line, fix.
   - Inline review threads: read the referenced file, apply the requested change.
   - Review summaries / PR conversation comments: locate files, apply the parsed asks.
2. **Run pre-commit checks** for this item (Step 5c).
3. **On pre-commit success:** stage the touched files by name (never `git add -A`), commit with a descriptive message that names the feedback item (e.g. `Fix null check in extractTokens (review thread #PRRT_xxx)`), capture the resulting short-sha, and add the FIX item to `COMMITTED_ITEMS = []` with `{item_key, sha, files, validation}`.
4. **On pre-commit failure** (5c returned a hard fail after the sub-fix attempt): revert this item with `git restore <files>` — safe because only this item's changes are in the worktree at this point, since every earlier FIX is already committed. Record the item under `BLOCKED_ITEMS = []` with `{item_key, files, pre_commit_error_tail}`. Continue with the next FIX item; blocked items will be turned into `automated-fix-failed` DEFER entries (with their own tracking issues) at the end of the loop iteration.

After all FIX items have been processed, the worktree is clean and `COMMITTED_ITEMS` lists every successful fix with its own sha. Each entry's sha is what 5e quotes in the corresponding "Fixed in `<sha>`" reply.

**Convert each blocked FIX into an `automated-fix-failed` DEFER before leaving 5b.** For every entry in `BLOCKED_ITEMS` (the items 5b reverted because pre-commit refused them), run the Step 5a' DEFER flow with `category="automated-fix-failed"`:

- Title: `Auto-fix failed pre-commit: <one-line summary of the original feedback>`.
- Issue body: include the reviewer's original feedback (quoted), the file paths the FIX touched, and the `pre_commit_error_tail` captured in 5b. Set the `**Why deferred:**` line to `automated-fix-failed — <one-line of the pre-commit error>`.
- File the tracking issue with `mcp__github__issue_write`, post the DEFER reply on the original thread / review summary / PR conversation comment using the `automated-fix-failed` prefix from Step 5a' and ending with `Tracked as #<issue_number> (<issue_html_url>).`, then record the item in `OUTCOME_MARKERS` and append it to `DEFERRED_ITEMS` — exactly like an evaluator-driven DEFER. Apply the same retry + `TODO: file as a separate issue` fallback if `issue_write` fails.

After this conversion, every blocked item has an explicit PR reply and (best-effort) a tracking issue, so the "Always Reply" core principle holds for blocked FIXes too. Clear `BLOCKED_ITEMS` for the iteration; do not include their entries in 5e (which only iterates `COMMITTED_ITEMS`).

**5c. Pre-commit checks** (from Step 2) — invoked by 5b for the current in-flight item only. Run in order: format → lint → type-check → test → build. If a formatter modifies files, stage them. If a check fails, attempt one sub-fix (does not count as a loop iteration). If the sub-fix also fails, **do not ask the user** — return a hard fail to 5b, which handles the revert and continues with the next FIX item. The check is bounded to this single item because earlier successful items are already committed and out of the worktree.

**5d. Push the iteration's commits.** After 5b finishes, if `git rev-list HEAD ^@{u} --count` (or, if no upstream is set yet, `git rev-list HEAD ^origin/<base-branch> --count`) is zero — no new commits — skip to 5f. Otherwise push all new commits in one operation.

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
- Inline review thread: call `mcp__github__add_reply_to_pull_request_comment` with `commentId = latestReviewerComment.databaseId` (the numeric REST ID of the thread's most recent reviewer comment — **not** the thread's GraphQL `id`). After the reply succeeds, call `mcp__github__pull_request_review_write` with `method="resolve_thread"` and `threadId = <thread.id>` (the GraphQL node ID from `get_review_comments`). If both calls succeed, add the thread to `ADDRESSED_THREAD_IDS`.
- Review summary or PR conversation comment: call `mcp__github__add_issue_comment` with `issue_number = pullNumber`. Start the body with `@reviewer Regarding your <review/comment> (<short identifier>):`, then include the fixed outcome. If the reply succeeds, add the item key to `REPLIED_ITEM_KEYS`.

This step is **mandatory** — never skip it. If a reply or resolve call fails with 403/429, wait 60s and retry once. After a failed retry, continue the code loop if needed, but do not count that feedback item as addressed and do not declare convergence; it must reappear on the next fetch/retry cycle until a reply is posted.

**5f. Wait for CI only after feedback is answered.** If any fetched feedback item still lacks an evaluation decision and an outcome reply, re-enter Step 4 immediately instead of waiting for CI. Once feedback is answered, wait passively for `<github-webhook-activity>` events from the active subscription. Treat these as the trigger to re-fetch:
- `check_run.completed` / `workflow_run.completed` — CI finished, re-fetch immediately.
- `pull_request_review.submitted` / `pull_request_review.edited` / `pull_request_review_comment.created` / `pull_request_review_comment.edited` / `issue_comment.created` / `issue_comment.edited` — new or edited feedback, re-fetch immediately and process it before waiting for more CI events.

Track wall-clock elapsed time since the last commit was pushed. If `CI_TIMEOUT` minutes elapse with no terminal CI event, **abort the loop** — record `ci_timeout` in the final summary and jump to Step 7. Do not prompt the user. If the subscription appears dropped (no events for an extended period but `CI_TIMEOUT` has not elapsed), re-call `mcp__github__subscribe_pr_activity` (idempotent) and continue.

**5g. Re-fetch state and check for fixed point.** Re-run Step 3's MCP calls. Filter out threads whose ID is in `ADDRESSED_THREAD_IDS` and PR-level feedback whose key is in `REPLIED_ITEM_KEYS`. For each item in `OUTCOME_MARKERS`, suppress it **only if** its latest reviewer marker still matches the value recorded at the prior REJECT/DEFER outcome; if a later reviewer reply exists, remove the item from `OUTCOME_MARKERS` and treat it as fresh feedback to re-evaluate in Step 4. If the merged state has a non-empty `errors` list, do **not** declare a fixed point — report the fetch failures and retry after 30 seconds.

**Fixed point reached** if:
- `ci_failures` is empty after filtering out `cancelled` (the only non-success conclusion treated as informational). Any remaining entry — including `timed_out`, `startup_failure`, `action_required`, and non-`github-actions` `failure` — blocks convergence and is reported to the user.
- No reviewer feedback item remains without an evaluation decision and an outcome reply.

→ Proceed to Step 6.

**Stale loop detected** if the same CI checks are failing with similar error patterns as the previous iteration → record `stale_loop` in the final summary and jump to Step 7. Do not prompt the user. (`BLOCKED_ITEMS` cannot accumulate across iterations because Step 5b now converts each blocked FIX into an `automated-fix-failed` DEFER and clears the list.)

**New issues found** → run Step 4 (evaluate new feedback) and continue the loop.

### Step 6: Monitoring Phase

Skip if `MONITOR_DURATION` is 0 or if there are CI failures or unanswered feedback items.

Report: **"All issues resolved. Monitoring for {MONITOR_DURATION} minutes..."**

Wait for `<github-webhook-activity>` events from the still-active subscription. If a relevant event arrives within the window, re-fetch state and re-enter the evaluate + fix loop (Step 4 → Step 5) with a fresh sub-loop. After fixing, resume monitoring with the remaining time. If the window elapses with no events, proceed to Step 7.

### Step 7: Final Summary and Cleanup

Call `mcp__github__unsubscribe_pr_activity` with `{owner, repo, pullNumber}` to clean up the subscription, regardless of how the loop exited (fixed point, stale loop, CI timeout, rebase abort, push failure, dirty worktree, monitoring timeout).

Then print:

```
## Autofix PR Summary

### PR: #<number> — <title>
### Iterations: N
### Exit reason: fixed-point | stale-loop | ci-timeout | rebase-conflict | push-failure | dirty-worktree | monitoring-timeout

### Changes Made (FIX outcomes)
| Iteration | Commit | Fixes Applied | Replies Posted |
|-----------|--------|---------------|----------------|
| 1 | abc123 | Fixed lint error in foo.ts, addressed review on bar.ts | @reviewer fixed thread in bar.ts via abc123 |
| 2 | def456 | Fixed test failure in baz_test.py | n/a |

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
- Reviewer feedback: All answered / M items still missing replies (list each)
- Issue creation failures: 0 / K (each requires manual filing — see Deferred table)
```

Do **not** ask the user anything at the end. The skill exits unconditionally after printing the summary:

- **Success exits** — `fixed-point` (CI green, all feedback answered) or `monitoring-timeout` (reached only by passing through the same green-CI / answered-feedback gate before entering Step 6, so a clean window-elapse is also success): print **"PR is ready for re-review."**
- **Failure exits** — `stale-loop`, `ci-timeout`, `rebase-conflict`, `push-failure`, `dirty-worktree`: print **"Autofix exited without converging — see summary above for required follow-up."** Do not loop again, do not prompt.

## References

- **`references/api-patterns.md`** — MCP tool signatures, expected response shapes, supersession algorithm, push and rebase handling, issue-creation flow, log-fetching gap
- **`references/comment-evaluation.md`** — Full evaluation prompt templates, FIX/DEFER/REJECT decision matrix, DEFER and REJECT taxonomies, ambiguity-to-DEFER policy
