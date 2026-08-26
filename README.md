# Skills

Personal skills for agentic coding with [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

## Installation

Install individual skills with the [`skills`](https://www.npmjs.com/package/skills) CLI:

```bash
npx skills@latest add pmatos/skills/<skill-name>
```

Add `-g` to install globally (`~/.claude/skills/`) instead of to the current project. Per-skill commands are listed below.

Or add the whole repository as a Claude Code plugin:

```bash
claude plugin add pmatos/skills
```

## Available Skills

### `/cp` — Commit & Push

```bash
npx skills@latest add pmatos/skills/cp
```

Commits and pushes changes to the current branch, running **only** the pre-commit checks described in the project's `CLAUDE.md` (or `AGENTS.md`). If the project specifies no requirements, it skips straight to commit and push.

What it does:
- Reads the nearest `CLAUDE.md`/`AGENTS.md` for commit-related requirements (formatting, linting, type-checking, tests, build, message conventions).
- Guards against accidental commits to `main`/`master`.
- Runs discovered checks in order: format → lint → type-check → test → build.
- Stages files, commits with a descriptive message, and pushes with upstream tracking.

Trigger phrases: `commit and push`, `cp`, `ship it`, `push my changes`.

### `/codex-2nd-opinion` — Codex Second Opinion

```bash
npx skills@latest add pmatos/skills/codex-2nd-opinion
```

Invokes OpenAI Codex CLI (GPT-5.4 with xhigh reasoning) to get an independent analysis on any discussion, plan, code, or thought. Presents both perspectives fairly with a structured comparison.

What it does:
- Gathers full context (code, Claude's analysis, constraints) into a self-contained prompt.
- Sends it to Codex CLI in read-only sandbox mode.
- Presents Codex's response alongside a structured comparison: points of agreement, disagreement, honest assessment, and recommended path forward.

Trigger phrases: `get a second opinion`, `ask codex`, `what does GPT think`, `compare with codex`, `2nd opinion`.

**Requires**: [OpenAI Codex CLI](https://github.com/openai/codex) installed and `OPENAI_API_KEY` set.

> **Scope — general-purpose, not just review.** This skill is deliberately broad: use it on any discussion, plan, code, or *thought*, not only on diffs. It assembles a self-contained prompt (Codex has no access to your conversation), respects the model and reasoning effort from your own Codex config rather than hardcoding them, and frames Claude's and Codex's views fairly against each other.
>
> For a *dedicated code-review* second opinion over git diffs, look at Trail of Bits' [`second-opinion` plugin](https://github.com/trailofbits/skills/tree/main/plugins/second-opinion). It is narrower but stronger for that one job: multi-model triangulation (OpenAI Codex **and** Google Gemini, run in parallel), diff-scope selection (uncommitted changes / branch diff / specific commit), and input guards (diff-size warnings, empty-diff detection).

### `/auto-merge-dependabot` — Auto-Merge Dependabot PRs

```bash
npx skills@latest add pmatos/skills/auto-merge-dependabot
```

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

```bash
npx skills@latest add pmatos/skills/wigo
```

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

```bash
npx skills@latest add pmatos/skills/pm-autofix-pr
```

Iteratively fixes CI failures and addresses reviewer feedback on a GitHub PR, working entirely in the local CLI. Monitors check results and reviewer feedback, evaluates each review on its merits, makes code changes only when warranted, runs local validation, commits, pushes, and repeats until CI is green, the PR has no merge conflicts with its base branch, and every feedback item has an outcome reply.

What it does:
- Detects the PR from the current branch (or accepts a PR number).
- Fetches failed CI checks, review threads, review summaries, and PR comments via the `gh` CLI.
- Evaluates each feedback item before acting: valid issues are fixed, invalid/out-of-scope issues are rejected with rationale, ambiguous comments prompt for user guidance.
- Runs local pre-commit checks from `CLAUDE.md` before each push.
- Commits and pushes fixes, then replies with what changed, where, and how it was validated.
- Replies to rejected feedback explaining why no code change was made.
- Processes new reviews as soon as they arrive instead of waiting for CI to finish first.
- Auto-resolves merge conflicts with the base branch by merging the base in, resolving conflicts, and re-running validation; exits with a clear `merge-conflict` failure only if a conflict genuinely can't be resolved automatically.
- Loops until fixed point: all CI green, no merge conflicts with the base branch, and all reviewer feedback answered one way or another.
- Presents a full summary of all changes for human review.

Trigger phrases: `autofix pr`, `fix pr locally`, `fix ci failures`, `fix review comments`, `iterate on pr`, `fix failing checks`, `fix pr comments`, `make ci green`, `fix the build`, `address reviewer feedback`.

**Requires**: [GitHub CLI](https://cli.github.com/) (`gh`), authenticated. A GitHub MCP server is optional — used opportunistically for thread resolution and comment posting if already connected, never required.

### `/rebase-pr` — Rebase a PR Safely

```bash
npx skills@latest add pmatos/skills/rebase-pr
```

Rebases a PR branch onto its base branch, resolves every conflict by hand, re-runs the project's quality gate, and force-pushes without clobbering a concurrent writer. `gh` CLI only — no GitHub MCP dependency.

What it does:
- Resolves the PR from the current branch (or accepts a PR number) and reads its real base branch — no hardcoded `main`.
- Captures the `--force-with-lease` anchor **before** the rebase, so a colleague who pushes mid-rebase is protected rather than overwritten; refreshing the anchor at push time is what silently clobbers them.
- Stands down, with their commits listed, if the branch already moved before the rebase started.
- Resolves conflicts file by file — never a bulk `git checkout ORIG_HEAD -- .` — and verifies zero unmerged paths, zero unstaged changes, and zero leftover conflict markers before each `git rebase --continue`.
- Detects the quality gate from `CLAUDE.md`/`AGENTS.md` or the manifests (npm/pnpm/yarn, uv/hatch, cargo, go, make, pre-commit) and runs each step separately, never `&&`-chained.
- Classifies each red step as REGRESSION (fix it) or PRE-EXISTING (verified once against the base branch, with evidence) instead of re-chasing known failures every session.
- Force-pushes through a lease armed with the pre-rebase anchor, then comments on the PR with what was resolved, what was skipped, and the gate results.
- Optionally waits for post-push CI under a single wall-clock budget, exiting with a resume-pointer comment rather than polling indefinitely (`--watch-ci`).

Trigger phrases: `rebase pr`, `rebase onto main`, `rebase this branch`, `rebase and force push`, `resolve rebase conflicts`, `my PR has conflicts`.

**Requires**: [GitHub CLI](https://cli.github.com/) (`gh`), authenticated.

### `/pm-plan` — Deep Implementation Planning (dual-harness)

```bash
npx skills@latest add pmatos/skills/pm-plan
```

Performs thorough, multi-phase implementation planning with parallel subagent exploration before any code is written. The workflow is identical whichever harness runs it — **Claude Code or OpenAI Codex CLI** — and only the mechanism for dispatching subagents (parallel exploration, plan naming, adversarial review) differs. The skill forks on capability, not identity: if it has a native `Agent`/`Task` tool (Claude Code) it spawns read-only `Explore` subagents directly; if its only way to run another model is the shell (Codex CLI) it dispatches `claude -p` headless subagents with a read-only tool allowlist. Produces a battle-tested, file-path-grounded plan at `.ultraplan/<plan-name>.md` (name generated from the task description).

What it does:
- Assesses task complexity and scales exploration depth accordingly (Small/Medium/Large).
- Dispatches parallel read-only Explore subagents — via the native `Agent`/`Task` tool (Claude Code) or backgrounded `claude -p` processes (Codex CLI) — to systematically map affected code areas.
- Drafts a structured plan with exact `file:line` references, ordered steps, and verification criteria.
- Validates all file references exist and dispatches an adversarial reviewer subagent to catch issues.
- Operates in strict read-only mode for the source tree — only `.ultraplan/<plan-name>.md` (and, on the shell path, a `/tmp/pm-plan-*` staging directory) are written. Read-only is enforced by a hard `Read,Grep,Glob` tool allowlist on the shell path and by the read-only `Explore` agent type on the native path.

Trigger phrases: `plan this`, `make a plan`, `implementation plan`, `deep plan`, `thorough plan`.

**Requires**: nothing extra on the native Claude Code path. On the Codex CLI (shell) path: `codex` invoked with `--sandbox workspace-write` (or higher) and the `claude` CLI authenticated and on `$PATH`.

### `/pm-cr` — Code Review

```bash
npx skills@latest add pmatos/skills/pm-cr
```

Reviews the current diff, or a PR number/branch/path target, for correctness bugs and reuse/simplification/efficiency/altitude/conventions cleanups at a chosen effort level.

What it does:
- Gathers the diff under review (`git diff <base>...HEAD` against the resolved default branch — `origin/HEAD` symref, then `gh repo view --json defaultBranchRef`, then a local `main`/`master`, with `HEAD~1` only as a disclosed last resort — plus any uncommitted working-tree changes and any untracked, non-ignored files), or reviews an explicit PR/branch/path argument (a PR or branch target must be checked out — the review is refused with a `gh pr checkout` hint rather than silently diffing the current branch).
- **low**: a single hunk-only read pass, no subagents, capped at 4 findings.
- **medium**: 8 parallel finder angles (3 correctness + Reuse/Simplification/Efficiency/Altitude/Conventions), up to 6 candidates each, then a 3-state verify pass (CONFIRMED/PLAUSIBLE/REFUTED) — capped at 8 findings, tuned for precision.
- **high**: the same 8 angles, but a recall-biased verify pass ("PLAUSIBLE by default") — capped at 10 findings, tuned for recall.
- **xhigh/max**: 10 parallel finder angles (adds a language-pitfall and a wrapper/proxy-correctness angle), up to 8 candidates each, recall-biased verify, plus a final gap-sweep pass — capped at 15 findings.
- **ultra**: no local equivalent to the built-in command's cloud multi-agent review, so it falls back to a local max-effort run instead.
- Falls back to a single inline pass through all angles for a level when no native subagent tool is available, instead of fanning out.
- `--fix` applies the reported findings to the working tree directly, skipping anything that would change behavior or fall outside the diff. `--comment` posts findings as inline PR comments (GitHub MCP tool, falling back to `gh api`). `--post`/`--no-post` only apply to `ultra` and are otherwise ignored with a note.
- Reuses the effort level last used earlier in the same conversation when none is given, defaulting to `medium` on first use.

Trigger phrases: `code review this`, `review this PR`, `review the diff`, `review my changes`, `review at high effort`, `review with fixes`.

### `/pm-simplify` — Simplify

```bash
npx skills@latest add pmatos/skills/pm-simplify
```

Cleans up the changed code without changing behavior. Reviews the diff for reuse, simplification, efficiency, and altitude issues, then fixes what it finds directly. Quality only — it does not hunt for correctness bugs.

What it does:
- Gathers the diff under review — the PR's base branch (or the remote's default branch) three-dot-diffed against `HEAD`, plus uncommitted working-tree changes and any untracked files (nothing gets staged) — or reviews an explicit PR/branch/path argument.
- If a native subagent tool (the `Agent`/`Task` tool) is available, launches four parallel review agents — one per angle: **Reuse** (re-implemented functionality that already exists in the codebase), **Simplification** (redundant state, copy-paste, deep nesting, dead code), **Efficiency** (redundant computation/I/O, sequential independent work, closures that leak large captured scopes), and **Altitude** (special cases bolted onto shared infrastructure instead of a deeper fix).
- Without a native subagent tool, works through all four angles inline in a single pass instead, and says so in its summary.
- Dedups overlapping findings and fixes each directly, skipping anything that would change behavior, reach outside the diff, or looks like a false positive — noting the skip rather than arguing with it.

Trigger phrases: `simplify this`, `simplify the diff`, `clean up this code`, `clean up the changed code`, `reuse pass`, `simplification pass`, `efficiency pass`, `altitude pass`.

### `/fork` — Dual-Model Implementation

```bash
npx skills@latest add pmatos/skills/fork
```

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

### `/best-of` — Code Comparison

```bash
npx skills@latest add pmatos/skills/best-of
```

Compares code across two git worktrees against 15 software-engineering best practices and the project's contribution guidelines (`CLAUDE.md`, `CONTRIBUTING.md`, linter configs). Dispatches parallel analysis agents, scores each solution on a weighted rubric, and presents a structured verdict with specific `file:line` evidence.

What it does:
- Validates both input paths are git worktrees.
- Dispatches parallel agents scoring correctness, security, SOLID/DRY, testing, idiomaticity, and project-convention adherence.
- Applies a 15-criteria weighted rubric; every claim is anchored to `file:line` evidence.
- Emits a structured verdict (winner, per-criterion scores, rationale, specific citations).
- Used internally by `/fork`, but runs standalone against any pair of worktrees.

Trigger phrases: `best of`, `compare worktrees`, `compare solutions`, `which solution is better`, `pick the better implementation`, `evaluate solutions`.

No external dependencies.

### `/is-skill` — Skill Extraction Analyzer

```bash
npx skills@latest add pmatos/skills/is-skill
```

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

### `brainstorming` — Collaborative Design

```bash
npx skills@latest add pmatos/skills/brainstorming
```

Guides collaborative design before implementation. Explores user intent through one-question-at-a-time dialogue, proposes 2-3 approaches with trade-offs, presents the design in sections for approval, then writes and commits a spec document. Stops at the approved spec — does not auto-trigger implementation.

What it does:
- Enforces a hard gate: no code, no scaffolding until the user approves a design.
- Explores project context (files, docs, recent commits) before asking questions.
- Asks clarifying questions one at a time to surface purpose, constraints, and success criteria.
- Proposes 2-3 approaches with trade-offs and a recommendation.
- Presents the design incrementally; each section requires explicit approval.
- Saves the spec to `docs/specs/YYYY-MM-DD-<topic>-design.md` and commits it.

Trigger phrases: `brainstorm`, `help me design`, `before I build this`, `let's figure out what to build`.

Forked from [obra/superpowers](https://github.com/obra/superpowers) with superpowers-specific references removed.

### `extract-design-system` — Extract a Design System from a URL

```bash
npx skills@latest add pmatos/skills/extract-design-system
```

Turns a public URL into a local git repo containing that site's real design assets: downloaded fonts, inline SVG logos, favicons, Open Graph image, stylesheets, and CSS custom properties. Produces a fact-only `README.md` and a structured `manifest.json` — ready to feed into `claude.ai/design` or use as a reference baseline.

What it does:
- Fetches the page with `requests` and parses HTML + all linked stylesheets (following `@import` one level).
- Downloads every `@font-face` source into `fonts/`.
- Extracts `:root` / `html` CSS custom properties into `tokens/variables.css`.
- Saves favicons, Apple touch icons, and web-manifest icons into `images/favicons/`.
- Captures inline `<svg>` blocks (candidate logos) into `logos/`.
- Writes a fact-only `README.md` — never inferred from visual inspection.
- Falls back to Playwright CLI (or MCP Playwright / claude-in-chrome) for JS-rendered pages.

Trigger phrases: `extract design system`, `steal a design`, `pull fonts and colors from a site`, `scrape design tokens`, `build a design-system repo from a URL`.

**Requires**: [`uv`](https://github.com/astral-sh/uv) for the extraction script; [Playwright](https://playwright.dev/) and `node` only if the target page is JS-rendered.

### `upscale` — Local Super-Resolution Image Upscaling

```bash
npx skills@latest add pmatos/skills/upscale
```

Upscales an existing raster image with a local OpenCV EDSR model, then writes and verifies an exact requested pixel size.

What it does:
- Uses OpenCV `dnn_superres` with EDSR models (`x2`, `x3`, or `x4`) rather than plain interpolation.
- Downloads models into `~/.cache/codex-upscale/models/` on first use.
- Processes large images in overlapping tiles to reduce memory spikes and avoid visible seams.
- Supports exact output dimensions with `stretch`, `cover`, or `contain` fitting.
- Can preserve the raw EDSR output before final resizing for inspection.
- Verifies the written file dimensions after generation.

Trigger phrases: `upscale image`, `enlarge this image`, `super-resolve`, `make this higher resolution`, `make a 5120x2160 version`.

**Requires**: [`uv`](https://github.com/astral-sh/uv) for the bundled script, plus network access on first use to download the EDSR model.

### `codestory` — Code as a Running Narrative

```bash
npx skills@latest add pmatos/skills/codestory
```

Turns a PR, branch, working-tree diff, file, path or whole project into a story told alongside the code, so a reviewer can check whether it does what they expect.

What it does:
- Narrates in **beats** — one narrative idea each — pausing after every beat to offer *continue*, *go deeper*, *show the verbatim code*, or *skip this area*.
- Follows the code's **flow**, not the file order. For a PR or branch the story is about the *change*: what it did before, what it does now, what that means for callers.
- Tells the story **against the stated intent** (PR description, commit messages, linked issue) and flags what the code does that the intent never mentioned.
- Dispatches **lens subagents** — interfaces, control/data flow, external dependencies, IO and side effects, error handling, situating context, tests-as-specification — which produce *leads*, never prose. The narrator re-reads the source before describing anything.
- Anchors every excerpt to `path:line`; simplified excerpts, inferences and invented examples all carry explicit markers.
- **Explains, never judges** — it will say "this early return skips the cleanup below", never "this is a bug". Verdicts belong to the reviewer.
- Scales by size tier (read-everything / partition-and-synthesise / structural map with lazy reads), computed deterministically and shown before it is spent.
- Reports every skipped file (lockfiles, generated, vendored, binaries) so nothing is silently unnarrated.
- Accumulates the story at `.stories/<slug>.md` as it goes; resumable, with a staleness check against the recorded SHA.

Trigger phrases: `walk me through this code`, `tell me the story of this PR`, `explain this branch`, `help me review this`, `what does this code actually do`, `codestory`.

**Requires**: a git repository. [`gh`](https://cli.github.com/) only for PR targets and issue context — it degrades to history-only when absent. Interactive only; there is no headless mode.

## License

MIT
