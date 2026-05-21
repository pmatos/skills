# API Patterns Reference

Detailed GitHub MCP tool signatures and response shapes for the pm-autofix-pr skill. The skill calls these tools directly — there is no script layer.

## Preflight: verify the MCP

```
mcp__github__get_me()
```

Returns the authenticated user object. Use `login` for self-comment filtering. If the tool is unavailable in the session or the call errors, the skill stops with the "GitHub MCP not available" message (see SKILL.md Step 0).

## Identifying the PR

The MCP has no equivalent of `gh pr view`'s branch autodetect, so combine local git with `list_pull_requests` and cascade through the remotes a user might have configured:

```bash
git remote get-url origin        # parse to {origin_owner}/{origin_repo}
git remote get-url upstream      # optional — present in fork checkouts
git rev-parse --abbrev-ref HEAD  # local branch name
```

Owner/repo parsing rules: strip `git@github.com:` or `https://github.com/` prefixes and any trailing `.git`.

**Origin lookup (default case):**

```
mcp__github__list_pull_requests(
  owner=<origin_owner>, repo=<origin_repo>,
  head="<origin_owner>:<branch>",
  state="open", perPage=5
)
```

**Upstream lookup (fork workflow fallback).** If origin returned no open PRs and an `upstream` remote exists, query upstream with `head` still scoped to the fork owner — GitHub expects `head="<fork_owner>:<branch>"` for cross-repo PRs:

```
mcp__github__list_pull_requests(
  owner=<upstream_owner>, repo=<upstream_repo>,
  head="<origin_owner>:<branch>",
  state="open", perPage=5
)
```

**`gh pr view` last-resort fallback.** If MCP lookups return empty and the user has `gh` installed, let `gh` resolve the base repo via `git config` (it walks the remote tracking branch and the `.github` config):

```bash
gh pr view --json number,headRepositoryOwner,headRepository,baseRepositoryOwner,baseRepository,url
```

Use the returned `baseRepositoryOwner.login` and `baseRepository.name` as the PR's owner/repo. If `gh` is not installed or returns nothing, stop and report that no open PR exists for the current branch.

Pick the first strategy that yields exactly one PR whose `head.ref` matches the local branch.

```
mcp__github__pull_request_read(
  method="get",
  owner=<owner>, repo=<repo>, pullNumber=<num>
)
```

Returns full PR details including `title`, `body`, `head.ref`, `head.sha`, `url`. Validate `head.ref` matches the local branch.

## Polling (CI / review / comment monitoring)

The GitHub MCP server exposes no event-stream tool the skill can rely on across harnesses, so all waiting is done by polling the same `pull_request_read` methods used in Step 3 of `SKILL.md`. There is no subscription to set up and nothing to tear down on exit.

The poll loop runs in two places:

- **Step 5f** — after every push, while waiting for CI to terminate or for new reviewer feedback to arrive.
- **Step 6** — after convergence, throughout the `MONITOR_DURATION` window.

Both use the same shape:

```text
loop:
  sleep POLL_INTERVAL          # default 30s, via Bash `sleep <n>`
  re-fetch PR state            # the five Step 3 MCP calls (see below)
  if state changed:            # compare against previous snapshot
    break and re-enter Step 4 / Step 5
  if wall-clock budget exceeded:
    abort with the appropriate exit reason
```

The "five Step 3 MCP calls" are exactly the sources Step 3 uses to build the state object — omit any one of them and the loop can declare a false fixed point because the missing channel will never report new feedback:

1. `pull_request_read method=get` — for `head.sha`.
2. `pull_request_read method=get_check_runs` — for CI conclusions.
3. `pull_request_read method=get_review_comments` — for inline review threads.
4. `pull_request_read method=get_reviews` — for review summaries.
5. `pull_request_read method=get_comments` — for PR conversation comments. **Do not skip this one** — it is the only channel that surfaces top-level PR comments, and missing it would violate the "Always Reply" core principle.

### What counts as a state change

A snapshot is considered changed (and the loop wakes the evaluator) if any of these differ from the previous iteration:

- `head.sha` from `pull_request_read method=get` — a new push from another contributor.
- Any check run from `get_check_runs` transitioned from null/`in_progress` to a terminal `conclusion`, or any check run was added or removed.
- Review-thread count, review-summary count, or PR conversation comment count from `get_review_comments` / `get_reviews` / `get_comments` changed.
- Any review thread's latest comment `updatedAt`/`updated_at`, any review's `updated_at`, or any PR conversation comment's `updated_at` advanced past the value recorded in the previous snapshot. This catches edits as well as new items uniformly.

### Cadence and bounds

- `POLL_INTERVAL` defaults to 30s. At that cadence, an hour of waiting costs ≈120 reads per loop instance — well below GitHub's REST rate limits for a single authenticated user on a single PR.
- `CI_TIMEOUT` is the wall-clock budget for Step 5f. Measure from the moment the loop's most recent push completed; abort when the budget is exceeded with **no** previously-pending check having reached a terminal `conclusion`.
- `MONITOR_DURATION` is the wall-clock budget for Step 6. Measure from entry to monitoring; exit cleanly when it elapses.

### Why polling, not webhook subscription

Earlier drafts of this skill referenced a `subscribe_pr_activity` / `unsubscribe_pr_activity` pair and consumed `<github-webhook-activity>` envelopes. Those tools are Claude Code coordinator-mode built-ins exposed only by certain long-running harnesses (e.g. Claude Code Web); they are not part of the upstream `github-mcp-server` toolset and are not available in the interactive Claude Code CLI or in Codex CLI sessions. Polling works uniformly across every harness this skill supports, at the cost of ~`POLL_INTERVAL/2` average latency between an external event and the loop reacting to it. For a fix loop bottlenecked on CI runs measured in minutes, that latency is invisible.

## CI check runs

```
mcp__github__pull_request_read(
  method="get_check_runs",
  owner=<owner>, repo=<repo>, pullNumber=<num>
)
```

Returns check runs for the PR head. Filter by `conclusion`:

| Conclusion | Fixable? | Action |
|-----------|----------|--------|
| `failure` + `app.slug == "github-actions"` | Yes | Fetch log tail (see below), diagnose, fix |
| `failure` + other `app.slug` | No | Report to user |
| `timed_out` | No | Report to user |
| `cancelled` | No | Informational; doesn't block fixed point |
| `startup_failure` | No | Report to user |
| `action_required` | No | Report to user |

### Fetching failure logs (the one remaining `gh` dependency)

The MCP exposes no tool for raw GitHub Actions job logs. For each fixable failure, use `Bash`:

```bash
gh run view --job <check_run.id> --log-failed 2>&1 | tail -<LOG_TAIL_LINES>
```

The check-run `id` from `get_check_runs` equals the `jobs.id` for GitHub Actions, so this fetches logs for the exact failing job. If the tail doesn't contain an obvious error, search the full output for common error markers: `FAIL`, `Error`, `error:`, `FAILED`, `assert`.

If `gh` is not installed, log-tail fetching is best-effort — fall back to whatever `output.summary` and `output.text` the check run carries, plus `details_url` for the user.

## Review threads and comments

```
mcp__github__pull_request_read(
  method="get_review_comments",
  owner=<owner>, repo=<repo>, pullNumber=<num>,
  perPage=100, after=<cursor>
)
```

Returns review threads with comments grouped by code location. Each thread carries `id` (GraphQL node ID for resolution), `isResolved`, `isOutdated`, `path`, `line`, and a `comments` array. Each comment carries `id`, `databaseId` (numeric REST ID — needed for replies), `body`, `author.login`, `createdAt`, and `updatedAt`/`updated_at` when available.

Paginate via `perPage` and `after` until exhausted.

Derived state:
- `unresolved_threads = [t for t in threads if not t.isResolved]`
- `resolved_thread_ids = [t.id for t in threads if t.isResolved]`
- `latestReviewerComment(thread)` = last non-self element of `thread.comments` (sort by `createdAt` if order is not guaranteed and ignore `author.login == GH_USER`). Use this for evaluation, reply anchoring, and `OUTCOME_MARKERS` re-evaluation tracking.
- `actionable_threads = [t for t in unresolved_threads if latestReviewerComment(t) != null]`. Drop unresolved self-only threads from feedback items; otherwise later reply code would dereference a missing `latestReviewerComment.databaseId`.
- `outcome_marker(thread)` = `<latestReviewerComment.databaseId>:<latestReviewerComment.updatedAt || latestReviewerComment.updated_at || latestReviewerComment.createdAt>`, so edited reviewer comments re-enter evaluation. The same marker scheme is used for both REJECT and DEFER outcomes — both are recorded in `OUTCOME_MARKERS`.

## Review summaries

```
mcp__github__pull_request_read(
  method="get_reviews",
  owner=<owner>, repo=<repo>, pullNumber=<num>
)
```

Returns reviews with `id`, `body`, `state` (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`), `user.login`, `submitted_at`, and `updated_at` when available. Track REJECT/DEFER review summaries in `OUTCOME_MARKERS` with a mutable marker such as `<review.id>:<review.updated_at>`; if the API does not expose an update timestamp, use `<review.id>:<hash(review.body)>` so edited review bodies re-enter evaluation.

### Supersession algorithm

1. Group reviews by `user.login`.
2. Within each group, sort by `submitted_at` ascending.
3. Find the index of the latest `APPROVED` or `DISMISSED` review (or `-1` if none).
4. Discard everything at or before that index.
5. From the remainder, keep only `CHANGES_REQUESTED` or `COMMENTED` reviews with a non-empty `body` and `user.login != GH_USER`.

The result is the actionable summary list.

## PR conversation comments

```
mcp__github__pull_request_read(
  method="get_comments",
  owner=<owner>, repo=<repo>, pullNumber=<num>
)
```

Returns issue-level comments on the PR. Filter out entries where `user.login == GH_USER` to avoid acting on the skill's own posts. Track REJECT/DEFER PR conversation comments in `OUTCOME_MARKERS` with a mutable marker such as `<comment.id>:<comment.updated_at>`; comment edits keep the same ID and must re-enter evaluation.

## Replying to review summaries and PR conversation comments

Review summaries and PR conversation comments do not have inline review-thread reply anchors. A pull request is also an issue, so use the issues comment tool to post a PR-level outcome reply:

```
mcp__github__add_issue_comment(
  owner=<owner>, repo=<repo>,
  issue_number=<pullNumber>,
  body="@reviewer Regarding your review/comment (<short identifier>):\n\nFixed in `<short-sha>`.\n\nChanged: <files/functions/behavior>.\nValidation: <checks run>."
)
```

Use the same tool for no-change decisions, replacing the fixed body with the rejection prefix and rationale from SKILL.md. Because this is a PR-level comment, include enough context for humans to connect the reply to the original feedback: reviewer login, review/comment ID or timestamp, and a short quoted/summarized ask.

## Replying to review threads

```
mcp__github__add_reply_to_pull_request_comment(
  owner=<owner>, repo=<repo>, pullNumber=<num>,
  commentId=<latestReviewerComment.databaseId>,
  body="Fixed in `<short-sha>`.\n\nChanged: <files/functions/behavior>.\nValidation: <checks run>."
)
```

`commentId` is a **comment** ID, not a thread ID. Pass the numeric `databaseId` of the thread's **latest non-self reviewer comment** — the tool rejects the thread's GraphQL `id`. Using the latest reviewer comment keeps replies attached to the current ask instead of replying to the skill's own previous outcome message. A failed reply is not a reason to revert a code fix, but it does block convergence; retry it on the next loop.

## Resolving review threads

Thread resolution goes through `pull_request_review_write` with `method="resolve_thread"` — there is no standalone `resolve_review_thread` tool:

```
mcp__github__pull_request_review_write(
  method="resolve_thread",
  threadId=<thread.id>,
  owner=<owner>, repo=<repo>, pullNumber=<num>
)
```

`threadId` is the thread's GraphQL node ID (the `id` field from `get_review_comments`, e.g. `PRRT_kwDOxxx`). The `owner`/`repo`/`pullNumber` are required by the tool schema but ignored by this method. Resolving an already-resolved thread is a no-op.

On success, add the thread to `ADDRESSED_THREAD_IDS`. On failure, leave it off `ADDRESSED_THREAD_IDS` so the next re-fetch re-surfaces it for retry.

## Rejecting feedback (REJECT outcome)

Use the same reply channel as the feedback source:
- Inline review thread: `add_reply_to_pull_request_comment` with a categorized prefix and disclaimer body (see SKILL.md Step 5a for the prefix table).
- Review summary or PR conversation comment: `add_issue_comment` with `issue_number=<pullNumber>`, reviewer/context prefix, and the categorized rationale.

Do **not** resolve rejected inline threads: rejected threads stay open so the reviewer can push back.

## Deferring feedback (DEFER outcome)

DEFER is "correct, but not in this PR" — the skill files a tracking issue and replies with a link. Two API calls per item:

### 1. File the tracking issue

```
mcp__github__issue_write(
  method="create",
  owner=<owner>, repo=<repo>,
  title="<short imperative phrase from feedback>",
  body="Deferred from #<pullNumber>: <one-line summary>.\n\nOriginal feedback by @<reviewer> on PR #<pullNumber> (<pr_url>):\n\n> <quoted feedback>\n\n**Context:** <file:line or short note>.\n\n**Why deferred:** <scope-creep | diminishing-returns | ambiguous> — <one-sentence rationale>.\n\n_Filed automatically by `pm-autofix-pr` after dual-evaluator triage by <LOCAL_LABEL> and <REMOTE_LABEL>._",
  labels=["deferred-from-pr"]   # optional, only if the repo has the label
)
```

Capture the returned issue `number` and `html_url`. Use them in the PR reply.

If `mcp__github__issue_write` errors with `403` or `429`, wait 60 seconds and retry once. After a single failed retry, post the DEFER reply with `TODO: file as a separate issue — automated issue creation failed (<error summary>).` instead of the issue link, and record the item in `DEFERRED_ITEMS` with `issue_number=null` so the Step 7 summary surfaces the gap.

If the repo doesn't have the `deferred-from-pr` label, the call may fail with a 422 — drop the `labels` field and retry once. Do not pre-create labels.

### 2. Reply on the PR with a link

Use the same reply channel as the feedback source — inline thread → `add_reply_to_pull_request_comment`; review summary / PR conversation comment → `add_issue_comment` — with body:

```
{prefix} {one-sentence rationale}. Tracked as #<issue_number> (<issue_html_url>).

_This assessment was made by two independent AI reviewers (<LOCAL_LABEL> and <REMOTE_LABEL>). If you disagree, please reply and we'll re-evaluate._
```

Prefix from SKILL.md Step 5a' (e.g. `**Out of scope for this PR** —`, `**Deferred (diminishing returns)** —`, `**Deferred for separate discussion** —`).

Do **not** resolve deferred inline threads: like rejected threads, they stay open so the reviewer can push back if the deferral is wrong.

## Rate limiting

If any MCP call errors with `403` or `429`, wait 60 seconds and retry once. After a single failed retry:
- Reply failures (`add_reply_to_pull_request_comment` or `add_issue_comment`) are not code-fatal, but they block convergence. Leave the item off `ADDRESSED_THREAD_IDS` / `REPLIED_ITEM_KEYS` so it re-surfaces for another reply attempt.
- Resolve failures (`pull_request_review_write` with `method="resolve_thread"`) are non-fatal but the thread stays off `ADDRESSED_THREAD_IDS` so it re-surfaces.
- Issue-create failures (`issue_write` with `method="create"`) trigger the DEFER fallback: post the DEFER reply with `TODO: file as a separate issue — automated issue creation failed (<error>).` and record `issue_number=null` in `DEFERRED_ITEMS`. Do not block convergence.
- State-fetch failures get added to the `errors` list and prevent the fixed-point declaration in Step 5g.

## Push handling (local `git`, fully automatic)

```bash
git rev-parse --abbrev-ref <branch>@{upstream}   # check upstream exists
git push                                          # if upstream exists
git push -u origin <branch>                       # if not
```

The skill never prompts the user during push. Two failure modes have automatic recovery:

**Rejected push (upstream has new commits):**

1. Run `git pull --rebase`.
2. If the rebase succeeds, re-run pre-commit checks on the rebased tree, then `git push` again.
3. If the rebase reports conflicts, run `git rebase --abort` to leave the worktree clean and exit through Step 7 with `exit reason: rebase-conflict`. Do not attempt to resolve conflicts automatically and do not prompt the user.

**Network error:** retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s). After the fourth failure, exit through Step 7 with `exit reason: push-failure`. Do not prompt the user.
