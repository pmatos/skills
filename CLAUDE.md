# Skills

Personal skills for agentic coding with Claude Code.

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

Slash command `/pm-autofix-pr` that iteratively fixes CI failures and addresses review comments on a GitHub PR from the local CLI. Fetches failures and comments, makes fixes, runs local pre-commit checks, commits, pushes, waits for CI, and loops until convergence or max iterations.

## pm-plan

Slash command `/pm-plan` that performs deep, multi-phase implementation planning with parallel agent exploration, targeted clarifying questions, and structured plan output to `.ultraplan/<plan-name>.md` — all locally, without web sessions.

## best-of

Slash command `/best-of` that compares code across two git worktrees against 15 software engineering best practices (correctness, security, SOLID, DRY, testing, etc.) and project contribution guidelines (CLAUDE.md, CONTRIBUTING.md, linter configs). Dispatches parallel analysis agents, scores each solution on a weighted rubric, and presents a structured verdict with specific file:line evidence.
