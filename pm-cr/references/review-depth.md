# Review depth

Angle text lives in `angles.md`. This file says which angles run at each
depth, and how.

| Depth | Finder angles | Candidates each | Verify | Sweep | Cap |
|---|---|---|---|---|---|
| low | none, one hunk-only pass | — | none | no | 4 |
| medium | A, B, C, Reuse, Simplification, Efficiency, Altitude, Conventions | 6 | 3-state | no | 8 |
| high | the same 8 | 6 | recall-biased | no | 10 |
| xhigh | A–F, plus the same 5 cleanup angles | 8 | recall-biased | yes | 15 |

Medium and above build the **Reviewer brief** first and run the **Scope
check** last (`angles.md`).

## low

Read the unified diff in one tool call, with no subagents and no full-file
reads. When the diff changes anything besides tests, skip test and fixture
hunks (`test/`, `tests/`, `spec/`, `__tests__/`, `fixtures/`, `testdata/`,
`*_test.*`, `*.test.*`).

Flag only runtime-correctness bugs visible from the hunk alone: an inverted
condition, an off-by-one, a null deref where adjacent lines show the value
can be absent, a removed guard, a falsy-zero check, a missing `await`, a
wrong-variable copy-paste, a swallowed error, or untrusted input reaching a
shell, SQL, or HTML sink. Also flag a duplicate of a helper visible in the
diff context, and dead code that the diff leaves behind. Report a finding
only when you are at least 80% sure, and drop the † items of **Never
report** unchecked.

## Medium and above

1. Launch every finder angle for the depth in one message, as fresh `Plan`
   subagents, which have no Edit or Write tool but still have Bash. Never
   use `subagent_type: "fork"`: a fork inherits this conversation, so a
   verifier would see the finders' reasoning. Pass `model: "opus"`, and at
   xhigh pass `effort: "xhigh"` to finders and the sweep. Give each
   subagent the brief, tell it not to modify anything, and give it the
   output shape: `file`, `line`, a one-line `summary`, a concrete
   `failure_scenario`, and a `category`.
2. Finders pass every candidate with a nameable failure scenario to verify,
   because dropping half-believed candidates early is the main cause of
   misses. Two angles that flag one line for different reasons give two
   candidates.
3. Verify each candidate with one fresh verifier: 3-state at medium, and
   recall-biased at high and xhigh (`angles.md`).
4. At xhigh, run the **Sweep for gaps** (`angles.md`).

Without a subagent tool, work through every angle yourself in one pass,
dedup near-duplicates, re-check each candidate against the diff, and still
run the sweep at xhigh. That pass runs at the skill's `high` effort. Say in
the assessment that the review was a single pass.
