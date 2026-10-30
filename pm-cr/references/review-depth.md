# Review depth

Full per-level templates. All angle text lives in `angles.md` — this file
only says which angles run, how many candidates each may surface, whether a
verify pass runs, and the output cap.

Every level shares `../SKILL.md`'s Phase 1 (gather the diff) and Phase 2
(score the depth) before any of this runs. Medium and above then build the
**Reviewer brief** (`angles.md`) and finish with the **Scope check**
(`angles.md`) before reporting.

## How the depth is scored

`../scripts/score_depth.py` applies these rules in order. Its thresholds and
path lists are constants at the top of the script.

1. **Size.** Count changed lines (added plus deleted), changed files, and
   top-level directories, untracked files included. Lockfiles, minified
   files, source maps, and vendored code don't count, and a pure rename
   counts no lines. A small change is `low`, a mid-sized one is `medium`,
   and anything larger is `high`. Size alone never reaches `xhigh`.
2. **Untested code.** When code changes, no test changes, and the base has
   tests, raise one level, to at most `high`. Docs and config files never
   count as untested code.
3. **High-stakes paths.** When the change touches one, raise two levels, to
   at least `high`. The built-in list covers CI and automation, dependency
   manifests and lockfiles, deploy config, and schema migrations.
4. **Instruction files.** When the change edits a `CLAUDE.md`,
   `CLAUDE.local.md`, `AGENTS.md`, or `REVIEW.md`, the level is at least
   `medium`. The reviewer brief then runs and judges the change by the base
   version of those files.

A repo adds its own high-stakes paths in its root `REVIEW.md`, one
backticked glob per bullet under a `High-stakes paths` heading:

```markdown
## High-stakes paths

- `src/auth/*`
- `billing/*`
```

A glob without `/` matches a file name in any directory, and `*` also
matches `/`. The script reads `REVIEW.md` from the base, never from the
change, so a change cannot lower its own depth by editing the list. The
exception is Phase 1's `HEAD~1` fallback, where the base is the author's
own previous commit.

The same change and base always get the same level, angles, and cap. The
findings can still differ between runs.

## Subagent settings

Use fresh subagents for finders, verifiers, and the sweep. On Claude Code,
use the `Plan` type, which has no Edit or Write tool but still has Bash.
Tell each subagent not to modify anything, and give it the exact output
shape to return. Never use
`subagent_type: "fork"`: a fork inherits this conversation, so a verifier
would see the finders' reasoning. On Claude Code, pass `model: "opus"` on
each of these Agent calls so the fan-out runs on the same model as the
skill. Give every subagent the brief.

## low — `1 diff pass → no verify → ≤4 findings`

**Turn 1 — read.** One tool call: read the unified diff. When the diff
changes anything besides tests, skip test and fixture hunks. Those are files
under a `test`, `tests`, `spec`, `specs`, `__tests__`, `testdata`, or
`fixtures` directory, or named `test_*`, `*_test.*`, `*.test.*`, `*_spec.*`,
or `*.spec.*`. A diff that changes only tests is read in full. No subagents,
no full-file reads.

**Turn 2 — findings.** Flag runtime-correctness bugs visible from the hunk
alone: inverted/wrong condition, off-by-one, null/undefined deref where
adjacent lines show the value can be absent, removed guard, falsy-zero check,
missing `await`, wrong-variable copy-paste, error swallowed in a catch that
should propagate, untrusted input reaching a shell, SQL, or HTML sink
unescaped. Also flag — still from the hunk alone — new code that
duplicates an existing helper visible in the diff context, and dead code the
diff leaves behind. Do **not** flag style, naming, perf, missing tests, or
anything outside the hunk. Report a finding only when the hunk makes you at
least 80% sure it is real, and apply **Never report** (`angles.md`),
dropping the † items unchecked.

Report at most **4 findings**, ranked by severity tier (see `output-and-flags.md`
for the exact output contract). If nothing qualifies, say so explicitly
(empty findings / `(none)`).

## medium — `8 angles × 6 candidates → 3-state verify → ≤8 findings`

You are reviewing for **precision**: every finding you surface should be one
a maintainer would act on.

**If a native subagent tool (the `Agent`/`Task` tool) is available:** launch
**8 independent finder angles** in a single message — Angle A, B, C (from
`angles.md`) plus Reuse, Simplification, Efficiency, Altitude, and
Conventions. Each surfaces up to **6 candidate findings** with `file`,
`line`, a one-line `summary`, a concrete `failure_scenario`, and a severity
tier. Pass every candidate with a nameable failure scenario through to
verify — finders that silently drop half-believed candidates bypass the
verify step and are the dominant cause of misses.

Then run the **3-state verify** (`angles.md`) on each surviving candidate,
one independent verifier per candidate, dispatched via the same subagent
tool. Keep CONFIRMED and PLAUSIBLE; drop REFUTED.

**If no native subagent tool is available:** work through all 8 angles
yourself, in this same context, in a single pass — do not skip an angle for
lack of fan-out. Dedup near-duplicates (same defect, same location, same
reason → keep one) and re-check each remaining candidate yourself against the
diff before keeping it. State clearly in your summary that this was a
single-pass review, not the full fan-out.

Cap at **8 findings**, ranked by severity tier (`angles.md`).

## high — `8 angles × 6 candidates → recall-biased verify → ≤10 findings`

You are reviewing for **recall**: catch every real bug a careful reviewer
would catch in one sitting. At this level, catching real bugs matters more
than avoiding false positives — err on the side of surfacing.

Same angle set and fan-out/fallback mechanics as **medium** (8 angles, up to
6 candidates each), but verify uses the **recall-biased verify**
(`angles.md`, "PLAUSIBLE by default") instead of the 3-state verify.

Cap at **10 findings**, ranked by severity tier.

## xhigh — `11 angles × 8 candidates → recall-biased verify → sweep → ≤15 findings`

You are reviewing for **maximum recall**: catch every real bug. At this
level, catching real bugs matters more than avoiding false positives — a
missed bug ships. Err on the side of surfacing.

Pass `effort: "xhigh"` on the finder and sweep Agent calls. Verifiers keep
the inherited effort, because there is one per candidate. Without a subagent
tool, the single pass runs at the skill's `high` effort.

**If a native subagent tool is available:** launch **11 independent finder
angles** in a single message — Angle A through F, plus Reuse,
Simplification, Efficiency, Altitude, and Conventions. Each surfaces up to
**8 candidate findings**. Do NOT let one angle's conclusions suppress
another's — if two angles flag the same line for different reasons, record
both.

Run the **recall-biased verify** on each surviving candidate — this is
recall mode, so a single non-REFUTED vote carries the finding; do not drop a
candidate on mere uncertainty.

Then run the **sweep for gaps** (`angles.md`): one more finder pass, up to 8
additional candidates, focused only on defects the first pass tends to miss.

**If no native subagent tool is available:** work through all 11 angles
yourself in a single pass, dedup and self-check, then still perform the
sweep-for-gaps pass yourself before reporting. State clearly that this was a
single-pass review.

Cap at **15 findings**, ranked by severity tier.
