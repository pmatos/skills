# Skills

Personal skills for agentic coding with [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

## Installation

Add this repository to your Claude Code configuration:

```bash
claude plugin add /path/to/skills
```

Or install from GitHub:

```bash
claude plugin add pmatos/skills
```

## Available Skills

### `/cp` — Commit & Push

Commits and pushes changes to the current branch, running **only** the pre-commit checks described in the project's `CLAUDE.md` (or `AGENTS.md`). If the project specifies no requirements, it skips straight to commit and push.

What it does:
- Reads the nearest `CLAUDE.md`/`AGENTS.md` for commit-related requirements (formatting, linting, type-checking, tests, build, message conventions).
- Guards against accidental commits to `main`/`master`.
- Runs discovered checks in order: format → lint → type-check → test → build.
- Stages files, commits with a descriptive message, and pushes with upstream tracking.

Trigger phrases: `commit and push`, `cp`, `ship it`, `push my changes`.

### `/codex-2nd-opinion` — Codex Second Opinion

Invokes OpenAI Codex CLI (GPT-5.4 with xhigh reasoning) to get an independent analysis on any discussion, plan, code, or thought. Presents both perspectives fairly with a structured comparison.

What it does:
- Gathers full context (code, Claude's analysis, constraints) into a self-contained prompt.
- Sends it to Codex CLI in read-only sandbox mode.
- Presents Codex's response alongside a structured comparison: points of agreement, disagreement, honest assessment, and recommended path forward.

Trigger phrases: `get a second opinion`, `ask codex`, `what does GPT think`, `compare with codex`, `2nd opinion`.

**Requires**: [OpenAI Codex CLI](https://github.com/openai/codex) installed and `OPENAI_API_KEY` set.

### `/auto-merge-dependabot` — Auto-Merge Dependabot PRs

Reviews all open Dependabot PRs in the current repository, assesses each for risk, and automatically merges safe ones while flagging those that need manual review.

What it does:
- Lists all open Dependabot PRs via `gh`.
- Assesses each PR on: version bump type (patch/minor/major), CI status, changed file scope, security advisories, and merge conflicts.
- Merges safe PRs (patch/minor, CI green, dependency-only changes) with `--squash --auto`.
- Requests `@dependabot rebase` on PRs with conflicts.
- Flags major bumps, CI failures, and unexpected changes for manual review.

Trigger phrases: `merge dependabot PRs`, `review dependabot`, `auto-merge dependencies`.

**Requires**: [GitHub CLI](https://cli.github.com/) (`gh`) authenticated.

### `/wigo` — What Is Going On?

Gives a comprehensive situational briefing on the current git tree. Mines git state, Claude session history, and GitHub to tell you where you are, what you've been doing, and what to do next.

What it does:
- Reports branch name, dirty state (staged/unstaged/untracked), and stashes.
- Summarizes recent git commits and how far ahead of the default branch you are.
- Searches Claude session logs to reconstruct what you were working on in previous sessions.
- Finds the PR associated with the current branch and reports CI status, reviews, mergeability, and recent comments.
- Suggests contextual next steps: merge the PR, address review feedback, investigate CI failures, commit and push, create a PR, etc.

Trigger phrases: `what's going on`, `wigo`, `status`, `where was I`, `what were we doing`, `catch me up`, `tree status`.

**Requires**: [GitHub CLI](https://cli.github.com/) (`gh`) authenticated.

### `/pm-autofix-pr` — Autofix PR

Iteratively fixes CI failures and addresses review comments on a GitHub PR, working entirely in the local CLI. Monitors check results and reviewer feedback, makes code changes, runs local validation, commits, pushes, and waits for CI — repeating until all issues are resolved or a maximum iteration count is reached.

What it does:
- Detects the PR from the current branch (or accepts a PR number).
- Fetches failed CI checks and unresolved review comments via `gh`.
- Classifies issues: clear fixes are applied automatically, ambiguous comments prompt for user guidance.
- Runs local pre-commit checks from `CLAUDE.md` before each push.
- Commits and pushes fixes, replies to addressed review comments.
- Waits for CI to complete, then checks for new issues.
- Loops until fix point (all CI green + no unresolved comments) or max iterations (default 5).
- Presents a full summary of all changes for human review.

Trigger phrases: `autofix pr`, `fix pr locally`, `fix ci failures`, `fix review comments`, `iterate on pr`, `fix failing checks`, `fix pr comments`, `make ci green`, `fix the build`, `address reviewer feedback`.

**Requires**: [GitHub CLI](https://cli.github.com/) (`gh`) authenticated with a token that has `repo` scope (read and write access to pull requests).

### `/pm-plan` — Deep Implementation Planning

Performs thorough, multi-phase implementation planning with parallel agent exploration before any code is written. Produces a battle-tested, file-path-grounded plan at `.ultraplan/<plan-name>.md` (name generated from the task description).

What it does:
- Assesses task complexity and scales exploration depth accordingly (Small/Medium/Large).
- Dispatches parallel Explore agents to systematically map affected code areas.
- Drafts a structured plan with exact `file:line` references, ordered steps, and verification criteria.
- Validates all file references exist and runs adversarial review to catch issues.
- Operates in strict read-only mode — only the plan file is written.

Trigger phrases: `plan this`, `make a plan`, `implementation plan`, `deep plan`, `thorough plan`.

No external dependencies.

### `/fork` — Dual-Model Implementation

Implements the same task with both Claude Code and OpenAI Codex CLI in parallel git worktrees, then runs the best-of skill to compare and select the superior implementation.

What it does:
- Creates two isolated git worktrees from the current HEAD.
- Sends the identical prompt to both Claude Code (`claude -p`) and Codex (`codex exec --full-auto`) in parallel.
- Collects the diffs and commit history from each implementation.
- Invokes the best-of skill to compare correctness, code quality, and completeness — or performs an inline comparison as a fallback.
- Merges the winning implementation into the original branch (with user confirmation).
- Cleans up worktrees and temporary branches.

Trigger phrases: `fork`, `race claude and codex`, `dual implement`, `run both models`, `compare implementations`, `implement with both`.

**Requires**: [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) and [OpenAI Codex CLI](https://github.com/openai/codex) installed with `OPENAI_API_KEY` set.


### `/is-skill` — Skill Extraction Analyzer

Analyzes the current session's conversation, context, and work patterns to determine whether the knowledge or workflow used could be extracted into a reusable Claude Code skill. Creates a GitHub issue with a structured proposal after user approval.

What it does:
- Mines session logs and conversation history to identify repeatable patterns, complex workflows, or domain knowledge worth codifying.
- Evaluates skill indicators: repeated workflows, complex coordination, domain knowledge bottlenecks, user-taught processes.
- Classifies the proposal as user-level (general, cross-project) or project-specific.
- Drafts a structured skill proposal with name, trigger phrases, workflow outline, and extracted knowledge.
- Presents the proposal for user approval before creating a GitHub issue.
- Creates the issue in `pmatos/skills` for user-level skills, or in the current project's repo for project-specific skills.

Trigger phrases: `is this a skill`, `can we extract a skill`, `skill extraction`, `is there a reusable pattern here`, `should this be a skill`, `extract skill`.

**Requires**: [GitHub CLI](https://cli.github.com/) authenticated (optional, for automated issue creation).

## License

MIT
