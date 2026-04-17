# API Patterns Reference

Detailed API interaction patterns for the pm-autofix-pr skill. These are implemented in the scripts but documented here for troubleshooting and manual use.

## Identifying the PR

Determine repository:
```bash
gh repo view --json nameWithOwner -q '.nameWithOwner'
```

Auto-detect PR from current branch:
```bash
gh pr view --json number,title,headRefName,url
```

Get current gh user (for filtering self-comments):
```bash
gh api user -q '.login'
```

## CI Check Runs

Fetch the PR head SHA:
```bash
sha=$(gh api repos/{owner}/{repo}/pulls/<number> --jq '.head.sha')
```

List check runs for that commit:
```bash
gh api repos/{owner}/{repo}/commits/$sha/check-runs --paginate \
  --jq '.check_runs[] | {id, name, status, conclusion, app_slug: .app.slug}'
```

### Terminal conclusions to handle

| Conclusion | Fixable? | Action |
|-----------|----------|--------|
| `failure` + `app_slug: github-actions` | Yes | Fetch logs, diagnose, fix |
| `failure` + other `app_slug` | No | Report to user |
| `timed_out` | No | Report to user |
| `cancelled` | No | Report (may need re-trigger) |
| `startup_failure` | No | Report to user |
| `action_required` | No | Report to user |

### Fetching failure logs

Find the workflow run for the head SHA:
```bash
run_id=$(gh api repos/{owner}/{repo}/actions/runs \
  --jq ".workflow_runs[] | select(.head_sha==\"${sha}\") | .id" | head -1)
```

Fetch failed job logs:
```bash
gh run view "$run_id" --log-failed 2>&1 | tail -$LOG_TAIL_LINES
```

If the tail doesn't contain an obvious error, search the full output for common error markers: `FAIL`, `Error`, `error:`, `FAILED`, `assert`.

## Review Threads (GraphQL)

Fetch all review threads with resolution state and full comment chains:

```graphql
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 50) {
            nodes {
              id
              databaseId
              body
              author { login }
              createdAt
            }
          }
        }
      }
    }
  }
}
```

- `isResolved` is the authoritative signal for whether a thread has been addressed
- `id` (node ID) is used for the GraphQL `resolveReviewThread` mutation
- `comments.nodes[0].databaseId` is the numeric REST ID needed for the reply endpoint

## Review Summaries

Fetch review bodies (top-level text submitted with each review):
```bash
gh api repos/{owner}/{repo}/pulls/<number>/reviews --paginate \
  --jq '.[] | select(.body != "" and .body != null) | {id, body, state, user: .user.login, submitted_at}'
```

### Supersession Logic

Group reviews by `user`, sort by `submitted_at`. For each reviewer, discard all reviews superseded by a later `APPROVED` or `DISMISSED` review from the same reviewer. Only then treat the remaining `CHANGES_REQUESTED` or `COMMENTED` reviews with actionable text as feedback.

## PR Conversation Comments

```bash
gh api repos/{owner}/{repo}/issues/<number>/comments --paginate \
  --jq '.[] | {id, body, user: .user.login, created_at}'
```

Filter out comments authored by the current `gh` user.

## Replying to Review Threads

Post a reply using the first comment's `databaseId`:
```bash
gh api repos/{owner}/{repo}/pulls/<number>/comments \
  -f body="Fixed in \`$(git rev-parse --short HEAD)\`" \
  -F in_reply_to_id=<comment-databaseId> \
  --method POST
```

## Resolving Review Threads

Use the thread's GraphQL node `id`:
```graphql
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { isResolved }
  }
}
```

## Rate Limiting

On 403 or 429 responses, wait 60 seconds and retry once. A failed resolve is non-fatal — the code fix is already pushed.

## Push Handling

Check for upstream:
```bash
git rev-parse --abbrev-ref <branch>@{upstream}
```

If upstream exists: `git push`. If not: `git push -u origin <branch>`.

On rejected push (upstream has new commits): stop and tell the user to `git pull --rebase` and re-invoke.

On network error: retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s).
