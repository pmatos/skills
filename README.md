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

## License

MIT
