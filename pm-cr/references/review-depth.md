# Review depth

| Depth | Finder angles | Candidates each | Verify | Sweep | Cap (bugs, cleanup) |
|---|---|---|---|---|---|
| low | none, one hunk-only pass | — | none | no | 4 in total |
| medium | A, B, C, Conventions, pm-simplify | 6 | 3-state | no | 8 each |
| high | the same, plus F | 6 | recall-biased | no | 10 each |
| xhigh | A–F, Conventions, pm-simplify | 8 | recall-biased | yes | 15 each |

Medium and above build the **Reviewer brief** first and run the **Scope
check** last (`angles.md`).

## low

Use only what Phase 1 loaded, with no subagents, no pm-simplify, and no `REVIEW.md` rules. When the diff changes
anything besides tests, skip test and fixture hunks (`test/`, `tests/`,
`spec/`, `__tests__/`, `fixtures/`, `testdata/`, `*_test.*`, `*.test.*`).

Flag only runtime-correctness bugs visible from the hunk alone: an inverted
condition, an off-by-one, a null deref where adjacent lines show the value
can be absent, a removed guard, a falsy-zero check, a missing `await`, a
wrong-variable copy-paste, a swallowed error, or untrusted input reaching a
shell, SQL, or HTML sink. Also flag a duplicate of a helper visible in the
diff context, and dead code that the diff leaves behind. Report a finding
only when you are at least 80% sure, and drop the † items of **Never
report** unchecked.

## Medium and above

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
