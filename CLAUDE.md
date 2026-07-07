# Skills

Personal skills for agentic coding with Claude Code.

## Checks

Run the lint gate before committing (also enforced in CI by
`.github/workflows/lint.yml`):

```bash
pre-commit run --all-files
```

It covers ruff (Python), shfmt + shellcheck (shell), markdownlint-cli2 (Markdown),
actionlint + zizmor (workflows), and the SKILL.md frontmatter validator. Install
the git hook once with `pre-commit install`.

## cp

Slash command `/cp` that commits and pushes changes to the current branch, running only the pre-commit checks described in the project's CLAUDE.md (or AGENTS.md) — nothing more, nothing less.

## codex-2nd-opinion

Slash command `/codex-2nd-opinion` that invokes OpenAI Codex CLI (GPT-5.4) to get an independent second opinion on any discussion, plan, or code. Presents both Claude's and Codex's perspectives with a structured, fair comparison.

## auto-merge-dependabot

Slash command `/auto-merge-dependabot` that reviews all open Dependabot PRs in the current repository, assesses each for risk (version bump type, CI status, file scope), and automatically merges safe ones while flagging those that need manual review.

## brainstorming

Skill that guides collaborative design before implementation. Explores user intent through one-at-a-time questions, proposes 2-3 approaches with trade-offs, presents the design incrementally for approval, then writes and commits a spec document. Stops at the approved spec — does not auto-trigger implementation. Forked from [obra/superpowers](https://github.com/obra/superpowers) brainstorming skill with all references to other superpowers skills removed.

## wigo

Slash command `/wigo` (What Is Going On?) that gives a comprehensive situational briefing on the current git tree: branch state, dirty files, recent session history, associated PR status (CI, reviews, mergeability), and suggests actionable next steps.

## pm-autofix-pr

Slash command `/pm-autofix-pr` that iteratively fixes CI failures and addresses reviewer feedback on a GitHub PR from the local CLI. Fetches CI and review state, evaluates each feedback item on its merits, fixes valid issues, replies with no-change rationale for invalid or out-of-scope feedback, auto-resolves merge conflicts with the base branch, runs local pre-commit checks, commits, pushes, and loops until CI is green, the PR has no merge conflicts, and all feedback has an outcome reply.

## pm-plan

Skill `/pm-plan` (dual-harness) that performs deep, multi-phase implementation planning before writing any code. The shared workflow runs under either harness; a capability fork selects the dispatch mechanism for parallel exploration, plan-name generation, and adversarial review: the native `Agent`/`Task` tool (Claude Code) or `claude -p` headless subagents (OpenAI Codex CLI, which has no native subagent tool). Mechanics live in `references/dispatch-claude.md` and `references/dispatch-codex.md`. Produces a structured plan at `.ultraplan/<plan-name>.md`. The shell path requires `codex --sandbox workspace-write` and `claude` on `$PATH`; the native path needs neither.

## fork

Slash command `/fork` that accepts a prompt and implements it with both Claude Code and OpenAI Codex CLI in parallel git worktrees. After both finish, runs the best-of skill to compare implementations and pick the winner.

## best-of

Slash command `/best-of` that compares code across two git worktrees against 15 software engineering best practices (correctness, security, SOLID, DRY, testing, etc.) and project contribution guidelines (CLAUDE.md, CONTRIBUTING.md, linter configs). Dispatches parallel analysis agents, scores each solution on a weighted rubric, and presents a structured verdict with specific file:line evidence.

## is-skill

Slash command `/is-skill` that analyzes the current session's conversation, context, and work patterns to determine whether the knowledge or workflow used could be extracted into a reusable Claude Code skill. Classifies proposals as user-level (cross-project, issue filed in `pmatos/skills`) or project-specific (issue filed in the current project's repo), then creates a GitHub issue with a structured skill proposal after user approval.

## upscale

Skill that upscales raster images with a local OpenCV EDSR super-resolution model, writes an exact requested pixel size, and verifies the final dimensions.
