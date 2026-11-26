---
name: vibe
description: >-
  Drive an epic or a batch of open issues with a given label to completion: triage, run /pm-fix in isolated worktrees, verify integration and merge serially. Use for "vibe an epic", "vibe #N", "fix every issue labelled X", or /vibe. For a single non-epic issue use pm-fix.
argument-hint: "[epic-number|#N|url|--label NAME] [ultracode] [--max-parallel N] [--report-every 1h]"
user-invocable: true
---

# vibe — Drive an Epic or Label Batch to Done

Fix independent issues in parallel. Only the orchestrator integrates PRs with
the default branch. Invoking `/vibe` authorises merging verified PRs; state
the repository, target branch and selected scope before dispatch.

## Arguments

- `<epic>`: an issue number, `#N`, `owner/repo#N` or a URL.
- `--label NAME`: select issues by one exact label instead of by epic. Reject
  both selectors together. Example: `/vibe --label "ready for fix" --max-parallel 3`.
- `ultracode`: run triage and the close-out audit as `Workflow` runs (below).
- `--max-parallel N`: the most fix agents at once. The default is the smaller of
  8 and half the cores (`nproc`).
- `--report-every D`: the status report interval, such as `30m` or `1h`
  (default `1h`). `0` turns reports off.

## Ultracode

Treat ultracode as on only if the user's own text contains `ultracode`, or a
system reminder says it is on. This skill's text does not count. When it is on,
load `workflow-authoring` and run triage and the close-out audit with the
`Workflow` tool. When it is off, say so in one line and run the same agents with
the `Agent` tool. Fix agents and merges always use `Agent` and the orchestrator:
they wait on CI and react to it, which a Workflow script cannot do.

## Steps

1. **Preflight.** Run `gh auth status` and confirm that you can push. Read the
   repo's allowed merge methods and prefer squash:

   ```bash
   gh api repos/{owner}/{repo} \
     --jq '{default_branch,allow_squash_merge,allow_merge_commit,allow_rebase_merge}'
   ```

   The working tree must be clean. Start the status schedule (below).
2. **Select the issues.** For `--label`, paginate open issues (not PRs):

   ```bash
   gh api --method GET --paginate repos/{owner}/{repo}/issues -f state=open \
     -f labels="$label" -F per_page=100 | jq -s --arg label "$label" \
     '[.[][] | select(has("pull_request") | not) | select(any(.labels[]; .name == $label)) | .number] | unique'
   ```

   Use `pipefail`; never dispatch a partial result. Save the complete list
   before dispatch under `$(git rev-parse --git-common-dir)/vibe/`, keyed by a
   hash of repository and label. Write atomically and reuse the unfinished
   batch on resume; don't admit newly labelled issues mid-run. An empty list is
   a successful no-op. Label mode has no parent to audit, comment on or close.

   For an epic, find its children as follows. With neither selector, use the open issue
   labelled `epic`. If there are several, ask which one. The children are the
   epic's sub-issues, including sub-issues of sub-issues, plus the issues in its
   task list:

   ```bash
   gh api repos/{owner}/{repo}/issues/<E>/sub_issues --paginate \
     --jq '.[] | {number,title,state,sub_issues_summary}'
   ```

   In epic mode read the epic body for its gate criteria. In both modes an
   issue is unblocked when every issue that blocks it is closed
   (`gh api repos/{owner}/{repo}/issues/<N>/dependencies/blocked_by`).
3. **Triage every selected open issue, read-only.** Use one agent per group of up to
   about eight related children. For each child, the agent reads the issue and
   its comments, tests the claim against the current default branch, and
   returns `done`, `partial`, `open` or `needs-ruling`, with evidence and the
   remaining work. Triage agents never comment, close or change code.
   - Under ultracode, pipe each `done` verdict to a second read-only agent that
     tries to refute it. Without ultracode, check the evidence yourself.
   - Close each `done` child that holds up, with the evidence in a comment.
   - Record the exact question for each `needs-ruling` issue and park it;
     continue independent work without waiting for an answer.
   - `open` and `partial` children go to the fix queue, with the remaining work.
4. **Dispatch independent workers**, up to `--max-parallel` at once. Recheck
   blockers before launch. If two fixes change the same contract, start the
   second after the first lands. Skip closed issues; never launch two workers
   for one issue. On resume, reconcile merged and already queued PRs first.
   - Look for the issue's existing closing PR and inspect `git worktree list
     --porcelain`. Reuse its clean, idle worktree or attach its existing
     branch to a fresh one. Resume a clean, identifiable prior vibe branch
     even if no PR was opened. Park ambiguous ownership, another author's PR,
     dirty worktrees or divergent local work; never reset or force checkout.
   - For new work only, fetch `origin` and use `git worktree add -b issue-<N>
     .claude/worktrees/vibe-<N> origin/<default>`. Record created paths for cleanup.
   - Give the worker the issue, triage evidence and worktree. Run `/pm-fix N`
     there, including its normal risk-based review. Verify the repo's full
     probe and conformance suites where defined, including on resumed PRs;
     reuse passing results only for the same final head. Wait for its checks.
     Return issue, PR, reviewed head SHA, commands/results and check links
     (or the blocker). Do not merge, rebase to chase main, or push after handoff.
5. **Integrate one PR at a time.** Confirm the PR still targets the default
   branch, its current head equals the handoff SHA, and every head check
   passed. Return an unexpected head to review; park failed or missing gates.
   Wait for CI on the current default tip; pause integration on red.
   - Prefer the repository's enforced GitHub merge queue. Verify that required
     integration checks (including the defined suites) actually run on
     `merge_group`. Enqueue with `gh pr merge <PR> --match-head-commit <SHA>`
     and wait for the result, not just queue admission. If conflict prevents
     admission, update only this PR as described below and retry admission.
   - Without a native queue, require **server-enforced strict up-to-date
     required checks** on the target branch, applicable to this merge. If
     protection or check coverage cannot be verified, leave the PR open;
     never change repository settings or use `--admin`. Fetch the current
     default tip. If it isn't an ancestor of the candidate, use `/rebase-pr`
     in its worktree even if GitHub reports no conflict.
   - After a rebase verify the new head and rerun the integration gates on it.
     If resolution changed the patch beyond replaying the reviewed change
     (or equivalence is unclear), return it for `/pm-cr --fix --comment` and
     fresh worker checks. For direct merges use `gh pr merge <PR> --<method>
     --match-head-commit <verified-SHA>`. If main moves again, refresh only
     this candidate; park it after two stale-base retries.
   - Confirm `MERGED` via `gh pr view` and issue closure via `gh issue view`.
     A still-open issue goes to audit. Release newly unblocked work. A failed
     candidate stays open; independent candidates can proceed on a green base.
6. **Close out** when no runnable work remains. Run a read-only audit agent
   that, for each selected issue, finds the merged PRs and states which issue
   criteria (and in epic mode, which epic gates) are met, with evidence. It recommends
   close, more work, or keep open, and drafts a closing comment for each close.
   Close the children that it shows are done. A child that misses a criterion
   closes only under a decision rule the user stated, such as "close it if it
   cannot be done without a regression". In epic mode, close the epic only
   when all children are closed and its gates are met; otherwise post its gaps.
   Report **merged and verified**, **still open** (failing check, dependency or
   ruling, with the next action), and **follow-up work**, linking issues, PRs
   and evidence. List uncovered work rather than claiming it shipped.
   Stop the schedule. Remove only clean worktrees created for completed work;
   preserve blocked work and its branch. Retire the label snapshot after the
   final report; an interrupted run keeps its snapshot.

## GitHub failures

For transient 5xx responses or transport timeouts, allow at most three retries
per operation with exponential backoff (2, 4, 8 seconds) plus jitter. Honor a longer
`Retry-After` or rate-limit reset and pause new dispatch during throttling.
After an ambiguous write, **read before retrying**: check the PR's queue or
merge state, issue closure, existing PR or matching comment as appropriate.
Retry only if the write demonstrably did not take effect and its original
preconditions still hold. If uncertain or out of retries, preserve the work
and report the operation and next check. Do not retry failed tests, denied
permissions or branch protection as network errors. Apply this policy to
workers as well as the orchestrator.

## Status reports

Unless `--report-every 0`, create a `CronCreate` job at an off-minute (never
:00 or :30) for the interval. Each report is under 150 words and starts no work:
done, in progress, blocked, next, and questions for the user. Take every fact
from `gh` and CI, not from memory. The job fires only while the session is idle,
lasts only as long as the session, and expires after seven days. Tell the user
the next run time and recreate the job before it expires.

## Rules

- Never write a closing keyword (close, fix, resolve) next to the epic's
  number, even negated: GitHub would close the epic when that PR merges.
- Never change a test threshold, skip list, baseline or snapshot, or take a
  release step, to get a PR green. Ask the user.
- An agent's report is a claim. Check merges and closures with `git` and `gh`
  before relaying them.
