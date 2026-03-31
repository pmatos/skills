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

### Codex Second Opinion

This skill has been removed. Use the [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) marketplace plugin instead.

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

## License

MIT
