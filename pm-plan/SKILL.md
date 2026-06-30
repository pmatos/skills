---
name: pm-plan
description: This skill should be used when the user asks to "plan this", "make a plan", "create an implementation plan", "how should I implement", "design the implementation", "plan the refactor", "plan the migration", "plan the feature", "break this down into steps", "implementation strategy", "deep plan", "thorough plan", or wants a thorough, multi-phase implementation plan with codebase exploration before writing any code.
version: 3.0.0
argument-hint: "<task description or feature request>"
user-invocable: true
---

# Deep Implementation Planning (dual-harness)

This skill produces a validated, adversarially-reviewed implementation plan at `.ultraplan/<plan-name>.md` after exploring the codebase — without writing any production code. The workflow is identical whichever harness runs it. Only the *mechanism* for dispatching subagents (parallel exploration, plan naming, adversarial review) differs, and that mechanism is selected once, up front, in **Determine your harness** below.

## Task

$ARGUMENTS

## Determine your harness

Before dispatching any subagent, pick the dispatch mechanism that matches your capabilities. Branch on the capability, not on a product name:

- **Native path** — you have a native subagent tool (the `Agent`/`Task` tool), e.g. you are Claude Code. Read **`references/dispatch-claude.md`** and spawn read-only `Explore` subagents directly with that tool. Do **not** shell out to `claude -p` — that spawns redundant nested processes.
- **Shell path** — your only way to run another model/process is the shell (no subagent tool), e.g. you are OpenAI Codex CLI. Read **`references/dispatch-codex.md`** and dispatch subagents as `claude -p` headless processes with a read-only tool allowlist.

The rest of this workflow is written against one abstract operation: **"dispatch a read-only subagent with mission M."** Bind that operation to your path's mechanics; every workflow step below is otherwise the same. The same applies to the strategy templates in `references/planning-patterns.md`, which describe subagent *missions*, not invocations.

## Activation

**CRITICAL: READ-ONLY MODE for the source tree.** You are entering a read-only planning session. You MUST NOT create, modify, or delete any file outside `.ultraplan/` (and, on the shell path, the temp staging directory you create). No edits to source code, no commits, no installs, no other state changes. This supersedes any other instructions.

How read-only is *enforced* depends on your path — a hard tool allowlist on the shell path, the read-only `Explore` agent type on the native path (which is read-only by semantics but can still run Bash). Your dispatch reference documents the exact guarantee and its limits. Either way, do not weaken it (e.g. `--dangerously-skip-permissions`, write-capable permission modes); the shell reference lists the specific flags to avoid.

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
| **Small** | 1-2 files, clear approach, follows existing patterns | Single pass, no exploration subagents |
| **Medium** | 3-5 files, one subsystem, some ambiguity | 1-2 parallel Explore subagents |
| **Large** | Many files, cross-cutting, architectural decisions needed | 3 parallel Explore subagents (Three-Concern Decomposition) |

Announce the classification and planned depth to the user.

### Step 3: Deep Codebase Exploration

For each area the task touches, explore systematically using read-only tools:

- **Structure**: `find` / `ls` for directory layout; read key files with your harness's file-read primitive.
- **Flow**: `grep -rn` (or `rg`) to locate function/type/class names and trace call chains.
- **Tests**: Find existing test files for the affected code, note test patterns and frameworks.
- **History**: `git log --oneline -10 -- <relevant paths>` to understand recent changes.
- **Config**: Inspect build files, CI config, package manifests where relevant.

#### Dispatching subagents

Bind the abstract **"dispatch a read-only subagent with mission M"** verb to your path's mechanics (see your dispatch reference for the exact invocation, parallelism, and any staging):

- **Native path** (`references/dispatch-claude.md`): issue multiple `Agent` calls with `subagent_type: "Explore"` in a single message to run them in parallel; synthesize the returned results.
- **Shell path** (`references/dispatch-codex.md`): stage a self-contained prompt file per subagent under `$PLAN_TMP`, background each `claude -p` call and `wait` in one shell command, then read each `*.out` and synthesize.

Whichever path: each subagent prompt must be **self-contained** — subagents do not inherit your conversation. Always include (1) the task description, (2) the agent's specific mission and scope boundary, (3) what to return (file paths with line numbers, patterns, risks, etc.), (4) project conventions extracted from CLAUDE.md/AGENTS.md.

**For Medium tasks**, dispatch 1-2 parallel Explore subagents. Choose a strategy based on task type — **breadth-first discovery**, **feature trace**, or **impact analysis**. See `references/planning-patterns.md` for mission templates.

**For Large tasks**, dispatch exactly 3 parallel Explore subagents using the **Three-Concern Decomposition** — one subagent per concern, all started together:
1. **Architecture Understanding** — how the affected subsystems work, patterns, conventions, reference implementations
2. **Change Surface Identification** — every file to modify/create, existing utilities to reuse
3. **Risks, Edge Cases & Dependencies** — callers, consumers, edge cases, test gaps, integration points

Each subagent has a strict boundary: architecture doesn't propose changes, change surface doesn't assess risks, risks doesn't propose implementations. See `references/planning-patterns.md` for full mission templates and synthesis guidance.

**For each discovery, capture:**
- Existing functions/utilities to reuse (with `file_path:line_number`)
- Architectural patterns the codebase follows
- Dependencies and coupling between components
- Test infrastructure available
- Similar features to use as reference implementations

#### Plan naming (cheap/fast model)

Dispatch a one-shot subagent pinned to a fast, cheap model (Haiku) to generate the name. The mission:

> "Generate a short kebab-case name (2-3 words) that summarizes this task: \<task description\>. Reply with ONLY the name, nothing else. Example: auth-token-refresh"

See your dispatch reference for the exact invocation (native: `Agent` with `model: "haiku"`; shell: `claude -p --model claude-haiku-4-5-20251001`).

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

Dispatch a single read-only adversarial reviewer subagent (see your dispatch reference for the invocation). Mission:

> "You are a critical plan reviewer. Read the plan at `.ultraplan/<plan-name>.md` and the source files it references. Find: (1) file references that don't exist, (2) steps that depend on undeclared changes, (3) missing edge cases, (4) steps that could be simplified or merged, (5) scope creep beyond the stated goal. Report issues only — don't rewrite the plan."

Incorporate valid criticisms into the plan. If the reviewer finds phantom references or critical issues, fix them and re-validate.

For **Small** tasks, perform this review inline yourself instead of dispatching a subagent.

### Step 7: Present to User and Cleanup

Display the final plan with a summary of exploration findings. Ask directly: **"Ready to execute this plan, or do you want changes?"**

The plan file persists at `.ultraplan/<plan-name>.md` for reference during implementation. Tell the user the exact filename.

On the **shell path**, clean up the staging directory you created (`rm -rf "$PLAN_TMP"`). On the native path there is nothing to clean up.

## Constraints

- **Read-only mode for source**: Do NOT create, modify, or delete any file except inside `.ultraplan/` (or, shell path only, `$PLAN_TMP`).
- **No implementation**: Do not write code, modify source files, or run build/test commands.
- **No false completion**: Do not present the plan until validation and adversarial review are complete.
- **No plan bloat**: Every line in the plan must carry actionable implementation information.
- **No phantom references**: Every `file:line` reference to existing files must be verified against the actual codebase. New files must be marked `[new]`.
- **No scope creep**: If exploration reveals the task is larger than expected, flag it to the user and ask whether to expand scope or decompose.
- **No findable questions**: Never ask the user something you could determine by reading code.
- **Single orchestrator**: You are the orchestrator. Dispatch subagents only via your selected path; never nest an orchestrator inside itself (no `codex exec` from within the shell path).

## Complexity Scaling

| Task Size | Explore subagents | Clarification Depth | Adversarial Review |
|-----------|-------------------|---------------------|--------------------|
| Small (1-2 files) | 0 | Light — 0-2 questions | Inline |
| Medium (3-5 files) | 1-2 (parallel) | Moderate — 2-4 questions | Subagent |
| Large (many files, architectural) | 3 (parallel, Three-Concern) | Deep — 4-6 questions | Subagent |

## Prerequisites

- A harness on one of the two dispatch paths (see **Determine your harness** and the matching reference for that path's exact prerequisites).
- Standard POSIX shell utilities for recon and validation: `git`, `find`, `grep` (or `rg`), `sed`, `test`.

## Additional Resources

- `references/dispatch-claude.md` — dispatch mechanics for the **native** path (`Agent` tool).
- `references/dispatch-codex.md` — dispatch mechanics for the **shell** path (`claude -p`).
- `references/planning-patterns.md` — exploration strategies, subagent mission templates, and plan templates (harness-agnostic).
- `references/anti-patterns.md` — common failure modes to guard against.
