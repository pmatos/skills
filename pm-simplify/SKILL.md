---
name: pm-simplify
description: This skill should be used when the user asks to "simplify this", "simplify the diff", "clean up this code", "clean up the changed code", "reuse pass", "simplification pass", "efficiency pass", "altitude pass", or wants the changed code reviewed for reuse, simplification, efficiency, and altitude issues and fixed directly — without hunting for correctness bugs. Also triggered by the /pm-simplify command.
argument-hint: "[<target>]"
user-invocable: true
---

# Simplify

Clean up the changed code without changing behavior. Review the diff for
reuse, simplification, efficiency, and altitude issues, then fix what you
find. This is a quality pass, not a bug hunt — do not look for correctness
bugs; that is a separate, dedicated review.

## Task

$ARGUMENTS

## Phase 0 — Gather the diff

Resolve the base to diff against, in this order:

1. If the current branch has an open PR, use its base: `gh pr view --json
   baseRefName -q .baseRefName`.
2. Otherwise use the remote's default branch — `git symbolic-ref
   refs/remotes/origin/HEAD` with the `refs/remotes/origin/` prefix
   stripped — falling back to `main` or `master` if that symref is absent.

Diff against the remote-tracking ref for that base: `git diff
origin/<base>...HEAD`. Not `@{upstream}` — once the branch is pushed that
resolves to the branch's own remote copy, so the three-dot diff is empty
and the whole committed PR silently drops out of scope. Not the local base
branch either: it is often stale, which widens the range to already-merged
work. With no remote at all, use the local `<base>...HEAD`, and `git diff
HEAD~1` only as a last resort.

Then pick up the working tree as well — this review often runs before the
commit. `git diff HEAD` covers modified tracked files; `git ls-files
--others --exclude-standard` lists the untracked ones, which `git diff
HEAD` omits entirely. Read each untracked file in full and treat it as
added lines. Do not stage anything to make a file show up in the diff (no
`git add`, no `git add -N`) — leave the index exactly as you found it. If
a PR number, branch name, or file path was passed as the argument above,
review that target instead. Treat the combined result as the review scope;
if it comes out empty, say the scope was empty rather than reporting the
code clean.

## Phase 1 — Review (four angles)

**If you have a native subagent tool (the `Agent`/`Task` tool) available:**
launch **four independent review agents** in a single message so they run
concurrently. Give each agent the diff and exactly one of the four angles
below. Each agent returns its findings with `file`, `line`, a one-line
`summary`, and the concrete cost — what is duplicated, wasted, or harder to
maintain.

**If no native subagent tool is available** (e.g. you're running headless,
or already inside a nested subagent that can't spawn further agents): work
through all four angles yourself, in this same context, in a single pass —
do not skip an angle for lack of fan-out. State clearly in your final
summary that this was a single-pass review, not the full four-agent
fan-out, so whoever reads it isn't misled about what actually ran.

### Reuse

Flag new code that re-implements something the codebase already has. Grep
shared/utility modules and files adjacent to the change, and name the
existing helper to call instead.

### Simplification

Flag unnecessary complexity the diff adds: redundant or derivable state,
copy-paste with slight variation, deep nesting, dead code left behind. Name
the simpler form that does the same job.

### Efficiency

Flag wasted work the diff introduces: redundant computation or repeated
I/O, independent operations run sequentially, blocking work added to
startup or hot paths. Also flag long-lived objects built from closures or
captured environments — they keep the entire enclosing scope alive for the
object's lifetime (a memory leak when that scope holds large values);
prefer a class/struct that copies only the fields it needs. Name the
cheaper alternative.

### Altitude

Check that each change is implemented at the right depth, not as a fragile
bandaid. Special cases layered on shared infrastructure are a sign the fix
isn't deep enough — prefer generalizing the underlying mechanism over
adding special cases.

## Phase 2 — Apply the fixes

Wait for all four review passes to complete (or, on the single-pass path,
finish working through all four angles). Dedup findings that point at the
same line or mechanism, and fix each remaining one directly. Skip any
finding whose fix would change intended behavior, require changes well
outside the reviewed diff, or that you judge to be a false positive — note
the skip rather than arguing with it. Finish with a brief summary of what
was fixed and what was skipped (or confirm the code was already clean).

## Constraints

- Quality only. Do not look for correctness bugs — that belongs to a
  dedicated code-review pass, not this one.
- Do not change behavior. A fix that would alter what the code does goes on
  the skip list, not into the diff.
- Stay inside the reviewed diff's scope — do not chase unrelated cleanups
  elsewhere in the codebase.
