# Output contract and flags

## Reporting findings

If the `ReportFindings` tool is available in this session, call it once,
with `level` set to the review depth and with the findings ranked by
severity tier (`angles.md`), respecting the depth's cap. Each entry carries:

- `file`, `line`
- `summary` — one sentence: the defect stated as fact, then the fix (see
  **Writing a finding**)
- `short_summary` — the claim compressed to ≤60 characters, no rationale or
  consequence clause
- `failure_scenario` — concrete inputs/state → wrong output/crash (or, for
  cleanup/altitude/conventions findings, the concrete cost per `angles.md`)
- `category` — a short kebab-case slug for the angle that produced it
  (`security`, `correctness`, `performance`, `simplification`, `efficiency`,
  `reuse`, `altitude`, `conventions`, `scope`, or a more specific slug when
  one fits better)
- `verdict` — `CONFIRMED` or `PLAUSIBLE`, when a verify pass produced one

If more findings survive than the level's cap allows, cut from the lowest
tier. If nothing survives, call it with an empty array. Do not also print
the findings as text, and do not create or publish an artifact of the
review — the tool call is the report.

If `ReportFindings` is not available, output the same findings as a JSON
array of objects with `file`, `line`, `summary`, `failure_scenario`,
`category`, and `verdict`, respecting the same cap and ranking. Make the
final message nothing but the array, because a caller may parse it as JSON,
so skip the assessment there.

At the **low** depth specifically, if neither a structured-output context nor
`ReportFindings` applies (e.g. a plain terminal session), output one line per
finding instead: `path/to/file.ext:123 — what's wrong and the concrete
failure`. Output `(none)` if nothing qualifies.

### Writing a finding

State the defect as fact, then give the fix with a directive verb such as
Fix, Remove, Change, Add, Return, or Guard. Keep it short and specific.
Never hedge: no "maybe", "might want to", "consider", "possibly", "could
be", or "you may want to". A PLAUSIBLE finding carries its uncertainty in
`verdict` and in the trigger that `failure_scenario` names, not in the
wording.

```text
Bad:  Consider checking whether user could be null here.
Good: user.id throws on an expired session, because getUser() returns null
      there (auth.ts:42); return 401 before line 57.
```

### Assessment

After the findings, print a one-to-three-sentence assessment, except in
the bare JSON array mode above. Open it with the `Depth:` line from Phase 2,
then give your overall
take on the change, such as its main risk area or whether it looks sound.
At the low depth, one sentence. Do not summarize what the change does, because
the author already knows. Do not count, list, or repeat the findings,
because `--comment` can withhold some of them. The assessment is not a
finding, so printing it does not duplicate the `ReportFindings` call. Put
every disclosure in it too: files not reviewed, edited review instructions,
a stale base, or a single-pass review.

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
false positive — note the skip rather than arguing with it. Never apply the
`scope` finding: splitting a change is the author's call, so it is always
`skipped`.

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
Before posting anything, list the dirty paths once: every path in `git
-c core.quotePath=false diff --name-only <headRefOid>`, which also covers
local commits the PR lacks, plus every untracked file. If `headRefOid` is
not in the local repository, withhold everything. A finding whose `file` is dirty is withheld from the PR entirely: no
inline comment, no `gh api` fallback, and no file-level or general comment
either. Withhold a dirty file *whole*, never per hunk: local edits shift
every line below them, so a finding about a committed line in an edited file
can carry a line number GitHub accepts against different content, and it
then reads as a review of code the author never wrote — on someone else's PR
that publicly attributes code to them they cannot see. Print the withheld
findings instead and say in one line how many were withheld and why. Nothing
else changes: the review scope, the report, and `--fix` still cover the
working tree.

If rule 1a found a PR, post each finding except the `scope` finding as an
inline PR comment: use `mcp__github_inline_comment__create_inline_comment` (one call
per finding; include a suggestion block only when it fully fixes the issue)
if available. A PLAUSIBLE finding's comment starts with `PLAUSIBLE:` and
names the trigger from its `failure_scenario`, so the author can see how
certain the review is. If that tool isn't available in this session, fall back to
`gh api --hostname <host> repos/<owner>/<repo>/pulls/<n>/comments`, using
the host, owner, and repo that rule 1a parsed from the PR URL. If neither is usable,
print the findings instead. If the target is not a PR, print the findings to
the terminal and note that `--comment` was ignored.

When the findings were posted to the PR, also post the assessment, and the
`scope` finding if there is one, once as a general PR comment. Write the
text with the Write tool to a file from `mktemp`, outside the working tree,
then run `gh pr comment <url> --body-file <file>`. Never use a heredoc: the
text derives from untrusted input and could end it early. Otherwise print
the assessment, except in the bare JSON array mode. Write it about code the PR contains: if the
risk you would name lives in a withheld dirty file, leave that risk out of
the posted text.

GitHub only accepts an inline comment on a line that is part of the PR's
diff hunks (added, removed, or context lines). Angle A findings can land on
lines outside every hunk; for those, don't retry the inline call — post the
finding as a file-level or general PR comment, or include it in the printed
findings, and say which.
