---
name: best-of
description: This skill should be used when the user asks to "compare code", "compare worktrees", "compare solutions", "which solution is better", "compare branches", "best of", "diff worktrees", "evaluate solutions", "pick the better implementation", "compare implementations", "review both solutions", or wants a structured, criteria-driven comparison of code across two git worktrees. Also triggered by the /best-of command.
argument-hint: "<worktree-path-A> <worktree-path-B> [focus area or file path]"
user-invocable: true
---

# Code Comparison

Compare two git worktrees side-by-side against software engineering best practices and project contribution guidelines. Produce a structured, evidence-based verdict on which solution is better and why.

## Task

$ARGUMENTS

## Workflow

### Step 1: Parse Inputs and Validate Worktrees

Extract the two worktree paths from the arguments. If an optional focus area or file path is provided, note it for scoped analysis.

```bash
# Validate both paths are git worktrees or repositories
git -C <worktree-A> rev-parse --show-toplevel
git -C <worktree-B> rev-parse --show-toplevel
```

If either path is invalid, report the error and stop. If only one path or no path is provided, ask the user for the missing worktree path(s) using the AskUserQuestion tool.

Identify the worktrees:
- **Worktree A**: first path argument
- **Worktree B**: second path argument

Run a quick orientation in both:

```bash
# For each worktree
git -C <worktree> log --oneline -5
git -C <worktree> branch --show-current
git -C <worktree> diff --stat HEAD~1 HEAD  # last commit's scope
```

If the two worktrees share a common ancestor (same repo, different branches), compute the divergence:

```bash
MERGE_BASE=$(git -C <worktree-A> merge-base HEAD <worktree-B-branch>)
git -C <worktree-A> diff --stat $MERGE_BASE HEAD
git -C <worktree-B> diff --stat $MERGE_BASE HEAD
```

### Step 2: Discover Project Guidelines

Search **both** worktrees for contribution and convention files. Collect every rule that applies.

Files to search for (using Glob in each worktree root):

- `CLAUDE.md`, `AGENTS.md`, `**/CLAUDE.md`, `**/AGENTS.md`
- `CONTRIBUTING.md`, `CONTRIBUTING.rst`
- `.editorconfig`
- Linter configs: `.eslintrc*`, `.prettierrc*`, `pyproject.toml`, `setup.cfg`, `.flake8`, `.rubocop.yml`, `biome.json`, `deno.json`
- CI configs: `.github/workflows/*.yml`, `Makefile`, `Taskfile.yml`, `justfile`
- `package.json` (scripts and lint config sections), `Cargo.toml`, `go.mod`

Read each file found. Extract every actionable rule, convention, or constraint. Compile them into a **Project Rules Checklist** — one line per rule, with the source file referenced. This checklist is used in Step 5.

If the two worktrees have different guideline files, note the differences — this itself is a finding.

### Step 3: Identify the Comparison Surface

Determine which files to compare. Use one of these strategies depending on context:

**Strategy A — Common ancestor diff** (preferred when worktrees share history):
```bash
# Files changed in A since divergence
git -C <worktree-A> diff --name-only $MERGE_BASE HEAD

# Files changed in B since divergence
git -C <worktree-B> diff --name-only $MERGE_BASE HEAD
```

**Strategy B — Direct diff** (when worktrees are independent):
```bash
diff -rq --exclude='.git' <worktree-A> <worktree-B> | head -100
```

**Strategy C — Focused** (when user specified a file or directory):
Compare only the specified path(s) across both worktrees.

Build the **File Comparison Manifest** — a list of file pairs to compare, categorized:
- Files modified in both (direct comparison)
- Files only in A (unique to A's approach)
- Files only in B (unique to B's approach)
- Files identical in both (skip these)

### Step 4: Deep Analysis — Parallel Agents

Dispatch **three** parallel agents (Agent tool, subagent_type: "general-purpose"). All three run in a single message. Each agent receives the File Comparison Manifest and the Project Rules Checklist from Step 2.

**Agent 1 — Correctness & Logic**
> "You are reviewing two code solutions side by side. Read the following files from both worktrees and evaluate:
> 1. **Correctness**: Does each solution produce correct results? Check edge cases, error paths, race conditions, off-by-one errors.
> 2. **Error handling**: Are errors caught at boundaries, propagated meaningfully, not swallowed?
> 3. **Type safety**: Are types precise? Are escape hatches (any, Object, void*) minimized?
> 4. **Security**: Check OWASP top 10 — injection, XSS, path traversal, secrets in code.
>
> For each criterion, state which worktree is stronger and cite specific file:line evidence.
>
> Worktree A: <path-A>
> Worktree B: <path-B>
> Files to compare: <manifest>
> Project rules: <checklist>"

**Agent 2 — Design & Architecture**
> "You are reviewing two code solutions side by side. Read the following files from both worktrees and evaluate:
> 1. **Readability & clarity**: Names, control flow, comments, formatting.
> 2. **DRY**: Duplication, reuse of existing utilities.
> 3. **SOLID principles**: Single responsibility, open/closed, dependency inversion — applied pragmatically.
> 4. **Separation of concerns**: Business logic vs I/O vs presentation.
> 5. **Complexity**: Cyclomatic complexity, nesting depth, cognitive load.
> 6. **API & interface design**: Function signatures, public surface area, consistency.
>
> For each criterion, state which worktree is stronger and cite specific file:line evidence.
>
> Worktree A: <path-A>
> Worktree B: <path-B>
> Files to compare: <manifest>
> Project rules: <checklist>"

**Agent 3 — Practices, Testing & Compliance**
> "You are reviewing two code solutions side by side. Read the following files from both worktrees and evaluate:
> 1. **Testing**: Coverage, test quality, edge case tests, alignment with project test patterns.
> 2. **Naming & conventions**: Adherence to project naming conventions found in linter configs and contribution docs.
> 3. **Git hygiene**: Commit atomicity, message quality, minimal diff, no debug artifacts.
> 4. **Performance**: Unnecessary allocations, algorithmic complexity, appropriate data structures.
> 5. **Project guideline compliance**: Check every rule in the Project Rules Checklist below. Flag each violation with the rule and source file.
>
> For each criterion, state which worktree is stronger and cite specific file:line evidence.
>
> Worktree A: <path-A>
> Worktree B: <path-B>
> Files to compare: <manifest>
> Project rules: <checklist>"

### Step 5: Synthesize and Score

Collect findings from all three agents. For each of the 15 evaluation criteria (see `references/evaluation-criteria.md`), assign a score (1-5) to each worktree based on agent findings:

| # | Criterion | Worktree A | Worktree B | Notes |
|---|-----------|:----------:|:----------:|-------|
| 1 | Correctness | | | |
| 2 | Readability & Clarity | | | |
| 3 | DRY | | | |
| 4 | SOLID Principles | | | |
| 5 | Error Handling | | | |
| 6 | Security | | | |
| 7 | Testing | | | |
| 8 | Performance | | | |
| 9 | Naming & Conventions | | | |
| 10 | Separation of Concerns | | | |
| 11 | Complexity | | | |
| 12 | Type Safety | | | |
| 13 | API & Interface Design | | | |
| 14 | Git Hygiene | | | |
| 15 | Project Guideline Compliance | | | |

Compute the totals. Do NOT use a simple sum as the verdict — weigh correctness and security higher than naming and git hygiene. Use this weighting:

| Weight | Criteria |
|--------|----------|
| **3x** | Correctness, Security |
| **2x** | Error Handling, Testing, Project Guideline Compliance |
| **1x** | All others |

### Step 6: Present the Verdict

Present to the user with this structure:

```
## Code Comparison: Worktree A vs Worktree B

### Summary
<2-3 sentence verdict: which solution is better overall and the primary reasons why>

### Scorecard
<the scoring table from Step 5, filled in with scores and notes>

### Weighted Totals
- **Worktree A**: <weighted score> / <max possible>
- **Worktree B**: <weighted score> / <max possible>

### Key Differentiators
<Top 3-5 criteria where the solutions differ most, with specific code citations>

#### Where A is Stronger
- <criterion>: <evidence with file:line>

#### Where B is Stronger
- <criterion>: <evidence with file:line>

### Project Guideline Violations
<List every violation found, grouped by worktree, with rule source>

### Recommendations
<If neither solution is clearly superior, describe how to combine the best parts of each.
 If one is clearly better, note any specific improvements it could still make.>
```

End by asking: **"Would you like me to go deeper on any specific criterion, or apply the best parts of both solutions into a combined implementation?"**

## Constraints

- **Read-only**: Do NOT modify any files in either worktree. This is a review, not an implementation.
- **Evidence-based**: Every claim must cite a specific file:line from one of the worktrees. No vague assertions.
- **Fair**: Do not favor one worktree over the other by default. Let the evidence decide.
- **Proportional**: Scale depth to the size of the diff. A 5-line change doesn't need 15 criteria analyzed in depth — focus on what matters. A 500-line change warrants thorough analysis across all criteria.
- **No phantom references**: Every file:line citation must be verified against the actual code.
- **Project-aware**: The Project Rules Checklist from Step 2 is mandatory. Compliance with project guidelines is not optional.

## Additional Resources

See `references/evaluation-criteria.md` (bundled with this skill) for detailed scoring guidance and criteria definitions.
