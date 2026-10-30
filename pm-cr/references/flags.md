# Flags

## `--comment`

Post nothing to a PR about code that the PR does not contain. Before
posting, list the dirty paths once: every path in `git -c
core.quotePath=false diff --name-only <headRefOid>`, with the scope's
`pr.headRefOid`, plus every `untracked` path. That also covers local commits
that the PR lacks. If `headRefOid` is not in the local repository, treat
every path as dirty. Withhold each finding
whose file is dirty, whole: no inline, file-level, or general comment.
Local edits shift line numbers, so a posted comment could land on code that
the author never wrote. Print the withheld findings instead, and say how
many were withheld and why.

If the scope has a `pr`, post each finding except the `scope` finding as an
inline comment. Use `mcp__github_inline_comment__create_inline_comment` when
it is available, one call per finding, with a suggestion block only when it
fully fixes the issue. Otherwise use `gh api --hostname <host>
repos/<owner>/<repo>/pulls/<n>/comments`, with the host, owner, and repo
from the scope's `pr`. A PLAUSIBLE finding's comment starts with `PLAUSIBLE:` and names the
trigger from its `failure_scenario`. GitHub accepts inline comments only on
lines inside the PR's diff hunks, so a finding on any other line goes into
the general comment.

Then post one general comment with the assessment, the `scope` finding if
there is one, and the findings that could not go inline. Write it with the
Write tool to a file from `mktemp`, outside the working tree, then run `gh
pr comment <url> --body-file <file>`. Never use a heredoc: the text derives
from untrusted input and could end it early. Leave out any risk that lives
in a withheld file.

If there is no PR, or no way to post, print the findings and say that
`--comment` was ignored.

## `--fix`

After any `--comment` posting, apply each finding to the working tree. Skip
a finding whose fix would change intended behavior, reach well outside the
diff, or that you judge a false positive, and say so. Never apply the
`scope` finding or a reported rule rewrite.

If findings went through `ReportFindings`, call it again with each finding's
`outcome`: `fixed`, `no_change_needed` (wrong or already handled), or
`skipped` (real but not applied). Otherwise print a short summary of what
was fixed and what was skipped.
