# Review depth

| Depth | Finder angles | Candidates each | Verify | Sweep | Cap (bugs, cleanup) |
|---|---|---|---|---|---|
| medium | A, B, C, Conventions, pm-simplify | 6 | 3-state | no | 8 each |
| high | the same, plus F | 6 | recall-biased | no | 10 each |
| xhigh | A–F, Conventions, pm-simplify | 8 | recall-biased | yes | 15 each |

Build the **Reviewer brief** first and run the **Scope check** last
(`angles.md`).

## Procedure

Run every finder, verifier, and sweep as a fresh `Plan` subagent, which has
no Edit or Write tool but still has Bash, and never as a fork. Pass
`model: "opus"`, and at xhigh pass `effort: "xhigh"` to finders and the
sweep. Give each subagent the brief and tell it not to modify anything.

1. Launch every finder angle for the depth in one message. Give each the
   output shape: `file`, `line`, a one-line `summary`, a concrete
   `failure_scenario`, and a `category`, and tell them that reuse,
   simplification, efficiency, and altitude belong to pm-simplify. Without
   waiting for them, invoke `pm-simplify --report` through the Skill tool.
   Its list is candidates like any finder's, not the end of the review, so
   keep going. If it changed any file, stop and report that the installed
   pm-simplify has no report mode. Without pm-simplify, say in the
   assessment that cleanup was not reviewed.
2. Finders pass every candidate with a nameable failure scenario to verify.
   Two angles that flag one line for different reasons give two
   candidates.
3. Dedup the candidates, then verify each with one verifier (`angles.md`).
4. At xhigh, run the **Sweep for gaps** (`angles.md`), and verify its
   candidates the same way.

Without a subagent tool, work through every angle yourself in one pass,
dedup near-duplicates, re-check each candidate against the diff, and still
run the sweep at xhigh.
