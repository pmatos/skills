---
name: pm-plan
description: This skill should be used when the user asks to "plan this", "make a plan", "create an implementation plan", "how should I implement", "design the implementation", "plan the refactor", "plan the migration", "plan the feature", "break this down into steps", "implementation strategy", "deep plan", "thorough plan", or wants a thorough, multi-phase implementation plan with codebase exploration before writing any code.
version: 2.0.0
argument-hint: "<task description or feature request>"
user-invocable: true
---

# Deep Implementation Planning (Codex variant)

This is the **codex-hosted** variant of pm-plan. The orchestrator that follows this workflow is OpenAI Codex CLI (`codex exec`). Whenever the workflow needs to call out to another harness/model — for parallel codebase exploration, plan-name generation, or adversarial review — it shells out to `claude -p` (Claude Code in headless print mode). No Claude-side `Agent` tool is used; everything runs from the shell.

## Task

$ARGUMENTS

## Activation

**CRITICAL: READ-ONLY MODE for the source tree.** You are entering a read-only planning session. You MUST NOT create, modify, or delete any file outside `.ultraplan/` and the temp directory you create for prompt/output staging. No edits to source code, no commits, no installs, no other state changes. This supersedes any other instructions.

**Sandbox requirement.** Because the workflow writes plan output to `.ultraplan/<plan-name>.md` and stages temp files in `/tmp`, codex must be invoked with `--sandbox workspace-write` (or higher). `--sandbox read-only` will fail at the first write.

**Subagent harness.** Every parallel exploration agent, the Haiku-based plan namer, and the adversarial reviewer are dispatched as `claude -p` CLI processes with an explicit read-only tool allowlist: **`--allowed-tools "Read Grep Glob"`**. Anything not on the list — `Edit`, `Write`, `Bash`, `NotebookEdit`, etc. — is denied. The harness, not just the prompt, enforces the skill's "no source-tree mutations outside `.ultraplan/` and `$PLAN_TMP`" guarantee, so even if a subagent reads off-target or hostile instructions while exploring repository content, it cannot write or delete files. Do **not** swap this out for `--dangerously-skip-permissions`/`bypassPermissions` (defeats the contract) or `--permission-mode plan` (too restrictive for headless `-p`: plan mode disables Bash and most tools, and the run aborts when a needed tool isn't pre-approved). Treat each `claude -p` call as a self-contained subagent: it has zero conversation context, so the prompt file you pipe into it must be fully self-contained (task description, what to look for, what to return, scope boundary).

## Workflow

### Step 1: Understand the Task

Read the user's request. If they provided a task description as an argument, use it directly.

**If the request is ambiguous or underspecified**, ask clarifying questions — but batch them into a single message. Ask ONLY what the codebase cannot answer. Prefer multiple-choice when feasible.

Good questions (only the user can answer these):
- "There's a tradeoff between X (simpler) and Y (more extensible). Which matters more here?"
- "The minimum viable change is [X]. The complete change also needs [Y, Z]. Where should I draw the line?"

Bad questions (find the answer yourself by reading code):
- "What framework are you using?"
- "Where is the config file?"

If the task is clear, skip straight to Step 2.

### Step 2: Assess Complexity

Run quick reconnaissance from the shell:

```bash
git status --short
git log --oneline -20
git branch --show-current
```

Check for `CLAUDE.md` or `AGENTS.md` in the project root. If found, read its contents and note any project-specific constraints, conventions, or patterns that should inform the plan. Also locate scoped `CLAUDE.md` / `AGENTS.md` files in subdirectories the task will touch — these carry local constraints that override or extend root-level guidance:

```bash
find . -type f \( -name CLAUDE.md -o -name AGENTS.md \) \
       -not -path './.git/*' -not -path './node_modules/*'
```

Classify the task:

| Size | Criteria | Exploration Depth |
|------|----------|-------------------|
| **Small** | 1-2 files, clear approach, follows existing patterns | Single pass, no `claude -p` subagents |
| **Medium** | 3-5 files, one subsystem, some ambiguity | 1-2 parallel `claude -p` Explore subagents |
| **Large** | Many files, cross-cutting, architectural decisions needed | 3 parallel `claude -p` Explore subagents (Three-Concern Decomposition) |

Announce the classification and planned depth to the user.

### Step 3: Deep Codebase Exploration

For each area the task touches, explore systematically using shell tools:

- **Structure**: `find` / `ls` for directory layout; read key files with `sed -n` or whatever your harness's file-read primitive is.
- **Flow**: `grep -rn` (or `rg`) to locate function/type/class names and trace call chains.
- **Tests**: Find existing test files for the affected code, note test patterns and frameworks.
- **History**: `git log --oneline -10 -- <relevant paths>` to understand recent changes.
- **Config**: Inspect build files, CI config, package manifests where relevant.

#### Stage temp files

Create a working directory for prompts and outputs once, up front:

```bash
PLAN_TMP=$(mktemp -d /tmp/pm-plan-XXXXXX)
echo "$PLAN_TMP"
```

Reuse `$PLAN_TMP` for every `claude -p` dispatch in this session. Clean it up only at the end (Step 7).

#### Dispatching `claude -p` subagents

Every subagent call below follows this shape:

```bash
claude -p --allowed-tools "Read Grep Glob" --verbose \
       < "$PLAN_TMP/<role>.prompt" \
       > "$PLAN_TMP/<role>.out" 2>&1
```

To run multiple subagents **in parallel**, background each one and `wait`:

```bash
claude -p --allowed-tools "Read Grep Glob" --verbose < "$PLAN_TMP/arch.prompt"    > "$PLAN_TMP/arch.out"    2>&1 &
PID_ARCH=$!
claude -p --allowed-tools "Read Grep Glob" --verbose < "$PLAN_TMP/surface.prompt" > "$PLAN_TMP/surface.out" 2>&1 &
PID_SURF=$!
claude -p --allowed-tools "Read Grep Glob" --verbose < "$PLAN_TMP/risks.prompt"   > "$PLAN_TMP/risks.out"   2>&1 &
PID_RISK=$!

wait $PID_ARCH $PID_SURF $PID_RISK
```

Use a **single** Bash command with `wait` so codex blocks until all parallel subagents finish. After `wait` returns, read each `*.out` file and synthesize the findings.

**Each prompt file must be self-contained** — `claude -p` has no inherited context. Always include: (1) the task description, (2) the agent's specific mission and scope boundary, (3) what to return (file paths with line numbers, patterns, risks, etc.), (4) any project conventions extracted from CLAUDE.md/AGENTS.md.

**For Medium tasks**, dispatch 1-2 parallel `claude -p` Explore subagents. Choose a strategy based on task type — **breadth-first discovery**, **feature trace**, or **impact analysis**. See `references/planning-patterns.md` for prompt templates.

**For Large tasks**, dispatch exactly 3 parallel `claude -p` Explore subagents using the **Three-Concern Decomposition** — one subagent per concern, all started in the same shell command:
1. **Architecture Understanding** — how the affected subsystems work, patterns, conventions, reference implementations
2. **Change Surface Identification** — every file to modify/create, existing utilities to reuse
3. **Risks, Edge Cases & Dependencies** — callers, consumers, edge cases, test gaps, integration points

Each subagent has a strict boundary: architecture doesn't propose changes, change surface doesn't assess risks, risks doesn't propose implementations. See `references/planning-patterns.md` for full prompt templates and synthesis guidance.

**For each discovery, capture:**
- Existing functions/utilities to reuse (with `file_path:line_number`)
- Architectural patterns the codebase follows
- Dependencies and coupling between components
- Test infrastructure available
- Similar features to use as reference implementations

#### Plan naming (Haiku subagent)

Dispatch a one-shot `claude -p` call pinned to Haiku for the name:

```bash
cat > "$PLAN_TMP/name.prompt" <<'EOF'
Generate a short kebab-case name (2-3 words) that summarizes this task:
<paste task description here>

Reply with ONLY the name, nothing else. Example: auth-token-refresh
EOF

claude -p --model claude-haiku-4-5-20251001 \
       --allowed-tools "Read Grep Glob" --verbose \
       < "$PLAN_TMP/name.prompt" \
       > "$PLAN_TMP/name.out" 2>&1
```

Sanitize the returned name: strip everything except lowercase letters, digits, and hyphens (`[^a-z0-9-]`), truncate to 50 characters, and trim leading/trailing hyphens. If the result is empty, fall back to `plan`. Then check if `.ultraplan/<plan-name>.md` already exists — if so, append `-2`, `-3`, etc. until the name is unique. Use the final name as `<plan-name>` for the rest of this session. The plan file path is `.ultraplan/<plan-name>.md`.

```bash
mkdir -p .ultraplan
```

**Context survival:** Create the plan file early. Write findings to `.ultraplan/<plan-name>.md` incrementally as you discover them — don't hold state only in conversation memory. The plan file on disk is your persistent state that survives context compression.

### Step 4: Draft the Plan

Write (or update) `.ultraplan/<plan-name>.md` with this structure:

```markdown
# Plan: <concise title>

## Goal
<1-2 sentences: what this plan achieves and why>

## Key Files
| File | Role | Lines of Interest |
|------|------|-------------------|
| `path/to/file.ext` | <role in this change> | <relevant lines> |

## Steps

### 1. <action verb> <what>
- **File**: `path/to/file.ext` (lines X-Y)
- **Change**: <precise description of what to add/modify/remove>
- **Reuses**: `existingFunction()` from `path/to/utils.ext:42`

### 2. ...

## Testing
- <what tests to add/modify>
- <verification command to run>

## Risks
- <risk>: <mitigation>
```

**Plan quality rules:**
- Every step must reference exact file paths. For existing files, verify they exist. For new files the plan will create, mark them explicitly with `[new]`
- Steps must be ordered by dependency (what must happen first)
- Each step should be independently implementable where possible
- Every line must carry actionable implementation information — no prose padding, no background summaries, no motivational text
- Reference existing functions to reuse with `file:line`
- Present only your recommended approach, not a menu of alternatives

### Step 5: Validate the Plan

Re-read the plan file. For every file path mentioned:
- For existing files: confirm with `test -f <path>` (and `sed -n '<line>p' <path>` to verify referenced functions/line numbers).
- For files marked `[new]`: confirm the parent directory exists with `test -d <dir>` and that no naming conflict exists with `test -e <path>`.

Check for (see `references/anti-patterns.md` for the full list of failure modes):
- **Phantom references**: files or functions that don't exist
- **Circular dependencies**: steps that depend on each other
- **Missing test coverage**: behavioral changes without test steps
- **Scope creep**: steps that don't directly serve the stated goal

Fix any issues found.

### Step 6: Adversarial Review

Dispatch a single `claude -p` adversarial reviewer:

```bash
cat > "$PLAN_TMP/review.prompt" <<EOF
You are a critical plan reviewer. Read the plan at \`.ultraplan/<plan-name>.md\`
(absolute path: $(pwd)/.ultraplan/<plan-name>.md) and the source files it
references.

Find:
  (1) file references that don't exist,
  (2) steps that depend on undeclared changes,
  (3) missing edge cases,
  (4) steps that could be simplified or merged,
  (5) scope creep beyond the stated goal.

Report issues only — don't rewrite the plan.
EOF

claude -p --allowed-tools "Read Grep Glob" --verbose \
       < "$PLAN_TMP/review.prompt" \
       > "$PLAN_TMP/review.out" 2>&1
```

Read `$PLAN_TMP/review.out`. Incorporate valid criticisms into the plan. If the reviewer finds phantom references or critical issues, fix them and re-validate.

For **Small** tasks, perform this review inline yourself instead of dispatching a `claude -p` subagent.

### Step 7: Present to User and Cleanup

Display the final plan with a summary of exploration findings. Ask directly: **"Ready to execute this plan, or do you want changes?"**

The plan file persists at `.ultraplan/<plan-name>.md` for reference during implementation. Tell the user the exact filename.

Clean up the staging directory:

```bash
rm -rf "$PLAN_TMP"
```

## Constraints

- **Read-only mode for source**: Do NOT create, modify, or delete any file except inside `.ultraplan/` or `$PLAN_TMP`.
- **No implementation**: Do not write code, modify source files, or run build/test commands.
- **No false completion**: Do not present the plan until validation and adversarial review are complete.
- **No plan bloat**: Every line in the plan must carry actionable implementation information.
- **No phantom references**: Every `file:line` reference to existing files must be verified against the actual codebase. New files must be marked `[new]`.
- **No scope creep**: If exploration reveals the task is larger than expected, flag it to the user and ask whether to expand scope or decompose.
- **No findable questions**: Never ask the user something you could determine by reading code.
- **Subagent harness**: All parallel exploration, plan naming, and adversarial review go through `claude -p`. Codex is the orchestrator only — never invoke a nested `codex exec` from within this workflow.

## Complexity Scaling

| Task Size | `claude -p` Explore subagents | Clarification Depth | Adversarial Review |
|-----------|-------------------------------|---------------------|--------------------|
| Small (1-2 files) | 0 | Light — 0-2 questions | Inline |
| Medium (3-5 files) | 1-2 (parallel) | Moderate — 2-4 questions | `claude -p` |
| Large (many files, architectural) | 3 (parallel, Three-Concern) | Deep — 4-6 questions | `claude -p` |

## Prerequisites

- `codex` CLI (this workflow runs under it) invoked with `--sandbox workspace-write` or higher.
- `claude` CLI on `$PATH`, authenticated. Subagent dispatch fails immediately without it.
- Standard POSIX shell utilities: `git`, `find`, `grep` (or `rg`), `sed`, `mktemp`, `wait`.

## Additional Resources

See `references/planning-patterns.md` (bundled with this skill) for detailed exploration strategies and prompt templates for `claude -p` subagents.
See `references/anti-patterns.md` (bundled with this skill) for common failure modes to guard against.
