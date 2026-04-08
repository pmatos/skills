---
name: pm-autofix-pr
description: This skill should be used when the user asks to "autofix pr", "fix pr locally", "fix ci failures", "fix review comments", "iterate on pr", "fix failing checks", "fix pr comments", "make ci green", "fix the build", "address reviewer feedback", or wants to iteratively fix CI failures and review comments on a GitHub PR from the local CLI. Also triggered by the /pm-autofix-pr command.
user-invocable: true
---

# Autofix PR

Iteratively fix CI failures and address review comments on a GitHub PR, working entirely in the local CLI. Fetch failures and reviewer feedback, make code fixes, run local validation, commit, push, and wait for CI — repeating until all issues are resolved or a maximum iteration count is reached.

## Prerequisites

- `gh` CLI installed and authenticated with a token that has `repo` scope (read and write access to pull requests). The skill posts reply comments on PR review threads, which requires write permission.

## Workflow

### Step 1: Identify the PR

Determine the current GitHub repository:

```bash
gh repo view --json nameWithOwner -q '.nameWithOwner'
```

If this fails, report the error and stop — the user likely needs to authenticate with `gh auth login` or is not inside a Git repository. Split the result into `{owner}` and `{repo}` for later API calls.

If the user provided a PR number as an argument, use it directly. Otherwise, auto-detect from the current branch:

```bash
gh pr view --json number,title,headRefName,url
```

If no PR is found, ask the user for a PR number.

Validate that the local branch matches the PR's `headRefName`:

```bash
git branch --show-current
```

If the branches don't match, ask the user whether to check out the PR branch (`git switch <headRefName>`) or abort.

Set `MAX_ITERATIONS` to 5, unless the user specified a different value as an argument (e.g., `/autofix-pr 10` or "autofix pr with 10 iterations").

Determine the current `gh` user for filtering self-comments later:

```bash
gh api user -q '.login'
```

### Step 2: Read the project's CLAUDE.md

Determine the Git repository root by running `git rev-parse --show-toplevel`. Look for a CLAUDE.md (or AGENTS.md) starting from the **working directory** and walking up through ancestor directories, stopping at the repo root. Use the nearest file found; if both exist in the same directory, prefer CLAUDE.md. Read the file and extract pre-commit requirements:

- Formatting commands (e.g. `prettier`, `black`, `gofmt`)
- Linting commands (e.g. `eslint`, `ruff`, `clippy`)
- Type-checking commands (e.g. `tsc --noEmit`, `mypy`)
- Test commands (e.g. `npm test`, `pytest`, `cargo test`)
- Build commands (e.g. `npm run build`, `cargo build`)

**Only** extract requirements that are explicitly stated. If CLAUDE.md says nothing about pre-commit checks, do not run any. These checks will be used as local validation before each push in the fix loop.

### Step 3: Initial assessment

Gather all current issues on the PR.

**CI failures** — get the PR head SHA and fetch check runs for that exact commit:

```bash
sha=$(gh api repos/{owner}/{repo}/pulls/<number> --jq '.head.sha')
```

List check runs for that commit:

```bash
gh api repos/{owner}/{repo}/commits/$sha/check-runs --paginate \
  --jq '.check_runs[] | {id, name, status, conclusion, app_slug: .app.slug}'
```

Filter for check runs with a terminal non-success `conclusion`. The conclusions to detect are: `failure`, `timed_out`, `cancelled`, `startup_failure`, and `action_required`. For each such check, inspect `app_slug` and `conclusion` to determine how to handle it:

- **Fixable failures** (`conclusion` is `failure` AND `app_slug` is `github-actions`): fetch failure logs via `gh run view <id> --log-failed 2>&1 | tail -500`. If the last 500 lines do not contain an obvious error, search the full output for common error markers (`FAIL`, `Error`, `error:`, `FAILED`, `assert`) to locate the root cause.
- **Non-fixable CI issues** (`conclusion` is `timed_out`, `cancelled`, `startup_failure`, or `action_required`, OR `app_slug` is not `github-actions`): logs are either unavailable or the issue is not code-fixable. Record the check name and conclusion, and report these to the user as CI issues requiring manual inspection. Do not attempt to auto-fix these.

Store each item with its check name, conclusion, log output (if available), check run ID, and whether it is fixable.

**Review comments** — fetch unresolved review threads using GraphQL to access thread resolution state:

```bash
gh api graphql -f query='
  query($owner: String!, $repo: String!, $number: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $number) {
        reviewThreads(first: 100) {
          nodes {
            id
            databaseId
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
' -f owner="{owner}" -f repo="{repo}" -F number=<number>
```

Filter for threads where `isResolved` is `false`. Each thread includes its full comment chain via `comments.nodes`, which contains the original comment and all replies. This replaces the need for separate self-reply detection — `isResolved` is the authoritative signal for whether a thread has been addressed.

**Review summaries** — fetch review bodies (the top-level text submitted with each review):

```bash
gh api repos/{owner}/{repo}/pulls/<number>/reviews --paginate \
  --jq '.[] | select(.body != "" and .body != null) | {id, body, state, user: .user.login, submitted_at}'
```

Filter out reviews authored by the current `gh` user. Apply supersession logic: group reviews by `user`, sort by `submitted_at`, and for each reviewer discard all reviews that are superseded by a later `APPROVED` or `DISMISSED` review from the same reviewer. Only then treat the remaining reviews with `state` of `CHANGES_REQUESTED` or `COMMENTED` that contain actionable text (e.g. "please add tests", "this needs error handling") as feedback to address.

**PR conversation comments** — fetch general discussion comments:

```bash
gh api repos/{owner}/{repo}/issues/<number>/comments --paginate \
  --jq '.[] | {id, body, user: .user.login, created_at}'
```

Filter out comments authored by the current `gh` user (from Step 1) — these are self-comments from prior runs.

Initialize `ADDRESSED_COMMENT_IDS` with the thread IDs of review threads where `isResolved` is `true` (from the GraphQL query above). No separate self-reply detection is needed — `isResolved` is the authoritative signal.

Present the initial assessment to the user:
- Number of failed CI checks, with their names (distinguishing Actions vs external CI)
- Number of unresolved review threads, with brief summaries
- Number of resolved review threads (skipped)
- Number of unresolved review summaries and conversation comments

Ask: **"I found N CI failures and M unresolved review comments. Shall I begin fixing them? (max MAX_ITERATIONS iterations)"**

If there are no failures and no unresolved comments, report that the PR looks clean and stop.

### Step 4: The Fix Loop

For each iteration `i` from 1 to `MAX_ITERATIONS`:

**4a. Classify issues**

For each piece of unresolved feedback not in `ADDRESSED_COMMENT_IDS`, classify it. This applies to all three feedback channels — review threads (from GraphQL), review summaries, and PR conversation comments.

For review threads, classify based on the **most recent reviewer comment** in the thread (from `comments.nodes`), not just the original top-level comment. Reviewers often post follow-up requests as replies (e.g. "that's still not right, please also handle X"), and the latest comment reflects the current ask:

- **Clear fix**: The feedback points to a specific code issue with an obvious resolution — a typo, missing null check, wrong variable name, style violation, missing test assertion, unused import, or other concrete code change where the reviewer's intent is unambiguous.
- **Ambiguous**: The feedback suggests an architectural change, asks an open question, proposes multiple alternatives, or has multiple valid interpretations. For these, present the comment to the user and ask for guidance before proceeding. Wait for user input — the user's guidance becomes the fix instruction.
- **No action**: The feedback is an approval, acknowledgment, praise, or informational note not requesting a code change ("looks good", "nice!", "FYI"). Skip these and add their IDs to `ADDRESSED_COMMENT_IDS`.

For CI failures, all are treated as actionable — read the error log and determine the fix.

**4b. Make fixes**

For CI failures:
1. Read the error log from Step 3 (or re-fetched in Step 4g).
2. Identify the failing file(s) and line(s) from the error output.
3. Read the relevant source files.
4. Make the code fix.

For inline review comments:
1. Read the file at the path and line referenced by the comment.
2. Understand the surrounding context.
3. Apply the requested change.

For review summaries and PR conversation comments:
1. Parse the feedback to identify specific requested changes (e.g. "add tests for X", "handle error case Y").
2. Locate the relevant source files based on the request context and PR diff.
3. Apply the requested changes.

Apply fixes one issue at a time. After each fix, verify the change makes sense in context.

**4c. Run local pre-commit checks**

Run the checks extracted from CLAUDE.md in Step 2, in order: format → lint → type-check → test → build.

- If a formatter modifies files, stage those formatting changes.
- If any check fails, attempt to fix the new failure immediately. This is a sub-iteration — it does **not** count against `MAX_ITERATIONS`.
- If the sub-fix fails after one attempt, report the failure to the user and ask how to proceed. Do **not** commit broken code.

If no pre-commit requirements were found in CLAUDE.md, skip this step.

**4d. Commit and push**

First check if there are any changes to commit:

```bash
git status --porcelain
```

If there are no changes (empty diff), skip the commit/push for this iteration and report: "No code changes were necessary for the identified issues." Proceed to Step 4f.

Otherwise:

1. Stage changes with explicit file names (not `git add -A`).
2. Commit with a descriptive message using a HEREDOC:

```bash
git commit -F - <<'EOF'
fix: address CI failures and review comments [i/MAX_ITERATIONS]

- <summary of each fix applied>
EOF
```

3. Push. Check whether the branch has an upstream configured via `git rev-parse --abbrev-ref <branch>@{upstream}`. If upstream exists, run `git push`. If not, run `git push -u origin <branch>`.

If the push is rejected (e.g. upstream has new commits), report the conflict to the user and suggest: "Push was rejected — run `git pull --rebase` and re-invoke `/autofix-pr`." Then stop.

If the push fails due to a network error, retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s).

**4e. Reply to addressed feedback and record IDs**

For each review thread addressed in this iteration, post a reply on GitHub. Use the `databaseId` of the first comment in the thread (from the GraphQL query's `comments.nodes[0].databaseId`) — this is the numeric REST ID required by the reply endpoint:

```bash
gh api repos/{owner}/{repo}/pulls/<number>/comments \
  -f body="Fixed in \`$(git rev-parse --short HEAD)\` [$i/$MAX_ITERATIONS]" \
  -F in_reply_to_id=<comment-databaseId> \
  --method POST
```

If the API call fails with 403 or 429 (rate limiting), wait 60 seconds and retry once. If it still fails, note the error and continue — the fix was already pushed.

Add the IDs of all addressed feedback to `ADDRESSED_COMMENT_IDS` — this includes review thread IDs, review summary IDs, and conversation comment IDs. All three channels must be tracked to prevent Step 4g from re-surfacing already-fixed items.

**4f. Wait for CI**

Wait for CI checks to complete:

```bash
gh pr checks <number> --watch --fail-fast -i 15
```

This blocks until checks complete. Use `--fail-fast` to return as soon as any check fails rather than waiting for all checks. Use a 15-second polling interval. Set a Bash timeout of 1200 seconds (20 minutes).

If the timeout is exceeded, inform the user: "CI has been running for over 20 minutes. Would you like to keep waiting or abort?" Wait for user input.

**4g. Check for fix point**

After CI completes, re-fetch the current state:

CI check results:
```bash
gh pr checks <number> --json name,state,bucket
```

For any checks with `bucket` of `fail`, re-fetch the PR head SHA and failure logs using the same approach as Step 3 (SHA-based check runs + `gh run view --log-failed` for Actions checks). This ensures the next iteration's Step 4b works with current diagnostic output, not stale logs from a prior assessment.

Unresolved review threads (re-run the same GraphQL query from Step 3):
```bash
gh api graphql -f query='...' -f owner="{owner}" -f repo="{repo}" -F number=<number>
```

Filter for threads where `isResolved` is `false`.

New review summaries:
```bash
gh api repos/{owner}/{repo}/pulls/<number>/reviews --paginate \
  --jq '.[] | select(.body != "" and .body != null) | {id, body, state, user: .user.login, submitted_at}'
```

Apply the same supersession logic as Step 3: group by reviewer, discard reviews superseded by a later `APPROVED` or `DISMISSED` from the same reviewer.

New PR conversation comments:
```bash
gh api repos/{owner}/{repo}/issues/<number>/comments --paginate \
  --jq '.[] | {id, body, user: .user.login}'
```

Filter out items already in `ADDRESSED_COMMENT_IDS` and self-comments across review summaries and conversation comments.

**Fix point reached** if:
- All CI checks have `bucket` of `pass` or `skipping` (no `fail` or `pending` buckets remain). Checks with `bucket` of `cancel` should be reported to the user as informational ("Check <name> was cancelled — this may need manual re-triggering") but do not block convergence, AND
- No new unresolved feedback exists across any channel (all IDs are in `ADDRESSED_COMMENT_IDS` or are self-comments)

→ Break the loop and proceed to Step 5.

**Stale loop detected** if:
- The same CI check names are failing as in the previous iteration, with similar error patterns in the logs

→ Report to the user: "The following failures persisted after my fix attempt: [list check names]. This may require human judgment or indicate a flaky test." Ask whether to continue trying or stop.

**New issues found**:
- New CI failures or new review comments appeared → continue to the next iteration.

**4h. Brief status update**

After each iteration, report:
```
Iteration i/MAX_ITERATIONS complete.
- Fixed: [list of issues addressed]
- Remaining: N CI failures, M unresolved review comments
- Proceeding to next iteration...
```

### Step 5: Final Summary

Present a comprehensive report:

```
## Autofix PR Summary

### PR: #<number> — <title>
### Iterations: i of MAX_ITERATIONS

### Changes Made
| Iteration | Commit | Fixes Applied |
|-----------|--------|---------------|
| 1/5       | abc123 | Fixed lint error in foo.ts, addressed review comment on bar.ts |
| 2/5       | def456 | Fixed test failure in baz_test.py |

### Current Status
- CI: All passing / N failures remaining
- Review comments: All addressed / M unresolved

### Unresolved Issues (if any)
- [List of remaining CI failures or review comments that could not be auto-fixed]
```

If there are unresolved issues, ask: **"Would you like me to attempt further fixes on the remaining issues, or would you prefer to handle them manually?"**

If everything is resolved: **"All CI checks pass and all review comments have been addressed. The PR is ready for re-review."**
