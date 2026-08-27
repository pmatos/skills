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

## Pull requests

**The PR title must be a Conventional Commit**, enforced by
`.github/workflows/lint-pr-title.yml`. This is a *separate* check from the
commit-message hook, and it reads the PR title only — a valid commit message
does not imply a valid PR title, so a title typed by hand at `gh pr create`
time is the usual thing that fails.

A skill name is a **scope**, not a type. The type prefix is mandatory:

```text
feat(pm-deepen): adopt the branch the caller prepared     # correct
pm-deepen: adopt the branch the caller prepared           # fails: no type
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
`build`, `ci`, `chore`, `revert`. Fix a rejected title in place with
`gh pr edit <n> --title "..."` — the check re-runs on edit, no push needed.

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

## rebase-pr

Slash command `/rebase-pr` that rebases a PR branch onto its base branch, resolves conflicts file by file, re-runs the project's detected quality gate, and force-pushes through a `--force-with-lease` armed with an anchor captured *before* the rebase — so a concurrent writer is protected instead of clobbered. `gh` CLI only. Bundles `scripts/capture-lease.sh` (anchor capture plus ahead/behind/diverged classification) and `scripts/safe-force-push.sh` (re-inspect, stand down, or push).

## pm-plan

Skill `/pm-plan` (dual-harness) that performs deep, multi-phase implementation planning before writing any code. The shared workflow runs under either harness; a capability fork selects the dispatch mechanism for parallel exploration, plan-name generation, and adversarial review: the native `Agent`/`Task` tool (Claude Code) or `claude -p` headless subagents (OpenAI Codex CLI, which has no native subagent tool). Mechanics live in `references/dispatch-claude.md` and `references/dispatch-codex.md`. Produces a structured plan at `.ultraplan/<plan-name>.md`. The shell path requires `codex --sandbox workspace-write` and `claude` on `$PATH`; the native path needs neither.

## pm-cr

Slash command `/pm-cr` that reviews the current diff, or a PR/branch/path target, for correctness bugs and reuse/simplification/efficiency/altitude/conventions cleanups at a chosen effort level (low/medium/high/xhigh/max/ultra, defaulting to whatever was last used this conversation). Low/medium favor precision; high through max fan out across up to 10 parallel finder angles, verify each candidate (3-state at medium, recall-biased above it), and xhigh/max add a gap-sweep pass. `--fix` applies the findings directly, `--comment` posts them as inline PR comments, `ultra` (no local cloud access) falls back to a local max-effort review. Mechanics live in `references/angles.md`, `references/effort-levels.md`, and `references/output-and-flags.md`.

## pm-simplify

Slash command `/pm-simplify` that cleans up the changed code without changing behavior. Reviews the diff for reuse, simplification, efficiency, and altitude issues via four parallel review agents (falling back to a single inline pass when no native subagent tool is available), then fixes what it finds directly. Quality only — does not hunt for correctness bugs.

## fork

Slash command `/fork` that accepts a prompt and implements it with both Claude Code and OpenAI Codex CLI in parallel git worktrees. After both finish, runs the best-of skill to compare implementations and pick the winner.

## best-of

Slash command `/best-of` that compares code across two git worktrees against 15 software engineering best practices (correctness, security, SOLID, DRY, testing, etc.) and project contribution guidelines (CLAUDE.md, CONTRIBUTING.md, linter configs). Dispatches parallel analysis agents, scores each solution on a weighted rubric, and presents a structured verdict with specific file:line evidence.

## is-skill

Slash command `/is-skill` that analyzes the current session's conversation, context, and work patterns to determine whether the knowledge or workflow used could be extracted into a reusable Claude Code skill. Classifies proposals as user-level (cross-project, issue filed in `pmatos/skills`) or project-specific (issue filed in the current project's repo), then creates a GitHub issue with a structured skill proposal after user approval.

## upscale

Skill that upscales raster images with a local OpenCV EDSR super-resolution model, writes an exact requested pixel size, and verifies the final dimensions.

## codestory

Slash command `/codestory` that turns a PR, branch, working-tree diff, file, path or whole project into a flow-ordered story told beat by beat, pausing after each beat so the reader can ask for more detail or move on. Built for code review: it explains so the human can judge and never issues verdicts itself. Lens subagents (interfaces, control flow, dependencies, IO, error handling, situating context, tests-as-spec) gather leads only — the narrator re-reads the source before every beat, and every excerpt carries a `path:line` anchor. Fan-out shape follows a size tier computed by `scripts/resolve-target.sh`. The story accumulates at `.stories/<slug>.md` and is resumable.

## pm-deepen

Slash command `/pm-deepen` that runs an architecture review end to end with **no questions**, so it is safe for cron jobs, routines and headless firings. Scans for deepening opportunities (shallow modules whose interface is nearly as complex as their implementation), scores each on leverage (doubled), locality, heat and inverted blast radius, auto-picks the top one, explores interfaces via `codebase-design`'s design-it-twice sub-agents, adjudicates the winner with a fresh sub-agent instead of the interactive `grilling` loop, implements it test-first, and opens a PR. It adopts the branch it was started on when that branch is provably its own to take (non-default, no unique history, no upstream, unpublished) — the state a headless harness leaves a prepared workspace in, and what keeps the PR discoverable by its head branch — otherwise cutting its own from `origin/<default-branch>`. The deliverable is a committed markdown report at `.architecture/reviews/<date>-<slug>.md` (GitHub-rendered Mermaid, no `xdg-open`) plus a persisted `.architecture/backlog.md` that dedups against already-landed refactors. Forked from Matt Pocock's [`improve-codebase-architecture`](https://github.com/mattpocock/skills), which is interactive by design; the exploration heuristics, candidate-card fields and vocabulary discipline are his.
