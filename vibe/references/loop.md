# The vibe loop in detail

Procedures behind `SKILL.md`. Nothing here overrides the rules table there.

## Phases and the queue

```text
preflight → triage (read-only, parallel by theme) → fix tracks → merge one PR at a time
        → keep main green → close-out audit → close or write the gap list
```

The queue is the list of PRs and steps. It must never be empty while work remains. The
loop is event-driven: a completion notice arrives, you verify, you launch the next step.
The scheduled report only reports.

## Who merges

Fix agents stop at **ready** (rebased, gated on the final head, checklist ticked or a
`gates green at <sha>` comment, required checks green) and return a structured result. The
single orchestrator merges, one PR at a time; it finishes post-merge CI before starting
the next merge:

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
2. Rebase on the newest default branch with `rebase-pr`: capture the remote PR head before
   rebasing, and publish only with its explicit-SHA `--force-with-lease`. If the head
   changed, restart the gates on the pushed final head.
3. Merge by the method the repo allows. Never `--auto` unless auto-merge is enabled.
4. Wait for the post-merge workflows on the merge commit to be green before starting the
   next merge. Use the same paginated SHA-specific query and expected-workflow check above.
   A merge that touched `CLAUDE.md`, `AGENTS.md`, `docs/agents/`, hooks, CI or lint
   config triggers a policy re-read (SKILL.md Step 6).

If the user passes `--no-merge`, complete steps 1 and 2 and all final-head gates and
required checks, then stop before step 3 and report the PR as ready.

## Throughput, honestly

A full gate chain (build, self-hosting check, the whole suite, differential checks) can take
about an hour of exclusive machine. With one shared lock that is about one PR an hour, however
many agents you start. So:

- Start agents to investigate and code in parallel, but queue gates once, behind the lock,
  and let them wait; never cancel a queued gate because it has waited.
- Do not add a fourth agent to a three-deep lock queue: it adds latency, not throughput.
- Prefer one correct PR to three that each need a rebase and a re-gate.
- Gates that must not share the machine (timings, memory peaks) run only when the load is
  low, by a bar you set in preflight (an example from the runs this was written from: other
  runnable tasks at p95 of 6 or fewer); a contended number is labelled, never scored.
- Advisory checks (perf bots with noisy runners) are recorded in the PR, never rerun until
  green. If one shows a real regression, cite it against your own deterministic measurement.

## The gate set (generic)

Derive the project's list from its CI workflows and contributor docs, then run, on the
**final head SHA** after the last rebase and push. First review the PR's own diff inline
in the agent's own worktree, apply findings, and simplify. Finish these edits before the
final push and the gate chain below; any later edit or rebase restarts the gates:

1. The full build and the project's self-hosting or bootstrap check, if it has one.
2. The **whole** test suite exactly as CI runs it, including any parity or differential
   step between implementations. A filtered run is for development only.
3. Every check CI runs only *after* merge. If it cannot run locally, say so in the PR and
   propose a PR-time job; if it can, run it.
4. The project's lint, format, commit and PR-title rules, and its file-size or complexity
   budget. Use the repo's own budget: if it has a ratchet, files over the limit may change
   but not grow, and new code goes in new small modules; if it has none, do not invent one,
   propose it with a memo.
5. Touched-area checks (generated files up to date, docs regenerated, schema or contract
   checks).

Never regenerate a baseline, snapshot, expected-output file or skip list to make a failure
pass; only when the change legitimately adds passing tests, and say so in the PR.

Then tick the PR checklist with the head SHA (a claim written before the last push is not a
claim about the tree that merges) or comment `gates green at <sha>`, and wait for the
required checks.

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
   the gate list: this is how "filtered tests" and "post-merge-only checks" stop recurring.

## Closing children

- Closing keywords (close, fix, resolve) next to an issue number close it on merge, even
  negated. `Closes #N` only when the acceptance criteria are met; otherwise `Part of #N`
  and no closing words near the number, epic number included. A bare `(#N)` suffix is
  harmless but jsse-style repos avoid it on partial stages as a precaution.
- A merged-but-open child goes through the close-out audit, not an optimistic close.
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

- A transcript with no write for an hour, no gate process and no PR comment is stalled.
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
the rulings comment on the epic (capped.sh path, cron id, run ids), `gh pr list --state all
--search '"Part of #<epic>" in:body'`, `git worktree list`, the open children, and the default branch's
CI. Recreate the cron job, resume dead named agents by name, relaunch workflows with
`resumeFromRunId`, and continue from the first unmet step. Say what was found.
