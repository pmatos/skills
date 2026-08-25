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

## Phase 1 — Gather the diff

Resolve the base branch first, in order, keeping it remote-qualified
wherever the tier names a remote: the remote default branch from
`git symbolic-ref refs/remotes/origin/HEAD` (strip only the
`refs/remotes/` prefix, so the base stays `origin/<branch>` — a bare name
resolves through `refs/heads/`, never `refs/remotes/origin/`); else `gh
repo view --json defaultBranchRef -q .defaultBranchRef.name`, which returns
a bare name — qualify it as `origin/<name>`, or `upstream/<name>` in a fork
checkout, and fall through if that remote-tracking ref isn't present
locally (the symref is absent after a `git remote add` without `git remote
set-head`; in a fork checkout, query the `upstream` remote's repo); else
whichever of `main` or `master` exists as a local head (bare here by
design — this tier tested for the local branch); else `@{upstream}` if the
branch has one. Then run `git diff <base>...HEAD`
— three dots, so the whole branch back to the merge base is under review,
not just its newest commit.

What you actually want is the branch point. Where more than one candidate
base resolves — in a fork checkout `origin`'s and `upstream`'s default
branches are both candidates, and tier 1 would otherwise always pick
`origin`'s because `git clone` sets `refs/remotes/origin/HEAD` while `git
remote add` never sets `upstream/HEAD` — compute `git merge-base <cand>
HEAD` for each and keep the candidate whose merge base is a *descendant* of
the others (`git merge-base --is-ancestor`). Three dots only protects you
from a base that is ahead of the branch point, not one that is behind: a
branch cut from `upstream/main` while the fork's own default sits three
commits back reviews those three upstream commits as if the author wrote
them. The descendant rule gets this right whether the fork's default is
stale, divergent, or the branch's actual base. Only if no base resolves at all, fall back to
`git diff HEAD~1` and state in the report that the scope was narrowed to the
last commit. If there are uncommitted changes, or the range diff is empty,
also run `git diff HEAD` and include the working-tree changes in scope — the
review often runs before the commit. `git diff` never reports untracked
files, so always also run `git ls-files --others --exclude-standard` (it
honors `.gitignore`) and treat every path it lists as a new file in scope,
reviewing its full contents as an all-additions hunk; skip binaries. This
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
