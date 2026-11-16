---
name: pm-fix
description: This skill should be used when the user asks to "fix issue #N and review it", "investigate and review", "fix and review issue #N", or wants a GitHub issue taken to an open PR that has then been reviewed and fixed in one run. Also triggered by the /pm-fix command.
argument-hint: "[issue-number]"
user-invocable: true
---

# Fix Issue

Take a GitHub issue to a reviewed PR. Run `/investigate`, `/pm-cr` and `/cp`
through the Skill tool. Run the steps in order, without stopping between them.

## Steps

1. If `$ARGUMENTS` names issue N, look for an open PR of yours that closes it:

   ```bash
   gh pr list --author "@me" --state open --json number,closingIssuesReferences \
     --jq '.[] | select(any(.closingIssuesReferences[]; .number == N)) | .number'
   ```

   If there is one, check it out with `gh pr checkout <PR>` and go to step 2.
   Otherwise run `/investigate $ARGUMENTS`. If it ends without opening a PR,
   report why and stop. Otherwise note the PR number.
2. Run `/pm-cr --fix --comment <PR>`.
3. If pm-cr applied fixes, re-run the project's tests and linters. Then run
   `/cp` with a commit message that says the commit applies review fixes.
4. Wait until the PR's head is your last commit and its checks have started.
   Then run `gh pr checks <PR> --watch` with a long timeout, repeating it until
   every check has finished.
5. Report the PR URL, the state of its checks, and what pm-cr found and fixed
   or skipped.

A failed step stops the run. Report the step that failed and leave the branch
as it is. A failing check is not a failed step: report it in step 5.
