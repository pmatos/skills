---
name: pm-fix
description: This skill should be used when the user asks to "fix issue #N and review it", "investigate, review and simplify", "fix, review and clean up issue #N", or wants a GitHub issue taken to an open PR that has then been reviewed, fixed and simplified in one run. Chains /investigate, /pm-cr --fix --comment and /pm-simplify, committing and pushing with /cp after each fix pass. Also triggered by the /pm-fix command.
argument-hint: "[issue-number]"
user-invocable: true
---

# Fix Issue

Take a GitHub issue to a reviewed and simplified PR. Run each step through the
Skill tool, and let each step finish before starting the next.

## Task

$ARGUMENTS

## Steps

1. Run `/investigate $ARGUMENTS`. If it ends without opening a PR, report why
   and stop. Otherwise note the PR number.
2. Run `/pm-cr --fix --comment <PR>`. It posts its findings on the PR, then
   applies the fixes to the working tree.
3. If the working tree changed, run `/cp` with a commit message that says the
   commit applies review fixes.
4. Run `/pm-simplify <PR>`.
5. If the working tree changed, run `/cp` again.
6. Report the PR URL, what pm-cr found and fixed or skipped, and what
   pm-simplify changed.

A failed step stops the run. Report the step that failed and leave the branch
as it is.
