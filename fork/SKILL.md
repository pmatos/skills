---
name: fork
description: This skill should be used when the user asks to "fork", "race claude and codex", "dual implement", "run both models", "compare implementations", "implement with both", "fork it", or wants the same task implemented by both Claude Code and OpenAI Codex in parallel to pick the best result. Also triggered by the /fork command.
user-invocable: true
argument-hint: "<implementation prompt>"
---

# Fork: Dual-Model Implementation

Implement the same task with both Claude Code and OpenAI Codex CLI in parallel git worktrees, then run the best-of skill to compare and select the superior implementation.

## Task

$ARGUMENTS

## Workflow

### Step 1: Validate Prerequisites

Verify both CLIs are available:

```bash
command -v claude || { echo "ERROR: claude CLI not found"; exit 1; }
CODEX=$(command -v codex || echo "$HOME/node_modules/.bin/codex")
test -x "$CODEX" || { echo "ERROR: codex CLI not found"; exit 1; }
```

If either is missing, report the error and stop.

### Step 2: Capture Context

Record the current state:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
BRANCH=$(git branch --show-current)
SHORT_SHA=$(git rev-parse --short HEAD)
```

Run `git status --porcelain`. If there are uncommitted changes, warn the user and ask whether to proceed — uncommitted changes will **not** be present in the worktrees — or abort.

### Step 3: Create Worktrees

Generate a short unique suffix:

```bash
SUFFIX=$(date +%s | tail -c 6)
```

Create two worktrees branching from the current HEAD:

```bash
git worktree add "$REPO_ROOT/../fork-claude-$SUFFIX" -b fork/claude-$SUFFIX HEAD
git worktree add "$REPO_ROOT/../fork-codex-$SUFFIX" -b fork/codex-$SUFFIX HEAD
```

Record the two worktree absolute paths and branch names — you will need them in every subsequent step.

### Step 4: Compose the Prompt

Create a temp file for the implementation prompt:

```bash
PROMPT_FILE=$(mktemp /tmp/fork-prompt-XXXXXX)
```

Write a self-contained implementation prompt to this file. The prompt must include:

1. The user's task from `$ARGUMENTS`.
2. Any project-level constraints from CLAUDE.md or AGENTS.md at the repo root (read the file and inline its relevant sections).
3. Key context: current branch name, language, framework — anything the task needs.
4. A closing instruction:

```
Implement this change completely. Commit all your work with a clear commit message when done.
```

This single prompt file is shared by both models so they receive identical instructions.

### Step 5: Run Both Models in Parallel

Launch both implementations simultaneously using **two parallel Bash tool calls**. Use a **600000 ms (10 minute) timeout** on both.

**Claude** (in worktree 1):

```bash
cd <claude-worktree-path> && \
claude -p --dangerously-skip-permissions --verbose < "$PROMPT_FILE"
```

**Codex** (in worktree 2):

```bash
cd <codex-worktree-path> && \
CODEX=$(command -v codex || echo "$HOME/node_modules/.bin/codex") && \
"$CODEX" exec --full-auto - < "$PROMPT_FILE"
```

No `-m` or `-c` flags for Codex — the user's `~/.codex/config.toml` supplies model and reasoning settings.

Both calls MUST be issued in the same message so they execute in parallel.

### Step 6: Handle Errors

After both complete, check results:

- **Both succeeded**: continue to Step 7.
- **One failed**: report the failure, present the successful implementation, and ask the user if they want to adopt it directly or retry the failed model.
- **Both failed**: report both errors, clean up (skip to Step 10), and suggest the user try the task manually.

A model "succeeded" if it exited zero AND produced at least one commit in its worktree (check with `git log <original-branch>..HEAD --oneline` in the worktree).

### Step 7: Collect Results

For each worktree, gather the implementation summary. Run these in **parallel** (two Bash calls):

```bash
cd <worktree-path> && \
echo "=== Commits ===" && \
git log --oneline <original-branch>..HEAD && \
echo "=== Stat ===" && \
git diff --stat <original-branch>..HEAD && \
echo "=== Diff ===" && \
git diff <original-branch>..HEAD
```

Note the results. Present a brief side-by-side summary to the user:

- Number of commits
- Files changed
- Lines added / removed

### Step 8: Run Best-Of

Invoke the `/best-of` skill, passing it:

- The original task prompt (`$ARGUMENTS`).
- **Claude's** branch name, worktree path, and the diff from Step 7.
- **Codex's** branch name, worktree path, and the diff from Step 7.

The best-of skill will compare both implementations — correctness, code quality, test coverage, adherence to the prompt — and recommend which to adopt or how to combine the best parts.

**Fallback** — if the best-of skill is not installed or fails to load: perform an inline comparison yourself. Read the diffs from Step 7 and evaluate both implementations on:

1. **Correctness** — does it fulfill the task?
2. **Code quality** — readability, idiomatic style, no unnecessary changes.
3. **Completeness** — tests, edge cases, documentation if warranted.
4. **Safety** — no security issues, no broken imports.

Present the comparison under this structure:

```
## Claude's Implementation
<brief summary and assessment>

## Codex's Implementation
<brief summary and assessment>

## Verdict
<which is better and why, or how to combine>
```

Then ask the user: **"Which implementation would you like to adopt — Claude's, Codex's, a combination, or neither?"**

### Step 9: Apply Winner

Based on the best-of result or the user's choice:

1. Switch back to the original branch:

   ```bash
   cd "$REPO_ROOT" && git switch <original-branch>
   ```

2. Merge the winning branch:

   ```bash
   git merge <winner-branch> --no-ff -m "Merge fork/<model>-$SUFFIX: <concise task summary>"
   ```

3. If the user chose a **hybrid** (parts from each): cherry-pick or manually apply the recommended combination, then commit.

**Always ask for user confirmation before merging.**

### Step 10: Cleanup

Remove the temp prompt file:

```bash
rm -f "$PROMPT_FILE"
```

Remove both worktrees:

```bash
git worktree remove "$REPO_ROOT/../fork-claude-$SUFFIX" --force
git worktree remove "$REPO_ROOT/../fork-codex-$SUFFIX" --force
git worktree prune
```

Optionally delete the fork branches if the user no longer needs them:

```bash
git branch -D fork/claude-$SUFFIX fork/codex-$SUFFIX
```

If the user wants to keep a worktree for inspection, skip its removal and report the path.

## Error Handling

- **Dirty working tree**: Warn and ask before proceeding — worktrees won't include uncommitted changes.
- **Worktree creation fails**: Clean up any partial state and report the error.
- **Model timeout**: If either model exceeds 10 minutes, kill the process, note the timeout, and proceed with whichever model finished.
- **Merge conflict**: If the winning branch conflicts with the original, report the conflicts and let the user resolve them.

## Constraints

- **Parallel execution**: Both models MUST run simultaneously, not sequentially.
- **Isolation**: Each model works in its own worktree and branch — no cross-contamination.
- **Identical starting point**: Both worktrees branch from the same HEAD commit.
- **Identical prompt**: Both models receive the exact same prompt file.
- **No bias**: Present results from both models without favoring either.
- **Cleanup**: Always remove worktrees and temp files unless the user explicitly asks to keep them.
- **User confirms merge**: Never merge a result without explicit user approval.
