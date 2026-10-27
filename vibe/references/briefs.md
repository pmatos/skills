# Agent briefs and workflow templates

Fill the `<…>` slots. Mark project-specific rules in a brief so the next
epic can swap them. The per-issue brief is adapted from a long-running epic loop.

## Common preamble for every agent

```text
Repo <owner/repo> at <path>, epic #<E> (<epic goal>). Read CLAUDE.md/AGENTS.md and the
docs they link; provision the repo's hooks in your worktree; never bypass hooks.
Work in your OWN git worktree and scratch directory, never the main checkout. Commit as
<identity from the run config>. Start from the newest default branch (git fetch). Publish
with git push -u origin HEAD; never plain --force, and do not rebase: the orchestrator
rebases a PR only when it has merge conflicts.

Rules that never bend:
- Never change a gate threshold, exclusion rule, contract, language semantics, baseline,
  snapshot or skip list, and take no release or publish step, without a human ruling: put
  the question in your result (needsRuling) and stop that part.
- Stage explicit paths, never git add -A. Never --no-verify or SKIP. Kill processes by
  recorded PID, never pkill -f.
- Run nothing locally to prove green: the PR's CI is the gate. "Green" means every required
  check on the final head SHA completed successfully; report a claim older than your last
  push as not run.
- Closing keywords (close, fix, resolve) next to an issue number close it on merge, even
  negated: your PR body says "Part of #<E>" for the epic, never a closing keyword, and
  "Fixes #N" for issue #N only when this PR completes it (the final stage), else "Part of #N".
- Do not merge. Stop at READY: review and simplify fixes pushed, required checks green on
  the final head SHA.

Waiting: Agent-tool subagents wait in the FOREGROUND, in blocking calls (`timeout 600 gh pr checks <pr> --watch`, or an until loop on a log and an exit-code
file) of at most about ten minutes each, repeated until the job is done.
A background job or a detached process does not reliably wake a subagent:
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

Pipeline (sequential, in your own worktree; each command's output is one step, keep going):
1. Run /investigate <N>: it takes the issue to an open PR (reproduce or design, fix with
   tests, commit, push, open the PR). Overrides: the PR body says "Part of #<E>" for the
   epic, never a closing keyword, and keeps investigate's "Fixes #<N>" only when this PR
   completes the issue (the final stage), else "Part of #<N>" (fix with gh pr edit). Follow <the repo's
   commit and PR-title rules>. If investigate stops on a blocker (no repro, ambiguous
   design), open no PR and report it in needsRuling.
2. Run /code-review high --fix --comment on the PR. Commit the applied fixes (explicit
   paths) and push.
3. Run /simplify. Commit and push what it applied.
4. Wait for the required checks on the FINAL head SHA; if one fails, fix, push and wait
   again. Run nothing locally to prove green. Then return READY.

Staging (large issues): each stage its own PR, ready before the next starts. Stop after any
stage where the next cannot be had without a regression; comment the measurements.

One stage per agent call under a Workflow (see the notes below); an Agent-tool agent
may run several stages in sequence.

Measuring: never run a benchmark or any timing-sensitive check yourself. When you need one,
push your branch and finish with needsMeasurement (what to measure, the protocol, the
control set); the orchestrator runs it in an exclusive window and continues you with the
numbers. Deterministic counts that need no quiet machine are fine to run.

Hard constraints: no regressions [project: the control set and tolerances]; if the
improvement cannot be had without one, do NOT force it: comment on the issue with
measurements instead (the orchestrator may close the issue as measured under a stated
decision rule). Known hazards in this codebase: <layout-sensitive hot paths, size
ratchet, generated files, dual-implementation rules>. A ruling-bound part is not yours:
comment the exact question on the issue and report it in needsRuling.

Final report, short, facts first: what shipped; the numbers; checks run and any not green;
whether #<N> is done; anything filed; cleanup done.
```

Workflow result schema (`READY`): `repo` (string), `issue` (number), `pr` (number, the PR
this stage opened), `sha` (string), `checks` (array of strings: check name and conclusion),
`needsRuling` (string, empty if none), `needsMeasurement` (string, empty if none), `notes`
(string). Plain `Agent` subagents return
prose: end the brief with "finish your report with a block: repo, issue, PR, SHA, checks,
needsRuling, needsMeasurement", parse it, and verify from `git` and `gh`.

## Triage brief (read-only)

```text
Theme '<theme>': issues <#a, #b, …>. For each: read the body and every comment, the code,
fixtures and skip rows it names, and test the claim against the current default branch
(run the reproducer). Classify done | partial | open | needs-ruling with concrete
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
// pool() keeps up to `limit` calls in flight and starts the next the moment one finishes, so a
// slow item never holds up the rest. TRIAGE_LIMIT is the slot count (Step 4); themes whose reproducers
// are measurements are left out and run alone afterwards, in a measurement window (Step 4).
async function pool(items, limit, fn) {
  const out = []
  let next = 0
  await Promise.all(Array.from({length: Math.min(limit, items.length)}, async () => {
    while (next < items.length) { const i = next++; out[i] = await fn(items[i]) }
  }))
  return out
}
return await pool(THEMES, TRIAGE_LIMIT, async theme => {
  try {
    const triage = await agent(TRIAGE_BRIEF(theme), {schema: TRIAGE, effort: 'medium'})
    if (triage && Array.isArray(triage.items)) return {theme, triage, incomplete: false}
  } catch (e) { log('Triage theme threw: ' + theme) }
  log('Incomplete triage theme: ' + theme)
  return {theme, triage: null, incomplete: true}
})

// ORCHESTRATOR BARRIER: retain triage evidence; retry incomplete themes, verify done
// children, surface needs-ruling items. Select only implementable open/partial items,
// deduplicate by repo and issue, sort by priority. FIX_ITEMS holds every startable child
// (Step 4: no open blocker, previous stage merged); children blocked by another item go in a
// later workflow run once their blocker merges. FIX_LIMIT is the slot count (1 under --serial).
// Files overlapping is not a reason to hold an item back. An item returning needsMeasurement
// is parked for a measurement window (Step 4), not retried.

// Workflow 2 — fixes to READY; no merges. FIX_BRIEF(item) covers ONE stage; a staged issue
// is launched once per stage, the next stage only after the previous one is merged.
export const meta = { name: 'epic-<N>-fix', description: '…', phases: [{title: 'Fix'}] }
// pool() as in Workflow 1.
return await pool(FIX_ITEMS, FIX_LIMIT, async item => {
  const ready = await agent(FIX_BRIEF(item), {schema: READY})
  if (!ready) log('Incomplete fix: ' + item.issue)
  return {item, ready}
})

// ORCHESTRATOR BARRIER: retain triage AND fixes, verify every READY result from git/gh.
// With --no-merge, ensure required checks are green on the final head, then stop.
```

`THEMES`, `TRIAGE`, `TRIAGE_LIMIT`, `FIX_ITEMS`, `FIX_LIMIT`, `READY`, and the brief functions are
yours to define from the templates above.  Notes that cost time once:

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
