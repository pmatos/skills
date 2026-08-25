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

Resolve the base to diff against, in this order — but if the argument
below is a PR number, resolve that PR first and let its `url` and
`baseRefName` stand in for rule 1's ambient lookup:

1. If the current branch has an open PR, use its base: `gh pr view --json
   url,baseRefName`. `baseRefName` is only a branch name, so take the base
   *repository* from `url` — a PR URL is always
   `https://github.com/<owner>/<repo>/pull/<n>` in the base repo, never in
   the fork. The base remote is the local remote whose *fetch* URL — the
   `(fetch)` line of `git remote -v`, equivalently `git remote get-url
   <name>` — points at that `<owner>/<repo>` (strip `git@github.com:`,
   `https://github.com/`, and a trailing `.git` before comparing). Match
   the fetch URL specifically: a remote may carry a separate push URL,
   and `git fetch` uses the fetch one. If no remote matches — a fork
   checkout with no `upstream` — use the clone URL
   `https://github.com/<owner>/<repo>.git`, which `git fetch` accepts in
   place of a remote name. If `gh pr view` cannot resolve a single
   repository on its own, fall through to rule 2.
2. Otherwise derive both the remote and the branch — do not assume a
   remote is named `origin`. The base remote is `origin` if `git remote`
   lists it, else the sole remote it lists, else the one the current
   branch tracks (`git config --get branch.<branch>.remote`). The base is
   that remote's default branch — `git symbolic-ref
   refs/remotes/<base-remote>/HEAD` with the
   `refs/remotes/<base-remote>/` prefix stripped — falling back to `main`
   or `master` if that symref is absent.

Refresh that base before diffing — `git fetch <base-remote> <base>` — and
diff `FETCH_HEAD...HEAD`. Both halves matter: hard-coding `origin/<base>`
diffs against the fork's copy of the branch on a cross-repository PR, and
any remote-tracking ref goes stale between fetches. Either way the
three-dot merge-base slides backwards and already-merged commits enter the
scope, where Phase 2 would edit code the change never touched. Do not
substitute `baseRefOid`: it is frozen at the base tip recorded when the PR
was opened and does not follow the base branch as that branch moves, so it
reintroduces the same stale merge-base. Not `@{upstream}` — once the
branch is pushed that resolves to the branch's own remote copy, so the
three-dot diff is empty and the whole committed PR silently drops out of
scope. Not the local base branch either: it is often stale, which widens
the range to already-merged work.

If the fetch fails, and only when the base remote is a *named* remote,
fall back to `<base-remote>/<base>...HEAD` and say the base may be stale —
a clone-URL base has no local ref to fall back to. With no usable remote
at all, use the local `<base>...HEAD`, and `git diff HEAD~1` only as a
last resort.

Then pick up the working tree as well — this review often runs before the
commit. `git diff HEAD` covers modified tracked files; `git ls-files
--others --exclude-standard` lists the untracked ones, which `git diff
HEAD` omits entirely. Run `readlink <path>` on each untracked path first:
if it succeeds the path is a symlink, so record the target it prints as
the single added line and do not read through the link — that is what git
itself stores for a symlink, and dereferencing one pulls whatever it
points at, possibly a file outside the repository, into the review and its
subagent prompts. Otherwise read the file in full and treat it as added
lines. Do not stage anything to make a file show up in the diff (no `git
add`, no `git add -N`) — leave the index exactly as you found it.

If a PR number, branch name, or file path was passed as the argument
above, review that target instead. A PR number or branch name must name
the current checkout. For a branch name, compare it against `git rev-parse
--abbrev-ref HEAD`; for a PR number, read `gh pr view <n> --json
url,baseRefName,headRefName,headRefOid,isCrossRepository` and compare its
`headRefName` against that same value. Stop if they differ — `gh pr view`
only displays a PR, it does not switch checkouts, so Phase 2 would
otherwise apply fixes to whatever branch is actually checked out. That
same command supplies the `url` and `baseRefName` rule 1 needs: a branch
can carry open PRs into two different bases, and diffing against the wrong
one both drops changes belonging to the requested PR and pulls in changes
outside it. A branch name identifies no repository, so when
`isCrossRepository` is true additionally require `git
merge-base --is-ancestor <headRefOid> HEAD` to exit zero; otherwise a
fork's same-named branch passes the name check while its code is nowhere
in this worktree. Any non-zero exit stops, including the exit-128 `fatal:
Not a valid commit name` an unfetched fork commit gives. Ancestry rather
than equality, and only for cross-repository PRs: this skill usually runs
before the commit, so a same-repo branch is routinely ahead of — or
rebased off — the PR head. Ask for the target to be checked out first.

Treat the combined result as the review scope; if it comes out empty, say
the scope was empty rather than reporting the code clean.

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
