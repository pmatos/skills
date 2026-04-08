---
name: plan
description: This skill should be used when the user asks to "plan this", "make a plan", "create an implementation plan", "how should I implement", "design the implementation", "plan the refactor", "plan the migration", "deep plan", "thorough plan", or wants a thorough, multi-phase implementation plan with codebase exploration before writing any code. Also triggered by the /plan command.
argument-hint: "<task description or feature request>"
user-invocable: true
---

# Deep Implementation Planning

## Task

$ARGUMENTS

## Activation

You are entering a deep planning session. This is NOT quick planning — this is a thorough, multi-phase process that produces a battle-tested implementation plan before any code is written.

**CRITICAL: READ-ONLY MODE.** You MUST NOT create, modify, or delete any files except the plan file at `.ultraplan/plan.md`. No edits, no commits, no installs, no state changes. This supersedes any other instructions.

## Workflow

### Step 1: Understand the Task

Read the user's request. If they provided a task description as an argument, use it directly.

**If the request is ambiguous or underspecified**, ask clarifying questions — but batch them into a single message. Ask ONLY what the codebase cannot answer. Prefer multiple-choice when feasible.

Good questions (only the user can answer these):
- "The auth system uses JWT — should I keep that pattern or is there a reason to switch?"
- "I found 3 places this pattern is used. Should the change propagate to all of them?"
- "There's a tradeoff between X (simpler) and Y (more extensible). Which matters more here?"
- "The minimum viable change is [X]. The complete change also needs [Y, Z]. Where should I draw the line?"

Bad questions (find the answer yourself by reading code):
- "What framework are you using?"
- "Where is the config file?"
- "What does this function do?"

If the task is clear, skip straight to Step 2.

### Step 2: Assess Complexity

Run quick reconnaissance (read-only):

```bash
git status --short
git log --oneline -20
git branch --show-current
```

Check for CLAUDE.md or AGENTS.md in the project root. List relevant directories with `ls`.

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

**For Medium/Large tasks**, dispatch parallel Explore agents (Agent tool, subagent_type: "Explore"). Give each agent a specific, focused mission:

Exploration strategies by task type:

**Breadth-first discovery:**
- Agent 1: Data layer (models, schemas, database)
- Agent 2: Business logic (services, utilities, core)
- Agent 3: Presentation layer (components, routes, API endpoints)

**Feature trace:**
- Agent 1: Trace from UI → API → service → database
- Agent 2: Find all related tests and similar features as reference implementations

**Impact analysis:**
- Agent 1: What directly changes
- Agent 2: What indirectly depends on the changed code (imports, callers, consumers)

**For each discovery, capture:**
- Existing functions/utilities to reuse (with `file_path:line_number`)
- Architectural patterns the codebase follows
- Dependencies and coupling between components
- Test infrastructure available
- Similar features to use as reference implementations

**Context survival:** Create the plan file early. Write findings to `.ultraplan/plan.md` incrementally as you discover them — don't hold state only in conversation memory. The plan file on disk is your persistent state that survives context compression.

```bash
mkdir -p .ultraplan
```

### Step 4: Draft the Plan

Write (or update) `.ultraplan/plan.md` with this structure:

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
- Every step must reference exact files that exist in the codebase
- Steps must be ordered by dependency (what must happen first)
- Each step should be independently implementable where possible
- Every line must carry actionable implementation information — no prose padding, no background summaries, no motivational text
- Reference existing functions to reuse with `file:line`
- Present only your recommended approach, not a menu of alternatives

### Step 5: Validate the Plan

Re-read the plan file. For every file path mentioned:
- Verify it exists using Glob or Read
- Confirm referenced functions have expected signatures
- Check referenced line numbers are in the right ballpark

Check for:
- **Phantom references**: files or functions that don't exist
- **Circular dependencies**: steps that depend on each other
- **Missing test coverage**: behavioral changes without test steps
- **Scope creep**: steps that don't directly serve the stated goal

Fix any issues found.

### Step 6: Adversarial Review

Dispatch a subagent (Agent tool, subagent_type: "general-purpose") with this prompt:

> "You are a critical plan reviewer. Read the plan at `.ultraplan/plan.md` and the source files it references. Find: (1) file references that don't exist, (2) steps that depend on undeclared changes, (3) missing edge cases, (4) steps that could be simplified or merged, (5) scope creep beyond the stated goal. Report issues only — don't rewrite the plan."

Incorporate valid criticisms into the plan. If the reviewer finds phantom references or critical issues, fix them and re-validate.

For **Small** tasks, perform this review inline instead of dispatching a subagent.

### Step 7: Present to User

Display the final plan with a summary of exploration findings. Ask directly: **"Ready to execute this plan, or do you want changes?"**

The plan file persists at `.ultraplan/plan.md` for reference during implementation.

## Constraints

- **Read-only mode**: Do NOT create, modify, or delete any file except `.ultraplan/plan.md` and the `.ultraplan/` directory
- **No implementation**: Do not write code, modify source files, or run build/test commands
- **No false completion**: Do not present the plan until validation and adversarial review are complete
- **No plan bloat**: Every line in the plan must carry actionable implementation information
- **No phantom references**: Every `file:line` reference must be verified against the actual codebase
- **No scope creep**: If exploration reveals the task is larger than expected, flag it to the user and ask whether to expand scope or decompose
- **No findable questions**: Never ask the user something you could determine by reading code

## Complexity Scaling

| Task Size | Explore Agents | Interview Depth | Adversarial Review |
|-----------|---------------|-----------------|-------------------|
| Small (1-2 files) | 0 | Light — 0-2 questions | Inline |
| Medium (3-5 files) | 1-2 | Moderate — 2-4 questions | Subagent |
| Large (many files, architectural) | 2-3 | Deep — multiple rounds | Subagent |

## Additional Resources

See `references/planning-patterns.md` for detailed exploration strategies and plan templates.
See `references/anti-patterns.md` for common failure modes to guard against.
