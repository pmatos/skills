---
name: pm-fix
description: This skill should be used when the user asks to "fix issue #N and review it", "investigate, review and simplify", "fix, review and clean up issue #N", or wants a GitHub issue taken to an open PR that has then been reviewed, fixed and simplified in one run. Also triggered by the /pm-fix command.
argument-hint: "[issue-number]"
user-invocable: true
---

# Fix Issue

Take a GitHub issue to a reviewed and simplified PR. Run each step through the
Skill tool, in order, without stopping between steps.

## Steps

1. Run `/investigate $ARGUMENTS`. If it ends without opening a PR, report why
   and stop. Otherwise note the PR number.
2. Run `/pm-cr --fix --comment <PR>`.
3. If pm-cr applied fixes, re-run the checks that investigate ran. Then run
   `/cp` with a commit message that says the commit applies review fixes.
4. Run `/pm-simplify <PR>`.
5. If pm-simplify changed code, re-run those checks and run `/cp` again.
6. Report the PR URL, what pm-cr found and fixed or skipped, and what
   pm-simplify changed.

A failed step stops the run. Report the step that failed and leave the branch
as it is.
