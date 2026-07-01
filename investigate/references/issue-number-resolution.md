# Issue-Number Resolution — Rules and Rationale

Detailed reference for Phase 1 of the investigate skill. The deterministic logic
lives in `scripts/resolve-issue.sh`; this file explains *why* it is shaped the
way it is. Read it when modifying the resolver or debugging a misresolved issue
number.

## Inputs

`resolve-issue.sh [raw-argument]` resolves an issue number from, in priority
order:

1. The explicit argument (with an optional leading `#` stripped, so `#123` and
   `123` both work). A positive integer here is authoritative and its source is
   recorded as `argument`.
2. The current branch name, if the argument did not yield a number.

The **source** (`argument` vs `branch`) matters later: it decides whether a
`gh issue view` "not found" aborts loudly or is silently discarded.

## Branch inference

Two rules, applied in order, stopping at the first match. Both operate so that
version numbers, dates, and dependency versions embedded in branch names are
never misread as issue references.

### Rule 1 — named-slot match

The branch contains an explicit issue keyword, anchored to a path boundary,
followed by an integer. Recognised keywords: `issue`, `gh`, `fix`, `bugfix`,
`bug`, `feature`, `feat`, with an optional `-`, `_`, or `/` separator.

| Branch pattern                                | Extracted integer |
|-----------------------------------------------|-------------------|
| `issue123`, `issue-123`, `issue/123`          | `123` |
| `gh-123`, `gh/123`                            | `123` |
| `fix-123`, `fix/123`, `bug-123`, `bugfix-123` | `123` |
| `feature-123`, `feat-123`, `feature/123`      | `123` |

The named keyword anchors the extraction so other integers in the branch
(semver components, dates, dependency versions) are ignored.

The regex is `(^|[-/_])(issue|gh|fix|bugfix|bug|feature|feat)[-/_]?([0-9]+)`.
The leading `(^|[-/_])` boundary is load-bearing: without it, a name like
`hotfix-1.2.3` would match the `fix` alternative *inside* the word `hotfix` and
silently extract the version digit `1`. Anchoring the keyword to the start of the
branch or a `-` / `_` / `/` separator prevents that.

### Rule 2 — single-obvious-integer fallback

Only if Rule 1 found nothing. Accept the integer **only when both** hold:

- exactly one integer is present in the entire branch name, and
- that integer sits on a path-segment boundary (start of branch, or after
  `-` / `_` / `/`, and either at end of branch or before `-` / `_` / `/`).

The boundary requirement rejects branches like `pr2024`, where the integer is
glued to leading letters. Without it, a coincidentally-real issue #2024 would be
picked up silently, because `gh issue view` validates only existence, not
provenance. If the branch contains zero or more than one integer, or the lone
integer is not boundary-anchored, Rule 2 does not match and the number stays
unresolved.

## Existence check and the two-failure-modes problem

Once a candidate number exists, it is verified with `gh issue view`. That command
exits nonzero for **two very different** reasons, and conflating them is a bug:

- **Issue does not exist** — `Could not resolve`, `Not Found`, or `HTTP 404` in
  stderr.
- **Could not reach GitHub** — missing auth, network failure, rate limit, other
  API error.

Treating both the same way would silently nuke an explicitly-passed
`/investigate 123` and surface a misleading "no issue number" message when the
real blocker is `gh`. The script captures stderr (`2>&1 >/dev/null` sends the
JSON to `/dev/null` and keeps stderr) and greps for the not-found signatures to
distinguish them.

## Two invariants the script enforces

- **An explicit `/investigate <N>` is never silently discarded.** If GitHub says
  the issue does not exist, the script aborts with
  `investigate: issue #<N> does not exist in this repo.` (exit 1). If the
  disagreement is `gh`'s fault (auth/network/etc.), it aborts with
  `investigate: 'gh issue view <N>' failed: <error>` (exit 1).
- **A branch-inferred guess is only cleared on a confirmed "not found".** Any
  other `gh` failure aborts (exit 1) so the user sees the real problem instead of
  a wrong "no issue number" message.

When no number can be resolved at all, the script exits 2 and prints the branch
name, leaving the caller to decide: ask the user (interactive) or emit the
non-interactive "no issue number" failure.

## Worked examples

| Branch                         | Outcome                                                                 |
|--------------------------------|-------------------------------------------------------------------------|
| `release/2.0-issue-123`        | Rule 1 via `-issue-123` → `123`. The `2.0` is ignored.                  |
| `dependabot/npm/foo-1.2.3`     | No named slot; three integers → Rule 2 fails → exit 2 (ask / fail).     |
| `hotfix-1.2.3`                 | `fix` inside `hotfix` is not boundary-anchored → Rule 1 fails; three integers → Rule 2 fails → exit 2. |
| `pr2024`                       | No keyword; one integer but glued to `pr` (not boundary) → Rule 2 fails → exit 2. |
| `issue-123`                    | Rule 1 → `123`.                                                          |
| `bugfix-123`                   | Rule 1 (`bugfix` is an explicit keyword) → `123`.                        |
