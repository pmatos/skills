# API Patterns Reference

Detailed GitHub MCP tool signatures and response shapes for the pm-autofix-pr skill. The skill calls these tools directly — there is no script layer.

## Preflight: verify the MCP

```
mcp__github__get_me()
```

Returns the authenticated user object. Use `login` for self-comment filtering. If the tool is unavailable in the session or the call errors, the skill stops with the "GitHub MCP not available" message (see SKILL.md Step 0).

## Identifying the PR

The MCP has no equivalent of `gh pr view`'s branch autodetect, so combine local git with `list_pull_requests`:

```bash
git remote get-url origin     # parse to {owner}/{repo}
git rev-parse --abbrev-ref HEAD
```

Owner/repo parsing rules: strip `git@github.com:` or `https://github.com/` prefixes and any trailing `.git`.

```
mcp__github__list_pull_requests(
  owner=<owner>,
  repo=<repo>,
  head="<owner>:<branch>",
  state="open",
  perPage=1
)
```

Returns an array of PR summaries. Empty → no open PR for the branch; stop.

```
mcp__github__pull_request_read(
  method="get",
  owner=<owner>, repo=<repo>, pullNumber=<num>
)
```

Returns full PR details including `title`, `body`, `head.ref`, `head.sha`, `url`. Validate `head.ref` matches the local branch.

## Subscription (event-driven CI/comment monitoring)

Subscribe **once** after PR identification:

```
mcp__github__subscribe_pr_activity(
  owner=<owner>, repo=<repo>, pullNumber=<num>
)
```

The call is idempotent. Once subscribed, GitHub events arrive in the conversation as `<github-webhook-activity>` messages covering:

- CI: `check_run.completed`, `workflow_run.completed`
- Reviews: `pull_request_review.submitted`
- Comments: `pull_request_review_comment.created`, `issue_comment.created`

These events replace the old `gh pr checks --watch` polling loop. Treat the arrival of a relevant event as a trigger to re-fetch state. Honour `CI_TIMEOUT` via wall-clock so the loop doesn't wait forever if a webhook is dropped.

Always unsubscribe on exit:

```
mcp__github__unsubscribe_pr_activity(
  owner=<owner>, repo=<repo>, pullNumber=<num>
)
```

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

Returns review threads with comments grouped by code location. Each thread carries `id` (GraphQL node ID for resolution), `isResolved`, `isOutdated`, `path`, `line`, and a `comments` array. Each comment carries `id`, `databaseId` (numeric REST ID — needed for replies), `body`, `author.login`, `createdAt`.

Paginate via `perPage` and `after` until exhausted.

Derived state:
- `unresolved_threads = [t for t in threads if not t.isResolved]`
- `resolved_thread_ids = [t.id for t in threads if t.isResolved]`
- `latestComment(thread)` = last element of `thread.comments` (sort by `createdAt` if order is not guaranteed). Used for `REJECTED_THREADS` re-evaluation tracking.

## Review summaries

```
mcp__github__pull_request_read(
  method="get_reviews",
  owner=<owner>, repo=<repo>, pullNumber=<num>
)
```

Returns reviews with `id`, `body`, `state` (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`), `user.login`, `submitted_at`.

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

Returns issue-level comments on the PR. Filter out entries where `user.login == GH_USER` to avoid acting on the skill's own posts.

## Replying to review threads

```
mcp__github__add_reply_to_pull_request_comment(
  owner=<owner>, repo=<repo>, pullNumber=<num>,
  commentId=<latestComment.databaseId>,
  body="Fixed in `<short-sha>`"
)
```

Use the **latest** comment's `databaseId` so replies attach correctly even on long threads. Reply failure is non-fatal — the code fix is already pushed.

## Resolving review threads

```
mcp__github__resolve_review_thread(
  threadId=<thread.id>
)
```

Uses the thread's GraphQL node ID (the `id` field from `get_review_comments`). On success, add the thread to `ADDRESSED_IDS`. On failure, leave it off `ADDRESSED_IDS` so the next re-fetch re-surfaces it for retry.

## Rejecting comments

Same tool as replying — `add_reply_to_pull_request_comment` — but with a categorized prefix and disclaimer body (see SKILL.md Step 5a for the prefix table). Do **not** call `resolve_review_thread`: rejected threads stay open so the reviewer can push back.

## Rate limiting

If any MCP call errors with `403` or `429`, wait 60 seconds and retry once. After a single failed retry:
- Reply failures (`add_reply_to_pull_request_comment`) are non-fatal — log and continue.
- Resolve failures (`resolve_review_thread`) are non-fatal but the thread stays off `ADDRESSED_IDS` so it re-surfaces.
- State-fetch failures get added to the `errors` list and prevent the fixed-point declaration in Step 5g.

## Push handling (unchanged — still local `git`)

```bash
git rev-parse --abbrev-ref <branch>@{upstream}   # check upstream exists
git push                                          # if upstream exists
git push -u origin <branch>                       # if not
```

On rejected push (upstream has new commits): stop and tell the user to `git pull --rebase` and re-invoke.

On network error: retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s).
