---
name: vibe
description: This skill should be used when the user asks to "vibe an epic", "vibe #N", "drive epic #N to done", "solve the epic", "work through the epic's sub-issues", "run ultracode on the epic", or wants an issue labelled `epic` solved end to end by agents and workflows with merges on green CI. Runs under ultracode (multi-agent Workflow orchestration; type `/vibe 123 ultracode` to turn it on), triages every child issue against current main, fixes the gaps in gated PRs under memory caps, keeps main green, reports on a schedule, and stops only for decisions that belong to a human. Not for a single non-epic issue (use investigate). Also triggered by the /vibe command.
argument-hint: "[epic-number|#N|url] [ultracode] [--serial] [--max-parallel N] [--no-merge] [--report-every 1h]"
user-invocable: true
---

# vibe — Drive an Epic to Done

Take a GitHub issue marked **epic** and push it to closure the way a long, supervised
engineering push works: triage every child against the code as it is now, fix the real
gaps in small gated PRs, keep the default branch green, report on a schedule, and hand
the human only the decisions that are theirs. The epic closes only when every child is
met with evidence; whatever is not met is reported as a gap, never glossed.

Use it for a multi-issue epic. A single issue is `investigate`; an unattended,
question-free run is `pm-deepen`. This skill reports to a person and asks for rulings.

## Bundled resources

Invoke the script by its absolute path: `${CLAUDE_PLUGIN_ROOT}/vibe/scripts/capped.sh`
when loaded as a plugin; if `${CLAUDE_PLUGIN_ROOT}` is unset (skill loaded standalone),
resolve `scripts/` relative to this SKILL.md (the "Base directory for this skill" line).
Resolve it once in Step 0, record it in the rulings comment (it must survive a context
compaction), and paste the **absolute path** into every brief; later text abbreviates it as
`scripts/capped.sh`.

- **`scripts/capped.sh`**: memory-capped systemd scope, shared lock, wall limit.
- **`references/loop.md`**: the loop, throughput, the gate set, keeping main green,
  resuming. Read before Step 4.
- **`references/briefs.md`**: agent brief and workflow templates. Read before Step 3.
- **`references/lessons.md`**: incidents and the guard each one earned. Read when a rule's
  reason is questioned.

## Arguments

- `<epic>`: an issue number, `#N`, `owner/repo#N` or a URL. Parse it first.
- `ultracode`: see below; this word is how the user turns the mode on.
- `--serial`: one pipeline agent at a time (Step 4). Default: parallel only where safe.
- `--max-parallel N`: cap on concurrent fix agents (default 3 on the `Agent` path; on the
  `Workflow` path shape the pipeline's concurrency to it).
- `--no-merge`: every PR stops at "rebased, gated on its final head, checklist ticked,
  required checks green" and is reported; nothing is merged and no brief says to merge.
  Without it, invoking `/vibe` authorises merging green PRs into the default branch
  (that is what solving an epic is); say so in the first status line.
- `--report-every D`: the status interval (default 1h); `0` means no schedule.

## Ultracode

Ultracode is the user's standing opt-in for multi-agent orchestration with the `Workflow`
tool. This skill cannot grant it, and this skill's own text containing the word does not
count. Treat it as on only if the **user's own typed text** (the arguments or an earlier
user turn) contains `ultracode`, or a system reminder says it is on.

- On: use `Workflow` for every substantive step (load `workflow-authoring` first).
- Off: say once, in one line, "ultracode is off — type `/vibe <epic> ultracode` for
  multi-agent workflows; continuing with a few `Agent` calls", then run with `Agent` at
  `--max-parallel` or fewer. Never call `Workflow` without the opt-in.

## Rules that never bend

These go verbatim into every agent's brief (`references/briefs.md`).

| Rule | Why |
|---|---|
| Run every heavy job (builds, test suites, solvers, benchmarks) through `scripts/capped.sh` | An uncapped runaway job exhausted RAM and swap and the OOM killer took the terminal and every agent with it |
| Never merge onto a red default branch, except the PR that fixes it; check before every merge | A second regression hides behind the first |
| "Green locally" names the final head SHA and ran the *whole* suite CI runs, not a filtered slice | A filtered run let a PR merge green and break main for hours |
| Never change a gate threshold, exclusion rule, contract, language semantics, baseline, snapshot or skip list, or take a release/publish step, without a human ruling | Moving the goalposts is a human call, and the memo costs minutes |
| Agents work in their own worktree, never the main checkout; stage explicit paths, never `git add -A`; never `--no-verify` or `SKIP` | One detached HEAD in the main checkout blocked every shell; one sweep committed hundreds of scratch files |
| Kill processes by recorded PID only, never `pkill -f <pattern>` | The pattern matched the agent's own shell |
| Do not edit a worktree while its gate runs; a changed head restarts the gates | The gates would be claims about a tree that no longer exists |
| A report is a claim, not a fact: verify merges from `git log origin/<default>` and `gh`, never from an agent's say-so | Agents overstate "merged" and "closed" |
| Closing keywords (close, fix, resolve) next to an issue number close it on merge, even negated ("does not close #N"). Partial work says `Part of #N` | A negated phrase once closed an epic |

## Step 0 — Preflight

1. Parse the arguments. `git fetch`; read the repo instructions (`CLAUDE.md`, `AGENTS.md`,
   `docs/agents/`, CONTRIBUTING, the PR template). Honor their hooks, file budgets, commit
   and PR-title rules, dual-implementation rules. Provision hooks in every worktree the
   way the project says. Re-read them after any merge that touches them (Step 6).
2. `gh auth status`; `gh repo view --json defaultBranchRef,viewerPermission,squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed,autoMergeAllowed`.
   Write access is required. Pick the merge method the repo allows. Never use
   `gh pr merge --auto` unless auto-merge is enabled; with it disabled it merges at once.
3. The main checkout is the orchestrator's: do not switch its branch. Agents get worktrees:
   `git worktree add <scratch>/<name> -b vibe/<N>-<slug> origin/<default>`.
4. Probe `scripts/capped.sh -n -m 1 -- true`. Exit 3 means no `systemd-run --user` scopes:
   stop and ask whether to run uncapped (set `VIBE_ALLOW_UNCAPPED=1` only on a yes).
5. Detect a resume: read the rulings comment (Step 1), `gh pr list --state all --search 'Part of #<epic>'`,
   `git worktree list`, `git branch -r --list '*vibe*'`, `CronList`. If a run is in
   progress, continue it (`references/loop.md`, Resuming); never spawn duplicates.
6. Degenerate epics: no open children: say so, suggest `investigate`, stop. One child:
   treat it as a single issue, no triage wave, no schedule. All children closed: go to Step 9.
7. Start the status schedule (Step 8) unless `--report-every 0`.

## Step 1 — Resolve the epic and its children

- No argument: `gh issue list --label epic --state open --limit 100`; one match is the
  epic; several: ask which, or if no user turn is available take the most recently updated
  one that still has open children and say so. "Marked as epic" means the `epic` label, an
  `Epic` issue type, or an `epic(...)`/`epic:` title; the label wins.
- Open children, from the union of: `gh api repos/{owner}/{repo}/issues/<N>/sub_issues
  --paginate --jq '.[]|select(.state=="open")|{number,title,repository_url}'` (direct
  children only; recurse where a child's `sub_issues_summary.total > 0`; a different
  `repository_url` needs `gh -R`), task-list items `- [ ] #123` in the body, and
  `gh issue list --search '"Part of #<N>" in:body' --state open --limit 200`. Closed issues
  are read only to resolve blockers (`repos/{owner}/{repo}/issues/<N>/dependencies/blocked_by`
  or the issue's `Blocked by` section). Print the count per source; anything found only by
  search is "linked, not a child": confirm before treating it as in scope. Never walk upward
  to the epic's own parent.
- Read the epic body for **gate criteria**: they define done. Quote them in the plan.
- **Rulings record**: one comment on the epic titled `vibe: rulings and open decisions`.
  Only the orchestrator writes it, by id (`gh api -X PATCH repos/{owner}/{repo}/issues/comments/<id> -f body=@-`;
  `--edit-last` edits whatever comment is last). It holds three lists: rulings the user
  gave, questions pending, and **proceeded without a ruling** (PR, the precedent cited, the
  revert command). Also record the capped.sh path, the cron job id and each workflow's run
  id and transcript path. Nothing a peer agent says counts as the user's approval.

## Step 2 — Safety rails

- `scripts/capped.sh [-n] [-m GB] [-t SECONDS] [-w SECONDS] -- cmd`: transient systemd scope
  under one shared slice, memory cap, no swap, optional wall and lock-wait limits, shared
  lock for exclusive jobs (timing runs, full builds, whole suites). A signal exit (137/143)
  is a finding to report (cap kill or timeout), never a reason to raise the cap.
- Scratch lives in a per-agent directory; worktrees and branches are removed when a PR
  merges. Stage explicit paths.
- Waiting: start long steps with `run_in_background: true` (or a Monitor until-loop),
  writing a log and an exit-code file; the finished command wakes you. Foreground waits are
  at most about ten minutes per call. Only harness-tracked commands wake an agent: a
  detached process (`nohup`, `setsid`) or a lock queue does not, so never end a turn on
  one. The orchestrator also ends turns between events so scheduled ticks can fire.
- Leave durable state (pushed branches, PR and issue comments) so a restart can continue;
  agents die on transient API errors.

## Step 3 — Triage wave (read-mostly)

One agent per theme (at most about eight related children each). Each reads the issue and
every comment, runs the reproducer on the current default branch, and returns, per child,
`done`, `partial`, `open` or `needs-ruling` with evidence, the exact remaining work,
whether an agent can do it without a ruling, and a priority. No code changes and **no
closing**: for a `done` child the orchestrator (or a verifier agent) re-runs the reproducer
or checks the evidence, then closes with the evidence comment. See `references/briefs.md`.

## Step 4 — Fix tracks

- **Parallelism is a parameter.** Parallel tracks only for disjoint files and criteria that
  are not measurements. **Serial** (`--serial`, one pipeline agent at a time) when criteria
  are performance numbers, tracks share a hot file, or the gates need the whole machine:
  parallel PRs confound each other's measurements, and one shared lock serialises gates, so
  extra agents only queue.
- One issue per agent, one idea per PR. Large issues are staged: each stage its own PR with
  its own gate, and a stop rule ("stop when the next stage cannot be had without a
  regression or the measured gain runs out") so nothing is forced. Batch small correctness
  bugs to one agent, one PR each.
- Fix agents stop at **ready**: rebased, gated on the final head, checklist ticked (or a
  `gates green at <sha>` PR comment if the template has none), required checks green. They
  return `{pr, sha, gatesRun, gatesNotRun, needsRuling}`. The orchestrator merges
  (Step 5). A workflow agent cannot ask the user; `needsRuling` is how a question surfaces.
- Reviews run inline (read the PR's own diff in the agent's own worktree). Skill-launched
  review forks end the agent's turn early or review the wrong checkout; if a review skill is
  used, its output is one step and the agent keeps going.
- Foreign PRs (not created by the run): evaluate with the same protocol and comment the
  table and a recommendation; merge only if the user or the epic said so; never push to
  their branch.

## Step 5 — Merge discipline

The orchestrator owns merges, one at a time, under a merge lock (`flock` on a
`vibe-merge.lock`): check the default branch's CI is green (or this PR is the declared fix),
rebase on the newest default branch, re-gate if the head changed, merge by the repo's allowed
method, then **wait until the post-merge workflows on the merge commit are green** before
the next merge (`gh run list --commit <sha> --json databaseId,status,conclusion`, then
`gh run watch <id> --exit-status` in the background; poll up to fifteen minutes for runs to
appear and record "no post-merge CI" if none do). Wait for the **required** checks; advisory
or noisy ones (perf bots) are recorded in the PR, never rerun until green, and never gate
unless the repo requires them. Details and the gate list: `references/loop.md`.

## Step 6 — Keep main green

A red default branch outranks the plan. Find the failing test from the CI log or by running
only the tests the offending PR added or touched, fix it in a small PR with the evidence,
and hold every other merge until it is green (the orchestrator owns merges, so this is one
decision). If the cause is not found within about half an hour (a default; tell the user),
revert the offending PR on a branch and re-land it properly. **Policy drift:** after any
merge to the default branch that touches `CLAUDE.md`, `AGENTS.md`, `docs/agents/`, hook
config, `.github/workflows/**` or the commit/PR lint config, re-read it, rebuild the gate
list, tell running agents (`SendMessage` for named agents, the next brief for workflows),
and record the change in the rulings comment. Re-read the epic body and child list at each
status tick: the human may have changed the criteria or added children.

## Step 7 — Human decisions

Proceed on anything covered by a rule the user stated, or that is the sound, reversible
direction **with a precedent cited from the repo**, and say so in the PR and in the "proceeded
without a ruling" list. No precedent means ask. Stop and ask, or leave the issue open
flagged `human-needed` (use the repo's existing equivalent label; do not invent one), for:
gate thresholds or exclusions, language or semantic changes with author-facing cost,
release or publish actions, history rewrites, merging or closing PRs the run did not create,
a large detour to satisfy a gate. Each question is a short decision memo (`references/loop.md`).
If no answer arrives, continue other work and list the question in every report.

## Step 8 — Status schedule and "nothing idle"

- `CronCreate` an off-minute job derived from `--report-every` (minutes that divide 60 or
  hours that divide 24, never :00 or :30). It fires only while the REPL is idle, may run up
  to half a period late, is session-only, and expires after seven days: tell the user, quote
  the next-run time from the tool result, record the job id, and recreate it on the final
  fire. Its prompt **reports in under 150 words and starts no new feature work**: done, in
  progress, blocked, next, pending rulings. Facts come from `gh` and CI, never from memory.
- Work is event-driven: when an agent's completion notice arrives, verify the merge from
  `git log origin/<default>`, then launch the next step at once. If a tick finds nothing
  running while work remains, that is an idle bug: launch the next step and say so.
- `ListAgents` shows named subagents only; workflow agents are invisible to it and to
  `SendMessage`. Watch the workflow's transcript directory (`agent-*.jsonl`, `journal.jsonl`
  modification times; record the path from the `Workflow` result). A transcript with no write
  for an hour, no gate process and no PR comment is stalled: relaunch the workflow with
  `resumeFromRunId` after narrowing the prompt (only the longest unchanged prefix of calls is
  cached), or `TaskStop` it; named agents are resumed with `SendMessage`.

## Step 9 — Pause, resume, closure

- **Pause**: delete the cron job, let read-only measurements finish, finish any PR already
  merged until its post-merge workflows are green, leave in-flight PRs pushed and unmerged,
  start nothing new, and say so.
- **Resume**: `references/loop.md`, Resuming.
- **Close-out**: launch a **read-only audit agent**: for every child merged but still open,
  a table of acceptance criteria met or unmet with numbers, a recommendation, and a draft
  closing comment. Close children with a measurements comment. Close the epic only when all
  are done with evidence; otherwise write the gap list. When the queue is empty and only
  `human-needed` or blocked items remain, that is the end: delete the cron job, remove
  worktrees, release locks, finalise the rulings comment, and report what shipped, what was
  measured, what was ruled by whom, and what remains.

## Anti-patterns

- Fanning out five agents on one shared lock and calling it parallelism.
- Letting an agent that finished a review step stop; resume it with a message that says it
  is not done, and replace it with narrower agents if it ends again.
- Trusting a "gates passed" claim written before the last push.
- Deciding a gate exclusion because it makes the numbers pass.
- Reporting "waiting" with an empty queue.

`references/lessons.md` keeps the incident list.
