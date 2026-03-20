---
name: auto-merge-dependabot
description: This skill should be used when the user asks to "merge dependabot PRs", "review dependabot", "auto-merge dependencies", "handle dependabot", "merge dependency updates", "check dependabot PRs", or wants to automatically review and merge open Dependabot pull requests. Also triggered by the /auto-merge-dependabot command.
user-invocable: true
---

# Auto-Merge Dependabot PRs

Review all open Dependabot pull requests in the current repository. Assess each PR for risk, and automatically merge those that are safe. Report any PRs that were skipped with clear reasoning.

## Workflow

### Step 1: Identify Repository

Determine the current GitHub repository using:

```bash
gh repo view --json nameWithOwner -q '.nameWithOwner'
```

If this fails, report the error and stop — the user likely needs to authenticate with `gh auth login` or is not inside a Git repository.

### Step 2: List Open Dependabot PRs

Fetch all open PRs authored by Dependabot:

```bash
gh pr list --author 'app/dependabot' --state open --json number,title,url,headRefName,body,labels,additions,deletions,files --limit 100
```

If there are no open Dependabot PRs, inform the user and stop.

Present a summary table to the user:

```
## Open Dependabot PRs

| # | Title | Files Changed | +/- |
|---|-------|---------------|-----|
```

### Step 3: Review Each PR

For each PR, assess the risk by checking:

1. **Version bump type** — Parse the PR title/body for semver information:
   - **Patch** (e.g., 1.2.3 → 1.2.4): Low risk. Auto-merge candidate.
   - **Minor** (e.g., 1.2.3 → 1.3.0): Low risk. Auto-merge candidate.
   - **Major** (e.g., 1.2.3 → 2.0.0): High risk. Skip and flag.

2. **CI status** — Check if CI checks have passed:
   ```bash
   gh pr checks <number> --json name,state
   ```
   - All checks passed: Good to merge.
   - Any check failed: Skip and flag.
   - Checks still pending: Skip and flag.

3. **Security advisories** — Look at the PR body for GitHub security advisory mentions. Dependabot security updates should be prioritized.

4. **Scope of changes** — Review the changed files:
   ```bash
   gh pr diff <number> --name-only
   ```
   - Only lockfile and manifest changes (e.g., `package-lock.json`, `Cargo.lock`, `go.sum`, `Gemfile.lock`, `poetry.lock`, `requirements.txt`): Low risk.
   - Source code changes or configuration changes beyond dependency files: Flag for review.

5. **Merge conflicts** — Check if the PR has conflicts:
   ```bash
   gh pr view <number> --json mergeable -q '.mergeable'
   ```
   - If `CONFLICTING`: Flag for rebase (will comment `@dependabot rebase` in Step 5).
   - If `MERGEABLE` or `UNKNOWN`: Continue with other checks.

Classify each PR into one of:
- **SAFE TO MERGE**: Patch/minor bump, CI passes, only dependency file changes, no conflicts.
- **NEEDS REBASE**: Has merge conflicts — will request Dependabot rebase.
- **NEEDS REVIEW**: Major bump, CI failures/pending, or unexpected file changes.

### Step 4: Present Review Summary

Present the review results clearly:

```
## Review Summary

### Safe to Merge
| # | Title | Reason |
|---|-------|--------|

### Needs Manual Review
| # | Title | Concern |
|---|-------|---------|
```

### Step 5: Merge Safe PRs

For each PR classified as **NEEDS REBASE**, comment to request a rebase:

```bash
gh pr comment <number> --body "@dependabot rebase"
```

For each PR classified as **SAFE TO MERGE**, merge it:

```bash
gh pr merge <number> --squash --auto
```

Use `--squash` to keep the commit history clean. Use `--auto` so that GitHub waits for required status checks before merging.

If a merge fails due to merge conflicts, do **not** close the PR. Instead, comment on it to request a rebase:

```bash
gh pr comment <number> --body "@dependabot rebase"
```

Record it as "Requested rebase" and continue with the remaining PRs.

For other merge failures (non-conflict errors), record the error and continue.

### Step 6: Final Report

Present a final summary:

```
## Results

### Merged
- #<number>: <title> ✓

### Requested Rebase (Conflicts)
- #<number>: <title> — commented @dependabot rebase

### Skipped (Needs Review)
- #<number>: <title> — <reason>

### Failed to Merge
- #<number>: <title> — <error>
```

If any PRs were skipped, ask the user: **"Would you like me to review any of the skipped PRs in more detail, or merge specific ones despite the concerns?"**
