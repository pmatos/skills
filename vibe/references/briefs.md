# Agent briefs and workflow templates

Fill the `<…>` slots. `<CAPPED>` is the absolute path of `vibe/scripts/capped.sh` resolved
in Step 0: substitute it before dispatch. Mark project-specific rules in a brief so the next
epic can swap them. The per-issue brief is adapted from the jsse epic loop.

## Common preamble for every agent

```text
Repo <owner/repo> at <path>, epic #<E> (<epic goal>). Read CLAUDE.md/AGENTS.md and the
docs they link; provision the repo's hooks in your worktree; never bypass hooks.
Work in your OWN git worktree and scratch directory, never the main checkout. Commit as
<identity>. Use the newest default branch (git fetch) and rebase before gating via rebase-pr's
pre-rebase remote-head capture and explicit-SHA --force-with-lease. Never plain --force;
if the lease fails, stop and re-inspect. Publish initially with git push -u origin HEAD.

Rules that never bend:
- Heavy commands (builds, suites, solvers, benchmarks) go through <CAPPED>:
  use its host-adaptive default with the lock for builds and suites, -n for small runs,
  and -n -t <project wall limit in seconds> for experiments. Preflight supplies the time
  limits and quiet-machine bar. Exit 124 (timeout status) or a signal exit (137/143) is a
  finding to report, never a reason to raise a cap.
- Never change a gate threshold, exclusion rule, contract, language semantics, baseline,
  snapshot or skip list, and take no release or publish step, without a human ruling: put
  the question in your result (needsRuling) and stop that part.
- Stage explicit paths, never git add -A. Never --no-verify or SKIP. Stop capped jobs with
  systemctl --user stop <printed-scope>; use recorded PIDs for other processes, never pkill -f. Do not edit a worktree while its gate runs.
- Closing keywords (close, fix, resolve) next to an issue number close it on merge, even
  negated: partial work says "Part of #N".
- Do not merge. Stop at READY: rebased, gated on the final head SHA, checklist ticked (or a
  "gates green at <sha>" PR comment), required checks green. [Only when the orchestrator
  delegates the merge: before merging check that the default branch's required workflows at its current SHA are all
  green or that this PR is the declared fix.]

Waiting: Agent-tool subagents wait in the FOREGROUND, in blocking calls (an until loop on a log and an exit-code
file, or a blocking flock) of at most about ten minutes each, repeated until the job is done.
A background job, a detached process or a lock queue does not reliably wake a subagent:
never end your turn while work is pending. Workflow stages and the orchestrator may instead
use supported run_in_background wakeups with durable logs and exit-code files; this
exception applies only when dispatched as a Workflow stage, not via the Agent tool. Leave durable state: push branches,
comment on the PR or issue as you go.
Do not end your turn until the task is complete or you hit a real blocker; the output of a
review or simplify step is one step, keep going.
```

## Per-issue fix brief

```text
Goal: resolve issue #<N> (<title>), part of epic #<E>. Read the issue and its comments
first, then <design docs, ADRs, the merged PRs that are the model>.

Pipeline (sequential):
1. Investigate. Reproduce on the current default branch before changing anything.
2. Implement in small PRs, one idea each; add tests for the observable behaviour and
   guard fixtures that fail on a wrong model. Follow <the repo's commit and PR-title rules>.
   "Closes #<N>" only if the acceptance criteria are truly met; for a partial stage
   "Part of #<N>". Every PR body also includes the non-closing epic reference "Part of #<E>".
3. Review your own PR diff inline, high effort; apply findings by hand; comment a summary.
4. Simplify pass, inline.
5. Gates on the FINAL head SHA: <the project's whole-suite gate list>. Tick the PR
   checklist with the SHA, wait for the required checks, then return READY.

Staging (large issues): each stage its own PR, ready before the next starts. Stop after any
stage where the next cannot be had without a regression; comment the measurements.

Hard constraints: no regressions [project: the control set and tolerances]; if the
improvement cannot be had without one, do NOT force it: comment on the issue with
measurements instead (the orchestrator may close the issue as measured under a stated
decision rule). Known hazards in this codebase: <layout-sensitive hot paths, size
ratchet, generated files, dual-implementation rules>. A ruling-bound part is not yours:
comment the exact question on the issue and report it in needsRuling.

Final report, short, facts first: what shipped; the numbers; gates run and any NOT run;
whether #<N> is done; anything filed; cleanup done.
```

Workflow result schema: `pr` (number), `sha` (string), `gatesRun` (array of strings),
`gatesNotRun` (array), `needsRuling` (string, empty if none), `notes` (string). Plain `Agent`
subagents return prose: end the brief with "finish your report with a block: PR, SHA, gates
run, gates NOT run, needsRuling", parse it, and verify from `git` and `gh`.

## Triage brief (read-only)

```text
Theme '<theme>': issues <#a, #b, …>. For each: read the body and every comment, the code,
fixtures and skip rows it names, and test the claim against the current default branch
(run the reproducer, capped). Classify done | partial | open | needs-ruling with concrete
evidence, the precise remaining work, whether an agent can do it without a ruling, and a
priority (1 = blocks the epic's gate or a soundness/coverage gap, 3 = nice to have).
Return status and evidence for partial children; the orchestrator updates their status
comments. Do not post comments, close issues, or change code: for a done child return the
evidence and the orchestrator verifies and closes.
```

Workflow schema: an `items` array of objects with `issue`, `title`, `status` (enum), `evidence`,
`remaining`, `implementable` (boolean), `priority` (number), all required.

## Read-only close-out audit brief

```text
READ-ONLY audit: do not close, comment on, or edit anything; no worktrees or PRs. For each
issue: read the thread and acceptance criteria, find the merged PRs and measurement
documents, decide which criteria are met or unmet (cite numbers), and judge whether a
worthwhile regression-free implementation remains or whether to close with documented
measurements. Final report: one table row per issue: number | title | criteria met/unmet
with numbers | recommendation (CLOSE-with-measurements | IMPLEMENT-remaining: what, size,
risk | KEEP-OPEN: why) | draft closing comment (at most 6 lines) for CLOSE rows. A child with
unmet criteria but solid numbers is CLOSE-as-measured: state the unmet criteria, the numbers, the
reason and the decision rule that justifies it.
```

## Gate-evidence brief

```text
Measure the CURRENT default branch (record the SHA; restart if it moves unless the new
commits touch only docs or CI). No code changes, no merges. Build, run the project's
self-hosting check, any verdict or differential comparison, oracle or property suites, and
the performance gate in windows that meet the quiet-machine bar (retry contaminated ones up
to 3 times and label what stays contaminated), merged through the project's own gate script
so the gate is non-provisional. Open an issue per failing criterion with numbers; change no
threshold. Post one comment with tables per criterion, bounds, the SHA, tool versions and
contamination labels.
```

## Evaluate-a-foreign-PR brief

```text
Review the diff for correctness; check the size/lint budget; check it rebases on the default
branch (do NOT resolve conflicts in the PR branch, report). Measure base versus
PR-merged-onto-default with the same protocol. If every bar passes, comment the table and
recommend merge; merge only when the invoking user explicitly authorised it, as recorded in the rulings comment. Never push to the
PR's branch.
```

## Workflow skeleton: triage, fix to ready, land sequentially

One workflow per phase; read the result between phases (per `workflow-authoring`).

```text
// Workflow 1 — triage only; return every theme, including failures
export const meta = { name: 'epic-<N>-triage', description: '…', phases: [{title: 'Triage'}] }
const results = []
for (const theme of THEMES) {
  const triage = await agent(TRIAGE_BRIEF(theme), {schema: TRIAGE, effort: 'medium'})
  if (!triage || !Array.isArray(triage.items)) {
    log('Incomplete triage theme: ' + theme)
    results.push({theme, triage: null, incomplete: true})
  } else results.push({theme, triage, incomplete: false})
}
return results

// ORCHESTRATOR BARRIER: retain triage evidence; retry incomplete themes, verify done
// children, surface needs-ruling items. Select only implementable open/partial items,
// deduplicate by repo/issue, sort by priority. Decide serial vs disjoint parallel batches
// in Step 4. FIX_BATCHES has <= MAX_PARALLEL items per batch (one under --serial);
// all items in a parallel batch must have disjoint files and non-measurement criteria.

// Workflow 2 — fixes to READY; no merges
export const meta = { name: 'epic-<N>-fix', description: '…', phases: [{title: 'Fix'}] }
const fixes = []
for (const batch of FIX_BATCHES) {
  const results = await Promise.all(batch.map(async item => {
    const ready = await agent(FIX_BRIEF(item), {schema: READY})
    if (!ready) log('Incomplete fix: ' + item.issue)
    return {item, ready}
  }))
  fixes.push(...results)
}
return fixes

// ORCHESTRATOR BARRIER: retain triage AND fixes, verify every READY result from git/gh.
// With --no-merge, ensure latest rebase, final-head gates and required checks, then stop.

// Workflow 3 — land (orchestrator-owned, one PR per agent, sequential)
export const meta = { name: 'epic-<N>-land', description: '…', phases: [{title: 'Land'}] }
for (const pr of READY_PRS) {
  // LAND checks all current-default-SHA workflows, lease-safe rebases/pushes,
  // re-runs gates if the head changed, merges, then waits for all required post-merge CI.
  const result = await agent(LAND_BRIEF(pr), {schema: LANDED})
  if (!result || !result.merged || !result.postMergeGreen) break
}

```

`THEMES`, `TRIAGE`, `FIX_BATCHES`, `MAX_PARALLEL`, `READY`, `LANDED`, and the brief functions are yours to define from the
templates above. Notes that cost time once:

- Prompts are template literals: use single quotes inside them. A stray backtick ends the
  string and the script fails to parse.
- One agent step per `agent()` call with a result schema. A long multi-PR agent ends early;
  a chain of narrow ones does not.
- Edit the script file and re-run with `resumeFromRunId`: only the longest unchanged prefix
  of calls is cached, so editing an early prompt re-runs everything after it; cached "merged"
  results can be stale, so verify from git.
- Workflow agents are invisible to `ListAgents` and cannot be messaged: record the run id and
  transcript path from the result, watch the transcript modification times, relaunch with
  `resumeFromRunId`.
- A workflow agent cannot ask the user: questions travel in `needsRuling`.
- Give a continuation brief the existing branch, PR and what is already done, and tell it to
  check `gh pr list --state all --search '#<N>'` first.
