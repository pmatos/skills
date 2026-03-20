---
name: cp
description: This skill should be used when the user asks to "commit and push", "cp", "commit push", "ship it", "push my changes", or wants to commit and push while respecting the project's CLAUDE.md (or AGENTS.md) commit requirements. Also triggered by the /cp command.
user-invocable: true
---

# Commit & Push

Commit and push changes to the current branch, running **only** the pre-commit checks described in the project's CLAUDE.md (or AGENTS.md). Does not invent extra steps — if the project specifies no requirements, skip straight to commit and push.

## Workflow

### Step 1: Read the project's CLAUDE.md

First determine the Git repository root by running `git rev-parse --show-toplevel`. Then look for a CLAUDE.md (or AGENTS.md) starting from the **working directory** and walking up through its ancestor directories, but stop once you reach that repo root and do not search beyond it. Use the nearest file found; if both CLAUDE.md and AGENTS.md exist in the same directory, prefer CLAUDE.md. Read the file and extract any commit-related requirements such as:

- Formatting commands (e.g. `prettier`, `black`, `gofmt`)
- Linting commands (e.g. `eslint`, `ruff`, `clippy`)
- Type-checking commands (e.g. `tsc --noEmit`, `mypy`)
- Test commands (e.g. `npm test`, `pytest`, `cargo test`)
- Build commands (e.g. `npm run build`, `cargo build`)
- Commit message conventions (e.g. conventional commits, prefix rules)

**Only** extract requirements that are explicitly stated. If CLAUDE.md says nothing about pre-commit checks, do not run any.

### Step 2: Determine the branch

Run `git branch --show-current` to get the current branch name. If the result is empty (detached HEAD) or is `main`/`master`, ask the user which branch to push to before proceeding — this is a safety guard to avoid accidental commits directly to `main`/`master`. Once the target branch is determined, switch to it:

- If the branch already exists locally: `git switch <branch-name>`
- If it needs to be created: `git switch -c <branch-name>`

If the current branch is neither `main`/`master` nor detached HEAD, use it as-is without switching.

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
git commit -F - <<'EOF'
<commit message here>
EOF
```

4. Run `git status` after committing to verify success.

### Step 5: Push

Check whether the branch already has an upstream configured by running `git rev-parse --abbrev-ref <branch-name>@{upstream}`.

- **Upstream exists**: simply run `git push` (no flags needed — git uses the existing tracking config).
- **No upstream**: determine the remote via `git config --get branch.<branch-name>.remote`, falling back to `origin`, then run:

```bash
git push -u <remote> <branch-name>
```

If the push fails due to a network error, retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s). If it fails for other reasons (e.g. rejected), report the error and stop.

### Step 6: Report

Tell the user:
- What checks were run (if any) and their results.
- The commit hash and message.
- The branch that was pushed to.
