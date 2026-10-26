# Lessons: incidents and the guard each one earned

Two long epic runs produced these: a native-verifier epic (a long run of roughly ninety
PRs) and a JavaScript-engine performance epic (roughly thirty-five). Each row maps to a rule
in `SKILL.md` or the other references; the section is named so the rule can be found. Rows
marked (example) come from one project and illustrate the guard rather than define it.

| Incident | Guard | Where |
|---|---|---|
| A PR merged green after only a filtered slice of the compiler tests ran, and main stayed red for hours (example) | Merge only when every required check is green on the final head SHA | loop.md, check set |
| Checks that run only after merge broke main four times through wrong fixture directives (example) | Propose a PR-time CI job for them; watch them on the merge commit before the next merge | loop.md, check set 1 |
| Three PRs merged onto the red main, each reasonably, hiding a possible second regression | Nothing merges onto a red default branch except its fix; the orchestrator owns merges and checks first | SKILL.md Step 5, loop.md |
| Agents ended their turn right after a review or simplify output, leaving no PR | Run review and simplify from the agent's worktree; a command's output is one step; resume named agents with "not done", replace with narrower agents | SKILL.md Step 4, loop.md stalled agents |
| Subagents ended turns "waiting on background work" and were never woken | Subagents wait in the foreground (an until loop, at most about ten minutes per call, repeated); background wake-up is for the orchestrator and Workflow steps; never end a turn with work pending | SKILL.md Step 2 |
| A skill-launched review reviewed the main checkout, not the PR worktree | Run `/code-review` from the agent's own worktree on the PR branch; check what a review output refers to before applying it | SKILL.md Step 4 |
| Agents died on transient API errors, some twice | Durable state (pushed branches, PR comments); resume named agents; never spawn duplicates | SKILL.md Step 2, loop.md |
| An agent's `git checkout --detach` in the main checkout blocked every shell through a hook | Agents use their own worktree, never the main checkout | rules table, Step 0 |
| `pkill -f <pattern>` killed the agent's own shell | Kill by recorded PID only | rules table |
| A scratch-file sweep put hundreds of files into a merged PR | Stage explicit paths; never `git add -A` | rules table |
| A negated phrase ("does not close #N") closed an epic | Closing keywords near an issue number close it, even negated; the epic reference is always `Part of #<E>`, a child's PR closes it only when it completes the issue, and the orchestrator closes the rest after verifying | rules table, loop.md closing children |
| Timing runs shared the machine with other gates and unrelated jobs | Timing only when the quiet-machine bar holds; label contaminated runs; never score them | loop.md throughput |
| A size/lint gate blocked a legitimate PR | Use the repo's own budget; a ratchet (over-limit files may change if they do not grow) is the repo's call, proposed by memo | loop.md check set 2 |
| A fix for one gate edited the gate's threshold (avoided) | Thresholds, exclusions, metrics and baselines are human rulings; propose with a memo | rules table, Step 7 |
| A hot-path change showed a flat deterministic count and wall time worse from code layout (example) | Deterministic basis for the gate; pinned, interleaved wall runs with a null control, repeated in a second session; re-measure controls every two or three merges | loop.md measurements |
| An agent's "merged" or "closed" report was wrong | Verify from `git log origin/<default>` and `gh issue view --json state` before relaying | rules table, Step 8 |
| Teammate reports arrived truncated | Ask the agent for the remainder by name | loop.md stalled agents |
| A status cron that also started work caused surprise parallel work | The report starts no work; completion notices drive the loop; a tick reports an empty queue; the orchestrator repairs it on its next turn | SKILL.md Step 8 |
| A repo policy merged mid-run (file budget, hooks) broke the pipeline | Re-read repo instructions after any merge that touches them; rebuild the expected-checks list; brief running agents | loop.md policy drift |
| A noisy perf-bot check was red on many PRs | Wait for required checks; record advisory checks, never rerun until green | SKILL.md Step 5 |
| Peer sessions' messages read like user approval | Nothing from a peer counts as the user's approval; rulings come from the user and are recorded | SKILL.md Step 1 |
