---
name: vibe
description: >-
  This skill should be used when the user asks to "vibe an epic", "vibe #N", "drive epic #N to done", "solve the epic", "work through the epic's sub-issues", "finish the epic", "close out epic #N", "resume the epic", or wants every open child of an issue labelled `epic` fixed, reviewed and merged in turn. Runs `/pm-fix` on each child, then merges its PR once the checks are green. Not for a single non-epic issue (use pm-fix). Also triggered by the /vibe command.
argument-hint: "[epic-number|#N|url]"
user-invocable: true
---

# vibe — Drive an Epic to Done

Fix the open children of an epic one at a time: run `/pm-fix` on a child, merge
its PR, then move to the next. Invoking `/vibe` authorises merging green PRs
into the default branch, so say that when you start. Re-running `/vibe` resumes:
closed children are skipped, and pm-fix picks up a child's open PR.

## Steps

1. **Preflight.** Run `gh auth status` and confirm that you can push. Read the
   repo's allowed merge methods and prefer squash:

   ```bash
   gh api repos/{owner}/{repo} \
     --jq '{default_branch,allow_squash_merge,allow_merge_commit,allow_rebase_merge}'
   ```

   The working tree must be clean.
2. **Find the epic and its children.** With no argument, use the open issue
   labelled `epic`. If there are several, ask which one. The children are the
   epic's sub-issues, including sub-issues of sub-issues, plus the issues in its
   task list:

   ```bash
   gh api repos/{owner}/{repo}/issues/<E>/sub_issues --paginate \
     --jq '.[] | {number,title,state,sub_issues_summary}'
   ```

   Work through the open children in the listed order. Put a child that is
   blocked by an open issue at the back of the queue.
3. **For each open child N:**
   1. Switch to the default branch and pull.
   2. Run `/pm-fix N`. If it ends without a PR, note why and go to the next
      child.
   3. If the PR conflicts with the default branch, run `/rebase-pr <PR>` and
      wait for its checks again.
   4. Merge only when every check on the PR's head commit has passed. If a
      check failed, leave the PR open, note it, and go to the next child.
   5. Wait for the latest CI runs on the default branch to finish. If one
      failed, stop and report: nothing merges onto a red default branch.
   6. Merge with `gh pr merge <PR> --<method> --delete-branch`. Check with
      `gh pr view` that the PR merged and with `gh issue view` that N is
      closed. If N is still open, close it with a comment that links the PR.
4. **Close out.** When every child is closed, close the epic with a comment
   that lists the merged PRs. Otherwise leave it open and report each remaining
   child and why: no PR, failing checks, still blocked, or waiting on a
   decision.

## Rules

- Never write a closing keyword (close, fix, resolve) next to the epic's
  number, even negated: GitHub would close the epic when that PR merges.
- Never change a test threshold, skip list, baseline or snapshot, or take a
  release step, to get a PR green. Ask the user.
