---
name: vibe
description: >-
  This skill should be used when the user asks to "vibe an epic", "vibe #N", "drive epic #N to done", "solve the epic", "work through the epic's sub-issues", "finish the epic", "close out epic #N", "resume the epic", or wants every open child of an issue labelled `epic` triaged, fixed, reviewed and merged. Triages the children, runs `/pm-fix` on each one that needs work in parallel, merges each PR once its checks are green, reports on a schedule, and audits the epic before closing it. Not for a single non-epic issue (use pm-fix). Also triggered by the /vibe command.
argument-hint: "[epic-number|#N|url] [ultracode] [--max-parallel N] [--report-every 1h]"
user-invocable: true
---

# vibe — Drive an Epic to Done

Triage the open children of an epic, fix the ones that need work in parallel
(one agent per child, each running `/pm-fix`), and merge the resulting PRs one at
a time. Invoking `/vibe` authorises merging green PRs into the default branch,
so say that when you start. Re-running `/vibe` resumes: closed children are
skipped, and pm-fix picks up a child's open PR.

## Arguments

- `<epic>`: an issue number, `#N`, `owner/repo#N` or a URL.
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
2. **Find the epic and its children.** With no argument, use the open issue
   labelled `epic`. If there are several, ask which one. The children are the
   epic's sub-issues, including sub-issues of sub-issues, plus the issues in its
   task list:

   ```bash
   gh api repos/{owner}/{repo}/issues/<E>/sub_issues --paginate \
     --jq '.[] | {number,title,state,sub_issues_summary}'
   ```

   Read the epic body for its gate criteria: they define when the epic is done.
   A child is unblocked when every issue that blocks it is closed
   (`gh api repos/{owner}/{repo}/issues/<N>/dependencies/blocked_by`).
3. **Triage every open child, read-only.** Use one agent per group of up to
   about eight related children. For each child, the agent reads the issue and
   its comments, tests the claim against the current default branch, and
   returns `done`, `partial`, `open` or `needs-ruling`, with evidence and the
   remaining work. Triage agents never comment, close or change code.
   - Under ultracode, pipe each `done` verdict to a second read-only agent that
     tries to refute it. Without ultracode, check the evidence yourself.
   - Close each `done` child that holds up, with the evidence in a comment.
   - Ask the user about each `needs-ruling` child.
   - `open` and `partial` children go to the fix queue, with the remaining work.
4. **Launch fix agents** for unblocked children in the fix queue, up to
   `--max-parallel` at once, all in one message. After an API rate-limit error,
   launch nothing new for 5 minutes. First create each child's worktree from
   the up-to-date default branch:

   ```bash
   git fetch origin
   git worktree add .claude/worktrees/vibe-<N> -B issue-<N> origin/<default>
   ```

   Give each agent this brief: work only in that worktree; the remaining work
   from triage; run `/pm-fix N` with the Skill tool; wait for the checks in the
   foreground and do not end the turn while waiting; reply with the PR number
   (or why there is none) and the state of its checks.
5. **Merge each PR as its agent reports, one merge at a time:**
   1. If there is no PR, or a check failed, leave it and note why.
   2. If the PR conflicts with the default branch, run `/rebase-pr <PR>` in the
      child's worktree and wait for its checks again.
   3. Merge only when every check on the PR's head commit has passed.
   4. Wait for the latest CI runs on the default branch to finish. If one
      failed, stop merging and report: nothing merges onto a red default
      branch.
   5. Remove the worktree, then merge with
      `gh pr merge <PR> --<method> --delete-branch`. Check with `gh pr view`
      that the PR merged and with `gh issue view` that N is closed. If N is
      still open, it goes to the close-out audit.
   6. Launch the next fix agent: a queued child, or one this merge unblocked.
6. **Close out** once the fix queue is empty. Run a read-only audit agent
   that, for each child, finds the merged PRs and states which of the issue's
   criteria and the epic's gate criteria are met, with evidence. It recommends
   close, more work, or keep open, and drafts a closing comment for each close.
   Close the children that it shows are done. A child that misses a criterion
   closes only under a decision rule the user stated, such as "close it if it
   cannot be done without a regression". Close the epic only when every child
   is closed. Otherwise leave it open and post the gap list: each remaining
   child, and why. Then delete the report schedule and remove any worktrees
   that are left.

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
