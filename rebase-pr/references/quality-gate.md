# The quality gate: detection, chaining, and failure classification

## Detect, never assume

The gate commands are a property of the repository, not of this skill. Resolution order:

1. **The project's own instructions.** `CLAUDE.md` / `AGENTS.md`, with the closest file winning on
   conflict. Gather them from the working directory upward **and** from each changed path upward —
   `git diff --name-only "$BASE_SHA"...HEAD` gives the paths. The upward-only walk is sufficient in a
   single-package repo and actively wrong in a monorepo: invoked at the root, it never sees
   `packages/foo/AGENTS.md`, so a PR confined to that package gets gated by root-level checks alone
   while the package's own mandated checks are skipped — and the branch is force-pushed on that
   basis. If they name a canonical command sequence, that sequence *is* the gate — do not add
   inferred steps around it.
2. **Manifests**, only when the instructions state nothing. See the table in `SKILL.md`.

Hardcoding `npm run lint && npm test` breaks on every non-JavaScript repository, and breaks on
JavaScript repositories that use `pnpm`, or that name the script `check` instead of `lint`. Read the
lockfile for the package manager and `package.json`'s `scripts` keys for the names that exist.

## Never chain the steps

Run each command as its own invocation:

```bash
uv run ruff check .
uv run ty check
uv run pytest
```

not

```bash
uv run ruff check . && uv run ty check && uv run pytest   # wrong
```

With `&&`, one flaky test aborts the chain and the build step never runs — and its absence looks
identical to a pass in the transcript. Separate invocations make each step's exit status observable,
which is also what makes the PRE-EXISTING / REGRESSION classification below possible: you need to
know *which* commands failed, not that *something* failed.

## Classify each failure once

A rebase moves the branch onto new base commits, so a red gate after a rebase has two very different
causes:

- **REGRESSION** — the rebase caused it: a conflict resolved slightly wrong, an API the base branch
  changed underneath the PR, a test that assumed the old base. Fix it, and amend the fix into the
  commit it belongs to so the rebased history stays coherent.
- **PRE-EXISTING** — the base branch fails the same way. Not this PR's problem, and not worth
  re-diagnosing on every rebase.

Classify with evidence, not intuition. On a clean worktree:

```bash
git switch --detach "$BASE_SHA"
<only the failing command>
git switch -
```

Same worktree, so installed dependencies and build caches are reused; detached, so no branch is
touched. If gitignored build artifacts make this unreliable, `git worktree add` a temporary checkout
of `$BASE_SHA` instead and run it there.

Record the outcome — command, exit status, one-line symptom — in the PR comment. That is what turns
"tests were red, I pushed anyway" into a reviewable claim.

## Known-failure lists belong to the repository

Verify a pre-existing failure **once per rebase**, not once per attempt. It is tempting to bake a
list of known-flaky suites into this skill, but such lists are repo-specific — a postinstall step
that needs a native toolchain, a test that needs a package linked from `dist/`, a watchdog with a
timing flake. They belong in that repository's own `CLAUDE.md` / `AGENTS.md`, where every skill and
every human reads them, and where they can be corrected when the flake is fixed. This skill reads
that note in Step 3 and honours it; it ships no list of its own.
