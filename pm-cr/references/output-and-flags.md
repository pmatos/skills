# Output contract and flags

## Reporting findings

If the `ReportFindings` tool is available in this session, call it once with
the findings ranked most-severe first, respecting the cap for the effort
level in use. Each entry carries:

- `file`, `line`
- `summary` — one-sentence statement of the defect
- `short_summary` — the claim compressed to ≤60 characters, no rationale or
  consequence clause
- `failure_scenario` — concrete inputs/state → wrong output/crash (or, for
  cleanup/altitude/conventions findings, the concrete cost per `angles.md`)
- `category` — a short kebab-case slug for the angle that produced it
  (`correctness`, `simplification`, `efficiency`, `reuse`, `altitude`,
  `conventions`, or a more specific slug like `test-coverage` when one fits
  better)
- `verdict` — `CONFIRMED` or `PLAUSIBLE`, when a verify pass produced one

If more findings survive than the level's cap allows, keep the most severe
and drop the rest. If nothing survives, call it with an empty array. Do not
also print the findings as text, and do not create or publish an artifact of
the review — the tool call is the report.

If `ReportFindings` is not available, output the same findings as a JSON
array of objects with `file`, `line`, `summary`, `failure_scenario` (the
tool-only fields — `short_summary`, `category`, `verdict` — are omitted),
respecting the same cap and ranking.

At **low** effort specifically, if neither a structured-output context nor
`ReportFindings` applies (e.g. a plain terminal session), output one line per
finding instead: `path/to/file.ext:123 — what's wrong and the concrete
failure`. Output `(none)` if nothing qualifies.

## `--fix`

`--fix` writes to the current working tree, so it is only valid when the
reviewed scope *is* that tree: no target, a path target, or a branch/PR
target whose head is what's checked out. Phase 1 already refuses to review
an off-checkout PR or branch target at all, so a review that reached this
point has the right tree; re-check it here anyway as a backstop, before
applying anything — compare `gh pr view <n> --json headRefOid -q
.headRefOid` (or `git rev-parse <branch>`) against `git rev-parse HEAD`.
Compare the commit, not the branch name: a local branch of the right name
that is stale or behind the PR head still has files on disk that the
reviewed diff's line numbers don't match. If the two differ, apply nothing
and say in one line that `--fix` was skipped because PR #<n> /
`<branch>` isn't checked out, and that `gh pr checkout <n>` (or `git switch
<branch>`) then a rerun with `--fix` will apply them. Never write fixes for
one branch's diff into another branch. A dirty tree is *not* a blocker —
reviewing uncommitted changes is a
supported mode (Phase 1).

Apply the findings to the working tree instead of stopping at the report:
fix each one directly — correctness bugs and cleanup/altitude/conventions
findings alike. Skip any finding whose fix would change intended behavior,
require changes well outside the reviewed diff, or that you judge to be a
false positive — note the skip rather than arguing with it.

If findings were reported via `ReportFindings`, call it again with the same
findings, each carrying an `outcome`: `fixed`, `no_change_needed` (the
finding was wrong or already handled), or `skipped` (real but not applied).
Do not repeat the findings as text — the host UI's per-finding status
updates only from that call. Otherwise, finish with a brief summary of what
was fixed and what was skipped.

## `--comment`

**Post nothing to the PR about code the PR does not contain.** Phase 1's
Step 5 folds uncommitted and untracked files into the review scope, so on a
dirty checkout some findings describe code that exists only on this machine.
Before posting anything, list the dirty paths once with `git -c
core.quotePath=false status --porcelain` — it covers staged, unstaged, and
untracked alike — and treat every path it names, both sides of a rename, as
dirty. A finding whose `file` is dirty is withheld from the PR entirely: no
inline comment, no `gh api` fallback, and no file-level or general comment
either. Withhold a dirty file *whole*, never per hunk: local edits shift
every line below them, so a finding about a committed line in an edited file
can carry a line number GitHub accepts against different content, and it
then reads as a review of code the author never wrote — on someone else's PR
that publicly attributes code to them they cannot see. Print the withheld
findings instead and say in one line how many were withheld and why. Nothing
else changes: the review scope, the report, and `--fix` still cover the
working tree.

If the review target is a GitHub PR, post each finding as an inline PR
comment: use `mcp__github_inline_comment__create_inline_comment` (one call
per finding; include a suggestion block only when it fully fixes the issue)
if available. If that tool isn't available in this session, fall back to
`gh api repos/{owner}/{repo}/pulls/{pr}/comments`. If neither is usable,
print the findings instead. If the target is not a PR, print the findings to
the terminal and note that `--comment` was ignored.

GitHub only accepts an inline comment on a line that is part of the PR's
diff hunks (added, removed, or context lines). Angle A findings can land on
lines outside every hunk; for those, don't retry the inline call — post the
finding as a file-level or general PR comment, or include it in the printed
findings, and say which.

## `--post` / `--no-post`

These only apply to the cloud `ultra` review (posting its findings to the PR
as a single comment from the user's GitHub account) and have no meaning for
a local review. If `--post` is typed alongside a local (non-`ultra`) run,
note in one short line that it was ignored, and that `--comment` is the flag
that posts local findings as inline PR comments.

## Effort persistence

If no level is given as an argument, reuse whatever level was last used for
`/pm-cr` earlier in this same conversation; default to `medium` on the first
invocation. Say which level you're using and why (explicit / reused /
defaulted) in one short line.

The built-in `/code-review` command persists the last-used level across
sessions via Claude Code's internal storage. A portable skill has no
equivalent storage to hook into, so this skill's persistence is
conversation-scoped only — note this if the user seems to expect
cross-session memory.
