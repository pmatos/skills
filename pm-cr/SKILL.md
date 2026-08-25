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

Resolve the base branch first, in order, keeping it remote-qualified
wherever the tier names a remote. **First, if there is a PR, use its
base**: `gh pr view --json url,baseRefName` for the current branch, or
resolve the PR parsed as the target in Phase 0. `baseRefName` is only a
branch name, so take the base *repository* from `url` — a PR URL is always
`https://github.com/<owner>/<repo>/pull/<n>` in the base repo, never in the
fork. The base remote is the local remote whose *fetch* URL points at that
`<owner>/<repo>` (strip `git@github.com:`, `https://github.com/`, and a
trailing `.git` before comparing); the base is then
`<base-remote>/<baseRefName>`. This tier is what makes a PR into a
non-default base such as `release/1.x` work: the default-branch tiers below
would pick `main`, whose merge base sits further back, so `release/1.x`'s
own commits enter the scope as author changes and `--fix` edits code
outside the PR. Fall through to those tiers when the branch has no open PR,
when `gh pr view` cannot resolve a single repository, or when no local
remote's fetch URL matches the base repo. The fall-through tiers: the
remote default branch from
`git symbolic-ref refs/remotes/origin/HEAD` (strip only the
`refs/remotes/` prefix, so the base stays `origin/<branch>` — a bare name
resolves through `refs/heads/`, never `refs/remotes/origin/`); else `gh
repo view --json defaultBranchRef -q .defaultBranchRef.name`, which returns
a bare name — qualify it as `origin/<name>`, or `upstream/<name>` in a fork
checkout, and fall through if that remote-tracking ref isn't present
locally (the symref is absent after a `git remote add` without `git remote
set-head`; in a fork checkout, query the `upstream` remote's repo); else
whichever of `main` or `master` exists as a local head (bare here by
design — this tier tested for the local branch). Refresh that base before
diffing — `git fetch <remote> <branch>` for the remote-qualified tiers —
and run `git diff FETCH_HEAD...HEAD`; the local-head tier has no remote to
refresh, so diff `<base>...HEAD` there. Three dots either way, so the whole
branch back to the merge base is under review, not just its newest commit.
Any remote-tracking ref goes stale between fetches, and then the three-dot
merge base slides backwards and already-merged commits enter the scope as
if this branch wrote them. Three dots is no protection once the branch has
merged the base in — or once `gh pr checkout` has fetched only the PR head
ref and left `origin/<branch>` behind — because `HEAD` already contains the
newer base commits and the three-dot range collapses to the two-dot one. If
the fetch fails, fall back to `<remote>/<branch>...HEAD` and say in the
report that the base may be stale. Never fall back to
`@{upstream}`: after `git push -u` a branch's tracking ref is
`origin/<this branch>` — its own tip, not its base — so `@{upstream}...HEAD`
is empty for every pushed commit. When no tier resolves (a `git clone
--single-branch` checkout has no `origin/HEAD`, no `origin/<default>`, and
no local `main`), take the disclosed `HEAD~1` last resort below rather than
a tracking ref that reviews nothing.

What you actually want is the branch point. When the PR base resolved
above, use it directly — the candidate comparison here exists to
disambiguate default-branch candidates. Where more than one candidate
base resolves — in a fork checkout `origin`'s and `upstream`'s default
branches are both candidates, and tier 1 would otherwise always pick
`origin`'s because `git clone` sets `refs/remotes/origin/HEAD` while `git
remote add` never sets `upstream/HEAD` — refresh each candidate the same way, then compute
`git merge-base <cand> HEAD` for each and keep the candidate whose merge base is a *descendant* of
the others (`git merge-base --is-ancestor`). Three dots only protects you
from a base that is ahead of the branch point, not one that is behind: a
branch cut from `upstream/main` while the fork's own default sits three
commits back reviews those three upstream commits as if the author wrote
them. The descendant rule gets this right whether the fork's default is
stale, divergent, or the branch's actual base. Only if no base resolves at all, fall back to
`git diff HEAD~1` and state in the report that the scope was narrowed to the
last commit — but guard it with `git rev-parse --verify -q HEAD~1` first,
because HEAD has no parent in a `--depth 1` clone or on a root commit and
the bare command dies. If the guard fails and `git rev-parse
--is-shallow-repository` says `true`, run `git fetch --deepen=1` and retry:
that recovers the real one-commit diff. If there is still no parent, report
that no scope could be resolved. Do **not** diff against the empty tree to
manufacture one — that puts every pre-existing file in the repo in scope,
which breaks the "stay inside the reviewed diff's scope" constraint below. If there are uncommitted changes, or the range diff is empty,
also run `git diff HEAD` and include the working-tree changes in scope — the
review often runs before the commit. `git diff` never reports untracked
files, so always also run `git -c core.quotePath=false ls-files --others
--exclude-standard` (it honors `.gitignore`) and treat every path it lists
as a new file in scope, reviewing its full contents as an all-additions
hunk; skip binaries. The `core.quotePath=false` matters: without it a
non-ASCII name is octal-escaped into a quoted path that does not exist, so
an untracked `café.py` is listed as `"caf\303\251.py"` and would be
skipped rather than reviewed. A name holding a quote, tab, or newline is
still C-quoted onto a single line; that residue does not name an existing
file, so report it as skipped rather than guessing at the real name. Do not
reach for `-z` here — NUL separators do not survive into this listing as
text, so every path boundary is lost. This
enumeration is unconditional — an untracked file is invisible to every
`git diff` form above even when the range diff is non-empty. If a PR number,
branch name, or file path was parsed as the target in Phase 0, review that
target instead. Treat this diff as the review scope. If the scope is
genuinely empty after all of this, say so explicitly rather than reporting a
clean review.

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
