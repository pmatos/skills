# Skills

Personal skills for agentic coding with Claude Code.

## cp

Slash command `/cp` that commits and pushes changes to the current branch, running only the pre-commit checks described in the project's CLAUDE.md (or AGENTS.md) — nothing more, nothing less.

## auto-merge-dependabot

Slash command `/auto-merge-dependabot` that reviews all open Dependabot PRs in the current repository, assesses each for risk (version bump type, CI status, file scope), and automatically merges safe ones while flagging those that need manual review.
