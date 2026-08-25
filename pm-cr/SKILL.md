---
name: pm-cr
description: This skill should be used when the user asks to "code review this", "review this PR", "review the diff", "review my changes", "review at high effort", "review with fixes", or wants the changed code reviewed for correctness bugs and reuse/simplification/efficiency/altitude/conventions cleanups at a given effort level (low/medium/high/xhigh/max/ultra), optionally applying fixes (--fix) or posting inline PR comments (--comment). Also triggered by the /pm-cr command.
argument-hint: "[low|medium|high|xhigh|max|ultra] [--fix] [--comment] [<pr#>|<branch>|<path>]"
user-invocable: true
---

# Code Review

Review the current diff, or a PR number/branch/path target, for correctness
bugs and reuse/simplification/efficiency/altitude/conventions cleanups at a
given effort level. Low and medium favor fewer, high-confidence findings;
high through max favor broader coverage and may include less-certain
findings. This is a bug hunt *and* a cleanup pass, unlike `pm-simplify`
(cleanup only) — run that instead if you only want the quality pass.

## Task

$ARGUMENTS

## Phase 0 — Parse arguments

From the task arguments above, extract:

- **Flags**: `--fix`, `--comment`, `--post`, `--no-post` (order-independent,
  can appear anywhere in the arguments).
- **Effort level**: if the first remaining token case-insensitively matches
  (or is an unambiguous prefix of) `low`, `medium`, `high`, `xhigh`, `max`,
  or `ultra`, treat it as the explicit level and consume it. Otherwise no
  explicit level was given — resolve it per **Effort persistence** in
  `references/output-and-flags.md`.
- **Target**: whatever tokens remain (a PR number, branch name, or file
  path). Empty if none.

A token that isn't consumed as a flag or as a valid effort level is never
discarded — it stays part of the Target. Common branch names (`main`,
`develop`, `staging`, `master`) are targets, not efforts. If no level was
consumed and the first remaining token is a near-miss for one (short,
alphabetic, no path separators, no digits), note in one line that you're
reading it as the target rather than an effort level, list the valid levels,
then resolve the level per **Effort persistence** in
`references/output-and-flags.md`.

A token consumed as a level is never also a target: `/pm-cr high` reviews
the current diff, not a branch named `high` — type the level first to reach
one (`/pm-cr medium high`). If a level (or an unambiguous prefix of one) was
consumed, the Target is empty, and Phase 1 finds that token names an
existing ref or path, add one line saying so alongside the level line.

## Phase 1 — Gather the diff

Resolve a base commit, diff it against `HEAD`, then add the working tree.

### The base record

Every rule below produces the same shape:

| field | meaning |
|---|---|
| `remote` | remote name, a clone URL, or `—` for a local head |
| `branch` | branch name at that remote/URL |
| `oid` | commit id from `git rev-parse FETCH_HEAD`, captured immediately after *this record's own* fetch |
| `local_ref` | `<remote>/<branch>` when that ref exists locally, else `—` |

### Step 1 — Resolve the base

Take the first rule that produces a record.

**1a. The PR's own base — wins outright.** Run `gh pr view --json
url,baseRefName` for the current branch, or for the PR parsed as the target
in Phase 0. `baseRefName` is only a branch name, so take the base
*repository* from `url`: a PR URL is always
`https://github.com/<owner>/<repo>/pull/<n>` in the base repo, never in the
fork. The base remote is the local remote whose *fetch* URL points at that
`<owner>/<repo>` (strip `git@github.com:`, `https://github.com/`, and a
trailing `.git` before comparing).

- A remote matches → `{remote, baseRefName}`.
- None matches — a fork checkout carrying only the fork's `origin`, or a URL
  form those strips miss → `{https://github.com/<owner>/<repo>.git,
  baseRefName, local_ref: —}`.

Then go straight to Step 3; a PR base never enters the Step 2 comparison.
Fall through to 1b only when the branch has no open PR, when `gh pr view`
cannot resolve a single repository, or when the fetch in Step 3 fails.

**1b. Default-branch candidates, once per remote.** For each `<remote>` that
`git remote` lists, take the first of these that answers, substituting that
pass's remote for `<remote>` in both:

1. `git symbolic-ref refs/remotes/<remote>/HEAD`, stripping only the
   `refs/remotes/` prefix → `{remote, branch}`.
2. `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` against
   that remote's repo, which returns a bare name → `{remote, name}`.

Keep every answer as a candidate, including one whose `<remote>/<branch>`
ref is absent locally. Output: zero or more records.

**1c. Local head — not per-remote.** When 1b produced no records at all, or
when every record it produced was dropped in Step 3 (each fetch failed and
none had a `local_ref` to fall back on): whichever of `main` or `master`
exists as a local head → `{remote: —, branch}`. A repository with no remotes
configured reaches this rule directly, since 1b's loop body never runs.

**1d. Nothing resolved** → Step 4.

### Step 2 — Pick the winner

Only when 1b produced more than one record. Fetch each candidate per Step 3
and capture its `oid`, compute `git merge-base <oid> HEAD` for each, and
keep the candidate whose merge base is a *descendant* of the others (`git
merge-base --is-ancestor`). Equal merge bases → either serves, since the
three-dot range is identical.

### Step 3 — Refresh and diff

| record | command | on success | on fetch failure |
|---|---|---|---|
| has a `remote` (a clone URL counts) | `git fetch <remote-or-url> <branch>` | set `oid`, diff `<oid>...HEAD` | `local_ref` present → `<local_ref>...HEAD`, and report the base may be stale; absent → drop the record |
| local head (1c) | none | diff `<branch>...HEAD` | n/a |

The `<branch>` operand is never optional. `git fetch <url>` with no ref
fetches that repository's `HEAD`, so `FETCH_HEAD` would name `main` and a PR
into `release/1.x` would be diffed against the wrong branch.

Identify a fetched candidate by its captured `oid`, never by `FETCH_HEAD` at
diff time: each fetch overwrites `FETCH_HEAD` with only that fetch, so after
several candidates it names whichever was fetched last. The `oid` is also
the only handle a candidate with no local ref has — do not assume the fetch
creates one, because a `git clone --single-branch` checkout has a narrowed
refspec and `git fetch origin main` there sets `FETCH_HEAD` without ever
writing `origin/main`.

### Step 4 — Last resort

Guard first: `git rev-parse --verify -q HEAD~1`. On success, `git diff
HEAD~1`, and state in the report that the scope was narrowed to the last
commit. If the guard fails and `git rev-parse --is-shallow-repository` says
`true`, run `git fetch --deepen=1` and retry — that recovers the real
one-commit diff. If there is still no parent, report that no scope could be
resolved.

### Step 5 — Add the working tree

If there are uncommitted changes, or the range diff is empty, also run `git
diff HEAD` and include the working-tree changes in scope — the review often
runs before the commit.

`git diff` never reports untracked files, so always also run `git -c
core.quotePath=false ls-files --others --exclude-standard` (it honors
`.gitignore`) and treat every path it lists as a new file in scope; skip
binaries. This enumeration is unconditional — an untracked file is invisible
to every `git diff` form above even when the range diff is non-empty.

Bind each listed path to a shell variable and expand it double-quoted. Read
through a path only once you have positively established it is a regular
file: run `readlink -- "$p"` first — with the `--`, because the worktree may
hold a file literally named `-n`. If it succeeds the path is a symlink, so
record the target it prints as the single added line and do not read through
the link. A `readlink` failure proves nothing on its own: it exits 1 alike
for "not a symlink" and for a path it could not resolve. So read the file in
full as an all-additions hunk only once `test -f "./$p"` succeeds and `test
-L "./$p"` fails — `test -f` follows the link, so it is not a symlink check
on its own. Skip and report anything that classifies as neither.

If a PR number, branch name, or file path was parsed as the target in Phase
0, review that target instead. Treat this diff as the review scope. If the
scope is genuinely empty after all of this, say so explicitly rather than
reporting a clean review.

### Why these rules are the way they are

- **Three dots, always.** The whole branch back to the merge base is under
  review, not just its newest commit.
- **Refresh before diffing.** Any remote-tracking ref goes stale between
  fetches, and then the three-dot merge base slides backwards and
  already-merged commits enter the scope as if this branch wrote them. Three
  dots is no protection once the branch has merged the base in — or once `gh
  pr checkout` has fetched only the PR head ref — because `HEAD` already
  contains the newer base commits and the three-dot range collapses to the
  two-dot one.
- **A PR base beats a default branch.** A PR into `release/1.x` diffed
  against `main` starts at an older merge base, so `release/1.x`'s own
  commits enter the scope as author changes and `--fix` edits code outside
  the PR.
- **Per remote, not once overall.** `git clone` sets
  `refs/remotes/origin/HEAD` while `git remote add` never sets
  `upstream/HEAD`, so a single pass always answers from `origin` and
  `upstream`'s default is never considered. Reading the symref tier as a
  literal `refs/remotes/origin/HEAD` in every pass makes the loop inert the
  same way.
- **The descendant rule.** Three dots only protects you from a base that is
  ahead of the branch point, not one behind it: a branch cut from
  `upstream/main` while the fork's own default sits three commits back
  reviews those three upstream commits as if the author wrote them.
- **Never `@{upstream}`.** After `git push -u` a branch's tracking ref is
  `origin/<this branch>` — its own tip, not its base — so
  `@{upstream}...HEAD` is empty for every pushed commit.
- **Never the empty tree.** Diffing against it to manufacture a scope puts
  every pre-existing file in the repo in scope, breaking the "stay inside the
  reviewed diff's scope" constraint below.
- **`core.quotePath=false`.** Without it a non-ASCII name is octal-escaped
  into a quoted path that does not exist, so an untracked `café.py` is listed
  as `"caf\303\251.py"` and would be skipped rather than reviewed. A name
  holding a quote, tab, or newline is still C-quoted onto a single line; that
  residue does not name an existing file, so report it as skipped rather than
  guessing. Do not reach for `-z` to read this listing yourself — a NUL
  arrives in your tool output as a space, indistinguishable from the space
  inside `plain space.py`, so every boundary is lost. It is still the correct
  form when a *shell loop* consumes it, which never puts the NUL into text.
- **Symlinks.** The target string is what git itself stores for a symlink,
  and dereferencing one pulls whatever it points at — possibly a file outside
  the repository — into the review, its subagent prompts, and any
  `--comment` output.

### Worked scenarios

| scenario | rule | base | diff |
|---|---|---|---|
| normal clone, PR into `main` | 1a, remote matches | `origin` + `main` | `git fetch origin main` → `<oid>...HEAD` |
| PR into `release/1.x`, matching remote | 1a | `origin` + `release/1.x` | `git fetch origin release/1.x` → `<oid>...HEAD` |
| fork checkout, only the fork's `origin`, PR into `release/1.x` | 1a, URL branch | clone URL + `release/1.x` | `git fetch <url> release/1.x` → `<oid>...HEAD` |
| fork with `origin` + `upstream`, no PR | 1b: origin via (1), upstream via (2) | two candidates | descendant merge base wins → `<oid>...HEAD` |
| `--single-branch` clone, no PR, `origin/main` absent | 1b(2), candidate kept | `origin` + `main`, `local_ref: —` | `git fetch origin main` → `<oid>...HEAD` |
| no remotes at all | 1c | local `main` | `main...HEAD` |
| `--depth 1`, HEAD has no parent | 1d | none | deepen, retry, else report no scope |

## Phase 2 — Run the review at the resolved level

Look up the resolved effort level in `references/effort-levels.md` and
follow that level's procedure exactly — it specifies which finder angles to
run (defined in `references/angles.md`), how many candidates each may
surface, which verify pass (if any) to run, whether a gap-sweep phase
applies, and the output cap.

| Level | Angles | Candidates/angle | Verify | Sweep | Cap |
|-------|--------|-------------------|--------|-------|-----|
| low | hunk-visible only, no angle fan-out | — | none | no | 4 |
| medium | 8 (A, B, C + Reuse, Simplification, Efficiency, Altitude, Conventions) | 6 | 3-state | no | 8 |
| high | same 8 | 6 | recall-biased | no | 10 |
| xhigh / max | 10 (A–E + Reuse, Simplification, Efficiency, Altitude, Conventions) | 8 | recall-biased | yes | 15 |
| ultra | no local equivalent — falls back to max, see `effort-levels.md` | | | | |

## Phase 3 — Report (and apply flags)

Report findings per the output contract in `references/output-and-flags.md`.
If `--fix` was passed, apply the fixes per that file's `--fix` section
immediately after reporting. If `--comment` was passed, post inline PR
comments per that file's `--comment` section. If `--post` or `--no-post` was
passed, handle it per that file's section (it only matters for `ultra`).

## Constraints

- Correctness bugs always outrank cleanup/altitude/conventions findings when
  the output cap forces a cut (see `angles.md`).
- Every finding needs a concrete `failure_scenario` (or, for
  cleanup/altitude/conventions, a concrete cost) — no vague "this could be a
  problem" findings.
- Do not fix anything unless `--fix` was passed — reporting and fixing are
  separate steps.
- Stay inside the reviewed diff's scope; don't chase unrelated issues
  elsewhere in the codebase.
- Do not publish an artifact of the review — the report itself (tool call,
  JSON, or printed lines) is the deliverable.

## Fidelity notes

This skill reproduces the built-in Claude Code `/code-review` command's
documented behavior and finder/verify/sweep structure as closely as a
portable skill can. Deliberately not replicated, because they depend on
Claude Code internals a skill can't reach:

- Per-model prompt/routing tuning (the built-in command runs different
  wording and finder budgets for specific model families).
- Diff-size-adaptive subagent fleet sizing.
- Cross-session persistence of the last-used effort level (this skill's
  persistence is conversation-scoped only — see `output-and-flags.md`).
- Internal telemetry/UI hooks and automatic chaining into other built-in
  commands after the review completes.
- The `ultra` cloud multi-agent review itself (no cloud access from a
  portable skill) — falls back to `max` locally instead.
