# Agent briefs and workflow templates

Fill the `<…>` slots. `<CAPPED>` is the absolute path of `vibe/scripts/capped.sh` resolved
in Step 0: substitute it before dispatch. Mark project-specific rules in a brief so the next
epic can swap them. The per-issue brief is adapted from the jsse epic loop.

## Common preamble for every agent

```text
Repo <owner/repo> at <path>, epic #<E> (<epic goal>). Read CLAUDE.md/AGENTS.md and the
docs they link; provision the repo's hooks in your worktree; never bypass hooks.
Work in your OWN git worktree and scratch directory, never the main checkout. Commit as
<identity>. Use the newest default branch (git fetch) and rebase before gating.

Rules that never bend:
- Heavy commands (builds, suites, solvers, benchmarks) go through <CAPPED>:
  -m 24 with the lock for builds and suites, -n -m 12 for small runs, -n -m 8 -t 900 for
  experiments. A signal exit (137/143) is a finding to report, never a reason to raise a cap.
- Never change a gate threshold, exclusion rule, contract, language semantics, baseline,
  snapshot or skip list, and take no release or publish step, without a human ruling: put
  the question in your result (needsRuling) and stop that part.
- Stage explicit paths, never git add -A. Never --no-verify or SKIP. Kill by recorded PID
  only, never pkill -f. Do not edit a worktree while its gate runs.
- Closing keywords (close, fix, resolve) next to an issue number close it on merge, even
  negated: partial work says "Part of #N".
- Do not merge. Stop at READY: rebased, gated on the final head SHA, checklist ticked (or a
  "gates green at <sha>" PR comment), required checks green. [Only when the orchestrator
  delegates the merge: before merging check that the default branch's latest CI run is
  green or that this PR is the declared fix.]

Waiting: run long steps with run_in_background (or a Monitor until-loop), writing a log and
an exit-code file; a finished background command wakes you. Foreground waits are at most
about ten minutes per call. A detached process or a lock queue does not wake you: never end
your turn on one. Leave durable state: push branches, comment on the PR or issue as you go.
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
   guard fixtures that fail on a wrong model. Conventional title, at most 100 characters.
   "Closes #<N>" only if the acceptance criteria are truly met; for a partial stage
   "Part of #<N>".
3. Review your own PR diff inline, high effort; apply findings by hand; comment a summary.
4. Simplify pass, inline.
5. Gates on the FINAL head SHA: <the project's whole-suite gate list>. Tick the PR
   checklist with the SHA, wait for the required checks, then return READY.

Staging (large issues): each stage its own PR, ready before the next starts. Stop after any
stage where the next cannot be had without a regression; comment the measurements.

Hard constraints: no regressions [project: the control set and tolerances]; if the
improvement cannot be had without one, do NOT force it: comment on the issue with
measurements instead. Known hazards in this codebase: <layout-sensitive hot paths, size
ratchet, generated files, dual-implementation rules>. A ruling-bound part is not yours:
comment the exact question on the issue and report it in needsRuling.

Final report, short, facts first: what shipped; the numbers; gates run and any NOT run;
whether #<N> is done; anything filed; cleanup done.
```

Workflow result schema: `pr` (number), `sha` (string), `gatesRun` (array of strings),
`gatesNotRun` (array), `needsRuling` (string, empty if none), `notes` (string).

## Triage brief (read-mostly)

```text
Theme '<theme>': issues <#a, #b, …>. For each: read the body and every comment, the code,
fixtures and skip rows it names, and test the claim against the current default branch
(run the reproducer, capped). Classify done | partial | open | needs-ruling with concrete
evidence, the precise remaining work, whether an agent can do it without a ruling, and a
priority (1 = blocks the epic's gate or a soundness/coverage gap, 3 = nice to have).
Post a short status comment on a partial child. Do NOT close anything: for a done child
return the evidence and the orchestrator verifies and closes. Change no code.
```

Workflow schema: an `items` array of objects with `issue`, `status` (enum), `evidence`,
`remaining`, `implementable` (boolean), `priority` (number), all required.

## Read-only close-out audit brief

```text
READ-ONLY audit: do not close, comment on, or edit anything; no worktrees or PRs. For each
issue: read the thread and acceptance criteria, find the merged PRs and measurement
documents, decide which criteria are met or unmet (cite numbers), and judge whether a
worthwhile regression-free implementation remains or whether to close with documented
measurements. Final report: one table row per issue: number | title | criteria met/unmet
with numbers | recommendation (CLOSE-with-measurements | IMPLEMENT-remaining: what, size,
risk | KEEP-OPEN: why) | draft closing comment (at most 6 lines) for CLOSE rows.
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
recommend merge; merge only when the user or the epic explicitly said so. Never push to the
PR's branch.
```

## Workflow skeleton: triage, fix to ready, land sequentially

One workflow per phase; read the result between phases (per `workflow-authoring`).

```text
// Workflow 1 — triage then fix to READY (no merges inside)
export const meta = { name: 'epic-<N>-fix', description: '…', phases: [{title: 'Triage'}, {title: 'Fix'}] }
const results = await pipeline(THEMES,
  t => agent(TRIAGE_BRIEF(t), {schema: TRIAGE, effort: 'medium'}),
  async (res, t) => {            // per theme, no barrier; items in order within a theme
    const out = []
    for (const it of res.items.filter(i => i.implementable)) out.push(await agent(FIX_BRIEF(it), {schema: READY}))
    return out
  })
return results

// Workflow 2 — land (orchestrator-owned, one PR per agent, sequential)
for (const pr of READY_PRS) {
  const r = await agent(LAND_BRIEF(pr), {schema: LANDED})   // checks main is green, rebases, merges, waits for post-merge CI
  if (!r || !r.merged || !r.postMergeGreen) break
}
```

`THEMES`, `TRIAGE`, `READY`, `LANDED`, and the brief functions are yours to define from the
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
