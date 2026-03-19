---
name: cp
description: This skill should be used when the user asks to "commit and push", "cp", "commit push", "ship it", "push my changes", or wants to commit and push while respecting the project's CLAUDE.md commit requirements.
user-invocable: true
---

# Commit & Push

Commit and push changes to the current branch, running **only** the pre-commit checks described in the project's CLAUDE.md (or AGENTS.md). Does not invent extra steps — if the project specifies no requirements, skip straight to commit and push.

## Workflow

### Step 1: Read the project's CLAUDE.md

Look for a CLAUDE.md (or AGENTS.md) in the **working directory** and its ancestors (up to the repo root). Read it and extract any commit-related requirements such as:

- Formatting commands (e.g. `prettier`, `black`, `gofmt`)
- Linting commands (e.g. `eslint`, `ruff`, `clippy`)
- Type-checking commands (e.g. `tsc --noEmit`, `mypy`)
- Test commands (e.g. `npm test`, `pytest`, `cargo test`)
- Build commands (e.g. `npm run build`, `cargo build`)
- Commit message conventions (e.g. conventional commits, prefix rules)

**Only** extract requirements that are explicitly stated. If CLAUDE.md says nothing about pre-commit checks, do not run any.

### Step 2: Determine the branch

Run `git branch --show-current` to get the current branch name. If the result is empty (detached HEAD) or is `main`/`master`, ask the user which branch to push to before proceeding. Otherwise use the current branch.

### Step 3: Run pre-commit checks

For each requirement found in Step 1, run the corresponding command via Bash. Execute them in a logical order: format → lint → type-check → test → build.

- If a formatter modifies files, stage the changes with `git add` on those files.
- If any check fails, report the failure to the user and stop. Do **not** commit broken code.

If no requirements were found in CLAUDE.md, skip this step entirely.

### Step 4: Stage and commit

1. Run `git status` and `git diff --stat` to review what will be committed.
2. Stage the relevant changed files (prefer explicit file names over `git add -A`).
3. Write a concise commit message that summarizes the **why** of the changes. Follow any commit message conventions found in CLAUDE.md. Use a HEREDOC to pass the message:

```bash
git commit -m "$(cat <<'EOF'
<commit message here>
EOF
)"
```

4. Run `git status` after committing to verify success.

### Step 5: Push

Push to the remote with:

```bash
git push -u origin <branch-name>
```

If the push fails due to a network error, retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s). If it fails for other reasons (e.g. rejected), report the error and stop.

### Step 6: Report

Tell the user:
- What checks were run (if any) and their results.
- The commit hash and message.
- The branch that was pushed to.
