---
name: investigate
description: This skill should be used when the user asks to "investigate issue", "investigate #N", "fix issue #N", "fix bug #N", "debug issue", "look into issue", "triage issue", "reproduce and fix GitHub issue", "close issue #N", or invokes the /investigate command. Runs the full end-to-end workflow for a GitHub issue — resolves the issue number (from argument or branch context), classifies the issue as bug or feature, reproduces or designs as appropriate, fixes/implements, validates against the project's checks, commits, pushes, and opens a PR that auto-closes the issue.
argument-hint: "[issue-number]"
user-invocable: true
---

# Investigate — End-to-End GitHub Issue Workflow

Repo-agnostic workflow that takes a GitHub issue (bug **or** feature request) from
reported state to an open pull request that closes the issue. Discover project
conventions at runtime — assume no build commands, test runners, or languages.

Two execution modes:

- **Interactive** — ask the user (via AskUserQuestion) to resolve ambiguity.
- **Non-interactive** — running headlessly (`claude -p`, CI, automation). Never
  ask the user; on irreducible ambiguity, fail with a clear error rather than
  guess silently.

Treat "Can I reach the user right now?" as the deciding factor. If not, the run
is non-interactive — surface the blocker and exit.

## Bundled resources

The deterministic shell logic lives in `scripts/`; the design rationale lives in
`references/`. Invoke a script by its absolute path. When loaded as a plugin,
that path is `${CLAUDE_PLUGIN_ROOT}/investigate/scripts/<name>`; if
`${CLAUDE_PLUGIN_ROOT}` is unset (skill loaded standalone), resolve `scripts/`
relative to this SKILL.md. The examples below abbreviate the prefix as
`scripts/`.

- **`scripts/resolve-issue.sh`** — Phase 1 issue-number resolution.
- **`scripts/git-safety-lib.sh`** — shared remote/default-branch resolvers
  (sourced by the two scripts below; never run directly).
- **`scripts/check-branch.sh`** — Phase 5.0 branch-safety guard.
- **`scripts/push-branch.sh`** — Phase 6 upstream-aware push.
- **`references/issue-number-resolution.md`** — Phase 1 rules, edge cases, and
  the two invariants the resolver enforces.
- **`references/git-safety.md`** — how the guard and push resolve the same
  remote and the repo's default branch, and why.

## Phase 1 — Resolve the issue number

Run the resolver, passing the raw invocation argument (empty if none):

```bash
scripts/resolve-issue.sh "${ARGUMENTS:-}"
```

It accepts `123` or `#123`, else infers the number from the branch name, then
verifies the issue exists. Act on its exit code:

- **0** — stdout is the issue number. Record it and continue.
- **2** — no number could be resolved; stdout is the current branch name.
  - Interactive: ask via AskUserQuestion — "What is the GitHub issue number to
    investigate?"
  - Non-interactive: fail with exactly this message (substitute the branch):
    ```
    investigate: no issue number provided and cannot infer from branch '<BRANCH>'. Re-run with the issue number, e.g. /investigate 123.
    ```
- **1** — hard failure (an explicit issue does not exist, or `gh` could not reach
  GitHub). The script already printed the specific message to stderr; relay it
  and abort.

The resolver deliberately never discards an explicit `/investigate <N>` silently,
and only clears a branch-inferred guess on a confirmed "not found". See
`references/issue-number-resolution.md` for the extraction rules and the
`release/2.0-issue-123` / `dependabot/...` / `pr2024` / `hotfix-1.2.3` cases.

## Phase 2 — Fetch and classify the issue

Fetch the full issue:

```bash
gh issue view "$ISSUE" --json number,title,body,labels,state,comments
```

If the issue is already closed, stop and confirm the user wants to proceed before
continuing.

Classify as **bug** or **feature**, in order:

1. **Labels (strongest signal).** Bug: `bug`, `defect`, `regression`, `crash`.
   Feature: `enhancement`, `feature`, `feature-request`, `new feature`.
2. **Title/body keywords**, if no decisive label. Bug: "expected … actual",
   "reproduce", "repro", "crash", "panic", "error", "fails", "broken",
   "regression", stack traces, version numbers. Feature: "would be nice",
   "support for", "add", "implement", "proposal", "feature request", "RFC".
3. **Still ambiguous.** Interactive: ask which workflow to follow.
   Non-interactive: default to the **bug workflow** (reproduction is harmless and
   reveals more context) and print: "Classified as bug by fallback heuristic;
   verify before merging."

Record the classification and proceed to the matching workflow.

## Phase 3 — Discover project conventions

Read the project's own instructions for how to build, test, lint, and commit:

```bash
cat CLAUDE.md AGENTS.md 2>/dev/null
ls README* CONTRIBUTING*
```

Also infer the toolchain from manifests:

- `package.json` → npm/yarn/pnpm scripts (`test`, `lint`, `build`, `typecheck`).
- `Cargo.toml` → `cargo test`, `cargo clippy`, `cargo fmt --check`, `cargo build`.
- `pyproject.toml` / `setup.py` → `pytest`, `ruff`/`flake8`, `mypy`/`pyright`,
  plus `uv`/`hatch` if present.
- `go.mod` → `go test ./...`, `go vet`, `gofmt -l`, `go build ./...`.
- `Makefile` → `test`, `lint`, `check`, `ci` targets.
- `pom.xml` / `build.gradle` → `mvn test` / `./gradlew test`.

Record the discovered test, lint/format-check, type-check, and build commands for
the validation phase. Prefer a project's own canonical command sequence (from
`CLAUDE.md` / `AGENTS.md`) over the inferred defaults.

## Phase 4 — Workflow dispatch

### 4A. Bug workflow

**4A.1 Analyse.** From the issue body and comments, extract the reported vs.
expected behaviour, reproduction steps, inputs, environment notes, the affected
version, and likely subsystem(s) from file paths, error messages, or stack
traces.

**4A.2 Reproduce.** Build a *minimal* reproducer using the project's normal
commands. Confirm the bug manifests locally before changing anything — keep the
reproducer small and self-contained so it doubles as a regression test. If the
bug cannot be reproduced, document the gaps. Interactive: ask for clarification.
Non-interactive: comment on the issue describing what was tried and what failed,
then exit documenting the blocker.

**4A.3 Locate.** Use `grep`/`rg` for error strings, function names, and log
messages from the repro, then read the suspects. For non-trivial bugs (multiple
files, subtle root cause), delegate to `/pm-plan` with a focused prompt
describing the bug, the repro, and the symptom.

**4A.4 Plan the fix.** Write a concise numbered plan, each step citing `file:line`
targets and the change to make (or use the `/pm-plan` output). Convert the plan to
a task list with **TaskCreate** before executing — one task per reviewable unit.

**4A.5 Fix (best effort).** Apply the changes. When tests are the right vehicle,
prefer `/tdd`: write a failing test seeded from the 4A.2 reproducer, make it pass
with the smallest change, then refactor while green. Mark each task `in_progress`
when starting it and `completed` the moment it is done — do not batch updates. On
hitting a wall (mismatched assumptions, scope explosion, blocked by another bug),
surface it: interactive — ask how to proceed; non-interactive — comment on the
issue, leave the partial branch, exit. **Do not** open a half-finished PR.

**4A.6 Validate.** Run the discovered checks in order — format/format-check, lint,
type-check, tests, build — stopping and iterating on any failure. Loop until all
are green, then proceed to Phase 5.

### 4B. Feature workflow

**4B.1 Explore.** Map the parts of the codebase the feature touches. Read the
relevant modules, study existing patterns (naming, layering, error handling, test
style), and note the conventions to mirror. For non-trivial features (multiple
modules, new abstractions, data-model changes), delegate to `/pm-plan` and treat
its output as the master plan.

**4B.2 Resolve design questions.** For any genuinely ambiguous decision (data
model, API shape, UX, where the feature lives):

- Interactive: stress-test the design with the user. Use `/grill-with-docs` (or
  the simpler `/grill-me`) if available; otherwise list the open questions and
  resolve each via AskUserQuestion before writing code. Update the plan with the
  answers.
- Non-interactive: if the design is ambiguous, fail with exactly this message
  (substitute the issue number):
  ```
  investigate: feature request #<N> is ambiguous and cannot be designed non-interactively. Provide more details or run interactively.
  ```

If the request is concrete enough that no design choices remain open (e.g. "add a
`--quiet` flag that suppresses progress output"), proceed without a design pass.

**4B.3 Plan.** As in 4A.4 — concise `file:line` step list, converted to a
TaskCreate task list before execution (or the `/pm-plan` output).

**4B.4 Implement (best effort).** Follow the repo norms from 4B.1. Prefer `/tdd`
for testable behaviour. Mark tasks `in_progress`/`completed` as work progresses.
Same blocker rules as 4A.5 — surface (interactive) or comment and exit
(non-interactive); no half-finished PRs.

**4B.5 Validate.** As in 4A.6 — run the discovered checks in order; loop until
green.

## Phase 5 — Commit

### Step 5.0 — Branch safety guard

Before any `git add`, `git commit`, or `git push`, verify the worktree is on a
topic branch — never the repo's default branch (whatever its name) and never a
detached HEAD:

```bash
scripts/check-branch.sh
```

Act on its exit code:

- **0** — safe (topic branch, or the default branch could not be resolved but HEAD
  is not detached). Proceed to Step 5.1.
- **5** — refuse. stdout is the offending branch name (or `detached HEAD`).
  - Interactive: ask (AskUserQuestion) which topic branch to use. `git switch
    <name>` for an existing branch or `git switch -c <name>` for a new one, then
    re-run this guard.
  - Non-interactive: fail with exactly this message (substitute the stdout value)
    and exit without committing or pushing:
    ```
    investigate: refusing to commit/push from '<BRANCH-or-detached>'. Re-run on a topic branch (e.g. issue<N>) or pass the branch explicitly.
    ```

This guards the common case of `/investigate` being invoked while still on the
default branch after the last PR merged. The guard resolves the remote and
default branch through `scripts/git-safety-lib.sh` — the same resolvers Phase 6
uses to push, so the two cannot disagree. See `references/git-safety.md`.

### Step 5.1 — Commit

Study the repo's commit style and match it:

```bash
git log --oneline -20
```

Most projects use Conventional Commits (`fix: <desc> (#N)` / `feat: <desc> (#N)`)
or free-form (`Fix <desc> (#N)` / `Add <desc> (#N)`). Whatever the style, the
subject **must reference the issue** with `(#N)`. Add a one-line body on *why*,
not *what*, when useful.

**Authorship rule.** Check the active git identity:

```bash
git config user.email
```

If it is `pmatos@igalia.com`, commit messages and PR bodies **must not** mention
Claude, AI, "co-authored-by Claude", or generation tooling. (This rule lives in
the user's global CLAUDE.md and supersedes default behaviour.)

Stage only the changed files (avoid `git add -A`), then commit:

```bash
git add <files>
git commit -m "<message>"
```

If a pre-commit hook fails, fix the underlying issue and create a **new** commit —
never `--no-verify`, never `--amend` over a failed hook.

## Phase 6 — Push and open the PR

Push the branch, honoring any existing upstream instead of hardcoding `origin`:

```bash
scripts/push-branch.sh
```

It first-pushes with `-u` on the remote resolved by `git-safety-lib.sh`, or does a
bare `git push` if the branch already has an upstream. This matters for fork
workflows and repos whose only remote is not `origin`. See `references/git-safety.md`.

Open a PR with `gh pr create`. The body **must** contain a closing keyword so
GitHub auto-closes the issue on merge — `Closes #N`, `Fixes #N` (preferred for
bugs), or `Resolves #N`. Invoke via HEREDOC to preserve formatting:

```bash
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary

- <1–3 bullets on what changed and why>

Fixes #<N>

## Test plan

- [ ] <discovered test command> — all passing
- [ ] <discovered lint command> — clean
- [ ] <discovered type-check command> — clean
- [ ] Manual repro confirms the bug is fixed   (bug workflow only)
- [ ] New regression test added                (bug workflow only)
EOF
)"
```

Mirror the commit subject in the PR title (minus the `(#N)` suffix — GitHub adds
the PR number). Return the PR URL to the user.

## Phase 7 — Post-PR

1. Post a friendly pointer on the issue (GitHub also links it via the closing
   keyword):
   ```bash
   gh issue comment "$ISSUE" --body "Opened PR <URL> to address this. Will auto-close on merge."
   ```
2. Do **not** close the issue manually — let the merged PR close it via the
   keyword, so a rejected PR leaves the issue open without intervention.
3. Report the PR URL and the test-plan checklist to the user.

## Supporting skills

Use if available in the active session; otherwise fall back to the per-step
alternative:

- **`/pm-plan`** — deep, multi-phase planning for non-trivial bugs or features.
  Fallback: write the plan directly with TaskCreate.
- **`/grill-with-docs`** (or `/grill-me`) — interactive design stress-test for
  ambiguous feature decisions. Fallback: a short AskUserQuestion-driven design
  pass before implementation.
- **`/tdd`** — red-green-refactor loop when tests are the right vehicle.
  Fallback: write the test, then the implementation, manually.

## Failure modes (quick reference)

Each row points to the phase that owns the exact behaviour and message — no
message is duplicated here, to keep the single source of truth in one place.

| Situation | Handled in |
|-----------|------------|
| No issue number; branch unparseable | Phase 1, exit 2 |
| Explicit issue does not exist, or `gh` unreachable | Phase 1, exit 1 (message from `resolve-issue.sh`) |
| Issue already closed | Phase 2 — stop and confirm |
| Bug cannot be reproduced | Phase 4A.2 — ask, or comment on the issue and exit |
| Feature ambiguous, non-interactive | Phase 4B.2 |
| On the default branch or detached HEAD | Phase 5.0, exit 5 |
| Pre-commit hook fails | Phase 5.1 — fix and re-commit; never `--no-verify` |
| Validation cannot be made green | Phase 4A.6 / 4B.5 — surface or comment and exit; do not open the PR |
