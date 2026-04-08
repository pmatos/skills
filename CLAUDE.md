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
