# API Patterns Reference

Detailed `gh` / `gh api` command signatures and response shapes for the pm-autofix-pr skill. `gh` is the primary path for all GitHub interaction — there is no script layer, and no hard dependency on any MCP server. Two operations are GraphQL-only regardless of `gh` vs. MCP (thread resolution state, and resolving a thread); everywhere else, if a GitHub MCP server happens to already be connected in the session, its tools may be used as an opportunistic fast path for posting comment bodies (it accepts the body as a typed field, sidestepping shell-escaping) — but the skill never waits for or requires one.

## Preflight: verify `gh`

```bash
gh auth status
```

Confirms `gh` is installed, authenticated, and can reach the host. If it exits non-zero, the skill stops with the "`gh` CLI not available" message (see SKILL.md Step 0b).

```bash
gh api user -q .login
```

Returns the authenticated user's login, captured as `GH_USER` for self-comment filtering. This is a REST-sourced login and never carries a `[bot]` suffix (see the note under "Review threads and comments" for why that matters when comparing against GraphQL-sourced logins).

## Identifying the PR

`gh pr view` (no arguments) does its own ambient remote resolution and, on a checkout with multiple GitHub remotes and no `gh repo set-default`, can be ambiguous or prompt for the base repository — which this skill can never do. So the default path resolves `{owner}/{repo}` explicitly from git remotes first, the same way SKILL.md's Step 1 tiers do:

```bash
git remote get-url origin        # parse to {origin_owner}/{origin_repo}
git remote get-url upstream      # optional — present in fork checkouts
git rev-parse --abbrev-ref HEAD  # local branch name
```

Owner/repo parsing rules: strip `git@github.com:` or `https://github.com/` prefixes and any trailing `.git`.

**Origin lookup (default case):**

```bash
gh pr list -R "$ORIGIN_OWNER/$ORIGIN_REPO" \
  --head "$BRANCH" --state open \
  --json number,url,headRefName,baseRefName
```

**Upstream lookup (fork workflow fallback).** If the origin lookup returned no open PRs and an `upstream` remote exists, query upstream instead:

```bash
gh pr list -R "$UPSTREAM_OWNER/$UPSTREAM_REPO" \
  --head "$BRANCH" --state open \
  --json number,url,headRefName,baseRefName
```

`gh pr list --head` filters by branch name only (it does not support the `owner:branch` qualifier some REST-based tools use) — scoping the query with `-R` to the fork's declared upstream is what disambiguates which repo's PR list to search.

**Ambient `gh pr view` last-resort fallback.** If both explicit-remote lookups return nothing (uncommon remote naming, or the base repo isn't reachable via `origin`/`upstream`), let `gh` resolve it:

```bash
gh pr view --json number,url,headRefName,baseRefName
```

Parse `{base_owner}/{base_repo}` directly out of the returned `url` field (`https://github.com/{owner}/{repo}/pull/{number}`) rather than depending on a `baseRepositoryOwner`/`baseRepository` JSON field — `gh pr view --json` does not expose those (verified against `gh` 2.96; the base repo is always the repo `gh` resolved against, which the `url` already encodes). Treat any non-zero exit — including `gh` being unable to pick a single unambiguous repo — as "no PR found": stop and report that no open PR exists for the current branch.

Pick the first strategy that yields exactly one PR whose `head.ref` matches the local branch.

```bash
gh api repos/{owner}/{repo}/pulls/{pull_number}
```

Returns full PR details as REST JSON, including `.title`, `.body`, `.head.ref`, `.head.sha`, `.base.ref`, `.html_url`, and mergeability (`.mergeable`, `.mergeable_state`). Validate `.head.ref` matches the local branch. See "Mergeability and base-branch conflict resolution" below for how the skill consumes the mergeability fields.

## Polling (CI / review / comment monitoring)

`gh`/GitHub expose no event-stream the skill can rely on across harnesses, so all waiting is done by polling the same calls used in Step 3 of `SKILL.md`. There is no subscription to set up and nothing to tear down on exit.

The poll loop runs in two places:

- **Step 5f** — after every push, while waiting for CI to terminate or for new reviewer feedback to arrive.
- **Step 6** — after convergence, throughout the `MONITOR_DURATION` window.

Both use the same shape:

```text
loop:
  sleep POLL_INTERVAL          # default 30s, via Bash `sleep <n>`
  re-fetch PR state            # the five Step 3 calls (see below)
  if state changed:            # compare against previous snapshot
    break and re-enter Step 4 / Step 5
  if wall-clock budget exceeded:
    abort with the appropriate exit reason
```

Step 6 adds one gate Step 5f doesn't need: on wall-clock budget exceeded, it first checks the most recent fetch's `errors` list. A non-empty list (e.g. an indeterminate `mergeable == null`) doesn't move `head.sha`, check runs, or comment counts, so it looks identical to "no change" — but mergeability was never actually confirmed. Step 6 does one extra re-fetch to resolve it before declaring the window elapsed clean (`monitoring-timeout`); if `errors` is still non-empty after that, it's treated as a state change and routed back into Step 4/5 instead. See SKILL.md Step 6.

The "five Step 3 calls" are exactly the sources Step 3 uses to build the state object — omit any one of them and the loop can declare a false fixed point because the missing channel will never report new feedback:

1. `gh api repos/{owner}/{repo}/pulls/{pull_number}` — for `head.sha`, `base.ref`, and mergeability.
2. `gh api repos/{owner}/{repo}/commits/{head_sha}/check-runs` — for CI conclusions.
3. `gh api graphql` (`reviewThreads` query) — for inline review threads and their resolution state.
4. `gh api repos/{owner}/{repo}/pulls/{pull_number}/reviews` — for review summaries.
5. `gh api repos/{owner}/{repo}/issues/{pull_number}/comments` — for PR conversation comments. **Do not skip this one** — it is the only channel that surfaces top-level PR comments, and missing it would violate the "Always Reply" core principle.

### What counts as a state change

A snapshot is considered changed (and the loop wakes the evaluator) if any of these differ from the previous iteration:

- `.head.sha` from call 1 — a new push from another contributor.
- `has_merge_conflict` (derived from `.mergeable`/`.mergeable_state` on call 1) flipped from false to true — the base branch advanced and now conflicts with the PR, which sends the loop into Step 5h.
- Any check run from call 2 transitioned from `null`/`in_progress` `.status` to a terminal `.conclusion`, or any check run was added or removed.
- Review-thread count, review-summary count, or PR conversation comment count from calls 3/4/5 changed.
- Any review thread's latest comment `updatedAt`, any review's `updated_at` (call 4), or any PR conversation comment's `updated_at` (call 5) advanced past the value recorded in the previous snapshot. This catches edits as well as new items uniformly.

### Cadence and bounds

- `POLL_INTERVAL` defaults to 30s. At that cadence, an hour of waiting costs ≈120 reads per loop instance — well below GitHub's REST/GraphQL rate limits for a single authenticated user on a single PR.
- `CI_TIMEOUT` is the wall-clock budget for Step 5f. Measure from the moment the loop's most recent push completed; abort when the budget is exceeded with **no** previously-pending check having reached a terminal `conclusion`.
- `MONITOR_DURATION` is the wall-clock budget for Step 6. Measure from entry to monitoring; exit cleanly when it elapses.

### Why polling, not webhook subscription

Earlier drafts of this skill referenced a `subscribe_pr_activity` / `unsubscribe_pr_activity` pair and consumed `<github-webhook-activity>` envelopes. Those tools are Claude Code coordinator-mode built-ins exposed only by certain long-running harnesses (e.g. Claude Code Web); they are not something `gh` or the upstream `github-mcp-server` toolset expose, and are not available in the interactive Claude Code CLI or in Codex CLI sessions. Polling works uniformly across every harness this skill supports, at the cost of ~`POLL_INTERVAL/2` average latency between an external event and the loop reacting to it. For a fix loop bottlenecked on CI runs measured in minutes, that latency is invisible.

## CI check runs

```bash
gh api repos/{owner}/{repo}/commits/{head_sha}/check-runs
```

Returns `.check_runs[]` for the PR head commit. Filter by `.conclusion`:

| Conclusion | Fixable? | Action |
|-----------|----------|--------|
| `failure` + `.app.slug == "github-actions"` | Yes | Fetch log tail (see below), diagnose, fix |
| `failure` + other `.app.slug` | No | Report to user |
| `timed_out` | No | Report to user |
| `cancelled` | No | Informational; doesn't block fixed point |
| `startup_failure` | No | Report to user |
| `action_required` | No | Report to user |

This is the REST vocabulary (`failure`, `timed_out`, `action_required`, all lowercase/snake) — deliberately not the GraphQL `CheckConclusionState` enum (`FAILURE`, `TIMED_OUT`, uppercase) that `gh pr checks --json state` returns. Using the REST endpoint keeps this table's values, and the check-run `.id`, consistent with what the log-tail command below expects.

### Fetching failure logs

```bash
gh run view --job <check_run.id> --log-failed 2>&1 | tail -<LOG_TAIL_LINES>
```

The check-run `.id` from the REST call above equals the `jobs.id` for GitHub Actions, so this fetches logs for the exact failing job (verified: `check-runs[].id` and the job id embedded in `check-runs[].details_url`'s `/job/<id>` segment are the same number). If the tail doesn't contain an obvious error, search the full output for common error markers: `FAIL`, `Error`, `error:`, `FAILED`, `assert`.

If `gh` is not installed, log-tail fetching is best-effort — fall back to whatever `.output.summary` and `.output.text` the check run carries, plus `.details_url` for the user.

## Review threads and comments

REST's `pulls/{pull_number}/comments` endpoint returns individual review comments but has **no concept of thread grouping or resolution state** — `isResolved` only exists in GitHub's GraphQL schema (`PullRequestReviewThread.isResolved`). This is a real gap in a purely REST-based mapping: it's not enough to swap `pull_request_read method="get_review_comments"` for a REST call, because REST cannot answer "is this thread resolved." So review-thread reading goes through `gh api graphql` regardless of whether an MCP happens to be connected — the same GraphQL requirement that already applies to thread *resolution* (see below) also applies to thread *reading*.

```bash
gh api graphql -f query='
  query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        reviewThreads(first: 100, after: $cursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            id
            isResolved
            isOutdated
            path
            line
            comments(last: 20) {
              nodes {
                id
                databaseId
                body
                author { login }
                createdAt
                updatedAt
              }
            }
          }
        }
      }
    }
  }' -f owner="$OWNER" -f repo="$REPO" -F pr="$PR_NUMBER"
```

Paginate `reviewThreads` via `pageInfo.hasNextPage`/`endCursor` until exhausted (omit `$cursor` on the first request).

Each thread node carries `id` (GraphQL node ID, needed for resolution), `isResolved`, `isOutdated`, `path`, `line`, and a `comments` connection. Each comment carries `id` (GraphQL node ID), `databaseId` (numeric REST ID — needed for replies), `body`, `author.login`, `createdAt`, and `updatedAt`.

**Use `comments(last: 20)`, not `first:`.** GraphQL connections default to oldest-first, and the skill needs the *latest* reviewer comment in the thread. `last: 20` also serves as a practical bound: `gh api graphql` doesn't do nested pagination (paginating comments within each thread while also paginating threads), so a generous `last` count is the pragmatic way to be confident of catching a thread's most recent comment without a second round-trip per thread. In the overwhelmingly common case (a handful of comments per thread) this captures everything.

Derived state:

- `unresolved_threads = [t for t in threads if not t.isResolved]`
- `resolved_thread_ids = [t.id for t in threads if t.isResolved]`
- `latestReviewerComment(thread)` = last non-self element of `thread.comments` (sort by `createdAt` if order is not guaranteed and ignore `author.login == GH_USER`). Use this for evaluation, reply anchoring, and `OUTCOME_MARKERS` re-evaluation tracking.
- `actionable_threads = [t for t in unresolved_threads if latestReviewerComment(t) != null]`. Drop unresolved self-only threads from feedback items; otherwise later reply code would dereference a missing `latestReviewerComment.databaseId`.
- `outcome_marker(thread)` = `<latestReviewerComment.databaseId>:<latestReviewerComment.updatedAt || latestReviewerComment.createdAt>`, so edited reviewer comments re-enter evaluation. The same marker scheme is used for both REJECT and DEFER outcomes — both are recorded in `OUTCOME_MARKERS`.

**`[bot]`-suffix note.** REST logins for bot accounts carry a `[bot]` suffix (e.g. `"dependabot[bot]"`); GraphQL `author.login` for the same account does not (`"dependabot"`) — verified by matching REST `pulls/.../comments[].user.login` against this query's `author.login` for the same comment (same `databaseId`) on a live PR. Don't assume which side `GH_USER` lands on: `gh api user` returns a REST-style login, but *what* it resolves to depends on how `gh` is authenticated (personal account vs. a bot/App identity in a headless run), and a bot identity's login could plausibly come back suffixed. Strip a trailing `[bot]` from **both** `GH_USER` and the comment/review login before every self-authorship comparison, regardless of which API sourced either value — that one rule is correct in all cases and doesn't require reasoning about which side is which.

## Review summaries

```bash
gh api repos/{owner}/{repo}/pulls/{pull_number}/reviews
```

Returns reviews with `.id`, `.body`, `.state` (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`), `.user.login`, `.submitted_at`. Track REJECT/DEFER review summaries in `OUTCOME_MARKERS` with a mutable marker such as `<review.id>:<review.submitted_at>`; if the review body can be edited without changing `submitted_at`, fall back to `<review.id>:<hash(review.body)>` so edited review bodies re-enter evaluation.

### Supersession algorithm

1. Group reviews by `user.login`.
2. Within each group, sort by `submitted_at` ascending.
3. Find the index of the latest `APPROVED` or `DISMISSED` review (or `-1` if none).
4. Discard everything at or before that index.
5. From the remainder, keep only `CHANGES_REQUESTED` or `COMMENTED` reviews with a non-empty `body` and `user.login != GH_USER`.

The result is the actionable summary list.

## PR conversation comments

```bash
gh api repos/{owner}/{repo}/issues/{pull_number}/comments
```

A pull request is also an issue, so its top-level conversation comments live under the issues endpoint. Returns comments with `.id`, `.body`, `.user.login`, `.created_at`, `.updated_at`. Filter out entries where `.user.login == GH_USER` to avoid acting on the skill's own posts. Track REJECT/DEFER PR conversation comments in `OUTCOME_MARKERS` with a mutable marker such as `<comment.id>:<comment.updated_at>`; comment edits keep the same ID and must re-enter evaluation.

## Replying to review summaries and PR conversation comments

Review summaries and PR conversation comments don't have inline review-thread reply anchors; post a PR-level comment through the issues endpoint. Write the body to a temp file first — a reviewer-authored or generated body can contain backticks, `$`, and newlines that are unsafe to inline as a shell argument:

```bash
gh pr comment <pull_number> -R {owner}/{repo} --body-file /tmp/reply-body.txt
```

(`gh issue comment` is equivalent, since a PR is an issue.) If a GitHub MCP server is already connected in the session, its comment tool may be used instead — its body is a typed field, so it sidesteps the temp-file step entirely. Because this is a PR-level comment, include enough context for humans to connect the reply to the original feedback: reviewer login, review/comment ID or timestamp, and a short quoted/summarized ask.

## Replying to review threads

Inline review-thread replies have no `gh pr comment` equivalent — use the REST reply endpoint directly, again via a temp file to avoid hand-escaping the body into a `-f` string:

```bash
jq -n --rawfile body /tmp/reply-body.txt '{body: $body}' \
  | gh api repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies --input -
```

`comment_id` is a **comment** ID, not a thread ID. Pass the numeric `databaseId` of the thread's **latest non-self reviewer comment** — the endpoint rejects the thread's GraphQL `id`. Using the latest reviewer comment keeps replies attached to the current ask instead of replying to the skill's own previous outcome message. If a GitHub MCP server is already connected, its reply tool may be used instead (typed body field, no `jq`/temp-file step needed). A failed reply is not a reason to revert a code fix, but it does block convergence; retry it on the next loop.

## Resolving review threads

Thread resolution is a GraphQL-only mutation — there is no REST endpoint for it, with or without an MCP in the picture:

```bash
gh api graphql -f query='
  mutation($id: ID!) {
    resolveReviewThread(input: { threadId: $id }) {
      thread { id isResolved }
    }
  }' -f id="$THREAD_ID"
```

`$THREAD_ID` is the thread's GraphQL node ID (the `id` field from the `reviewThreads` query above, e.g. `PRRT_kwDOxxx`). Resolving an already-resolved thread is a no-op. If a GitHub MCP server is already connected in the session, its thread-resolve method may be used instead — it performs the exact same `resolveReviewThread` mutation, so treat it as a fast path, not a different behavior.

On success, add the thread to `ADDRESSED_THREAD_IDS`. On failure, leave it off `ADDRESSED_THREAD_IDS` so the next re-fetch re-surfaces it for retry.

## Rejecting feedback (REJECT outcome)

Use the same reply channel as the feedback source:

- Inline review thread: the `.../replies` endpoint (or connected MCP) with a categorized prefix and disclaimer body (see SKILL.md Step 5a for the prefix table).
- Review summary or PR conversation comment: `gh pr comment`/`gh issue comment --body-file <tmpfile>` (or connected MCP) with `issue_number = pullNumber`, reviewer/context prefix, and the categorized rationale.

Do **not** resolve rejected inline threads: rejected threads stay open so the reviewer can push back.

## Deferring feedback (DEFER outcome)

DEFER is "correct, but not in this PR" — the skill files a tracking issue and replies with a link. Two calls per item:

### 1. File the tracking issue

Write the body to a temp file (same escaping rationale as replies), then:

```bash
gh issue create -R {owner}/{repo} \
  --title "<short imperative phrase from feedback>" \
  --body-file /tmp/issue-body.txt \
  --label deferred-from-pr
```

Body template:

```text
Deferred from #<pullNumber>: <one-line summary>.

Original feedback by @<reviewer> on PR #<pullNumber> (<pr_url>):

> <quoted feedback>

**Context:** <file:line or short note>.

**Why deferred:** <scope-creep | diminishing-returns | ambiguous> — <one-sentence rationale>.

_Filed automatically by `pm-autofix-pr` after dual-evaluator triage by <LOCAL_LABEL> and <REMOTE_LABEL>._
```

`gh issue create` prints the new issue's URL to stdout on success — capture it and derive the issue number from its trailing path segment (`.../issues/<number>`). Use both in the PR reply.

If the repo doesn't have the `deferred-from-pr` label, `gh issue create --label` fails (`could not add label: ... not found`) — drop `--label` and retry once. Do not pre-create the label.

If `gh issue create` errors with an HTTP 403 or 429 in its output, wait 60 seconds and retry once. After a single failed retry, post the DEFER reply with `TODO: file as a separate issue — automated issue creation failed (<error summary>).` instead of the issue link, and record the item in `DEFERRED_ITEMS` with `issue_number=null` so the Step 7 summary surfaces the gap.

### 2. Reply on the PR with a link

Use the same reply channel as the feedback source — inline thread → the `.../replies` endpoint; review summary / PR conversation comment → `gh pr comment`/`gh issue comment` (or connected MCP either way) — with body:

```text
{prefix} {one-sentence rationale}. Tracked as #<issue_number> (<issue_html_url>).

_This assessment was made by two independent AI reviewers (<LOCAL_LABEL> and <REMOTE_LABEL>). If you disagree, please reply and we'll re-evaluate._
```

Prefix from SKILL.md Step 5a' (e.g. `**Out of scope for this PR** —`, `**Deferred (diminishing returns)** —`, `**Deferred for separate discussion** —`).

Do **not** resolve deferred inline threads: like rejected threads, they stay open so the reviewer can push back if the deferral is wrong.

## Rate limiting

If any `gh api` call fails with an HTTP 403 or 429 (visible in its non-zero exit and stderr), wait 60 seconds and retry once. After a single failed retry:

- Reply failures (the `.../replies` endpoint, `gh pr comment`, `gh issue comment`) are not code-fatal, but they block convergence. Leave the item off `ADDRESSED_THREAD_IDS` / `REPLIED_ITEM_KEYS` so it re-surfaces for another reply attempt.
- Resolve failures (`resolveReviewThread`) are non-fatal but the thread stays off `ADDRESSED_THREAD_IDS` so it re-surfaces.
- Issue-create failures (`gh issue create`) trigger the DEFER fallback: post the DEFER reply with `TODO: file as a separate issue — automated issue creation failed (<error>).` and record `issue_number=null` in `DEFERRED_ITEMS`. Do not block convergence.
- State-fetch failures get added to the `errors` list and prevent the fixed-point declaration in Step 5g; during Step 6 monitoring, a non-empty `errors` list also blocks a clean `monitoring-timeout` exit until one more re-fetch resolves it (see "Polling" above).

## Mergeability and base-branch conflict resolution

```bash
gh api repos/{owner}/{repo}/pulls/{pull_number}
```

surfaces the same two fields as the REST `GET /pulls/{n}` schema always has:

| Field | Values | Meaning |
|-------|--------|---------|
| `mergeable` | `true` / `false` / `null` | `null` = GitHub has not finished computing the merge yet. `false` = the PR conflicts with its base. |
| `mergeable_state` | `clean`, `dirty`, `blocked`, `behind`, `unstable`, `has_hooks`, `unknown`, `draft` | `dirty` is the content-conflict state. The others are not conflicts (see below). |

Use this REST call rather than `gh pr view --json mergeable,mergeStateStatus` — that flag returns GraphQL's vocabulary instead (`MERGEABLE`/`CONFLICTING`/`UNKNOWN`, uppercase `mergeStateStatus`; verified these differ from the REST values on the same PR). Mixing the two vocabularies in one skill is a good way to introduce a silent mismatch, so every mergeability read in this skill goes through REST.

GitHub computes mergeability asynchronously: the **first** `get` after the base or head moves often returns `mergeable: null`. The skill re-fetches up to 3 times with a 3-second sleep and only acts on a definitive `true`/`false`. If it stays `null`, record the indeterminate state in `errors` so Step 5g re-fetches instead of declaring a false fixed point.

Derive `has_merge_conflict = (mergeable == false) || (mergeable_state == "dirty")`. Only these mean "conflicts with base." The other terminal states do **not** block the fixed point:

- `clean` — mergeable, nothing to do.
- `behind` — the branch is behind base but has no conflicts; a repo may still require it be up to date, but that is a merge-queue/branch-protection concern, not a conflict. Step 5h's base merge would clear it as a side effect if a conflict ever coexists, but `behind` alone does not trigger 5h.
- `blocked` — a required check or review is pending; surfaced through CI/review channels, not here.
- `unstable` — mergeable but a non-required check is failing; handled via the check-runs call.
- `has_hooks` / `unknown` — treat as non-conflicting; the re-fetch loop above resolves `unknown` → a real state in most cases.

### Resolving a conflict (Step 5h)

The skill merges the base **into** the PR branch — never rebases — so an already-published branch is not force-pushed and the reviewer's commit history is preserved. Fetch from `BASE_REMOTE` (captured in Step 1), which is the *base* repository's remote or clone URL — **not** necessarily `origin`. On a fork PR the base branch lives on `upstream` (or a direct URL); `origin/<base.ref>` would be the fork's stale copy or missing entirely:

```bash
git fetch <BASE_REMOTE> <base.ref>    # BASE_REMOTE = base repo remote/URL (origin on same-repo PRs, upstream/URL on forks)
git merge --no-edit FETCH_HEAD        # merges exactly what was just fetched — works for a named remote or a URL
```

- **Clean merge (exit 0):** the merge commit already exists; run pre-commit checks; on success fold any formatter/sub-fix edits into it (`git add` + `git commit --amend --no-edit`) so the pushed tree matches what passed validation and the worktree is clean, then `git push`; on an unfixable pre-commit failure undo with `git reset --hard ORIG_HEAD` (set by `git merge` to the pre-merge commit) and exit `merge-conflict`.
- **Conflicted merge (non-zero exit):** `git diff --name-only --diff-filter=U` lists the conflicted files. Resolve each by hand (keep both the PR's change and the base's independent change; leave no `<<<<<<<`/`=======`/`>>>>>>>` marker), `git add` them, run pre-commit, then `git commit --no-edit`. If resolution can't be done confidently or pre-commit still fails after one sub-fix, `git merge --abort` and exit `merge-conflict`.

Push the resulting merge commit with the same handling as the section below, then continue the loop so the fresh CI run is awaited and mergeability is re-checked.

This `merge-conflict` exit (conflict with the base branch) is distinct from the `rebase-conflict` exit below (conflict with the PR branch's **own** upstream during a push).

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
