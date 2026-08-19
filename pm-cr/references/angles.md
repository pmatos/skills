# Angle bank

Shared finder angles, referenced by `../SKILL.md` and `effort-levels.md`.
Higher effort levels use more of these angles per phase; all levels share the
same angle *text* — only which ones run, and how many candidates each may
surface, changes per level.

## Correctness angles

### Angle A — line-by-line diff scan

Read every hunk in the diff, line by line. Then Read the enclosing function for
each hunk — bugs in unchanged lines of a touched function are in scope (the PR
re-exposes or fails to fix them). For every line ask: what input, state, timing,
or platform makes this line wrong? Look for inverted/wrong conditions,
off-by-one, null/undefined deref, missing `await`, falsy-zero checks,
wrong-variable copy-paste, error swallowed in catch, unescaped regex metachars.

### Angle B — removed-behavior auditor

For every line the diff DELETES or replaces, name the invariant or behavior it
enforced, then search the new code for where that invariant is re-established.
If you can't find it, that's a candidate: a removed guard, a dropped error
path, a narrowed validation, a deleted test that was covering a real case.

### Angle C — cross-file tracer

For each function the diff changes, find its callers (Grep for the symbol) and
check whether the change breaks any call site: a new precondition, a changed
return shape, a new exception, a timing/ordering dependency. Also check callees:
does a parallel change in the same diff make a call unsafe?

### Angle D — language-pitfall specialist (xhigh/max only)

Scan for the classic pitfalls of the diff's language/framework — for example:
JS falsy-zero, `==` coercion, closure-captured loop var; Python mutable default
args, late-binding closures; Go nil-map write, range-var capture; SQL injection;
timezone/DST drift; float equality. Flag any instance the diff introduces.

### Angle E — wrapper/proxy correctness (xhigh/max only)

When the diff adds or modifies a type that wraps another (cache, proxy,
decorator, adapter): check that every method routes to the wrapped instance and
not back through a registry/session/global — e.g. a caching provider holding a
`delegate` field that resolves IDs via `session.get(...)` instead of
`delegate.get(...)` will re-enter the cache or recurse. Also check that the
wrapper forwards all the methods the callers actually use.

## Cleanup, altitude, and conventions angles

The angles above hunt for bugs; these hunt for cleanup, depth, and convention
issues in the changed code instead.

### Reuse

Flag new code that re-implements something the codebase already has — Grep
shared/utility modules and files adjacent to the change, and name the existing
helper to call instead.

### Simplification

Flag unnecessary complexity the diff adds: redundant or derivable state,
copy-paste with slight variation, deep nesting, dead code left behind. Name
the simpler form that does the same job.

### Efficiency

Flag wasted work the diff introduces: redundant computation or repeated I/O,
independent operations run sequentially, blocking work added to startup or
hot paths. Also flag long-lived objects built from closures or captured
environments — they keep the entire enclosing scope alive for the object's
lifetime (a memory leak when that scope holds large values); prefer a
class/struct that copies only the fields it needs. Name the cheaper
alternative.

### Altitude

Check that each change is implemented at the right depth, not as a fragile
bandaid. Special cases layered on shared infrastructure are a sign the fix
isn't deep enough — prefer generalizing the underlying mechanism over adding
special cases.

### Conventions (CLAUDE.md)

Find the CLAUDE.md files that govern the changed code: the user-level
`~/.claude/CLAUDE.md`, the repo-root `CLAUDE.md`, plus any `CLAUDE.md` or
`CLAUDE.local.md` in a directory that is an ancestor of a changed file (a
directory's CLAUDE.md only applies to files at or below it). Read each one
that exists, then check the diff for clear violations of the rules they
state. Only flag a violation when you can quote the exact rule and the exact
line that breaks it — no style preferences, no vague "spirit of the doc"
inferences. In the finding, name the CLAUDE.md path and quote the rule so the
report can cite it. If no CLAUDE.md applies, return nothing for this angle.

## Shared candidate shape

Cleanup, altitude, and conventions candidates use the same `file`/`line`/
`summary` shape as correctness candidates; in `failure_scenario`, state the
concrete cost (what is duplicated, wasted, harder to maintain, or which
CLAUDE.md rule is broken) instead of a crash. **Correctness bugs always
outrank cleanup, altitude, and conventions findings** when the output cap
forces a cut.

## Verify — 3-state (medium effort)

For each surviving candidate, run one independent verifier (a fresh subagent,
or yourself in a fresh pass on the single-pass path) that has NOT seen the
finder's reasoning — give it the diff, the relevant file(s), and the
candidate, and have it return exactly one of:

- **CONFIRMED** — can name the inputs/state that trigger it and the wrong
  output or crash. Quote the line.
- **PLAUSIBLE** — mechanism is real, trigger is uncertain (timing, env,
  config). State what would confirm it.
- **REFUTED** — factually wrong (code doesn't say that) or guarded elsewhere.
  Quote the line that proves it.

Keep candidates where the vote is CONFIRMED or PLAUSIBLE. Drop REFUTED.

## Verify — recall-biased (high/xhigh/max effort)

Same mechanics as the 3-state verify above, but biased toward keeping:

**PLAUSIBLE by default** — do not refute a candidate for being "speculative"
or "depends on runtime state" when the state is realistic: concurrency races,
nil/undefined on a rare-but-reachable path (error handler, cold cache, missing
optional field), falsy-zero treated as missing, off-by-one on a boundary the
code does not exclude, retry storms / partial failures, regex/allowlist that
lost an anchor. These are PLAUSIBLE.

**REFUTED** only when constructible from the code: factually wrong (quote the
actual line); provably impossible (type/constant/invariant — show it); already
handled in this diff (cite the guard); or pure style with no observable effect.

Keep CONFIRMED and PLAUSIBLE. Drop REFUTED.

## Sweep for gaps (xhigh/max effort only)

Run one more finder pass — a fresh reviewer who has the verified/deduplicated
list. Re-read the diff and enclosing functions looking ONLY for defects not
already listed. Do not re-derive or re-confirm anything already there — the
job is gaps. Focus on what the first pass tends to miss: moved/extracted code
that dropped a guard or anchor; second-tier footguns (dataclass default
evaluated once, `hash()` non-determinism, lock-scope shrink, predicate methods
with side effects); setup/teardown asymmetry in tests; config defaults
flipped.

Surface up to 8 additional candidates, each naming a defect not already on the
list. If nothing new, return nothing from this phase — do not pad.
