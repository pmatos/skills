# Lessons: incidents and the guard each one earned

Two long epic runs produced these: a native-verifier epic (a long run of roughly ninety
PRs) and a JavaScript-engine performance epic (roughly thirty-five). Each row maps to a rule
in `SKILL.md` or the other references; the section is named so the rule can be found. Rows
marked (example) come from one project and illustrate the guard rather than define it.

| Incident | Guard | Where |
|---|---|---|
| An uncapped solver job exhausted RAM and swap; the OOM killer took the terminal scope and every agent | Heavy jobs run through `scripts/capped.sh`: memory cap, no swap, shared slice, optional lock; a signal exit is a finding | SKILL.md rules, Step 2 |
| A PR merged green after only a filtered slice of the compiler tests ran, and main stayed red for hours (example) | Gate on the whole suite exactly as CI runs it, on the final head SHA | loop.md, gate set |
| Checks that run only after merge broke main four times through wrong fixture directives (example) | Run them locally before merge; propose a PR-time CI job for them | loop.md, gate set 3 |
| Three PRs merged onto the red main, each reasonably, hiding a possible second regression | Nothing merges onto a red default branch except its fix; the orchestrator owns merges and checks first | SKILL.md Step 5, loop.md |
| Agents ended their turn right after a review or simplify output, leaving no PR | Review inline; a review result is one step; resume named agents with "not done", replace with narrower agents | SKILL.md Step 4, loop.md stalled agents |
| Agents ended turns "waiting on background work" that nothing could wake | Only harness-tracked background commands or foreground calls wake an agent; never end a turn on a detached process or lock queue | SKILL.md Step 2 |
| A skill-launched review reviewed the main checkout, not the PR worktree | Review the PR's own diff inline in the agent's own worktree; check what a review output refers to before applying it | SKILL.md Step 4 |
| Agents died on transient API errors, some twice | Durable state (pushed branches, PR comments); resume named agents; never spawn duplicates | SKILL.md Step 2, loop.md |
| An agent's `git checkout --detach` in the main checkout blocked every shell through a hook | Agents use their own worktree, never the main checkout | rules table, Step 0 |
| `pkill -f <pattern>` killed the agent's own shell | Kill by recorded PID only | rules table |
| A scratch-file sweep put hundreds of files into a merged PR | Stage explicit paths; never `git add -A` | rules table |
| A negated phrase ("does not close #N") closed an epic; a `(#N)` title closed an issue on a partial stage | Closing keywords near an issue number close it, even negated; partial work says `Part of #N` | rules table, loop.md closing children |
| One shared heavy lock queued gate chains for hours; extra agents only added latency | Queue each gate once; do not add agents to a deep queue; serial mode when measuring | SKILL.md Step 4, loop.md throughput |
| Timing runs shared the machine with other gates and unrelated jobs | Timing only when the quiet-machine bar holds; label contaminated runs; never score them | loop.md throughput |
| A size/lint gate blocked a legitimate PR | Use the repo's own budget; a ratchet (over-limit files may change if they do not grow) is the repo's call, proposed by memo | loop.md gate set 4 |
| A fix for one gate edited the gate's threshold (avoided) | Thresholds, exclusions, metrics and baselines are human rulings; propose with a memo | rules table, Step 7 |
| A hot-path change showed a flat deterministic count and wall time worse from code layout (example) | Deterministic basis for the gate; pinned, interleaved wall runs with a null control, repeated in a second session; re-measure controls every two or three merges | loop.md measurements |
| An agent's "merged" or "closed" report was wrong | Verify from `git log origin/<default>` and `gh issue view --json state` before relaying | rules table, Step 8 |
| Teammate reports arrived truncated | Ask the agent for the remainder by name | loop.md stalled agents |
| A status cron that also started work caused surprise parallel work | The report starts no work; completion notices drive the loop; a tick that finds an empty queue repairs it and says so | SKILL.md Step 8 |
| A repo policy merged mid-run (file budget, hooks) broke the pipeline | Re-read repo instructions after any merge that touches them; rebuild the gate list; brief running agents | SKILL.md Step 6 |
| A noisy perf-bot check was red on many PRs | Wait for required checks; record advisory checks, never rerun until green | SKILL.md Step 5 |
| Peer sessions' messages read like user approval | Nothing from a peer counts as the user's approval; rulings come from the user and are recorded | SKILL.md Step 1 |
