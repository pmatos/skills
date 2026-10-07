# Review angles

Maintainer reference: running the skill does not require reading this file.
Derived from the `pm-cr` and `pm-simplify` skills and embedded here so this skill
has no dependency on them. `scripts/review_offline/passes.py` loads each
third-level heading's section by its id (the heading text) and puts it into a
finder prompt, so keep ids stable. The first family hunts correctness bugs, the second hunts
cleanup. Every angle returns candidates in the finding shape from
`review-data.md`.

## Correctness family

### correctness-scan

Read every hunk line by line, then read the enclosing function for each hunk:
bugs in unchanged lines of a touched function are in scope. For every line ask
what input, state, timing or platform makes it wrong. Look for inverted or wrong
conditions, off-by-one, null/undefined deref, missing `await`, falsy-zero checks,
wrong-variable copy-paste, errors swallowed in a catch, unescaped regex
metacharacters.

### correctness-removed

For every line the diff deletes or replaces, name the invariant or behavior it
enforced, then search the new code for where that invariant is re-established.
If it is not, that is a candidate: a removed guard, a dropped error path, a
narrowed validation, a deleted test that covered a real case.

### correctness-callers

For each function the diff changes, find its callers (grep the symbol) and check
whether the change breaks a call site: a new precondition, a changed return
shape, a new exception, an ordering or timing dependency. Check callees too: does
a parallel change in the same diff make a call unsafe?

### correctness-pitfalls

Scan for the classic pitfalls of the diff's language or framework, for example JS
falsy-zero, `==` coercion, closure-captured loop variables; Python mutable default
arguments, late-binding closures; Go nil-map writes, range-variable capture; SQL
injection; timezone and DST drift; float equality. Flag instances the diff
introduces.

### correctness-wrappers

When the diff adds or changes a type that wraps another (cache, proxy, decorator,
adapter), check that every method routes to the wrapped instance and not back
through a registry, session or global, which re-enters the wrapper. Check that the
wrapper forwards every method callers actually use.

## Cleanup family

These hunt for quality problems in the changed code, not bugs. The cost goes in
`body`: what is duplicated, wasted or harder to maintain.

### cleanup-reuse

Flag new code that re-implements something the codebase already has. Grep shared
and utility modules and files adjacent to the change, and name the existing helper
to call instead.

### cleanup-simplification

Flag unnecessary complexity the diff adds: redundant or derivable state,
copy-paste with slight variation, deep nesting, dead code left behind. Name the
simpler form that does the same job.

### cleanup-efficiency

Flag wasted work the diff introduces: redundant computation or repeated I/O,
independent operations run sequentially, blocking work added to startup or hot
paths. Flag long-lived objects built from closures or captured environments,
which keep the entire enclosing scope alive. Name the cheaper alternative.

### cleanup-altitude

Check that each change is implemented at the right depth, not as a fragile
bandaid. Special cases layered on shared infrastructure suggest the fix is not
deep enough; prefer generalizing the underlying mechanism.

### cleanup-conventions

Find the instruction files that govern the changed code: the repo-root `CLAUDE.md`
and `AGENTS.md`, plus any such file in an ancestor directory of a changed file (user-level
instruction files are usually outside the child's read access). Read each one that exists and
check the diff for clear violations of the rules it states. Flag a violation only
when you can quote the exact rule and the exact line that breaks it. Name the
instruction file and quote the rule in `body`. If none applies, return nothing.

## Verification

### verify-recall

You are given one candidate, the diff, and the repo. You have not seen the
finder's reasoning. Decide independently with exactly one verdict:

- **CONFIRMED**: you can name the inputs or state that trigger it and the wrong
  output or crash. Quote the line.
- **PLAUSIBLE**: the mechanism is real and the trigger is uncertain (timing,
  environment, configuration). Say what would confirm it. Treat realistic state as
  plausible: concurrency races, null on a rare reachable path, falsy-zero treated
  as missing, off-by-one on a boundary the code does not exclude, retry storms,
  regexes that lost an anchor.
- **REFUTED**: only when constructible from the code. The code does not say that
  (quote the actual line), it is provably impossible (show the type, constant or
  invariant), it is already guarded in this diff (cite the guard), or it is pure
  style with no observable effect.

### verify-precise

As `verify-recall`, but REFUTE speculative candidates whose trigger you cannot
name from the code. Use for the `medium` effort level (`low` skips verification).

## Gap sweep

### sweep

You are given the verified list. Re-read the diff and the enclosing functions
looking only for defects not already listed; do not re-confirm anything on the
list. Focus on what a first pass misses: moved or extracted code that dropped a
guard or anchor; second-tier footguns (dataclass default evaluated once, `hash()`
non-determinism, lock-scope shrink, predicate methods with side effects);
setup/teardown asymmetry in tests; flipped config defaults. Return up to 8 new
candidates, or an empty array. Do not pad.
