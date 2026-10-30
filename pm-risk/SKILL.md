---
name: pm-risk
description: This skill should be used when the user asks "how risky is this PR", "what's the merge risk", "score this change's risk", "is this safe to merge", or wants a reproducible low/medium/high/critical merge-risk score for a PR, a branch, or the working tree, with the signals behind it. pm-cr also calls it to size its review. Also triggered by the /pm-risk command.
argument-hint: "[--comment] [<pr#>|<branch>] | --base <rev> [--head <rev>] [--path <path>]"
allowed-tools:
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/score_risk.py *)
  - Bash(gh pr view *)
  - Bash(git rev-parse *)
---

# Merge risk

Score how risky a change is to merge, from its size, its test coverage, and the paths it touches. A script does the scoring, so the same change always gets the same risk. Report the score and its signals, never your own view of the code.

## Task

$ARGUMENTS

## 1. Pick the revisions

- **`--base` given** (pm-cr's call): use it, with `--head` and `--path` if given.
- **A PR number**, or no target while the current branch has an open PR: run `gh pr view [<n>] --json number,baseRefName,url`. From the PR's repository (its `url` up to `/pull/`, plus `.git`), run `git fetch <repo-url> <baseRefName>` and then `git fetch <repo-url> refs/pull/<n>/head`. After each fetch, take its commit with `git rev-parse FETCH_HEAD`. Those are `--base` and `--head`.
- **A branch**: `--head` is the branch, and `--base` is the default branch, `origin/HEAD` or else `main`.
- **Nothing else**: `--base` is the default branch, and leave out `--head` to score the working tree, uncommitted and untracked files included.

## 2. Score

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/score_risk.py --base '<base>' [--head '<head>'] [--path '<path>']
```

Put each value in single quotes. If `${CLAUDE_SKILL_DIR}` was not expanded, resolve `scripts/` relative to this file. If the script fails, report its error and no score.

## 3. Report

```text
Merge risk: <risk>
- <each entry of steps, in plain words>
```

Name the rule behind each high-stakes path, and add nothing else. This is a score of size and exposure, not a review. With `--comment` and a PR target, also post the report as a PR comment, passing it on stdin with `gh pr comment <n> --body-file -`. `references/rules.md` explains every rule and output field, and how a repo adds its own high-stakes paths.
