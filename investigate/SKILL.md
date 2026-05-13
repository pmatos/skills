---
name: investigate
description: This skill should be used when the user asks to "investigate issue", "investigate #N", "fix issue #N", "fix bug #N", "debug issue", "look into issue", "triage issue", "reproduce and fix GitHub issue", "close issue #N", or invokes the /investigate command. Runs the full end-to-end workflow for a GitHub issue — resolves the issue number (from argument or branch context), classifies the issue as bug or feature, reproduces or designs as appropriate, fixes/implements, validates against the project's checks, commits, pushes, and opens a PR that auto-closes the issue.
argument-hint: "[issue-number]"
user-invocable: true
---

# Investigate — End-to-End GitHub Issue Workflow

Repo-agnostic workflow that takes a GitHub issue (bug **or** feature request) from reported state to an open pull request that closes the issue. The skill discovers project conventions at runtime — there are no hardcoded build commands, test runners, or language assumptions.

Two execution modes:

- **Interactive** — Claude may ask the user (via AskUserQuestion) to resolve ambiguity.
- **Non-interactive** — when running headlessly (e.g. `claude -p`, CI, automation). The skill **must not** ask the user. If irreducible ambiguity is encountered, fail with a clear error message rather than guess silently.

Treat "Can I reach the user right now?" as the deciding factor. If you cannot, you are non-interactive — surface the blocker and exit.

---

## Phase 1 — Resolve the Issue Number

Set `$ARGUMENTS` from the invocation. Strip an optional leading `#` (the description advertises triggers like `investigate #N`, so users may pass `#123` as well as `123`). If the result parses as a positive integer, that is the issue number — and **remember that it came from explicit user input** (used later to decide whether a `gh issue view` failure should abort vs. retry):

```bash
ARG="${ARGUMENTS:-}"
ARG="${ARG#\#}"   # accept "#123" as well as "123"
ISSUE=""
ISSUE_SOURCE=""   # "argument" | "branch" | "" (none)
if [[ "$ARG" =~ ^[0-9]+$ ]]; then
  ISSUE="$ARG"
  ISSUE_SOURCE="argument"
fi
```

If `$ISSUE` is empty, **try to infer** from the current branch name. Match against common patterns (case-insensitive) — but only if the integer is **unambiguously** the issue number. Branches like `release/2.0-issue-123` or `dependabot/npm/foo-1.2.3` contain version numbers that must not be misread as issue references.

Rule (apply in order, stop at the first match):

1. **Named-slot match** — the branch contains an explicit issue keyword followed by an integer. Recognised keywords: `issue`, `gh`, `fix`, `bugfix`, `bug`, `feature`, `feat`, with an optional `-`, `_`, or `/` separator. Examples:

   | Branch pattern                              | Extracted integer |
   |---------------------------------------------|-------------------|
   | `issue123`, `issue-123`, `issue/123`        | `123` |
   | `gh-123`, `gh/123`                          | `123` |
   | `fix-123`, `fix/123`, `bug-123`, `bugfix-123` | `123` |
   | `feature-123`, `feat-123`, `feature/123`    | `123` |

   The named keyword anchors the extraction so other integers in the branch (semver components, dates, dependency versions) are ignored.

2. **Single-obvious-integer fallback** — only if rule 1 found nothing. Accept the integer **only when both** of these hold:

   - exactly one integer is present in the entire branch name, and
   - that integer sits on a path-segment boundary (start of branch, or after `-` / `_` / `/`, and either at end of branch or before `-` / `_` / `/`).

   The boundary requirement rejects branches like `pr2024`, where the integer is glued to leading letters — without it, a coincidentally-real issue #2024 would be picked up silently because `gh issue view` only validates existence, not provenance. If the branch contains zero or more than one integer, or the lone integer is not boundary-anchored, this rule does not match and `$ISSUE` stays empty.

Implementation:

```bash
BRANCH="$(git branch --show-current)"
if [[ -z "$ISSUE" ]]; then
  LBRANCH="$(printf '%s' "$BRANCH" | tr '[:upper:]' '[:lower:]')"
  # Rule 1: named-slot keyword followed by an integer.
  # Anchor the keyword to the start of the branch or to a path separator
  # (-, _, /) so names like `hotfix-1.2.3` or `prefix-123` cannot match the
  # `fix` alternative inside the word and silently extract a version digit.
  if [[ "$LBRANCH" =~ (^|[-/_])(issue|gh|fix|bugfix|bug|feature|feat)[-/_]?([0-9]+) ]]; then
    ISSUE="${BASH_REMATCH[3]}"
    ISSUE_SOURCE="branch"
  else
    # Rule 2: fall back only if the branch contains exactly one integer AND
    # that integer sits on a path-segment boundary (start of branch, after
    # `-` / `_` / `/`, and either at end or before `-` / `_` / `/`).
    # The boundary check rejects branches like `pr2024` where the integer
    # is glued to leading/trailing letters — otherwise `gh issue view`
    # would accept any coincidentally-real issue number with that value.
    NUMS="$(printf '%s' "$BRANCH" | grep -oE '[0-9]+')"
    if [[ "$(printf '%s\n' "$NUMS" | grep -c .)" == "1" ]] \
        && [[ "$BRANCH" =~ (^|[-/_])"$NUMS"([-/_]|$) ]]; then
      ISSUE="$NUMS"
      ISSUE_SOURCE="branch"
    fi
  fi
fi
```

Then verify the candidate exists as a real issue before committing to it. Be careful here: `gh issue view` exits nonzero for **two very different** reasons — "issue does not exist" and "I could not reach GitHub" (missing auth, network failure, rate limit, API error). Treating both the same way silently nukes an explicitly-passed `/investigate 123` and surfaces a misleading "no issue number" message when the real blocker is `gh`. Distinguish them:

```bash
if [[ -n "$ISSUE" ]]; then
  GH_ERR="$(gh issue view "$ISSUE" --json number 2>&1 >/dev/null)"
  GH_EXIT=$?
  if (( GH_EXIT != 0 )); then
    if printf '%s' "$GH_ERR" | grep -qE 'Could not resolve|Not Found|HTTP 404'; then
      # Truly does not exist.
      if [[ "$ISSUE_SOURCE" == "argument" ]]; then
        echo "investigate: issue #$ISSUE does not exist in this repo." >&2
        exit 1
      else
        ISSUE=""           # only ever silently clear a branch-inferred guess
        ISSUE_SOURCE=""
      fi
    else
      # Auth / network / API failure — surface and abort regardless of source.
      echo "investigate: 'gh issue view $ISSUE' failed: $GH_ERR" >&2
      exit 1
    fi
  fi
fi
```

Two invariants this enforces:

- An explicit `/investigate <N>` is never silently discarded. If GitHub disagrees (issue doesn't exist), the skill says so directly; if the disagreement is `gh`'s fault (auth/network/etc.), the skill surfaces that error.
- A branch-inferred guess is only cleared on a confirmed "not found"; any other failure aborts so the user sees the real problem.

Branches with ambiguous numbering (e.g. `release/2.0-issue-123`) hit rule 1 via the `issue` keyword (preceded by `-`) and resolve to `123`. Branches like `dependabot/npm/foo-1.2.3` match no named slot and contain three integers, so rule 2 also fails — the skill falls through to AskUserQuestion (interactive) or the non-interactive failure message. The leading `(^|[-/_])` boundary on rule 1 also keeps names like `hotfix-1.2.3` from matching `fix` inside the keyword `hotfix` and silently extracting `1`. And the path-segment boundary requirement on rule 2 keeps names like `pr2024` from being misread as issue `2024` just because `gh issue view` happens to find a real issue with that number. This is the documented "single obvious integer" guarantee.

If `$ISSUE` is still empty:

- **Interactive**: ask the user via AskUserQuestion: "What is the GitHub issue number to investigate?"
- **Non-interactive**: fail with exactly this message:
  ```
  investigate: no issue number provided and cannot infer from branch '<BRANCH>'. Re-run with the issue number, e.g. /investigate 123.
  ```

Record `ISSUE` for later phases.

---

## Phase 2 — Fetch and Classify the Issue

Fetch the issue with:

```bash
gh issue view "$ISSUE" --json number,title,body,labels,state,comments
```

If the issue is already closed, stop and report this to the user — confirm they want to proceed before continuing.

Classify the issue as **bug** or **feature** using these heuristics, in order:

1. **Labels (strongest signal)** — if the issue carries any of these labels, the verdict is decided:
   - Bug: `bug`, `defect`, `regression`, `crash`
   - Feature: `enhancement`, `feature`, `feature-request`, `new feature`
2. **Title/body keywords** — if no decisive label:
   - Bug indicators: "expected ... actual", "reproduce", "repro", "crash", "panic", "error", "fails", "broken", "regression", stack traces, version numbers ("seen in v1.2.3").
   - Feature indicators: "would be nice", "support for", "add", "implement", "proposal", "feature request", "RFC".
3. **Still ambiguous**:
   - Interactive: ask the user which workflow to follow.
   - Non-interactive: default to the **bug workflow** (more conservative — reproduction step is harmless and reveals more context). Print a note: "Classified as bug by fallback heuristic; verify before merging."

Record the classification and proceed to the matching workflow.

---

## Phase 3 — Discover Project Conventions

Before doing real work, read the project's own instructions for how to build, test, lint, and commit. Check these in order and use whichever exist:

```bash
cat CLAUDE.md AGENTS.md 2>/dev/null
ls README* CONTRIBUTING*
```

Also infer toolchain from manifests:

- `package.json` → npm/yarn/pnpm scripts (`test`, `lint`, `build`, `typecheck`).
- `Cargo.toml` → `cargo test`, `cargo clippy`, `cargo fmt --check`, `cargo build`.
- `pyproject.toml` / `setup.py` → `pytest`, `ruff`/`flake8`, `mypy`/`pyright`, plus `uv`/`hatch` if present.
- `go.mod` → `go test ./...`, `go vet`, `gofmt -l`, `go build ./...`.
- `Makefile` → look for `test`, `lint`, `check`, `ci` targets.
- `pom.xml` / `build.gradle` → `mvn test` / `./gradlew test`.

Record the **discovered commands** (test, lint/format-check, type-check, build) — you will run them in the validation phase. If a project specifies its own canonical command sequence in `CLAUDE.md` / `AGENTS.md`, **prefer that over the inferred defaults**.

---

## Phase 4 — Workflow Dispatch

Run the matching workflow.

### 4A. Bug Workflow

#### Step 4A.1 — Analyse

From the issue body and comments, extract:
- Reported behaviour (symptom) and expected behaviour.
- Reproduction steps, code snippets, inputs, environment notes.
- Affected version (if mentioned).
- Likely subsystem(s) based on file paths, error messages, or stack traces.

#### Step 4A.2 — Reproduce

Build a *minimal* reproducer. Use the project's normal commands discovered in Phase 3. Confirm the bug manifests locally before changing anything.

- Keep the reproducer small and self-contained — it doubles as a regression test.
- If the bug cannot be reproduced, document the gaps (missing env, version skew, unclear steps) and:
  - Interactive: ask the user for clarification on AskUserQuestion.
  - Non-interactive: post a comment on the issue describing what was tried and what failed, then exit with status documenting the blocker.

#### Step 4A.3 — Locate

Identify the files most likely involved. Use `grep`/`rg` for error strings, function names, log messages from the repro. Read the suspects.

For non-trivial bugs (multiple files, subtle root cause, anything where you'd benefit from a structured analysis), delegate to `/pm-plan` with a focused prompt describing the bug, the repro, and the symptom — `/pm-plan` produces a file-path-grounded fix plan you can execute.

#### Step 4A.4 — Plan the Fix

Write a concise plan: numbered steps, each citing `file:line` targets and the change to make. If `/pm-plan` was used, this is its output.

Convert the plan to a task list with **TaskCreate** before executing (see global rule on task management). One task per reviewable unit of change.

#### Step 4A.5 — Fix (best effort)

Apply the changes. When tests are the right vehicle for the fix, prefer the `/tdd` workflow:

1. Write a failing test that captures the bug (using the Phase 4A.2 reproducer as the seed).
2. Make it pass with the smallest change that works.
3. Refactor if needed, keeping the test green.

Mark tasks `in_progress` when you start them and `completed` as soon as each is done — do not batch updates.

If you hit a wall (mismatched assumptions, unfixable without scope expansion, blocked by another bug), surface it:
- Interactive: ask the user how to proceed.
- Non-interactive: post a comment on the issue describing the blocker, leave the partial branch as-is, and exit with a clear message. **Do not** open a half-finished PR.

#### Step 4A.6 — Validate

Run the project's checks in order. Stop and iterate on any failure:

1. Format / format-check.
2. Lint.
3. Type-check.
4. Tests.
5. Build (if separate from tests).

Use the exact commands discovered in Phase 3. Loop until all are green. Then proceed to Phase 5.

### 4B. Feature Workflow

#### Step 4B.1 — Explore

Map the parts of the codebase the feature touches. Read the relevant modules, study existing patterns (naming, layering, error handling, test style), and note the conventions to mirror.

For non-trivial features (touches multiple modules, introduces new abstractions, requires data-model changes), delegate to `/pm-plan` with the feature description from the issue. Treat its output as the master plan.

#### Step 4B.2 — Resolve Design Questions

A feature request often leaves design space open. For any genuinely ambiguous decision (data model, API shape, UX, where the feature lives):

- **Interactive**: stress-test the design with the user. Use `/grill-with-docs` (or the simpler `/grill-me`) if either skill is available in the active session — it walks through ADRs, the project's existing vocabulary, and the decision branches. If neither sibling skill is available (e.g. the skill is installed standalone), fall back to a short interactive design pass: list the open questions, then use AskUserQuestion to resolve each one with the user before writing code. Update the plan with the answers either way.
- **Non-interactive**: if the design is ambiguous, fail with exactly this message:
  ```
  investigate: feature request #<N> is ambiguous and cannot be designed non-interactively. Provide more details or run interactively.
  ```
  Replace `<N>` with the issue number. Do not guess.

If the request is concrete enough that no design choices remain open (e.g. "add a `--quiet` flag that suppresses progress output"), proceed without a design pass.

#### Step 4B.3 — Plan

Same as 4A.4 — concise step list with `file:line` targets, converted to a TaskCreate task list before execution. If `/pm-plan` ran in 4B.1, use its plan.

#### Step 4B.4 — Implement (best effort)

Follow repo norms learned in 4B.1. Where new behaviour is testable, prefer `/tdd`:

1. Write a failing test describing the new behaviour.
2. Make it pass.
3. Refactor.

Mark tasks `in_progress`/`completed` as you go.

Same blocker rules as 4A.5: surface to the user (interactive) or comment on the issue and exit cleanly (non-interactive). No half-finished PRs.

#### Step 4B.5 — Validate

Same as 4A.6 — run the discovered format / lint / type-check / test / build commands in order. Loop until green.

---

## Phase 5 — Commit

### Step 5.0 — Branch safety guard

**Before any `git add`, `git commit`, or `git push`,** verify the worktree is on a topic branch — never on the repo's default branch (whatever its name) and never in detached HEAD. The guard and Phase 6's push **must** agree on which remote is canonical — otherwise the guard can pass on local `main` against remote A's default while Phase 6 then pushes to remote B, defeating the protection. Define the resolver once here and reuse it verbatim in Phase 6:

```bash
BRANCH="$(git branch --show-current)"

# resolve_push_remote: pick the remote Phase 6 will push to.
# Tried in order; first non-empty wins:
#   1. the branch's existing upstream (set by a prior `git push -u`)
#   2. branch.<name>.remote in git config
#   3. `git remote | head -1` — the alphabetically-first configured remote.
#      Deterministic only when there is exactly one remote (the common
#      fork-only case, e.g. only `upstream`); on multi-remote checkouts it
#      picks whatever sorts first, which may or may not be the one the user
#      intends. We use it as a best-effort guess.
#   4. literal "origin" (final fallback when `git remote` is empty)
resolve_push_remote() {
  local branch="$1" upstream remote
  if upstream=$(git rev-parse --abbrev-ref --symbolic-full-name "$branch"@{u} 2>/dev/null) \
       && [[ -n "$upstream" ]]; then
    printf '%s' "${upstream%%/*}"; return
  fi
  if remote=$(git config --get "branch.$branch.remote" 2>/dev/null) && [[ -n "$remote" ]]; then
    printf '%s' "$remote"; return
  fi
  if remote=$(git remote | head -1) && [[ -n "$remote" ]]; then
    printf '%s' "$remote"; return
  fi
  printf '%s' "origin"
}

REMOTE="$(resolve_push_remote "$BRANCH")"

# Resolve the default branch on that remote.
# 1. Local symref: refs/remotes/<remote>/HEAD — present after `git clone`, but
#    *missing* after `git remote add` + manual fetch unless the user ran
#    `git remote set-head` afterwards.
# 2. Remote-aware: `gh repo view --json defaultBranchRef`. This is the
#    authoritative source for a GitHub repo and handles the `trunk`/`develop`
#    case when the local symref is absent. Tolerates `gh` not being
#    authenticated by quietly returning empty.
# 3. Local heuristic: `main` or `master` if they exist as heads. This is
#    a last resort and intentionally does NOT include `trunk`/`develop` —
#    if the user has those locally but no remote signal, treat the default
#    as unresolved rather than guess.
DEFAULT_BRANCH=$(git symbolic-ref "refs/remotes/$REMOTE/HEAD" 2>/dev/null \
  | sed "s|refs/remotes/$REMOTE/||")
if [[ -z "$DEFAULT_BRANCH" ]]; then
  # gh repo view with no argument resolves to the current directory's repo
  # (typically origin), which may not match $REMOTE in fork-style checkouts.
  # Derive owner/repo from $REMOTE's URL so gh queries the same repo Phase 6
  # will push to. Handles the common URL forms:
  #   git@github.com:OWNER/REPO[.git]
  #   https://github.com/OWNER/REPO[.git]
  #   ssh://git@github.com/OWNER/REPO[.git]
  REMOTE_URL=$(git remote get-url "$REMOTE" 2>/dev/null)
  if [[ -n "$REMOTE_URL" ]]; then
    REMOTE_REPO=$(printf '%s' "$REMOTE_URL" | sed -E \
      -e 's|^git@[^:]+:||' \
      -e 's|^ssh://[^@]+@[^/]+/||' \
      -e 's|^https?://[^/]+/||' \
      -e 's|\.git/*$||')
    DEFAULT_BRANCH=$(gh repo view "$REMOTE_REPO" --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null)
  fi
fi
if [[ -z "$DEFAULT_BRANCH" ]]; then
  if git show-ref --verify --quiet refs/heads/main 2>/dev/null; then
    DEFAULT_BRANCH=main
  elif git show-ref --verify --quiet refs/heads/master 2>/dev/null; then
    DEFAULT_BRANCH=master
  fi
fi

if [[ -z "$BRANCH" || ( -n "$DEFAULT_BRANCH" && "$BRANCH" == "$DEFAULT_BRANCH" ) ]]; then
  # Refuse to commit/push from the default branch or detached HEAD.
  : # see action table below
fi
```

If `$DEFAULT_BRANCH` cannot be resolved at all (no `<remote>/HEAD`, no `gh` answer, no local `main`/`master`), still refuse detached HEAD but allow other branches through — there is no reliable default to compare against, and forcing the user to set one would block legitimate first-commit scenarios.

Action:

- **Interactive**: ask the user (AskUserQuestion) which topic branch to use. If they name an existing branch, `git switch <name>`; if they name a new one, `git switch -c <name>`. Then re-enter Phase 5 on the new branch.
- **Non-interactive**: fail with exactly this message and exit without committing or pushing:
  ```
  investigate: refusing to commit/push from '<BRANCH-or-detached>'. Re-run on a topic branch (e.g. issue<N>) or pass the branch explicitly.
  ```

This guard protects against the common case of `/investigate` being invoked while the user is still on the default branch (`main`, `master`, `trunk`, `develop`, or whatever the repo uses) after the last PR merged — without it, Phases 5 and 6 would commit and push straight to the default branch.

### Step 5.1 — Commit

Study the repo's existing commit style:

```bash
git log --oneline -20
```

Match it. Most projects use one of:
- Conventional Commits: `fix: <desc> (#N)` / `feat: <desc> (#N)`.
- Free-form: `Fix <desc> (#N)` / `Add <desc> (#N)`.

Whatever the style, the commit subject **must reference the issue** with `(#N)` so the link is visible in `git log`.

Commit body (optional but recommended): one short paragraph on *why*, not *what*.

**Authorship rule:** Under `pmatos@igalia.com`, commit messages and PR bodies **must not** mention Claude, AI, "co-authored-by Claude", or generation tooling. Check the active git identity:

```bash
git config user.email
```

If it matches `pmatos@igalia.com`, omit any such attribution. (This rule lives in the user's global CLAUDE.md and supersedes default behaviour.)

Stage only the files you changed (avoid `git add -A`):

```bash
git add <files>
git commit -m "<message>"
```

If a pre-commit hook fails, fix the underlying issue and create a **new** commit — never use `--no-verify`, never `--amend` over a failed hook.

---

## Phase 6 — Push and Open the PR

Push the branch — respect the branch's existing upstream / configured push remote rather than hardcoding `origin`. This matters for fork workflows (where the branch may already track `upstream` or a fork-named remote) and for repos whose only remote isn't `origin`. **Use the same `resolve_push_remote` from Step 5.0** so the guard and the push always pick the same remote:

```bash
# Resolver returns the right remote in both cases (existing upstream OR first
# push). We only need a second piece of info: is the branch's upstream already
# configured? `branch.<name>.merge` is set iff the branch has an upstream, so
# checking that config key is a cheap, parse-free proxy and avoids re-running
# the same `@{u}` lookup the resolver already did internally.
REMOTE="$(resolve_push_remote "$BRANCH")"
if git config --get "branch.$BRANCH.merge" >/dev/null 2>&1; then
  # Upstream already configured — bare push uses the existing tracking, no -u.
  git push
else
  # First push of this branch — set the upstream explicitly via -u.
  git push -u "$REMOTE" "$BRANCH"
fi
```

Never hardcode `git push -u origin HEAD` — `-u` overrides any existing upstream, so if the branch already tracks a different remote the push silently moves the upstream pointer to `origin`. And never use a different resolver from Step 5.0; the two must stay in lockstep so the default-branch guard cannot pass against remote A while the push lands on remote B.

Open a PR with `gh pr create`. The PR body **must** contain a closing keyword so GitHub auto-closes the issue when the PR merges — use one of:

- `Closes #N`
- `Fixes #N` (preferred for bugs)
- `Resolves #N`

Suggested PR body template:

```markdown
## Summary

<1–3 bullets on what changed and why>

Fixes #<N>

## Test plan

- [ ] <discovered test command> — all passing
- [ ] <discovered lint command> — clean
- [ ] <discovered type-check command> — clean
- [ ] Manual repro confirms the bug is fixed   (bug workflow only)
- [ ] New regression test added                (bug workflow only)
```

Invoke via HEREDOC to preserve formatting:

```bash
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary

- ...

Fixes #<N>

## Test plan

- [ ] ...
EOF
)"
```

The PR title should mirror the commit subject (minus the `(#N)` suffix — GitHub adds the PR number itself).

Return the PR URL to the user.

---

## Phase 7 — Post-PR

After the PR is open:

1. Post a brief comment on the **issue** linking to the PR (GitHub does this automatically via the closing keyword, but an explicit pointer is friendlier):
   ```bash
   gh issue comment "$ISSUE" --body "Opened PR <URL> to address this. Will auto-close on merge."
   ```
2. Do **not** close the issue manually — let the PR merge close it via the keyword. If the PR is rejected later, the issue remains open without manual intervention.
3. Report the PR URL and the test-plan checklist back to the user.

---

## Key Rules (Summary)

- **Repo-agnostic**: discover commands at runtime from `CLAUDE.md`, `AGENTS.md`, README, and manifests. No hardcoded build steps.
- **Interactive vs non-interactive**: ask the user when interactive; fail with a clear message when not. Never guess silently on irreducible ambiguity.
- **Task tracking**: every plan becomes a TaskCreate task list before execution. Mark tasks as you progress.
- **Best effort, surface blockers**: if you cannot fix it, say so explicitly — do not open a half-finished PR.
- **Closing keyword**: every PR body has `Fixes #N` / `Closes #N`.
- **Authorship**: under `pmatos@igalia.com`, no mention of Claude/AI in commits or PR bodies.
- **Pre-commit hooks**: fix the underlying issue and create a new commit; never `--no-verify`.
- **Supporting skills** (use if available in the active session; otherwise fall back to the per-step alternative):
  - `/pm-plan` — deep, multi-phase planning for non-trivial bugs or features. Fallback: write the plan yourself with TaskCreate.
  - `/grill-with-docs` (or `/grill-me`) — interactive design stress-test for ambiguous feature decisions. Fallback: short AskUserQuestion-driven design pass before implementation.
  - `/tdd` — red-green-refactor loop when tests are the right vehicle. Fallback: write the test, then the implementation, manually.

## Failure Modes (Quick Reference)

| Situation                                                                 | Action                                                                                                  |
|---------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| No issue number, non-interactive, branch unparseable                      | Exit: `investigate: no issue number provided and cannot infer from branch '<name>'. Re-run with the issue number, e.g. /investigate 123.` |
| Issue already closed                                                       | Stop and confirm with user (or note loudly in non-interactive) before continuing.                       |
| Bug cannot be reproduced                                                   | Interactive: ask. Non-interactive: comment on the issue with what was tried and exit.                   |
| Feature is ambiguous, non-interactive                                      | Exit: `investigate: feature request #<N> is ambiguous and cannot be designed non-interactively. Provide more details or run interactively.` |
| Pre-commit hook fails                                                      | Fix the underlying issue; create a new commit. Never `--no-verify`.                                     |
| On the repo's default branch (resolved by `<remote>/HEAD` → `gh repo view` → local `main`/`master`; remote chosen by `resolve_push_remote`: upstream → `branch.<name>.remote` → first remote → `origin`) or detached HEAD at Phase 5 | Interactive: ask which topic branch to switch to. Non-interactive: exit with `investigate: refusing to commit/push from '<BRANCH-or-detached>'. Re-run on a topic branch (e.g. issue<N>) or pass the branch explicitly.` |
| Validation (tests/lint/etc.) cannot be made green within reasonable effort | Surface to user (interactive) or comment on the issue + exit (non-interactive). Do not open the PR.     |
