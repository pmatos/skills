# Agent briefs and workflow templates

Fill the `<…>` slots. `<CAPPED>` is the absolute path of `vibe/scripts/capped.sh` resolved
in Step 0: substitute it before dispatch. Mark project-specific rules in a brief so the next
epic can swap them. The per-issue brief is adapted from a long-running epic loop.

## Common preamble for every agent

```text
Repo <owner/repo> at <path>, epic #<E> (<epic goal>). Read CLAUDE.md/AGENTS.md and the
docs they link; provision the repo's hooks in your worktree; never bypass hooks.
Work in your OWN git worktree and scratch directory, never the main checkout. Commit as
<identity from the run config>. Use the newest default branch (git fetch) and rebase before
gating: resolve conflicts by hand, run <REBASE_PR>/scripts/capture-lease.sh <remote> <branch> BEFORE
the rebase and <REBASE_PR>/scripts/safe-force-push.sh <remote> <branch> <captured-sha> to publish.
Do not use rebase-pr's own gate step: your gates go through <CAPPED>. Never plain --force;
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
- "Green locally" names the final head SHA and means the WHOLE suite CI runs, not a
  filtered slice. Report a claim older than your last push as not run.
- Closing keywords (close, fix, resolve) next to an issue number close it on merge, even
  negated: your PR body says "Part of #N" and "Part of #<E>", never a closing keyword.
- Do not merge. Stop at READY: rebased, gated on the final head SHA, checklist ticked (or a
  "gates green at <sha>" PR comment), required checks green.

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
   The PR body says "Part of #<N>" even when the
   acceptance criteria look met (the orchestrator verifies and closes), and also "Part of #<E>".
3. Review your own PR diff inline, high effort; apply findings by hand; comment a summary.
4. Simplify pass, inline.
5. Gates on the FINAL head SHA: <the project's whole-suite gate list>. Tick the PR
   checklist with the SHA, wait for the required checks, then return READY.

Staging (large issues): each stage its own PR, ready before the next starts. Stop after any
stage where the next cannot be had without a regression; comment the measurements.

One stage per agent call under a Workflow (see the notes below); an Agent-tool agent
may run several stages in sequence.

Hard constraints: no regressions [project: the control set and tolerances]; if the
improvement cannot be had without one, do NOT force it: comment on the issue with
measurements instead (the orchestrator may close the issue as measured under a stated
decision rule). Known hazards in this codebase: <layout-sensitive hot paths, size
ratchet, generated files, dual-implementation rules>. A ruling-bound part is not yours:
comment the exact question on the issue and report it in needsRuling.

Final report, short, facts first: what shipped; the numbers; gates run and any NOT run;
whether #<N> is done; anything filed; cleanup done.
```

Workflow result schema (`READY`): `repo` (string), `issue` (number), `pr` (number, the PR
this stage opened), `sha` (string), `gatesRun` (array of strings), `gatesNotRun` (array),
`needsRuling` (string, empty if none), `notes` (string). Plain `Agent` subagents return
prose: end the brief with "finish your report with a block: repo, issue, PR, SHA, gates run,
gates NOT run, needsRuling", parse it, and verify from `git` and `gh`.

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

Workflow schema (`TRIAGE`): an `items` array of objects with `repo`, `issue`, `title`,
`status` (enum `done | partial | open | needs-ruling`), `evidence`, `remaining`,
`implementable` (boolean), `priority` (number), all required.

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

## Workflow skeleton: triage, then fix to ready

One workflow per phase; read the result between phases (per `workflow-authoring`).
Landing is not a workflow: the orchestrator merges inline (SKILL.md Step 5).

```text
// Workflow 1 — triage only; return every theme, including failures
export const meta = { name: 'epic-<N>-triage', description: '…', phases: [{title: 'Triage'}] }
// Themes run in parallel; when the reproducers are measurements, replace Promise.all with
// a sequential for-loop so themes do not confound each other.
const results = await Promise.all(THEMES.map(async theme => {
  const triage = await agent(TRIAGE_BRIEF(theme), {schema: TRIAGE, effort: 'medium'})
  if (!triage || !Array.isArray(triage.items)) {
    log('Incomplete triage theme: ' + theme)
    return {theme, triage: null, incomplete: true}
  }
  return {theme, triage, incomplete: false}
}))
return results

// ORCHESTRATOR BARRIER: retain triage evidence; retry incomplete themes, verify done
// children, surface needs-ruling items. Select only implementable open/partial items,
// deduplicate by repo and issue, sort by priority. Decide serial vs disjoint parallel batches
// in Step 4. FIX_BATCHES has <= MAX_PARALLEL items per batch (one under --serial);
// all items in a parallel batch must have disjoint files and non-measurement criteria.

// Workflow 2 — fixes to READY; no merges. FIX_BRIEF(item) covers ONE stage; a staged issue
// is launched once per stage, the next stage only after the previous one is merged.
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
```

`THEMES`, `TRIAGE`, `FIX_BATCHES`, `MAX_PARALLEL`, `READY`, and the brief functions are
yours to define from the templates above. `<REBASE_PR>` is the absolute path of the
`rebase-pr` skill directory, resolved like `<CAPPED>`. Notes that cost time once:

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
