# Agent briefs and workflow templates

Fill the `<…>` slots. Mark project-specific rules in a brief so the next
epic can swap them. The per-issue brief is adapted from a long-running epic loop.

## Common preamble for every agent

```text
Repo <owner/repo> at <path>, epic #<E> (<epic goal>). Read CLAUDE.md/AGENTS.md and the
docs they link; provision the repo's hooks in your worktree; never bypass hooks.
Work in your OWN git worktree and scratch directory, never the main checkout. Commit as
<identity from the run config>. Start from the newest default branch (git fetch). Publish
with git push -u origin HEAD; never plain --force, and do not rebase unless the orchestrator hands
a conflicting PR back to you (hand-back brief below).

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

Measuring: never run a timing-sensitive check yourself. Finish steps 1-4 first, then comment
the request on the PR, starting "vibe: measurement request" (what to measure, the protocol,
the control set), and return READY with needsMeasurement carrying the same text; `checks`
is the state at that sha, and the PR is not mergeable until the numbers are in. If you
cannot get as far as a PR without numbers, return at that point with needsMeasurement and
`notes` listing the pipeline steps left. Deterministic counts that need no quiet machine
are fine to run.

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
this stage opened; 0 if none yet), `sha` (string, empty if none), `checks` (array of strings: check name and conclusion),
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

Measuring: never run a timing-sensitive reproducer yourself. For a child whose reproducer
is a measurement, classify it from the issue and any recorded numbers, set needsMeasurement
to the request (what to measure on the default branch, the protocol), and say what you
could not verify. You cannot comment: the orchestrator records the request.
```

Workflow schema (`TRIAGE`): an `items` array of objects with `repo`, `issue`, `title`,
`status` (enum `done | partial | open | needs-ruling`), `evidence`, `remaining`,
`implementable` (boolean), `priority` (number), `needsMeasurement` (string, empty if none),
all required.

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

## Hand-back continuation brief

```text
Your PR #<pr> (branch <branch>) conflicts with <default> in a way the orchestrator will not
resolve. Rebase it yourself, in your own worktree, with rebase-pr's scripts only:
<REBASE_PR>/scripts/capture-lease.sh <remote> <branch> before the rebase, and
<REBASE_PR>/scripts/safe-force-push.sh <remote> <branch> <captured-sha> to publish (an
explicit-SHA --force-with-lease; never plain --force). Resolve the conflicts keeping both
sides' intent, then run /code-review high --fix --comment and /simplify as before, and wait
for the required checks on the new final head. Return READY with that SHA.
```

## Measurement-window brief

```text
You hold an exclusive measurement window. Default branch SHA: <sha> (pinned; stop and
report if the checkout is not at it). Requests, run one after another, each one of:
- PR request: <PR branch, protocol, control set>. Measure the default SHA, then the PR
  branch merged onto it, with the same protocol, interleaved with a null control.
- Reproducer request: <issue, protocol>. Run the reproducer on the default SHA only; no
  PR branch involved.
- Gate-evidence or foreign-PR request: follow that brief (below), with this window as its
  quiet machine.
Check the load against the quiet bar (<bar>) before each run; retry contaminated runs up to
3 times and label what stays contaminated, never score it. No code changes, no merges, no
threshold changes. Comment the tables, bounds, SHA, tool versions and contamination labels
on each request's PR (or issue), starting "vibe: measurement result" and citing the
request ("vibe: measurement partial" for anything unfinished), and return the numbers.
```

## Gate-evidence brief

```text
Measure the CURRENT default branch (record the SHA; restart if it moves unless the new
commits touch only docs or CI). No code changes, no merges. Build, run the project's
self-hosting check, any verdict or differential comparison, oracle or property suites, and
the performance gate in the measurement window you were given (check the quiet bar before
each run, retry contaminated runs up to 3 times and label what stays contaminated),
merged through the project's own gate script so the gate is non-provisional. Open an issue per failing criterion with numbers; change no
threshold. Post one comment with tables per criterion, bounds, the SHA, tool versions and
contamination labels, starting "vibe: measurement result" and citing the request. The quiet
bar is <bar>.
```

## Evaluate-a-foreign-PR brief

```text
Review the diff for correctness; check the size/lint budget; check it rebases on the default
branch (do NOT resolve conflicts in the PR branch, report). Measure base versus
PR-merged-onto-default with the same protocol, in the window you were given (quiet bar checked before each run, contaminated runs
retried up to 3 times and labelled, never scored; the quiet bar is <bar>). If every bar
passes, comment the table, starting "vibe: measurement result" and citing the request, and
recommend merge; merge only when the invoking user explicitly authorised it, as recorded in the rulings comment. Never push to the
PR's branch.
```

## Workflow skeleton: triage, then fix to ready

One workflow per phase; read the result between phases (per `workflow-authoring`).
Landing is not a workflow: the orchestrator merges inline (SKILL.md Step 5).

```text
// Workflow 1 — triage ONE theme; one run per theme, so a slow theme never holds the rest.
// The theme arrives in args.
export const meta = { name: 'epic-triage', description: 'Triage one theme of the epic', phases: [{title: 'Triage'}] }
const triage = await agent(TRIAGE_BRIEF(args.theme), {schema: TRIAGE, effort: 'medium', label: 'triage ' + args.theme})
if (triage && Array.isArray(triage.items)) return {theme: args.theme, triage, incomplete: false}
log('Incomplete triage theme: ' + args.theme)
return {theme: args.theme, triage: null, incomplete: true}

// ORCHESTRATOR, per finished run: retain triage evidence; retry an incomplete theme, verify
// done children, surface needs-ruling items. A child returned with needsMeasurement is
// measured in a window (Step 4, reproducer request) and the orchestrator sets its final
// status from the numbers. Startable open/partial items launch at once (Step 4), without
// waiting for the other themes: deduplicate by repo and issue, highest priority first.

// Workflow 2 — one fix to READY; no merges; one run per item, so its completion notice
// frees exactly one slot. FIX_BRIEF(item) covers ONE stage; a staged issue is launched once
// per stage, the next stage only after the previous one is merged. The item arrives in args.
export const meta = { name: 'epic-fix', description: 'Fix one epic child to READY', phases: [{title: 'Fix'}] }
const ready = await agent(FIX_BRIEF(args.item), {schema: READY, label: 'fix #' + args.item.issue})
if (!ready) log('Incomplete fix: ' + args.item.issue)
return {item: args.item, ready}

// ORCHESTRATOR, per finished run: verify the READY result from git/gh. A null `ready` is an
// agent that died (agent() returns null, it does not throw), so check its branch and PR
// before relaunching with a continuation brief. A fix returning needsMeasurement is parked
// for a window, not retried. With --no-merge, ensure required checks are green on the final
// head, then stop.
```

`TRIAGE`, `READY`, and the brief functions are
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
