---
name: pm-plan
description: This skill should be used when the user asks to "plan this", "make a plan", "create an implementation plan", "how should I implement", "design the implementation", "plan the refactor", "plan the migration", "plan the feature", "break this down into steps", "implementation strategy", "deep plan", "thorough plan", or wants a thorough, multi-phase implementation plan with codebase exploration before writing any code.
version: 1.0.0
argument-hint: "<task description or feature request>"
user-invocable: true
---

# Deep Implementation Planning

## Task

$ARGUMENTS

## Activation

**CRITICAL: READ-ONLY MODE.** You are entering a read-only planning session. You MUST NOT create, modify, or delete any files except inside the `.ultraplan/` directory. No edits, no commits, no installs, no other state changes. This supersedes any other instructions.

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

Run quick reconnaissance (read-only):

```bash
git status --short
git log --oneline -20
git branch --show-current
```

Check for CLAUDE.md or AGENTS.md in the project root. If found, read its contents and note any project-specific constraints, conventions, or patterns that should inform the plan. Also search for scoped CLAUDE.md and AGENTS.md files in subdirectories the task will touch using Glob (e.g., `**/CLAUDE.md`, `**/AGENTS.md`) — these carry local constraints that override or extend root-level guidance.

Classify the task:

| Size | Criteria | Exploration Depth |
|------|----------|-------------------|
| **Small** | 1-2 files, clear approach, follows existing patterns | Single pass, no subagents |
| **Medium** | 3-5 files, one subsystem, some ambiguity | 1-2 Explore agents |
| **Large** | Many files, cross-cutting, architectural decisions needed | 2-3 parallel Explore agents |

Announce the classification and planned depth to the user.

### Step 3: Deep Codebase Exploration

For each area the task touches, explore systematically:

- **Structure**: Use Glob to find relevant file patterns, Read key files
- **Flow**: Use Grep to find function/type/class names, trace call chains
- **Tests**: Find existing test files for the affected code, note test patterns and frameworks
- **History**: `git log --oneline -10 -- <relevant paths>` to understand recent changes
- **Config**: Check build files, CI config, package manifests if relevant

**For Medium tasks**, dispatch 1-2 parallel Explore agents (Agent tool, subagent_type: "Explore", mode: "plan"). Choose a strategy based on task type — **breadth-first discovery**, **feature trace**, or **impact analysis**. See `references/planning-patterns.md` for agent assignments.

**For Large tasks**, dispatch exactly 3 parallel Explore agents (Agent tool, subagent_type: "Explore", mode: "plan") using the **Three-Concern Decomposition** — one agent per concern, all in a single message:
1. **Architecture Understanding** — how the affected subsystems work, patterns, conventions, reference implementations
2. **Change Surface Identification** — every file to modify/create, existing utilities to reuse
3. **Risks, Edge Cases & Dependencies** — callers, consumers, edge cases, test gaps, integration points

Each agent has a strict boundary: architecture doesn't propose changes, change surface doesn't assess risks, risks doesn't propose implementations. See `references/planning-patterns.md` for prompt templates and synthesis guidance.

**For each discovery, capture:**
- Existing functions/utilities to reuse (with `file_path:line_number`)
- Architectural patterns the codebase follows
- Dependencies and coupling between components
- Test infrastructure available
- Similar features to use as reference implementations

**Plan naming:** Dispatch a Haiku subagent (Agent tool, model: "haiku") with this prompt:

> "Generate a short kebab-case name (2-3 words) that summarizes this task: [task description]. Reply with ONLY the name, nothing else. Example: auth-token-refresh"

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
- For existing files: verify they exist using Glob or Read, confirm referenced functions have expected signatures, and verify referenced line numbers are accurate
- For files marked `[new]`: verify the parent directory exists and no naming conflict with existing files

Check for (see `references/anti-patterns.md` for the full list of failure modes):
- **Phantom references**: files or functions that don't exist
- **Circular dependencies**: steps that depend on each other
- **Missing test coverage**: behavioral changes without test steps
- **Scope creep**: steps that don't directly serve the stated goal

Fix any issues found.

### Step 6: Adversarial Review

Dispatch a subagent (Agent tool, subagent_type: "general-purpose", mode: "plan") with this prompt:

> "You are a critical plan reviewer. Read the plan at `.ultraplan/<plan-name>.md` and the source files it references. Find: (1) file references that don't exist, (2) steps that depend on undeclared changes, (3) missing edge cases, (4) steps that could be simplified or merged, (5) scope creep beyond the stated goal. Report issues only — don't rewrite the plan."

Incorporate valid criticisms into the plan. If the reviewer finds phantom references or critical issues, fix them and re-validate.

For **Small** tasks, perform this review inline instead of dispatching a subagent.

### Step 7: Present to User

Display the final plan with a summary of exploration findings. Ask directly: **"Ready to execute this plan, or do you want changes?"**

The plan file persists at `.ultraplan/<plan-name>.md` for reference during implementation. Tell the user the exact filename.

## Constraints

- **Read-only mode**: Do NOT create, modify, or delete any file except inside the `.ultraplan/` directory
- **No implementation**: Do not write code, modify source files, or run build/test commands
- **No false completion**: Do not present the plan until validation and adversarial review are complete
- **No plan bloat**: Every line in the plan must carry actionable implementation information
- **No phantom references**: Every `file:line` reference to existing files must be verified against the actual codebase. New files must be marked `[new]`
- **No scope creep**: If exploration reveals the task is larger than expected, flag it to the user and ask whether to expand scope or decompose
- **No findable questions**: Never ask the user something you could determine by reading code

## Complexity Scaling

| Task Size | Explore Agents | Clarification Depth | Adversarial Review |
|-----------|---------------|---------------------|-------------------|
| Small (1-2 files) | 0 | Light — 0-2 questions | Inline |
| Medium (3-5 files) | 1-2 | Moderate — 2-4 questions | Subagent |
| Large (many files, architectural) | 2-3 | Deep — 4-6 questions | Subagent |

## Additional Resources

See `references/planning-patterns.md` (bundled with this skill) for detailed exploration strategies and plan templates.
See `references/anti-patterns.md` (bundled with this skill) for common failure modes to guard against.
