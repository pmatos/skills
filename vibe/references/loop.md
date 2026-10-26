# The vibe loop in detail

Procedures behind `SKILL.md`. Nothing here overrides the rules table there.

## Phases and the queue

```text
preflight → triage (read-only, parallel by theme unless measuring) → fix tracks → merge one PR at a time
        → keep main green → close-out audit → close or write the gap list
```

The queue is the list of PRs and steps. It must never be empty while work remains. The
loop is event-driven: a completion notice arrives, you verify, you launch the next step.
The scheduled report only reports.

## Who merges

Fix agents stop at **ready** (SKILL.md Step 4) and return a structured result. The single
orchestrator merges, one PR at a time, and finishes post-merge CI before the next merge:

1. Fetch the default branch and record its current SHA (`git fetch origin <default>`,
   then `git rev-parse origin/<default>`). Query **all pages** of workflows for that SHA:
   `gh api --method GET --paginate repos/{owner}/{repo}/actions/runs -f branch=<default>
   -f head_sha=<sha> -f per_page=100
   --jq '.workflow_runs[] | {id,workflow_id,event,status,conclusion,head_sha}'`.
   Match the expected workflows from the repo's CI policy; a missing, queued or running
   required workflow is not green. Require completed successful required workflows (or an
   explicit policy-allowed neutral/skipped result); record advisory results separately.
   No runs is not evidence of green: wait for expected runs or record a policy-backed
   "no CI applies" decision. Refuse a red branch unless this PR is its declared fix.
   Re-check the remote head before merging; if it moved, repeat this check.
2. Check the PR: `gh pr view <pr> --json mergeable,mergeStateStatus` (re-query while it says
   UNKNOWN). If it is CONFLICTING, or BEHIND under a repo rule that requires an up-to-date
   branch, rebase on the newest default branch, resolving conflicts by hand, in the PR's own
   worktree: reuse the agent's (idle at READY, tracking `origin/<branch>`), or if it is gone
   `git worktree add -B <branch> <dir> origin/<branch>` then
   `git -C <dir> branch --set-upstream-to=origin/<branch>`. Run the scripts from that
   directory, never the main checkout: the scripts compare and push `HEAD`. Use only
   `rebase-pr`'s scripts: `capture-lease.sh <remote> <branch>` before the rebase and
   `safe-force-push.sh <remote> <branch> <captured-sha>` to publish (explicit-SHA
   `--force-with-lease`). Do not run `rebase-pr`'s own gate step: the PR's CI is the gate.
   The push restarts the checks: wait for the required checks to be green on the new head,
   then repeat the remote-head check of step 1. A PR that is neither CONFLICTING nor BEHIND
   is merged as it stands.
3. Merge by the method the repo allows, only with every required check green on the PR's
   current head. Never `--auto`.
4. Wait for the post-merge workflows on the merge commit to be green before starting the
   next merge. Use the same paginated SHA-specific query and expected-workflow check above.
   A merge that touched `CLAUDE.md`, `AGENTS.md`, `docs/agents/`, hooks, CI or lint
   config triggers a policy re-read (Policy drift, below).

If the user passes `--no-merge`, complete steps 1 and 2 (including green required checks on the final head), then stop
before step 3 and report the PR as ready.

## Throughput, honestly

CI on a PR can take an hour, and merges are one at a time, each followed by its post-merge
workflows. So:

- Start agents to investigate and code in parallel, but never cancel a PR's checks because
  they have waited.
- Prefer one correct PR to three that each hit conflicts: every merge moves the default
  branch, so each queued PR may need a rebase and a fresh run of the checks.
- Measurements that must not share the machine (timings) run only when the load is
  low, by a bar you set in preflight (an example from the runs this was written from: other
  runnable tasks at p95 of 6 or fewer); a contended number is labelled, never scored.
- Advisory checks (perf bots with noisy runners) are recorded in the PR, never rerun until
  green. If one shows a real regression, cite it against your own deterministic measurement.

## The check set (generic)

The gate is the PR's own CI; nothing is run locally to prove green. Derive the expected
required workflows and checks from the repo's CI workflows and contributor docs. After the
last push (the `/investigate` PR, then the review and simplify fixes), wait for every
required check to complete successfully on the **final head SHA**. A missing, queued or
running required check is not green; advisory checks are recorded separately. Any push
restarts the checks, so finish review and simplify before waiting.

1. Checks CI runs only *after* merge: say so in the PR and propose a PR-time job; the
   orchestrator watches them on the merge commit before the next merge.
2. The project's lint, format, commit and PR-title rules, and its file-size or complexity
   budget, are enforced by CI and hooks. Use the repo's own budget: if it has a ratchet,
   files over the limit may change but not grow, and new code goes in new small modules; if
   it has none, do not invent one, propose it with a memo.

Never regenerate a baseline, snapshot, expected-output file or skip list to make a failure
pass; only when the change legitimately adds passing tests, and say so in the PR.

## Staging and the stop rule

Large issues split into stages; each stage is a PR through the full pipeline and merged
before the next. The brief carries a stop rule: stop after any stage where the next cannot
be had without a regression or unacceptable risk, comment on the issue with the
measurements, and report. Do not force a result to close an issue.

## Measurements (perf epics)

When a criterion is a number:

- Prefer a deterministic basis (instruction counts) for the gate; judge wall-clock only at
  low load, pinned, with interleaved runs and a byte-identical null control, repeated in a
  second session before shipping. Layout noise can move wall time several percent while the
  deterministic count is flat.
- Re-measure the control set every two or three merges, not only per PR.
- Record the numbers in the repo (a measurements document per issue: before and after
  table, controls, the noise estimate, rejected variants and why), and post them on the
  issue when it is closed.
- Never answer a measurement miss by changing the metric. A fixture where one side does not
  decide is a *proposal to the maintainer* to exclude, with both times listed.

## Keeping main green

1. Find the failing test from the CI log, or run only the tests the offending PR added or
   touched. Do not rerun a whole suite to find one failure.
2. Fix with the smallest change, prove it under every implementation CI runs, open a PR,
   merge on green, and confirm the next post-merge run.
3. Hold all other merges (one orchestrator owns them). If the cause is not found in about
   half an hour (a default; tell the user), revert the offending PR on a branch with a small
   PR so main goes green, then re-land properly.
4. Put the cause and the missing guard in the issue the PR belonged to, and add the guard to
   the required checks: this is how "filtered tests" and "post-merge-only checks" stop recurring.

**Policy drift.** After any merge to the default branch that touches `CLAUDE.md`,
`AGENTS.md`, `docs/agents/`, hook config, `.github/workflows/**` or the commit/PR lint
config, re-read it, rebuild the expected-checks list, tell running agents (`SendMessage` for named
agents, the next brief for workflows), and record the change in the rulings comment.

## Closing children

- Closing keywords are governed by the rules table (SKILL.md): only the PR that completes a
  child may close it; stage PRs and the epic reference say `Part of #N`, and the
  orchestrator closes the rest after verification. A bare `(#N)` suffix is harmless but some repos
  avoid it on partial stages as a precaution.
- A merged-but-open child goes through the close-out audit, not an optimistic close. If a
  gate criterion needs a fresh measurement of the default branch, run the gate-evidence
  brief first; then launch the read-only audit brief: per child, a table of criteria met or
  unmet with numbers, a recommendation, and a draft closing comment.
- **Closed-as-measured**: criteria unmet but with numbers, the reason, and a stated decision
  rule ("regression-free, or don't force it"). Allowed only when the user stated the rule up
  front or confirms the list before the epic closes; the thread records the miss.
- Every closure comment states evidence: the commit, the measured values, the fixtures.
- Triage agents never close; the orchestrator verifies the evidence first.

## Human decisions

A decision memo has: the question, the options with what each costs, the evidence (numbers,
repro, counterexample), a recommendation, and what happens on each answer. Post it on the
issue, add it to the rulings comment on the epic, and list it in the next status report.
Proceeding without a ruling needs a precedent cited from the repo, a change that is trivially
revertible, and no movement of a gate; it goes on the "proceeded without a ruling" list with
the revert command. When in doubt, ask.

## Stalled and dead agents

- `ListAgents` shows named subagents only; workflow agents are invisible to it and to
  `SendMessage`. Watch the workflow's transcript directory (`agent-*.jsonl`, `journal.jsonl`
  modification times).
- A transcript with no write for an hour, no pending check and no PR comment is stalled:
  relaunch the workflow with `resumeFromRunId` after narrowing the prompt (only the longest
  unchanged prefix of calls is cached), or `TaskStop` it.
- Agents that end right after a review or simplify output are common: resume a named agent
  with a message saying the task is not done and listing the remaining steps; if it ends
  again, replace it with narrower agents (one step each, structured result). Workflow agents
  cannot be messaged: narrow the prompt and relaunch with `resumeFromRunId`.
- Agents die on transient API errors: resume by name, never spawn a duplicate; the
  continuation brief names the existing branch and PR and says to check
  `gh pr list --state all --search '#<N>'` first.
- Reports can arrive truncated; ask the agent for the remainder.

## Resuming

A session restart loses the schedule and the in-memory queue. Rebuild from durable state:
the rulings comment on the epic (run config, cron id, run ids), `gh pr list --state all
--search '"Part of #<epic>" in:body'`, `git worktree list`, the open children, and the default branch's
CI. Recreate the cron job, resume dead named agents by name, relaunch workflows with
`resumeFromRunId`, and continue from the first unmet step. Say what was found.
