---
name: pm-plan
description: This skill should be used when the user asks to "plan this", "make a plan", "create an implementation plan", "how should I implement", "design the implementation", "plan the refactor", "plan the migration", "plan the feature", "break this down into steps", "implementation strategy", "deep plan", "thorough plan", or wants a thorough, multi-phase implementation plan with codebase exploration before writing any code.
version: 4.2.0
argument-hint: "<task description or feature request>"
user-invocable: true
---

# Deep Implementation Planning

This skill produces a validated implementation plan (adversarially reviewed unless the task is Small) at `.ultraplan/<plan-name>.md` after exploring the codebase — without writing any production code.

## Task

$ARGUMENTS

## Activation

**CRITICAL: READ-ONLY MODE for the source tree.** You are entering a read-only planning session. You MUST NOT create, modify, or delete any file outside `.ultraplan/`. No edits to source code, no commits, no installs, no other state changes. This supersedes any other instructions.

Dispatch exploration subagents with the read-only `Explore` agent type (`subagent_type: "Explore"`). Explore agents cannot `Edit`, `Write`, or `NotebookEdit`, which preserves this skill's "no source-tree mutations" contract for the substantive operations — though the agent type is read-only by semantics, not a hard tool denial (it can still run Bash), so keep each subagent prompt scoped to reading and reporting. Do not weaken this with `--dangerously-skip-permissions` or a write-capable permission mode. The Step 6 reviewer subagent runs under the same rules with the read-only `Plan` agent type. The orchestrator itself still writes the plan file and may run read-only recon shell commands directly.

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

**Headless runs.** The test is "can I reach the user right now?" If not (a cron job, a routine, `claude -p`, or any session without an interactive question tool), the run is headless: never block on a question. Defer each question until after Step 3, since exploration often answers it. Answer the ones still open yourself, in this order: (1) consult the advisor if one is available — state the questions and the options in-transcript, then call it; (2) otherwise pick the best-guess answer, preferring the smallest change that satisfies the request. Record every answer you supplied under `## Assumptions` in the plan so the reader can see what was guessed. If there is no task description at all, stop and report that instead of inventing one.

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
| **Small** | 1-2 files, clear approach, follows existing patterns (includes trivial changes) | Single pass, no subagents, no adversarial review |
| **Medium** | 3-5 files, one subsystem, some ambiguity | 1-2 parallel Explore subagents |
| **Large** | Many files, cross-cutting, architectural decisions needed | 3 parallel Explore subagents (Three-Concern Decomposition) |

Announce the classification and planned depth to the user.

### Step 3: Deep Codebase Exploration

For each area the task touches, explore systematically using read-only tools:

- **Structure**: `find` / `ls` for directory layout; `Read` for key files.
- **Flow**: `grep -rn` (or `rg`) to locate function/type/class names and trace call chains.
- **Tests**: Find existing test files for the affected code, note test patterns and frameworks.
- **History**: `git log --oneline -10 -- <relevant paths>` to understand recent changes.
- **Config**: Inspect build files, CI config, package manifests where relevant.

#### Dispatching subagents

If a native subagent tool is available, issue multiple `Agent` calls with `subagent_type: "Explore"` in a single message to run them in parallel; synthesize the returned results directly — there is nothing to stage or read back from disk. **Without one**, perform the same exploration yourself, inline, working through each concern in turn instead of in parallel — slower, not different.

Each subagent prompt must be **self-contained** — subagents do not inherit your conversation. Always include (1) the task description, (2) the agent's specific mission and scope boundary, (3) what to return (file paths with line numbers, patterns, risks, etc.), (4) project conventions extracted from CLAUDE.md/AGENTS.md. Working inline, hold the same mission boundaries in your own head as you move from one concern to the next — they exist to keep the findings non-overlapping, not just to brief a subagent.

**For Medium tasks**, dispatch 1-2 parallel Explore subagents (or, without a subagent tool, cover the same ground yourself in sequence). Choose a strategy based on task type — **breadth-first discovery**, **feature trace**, or **impact analysis**. See `references/planning-patterns.md` for mission templates.

**For Large tasks**, dispatch exactly 3 parallel Explore subagents using the **Three-Concern Decomposition** — one subagent per concern, all started together (or, without a subagent tool, work through the same three concerns yourself, one at a time):
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

#### Plan naming

For Medium and Large tasks, if a native subagent tool is available, dispatch a one-shot `Agent` call pinned to a fast, cheap model (`model: "haiku"`) to generate the name. The mission:

> "Generate a short kebab-case name (2-3 words) that summarizes this task: \<task description\>. Reply with ONLY the name, nothing else. Example: auth-token-refresh"

**For Small tasks, or without a native subagent tool**, pick the name yourself inline — the dispatch exists mainly to keep naming cheap, and a subagent round-trip costs more than it saves on a Small task.

Sanitize the returned (or self-picked) name: strip everything except lowercase letters, digits, and hyphens (`[^a-z0-9-]`), truncate to 50 characters, and trim leading/trailing hyphens. If the result is empty, fall back to `plan`. Then check if `.ultraplan/<plan-name>.md` already exists — if so, append `-2`, `-3`, etc. until the name is unique. Use the final name as `<plan-name>` for the rest of this session. The plan file path is `.ultraplan/<plan-name>.md`.

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

## Assumptions
- <decision made without the user>: <choice> (advisor | best guess)

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

Include `## Assumptions` only when a decision was made without the user (a clarifying question answered, a scope call made, any other guess); omit it otherwise. It sits right after Goal so the reader sees the guesses before the steps built on them.

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

**Small tasks skip this step** — validation in Step 5 is enough — unless the drafted plan turned out larger than Step 2 sized it (more than two files under Key Files, or exploration contradicted the classification); then reclassify the task as Medium and run it. For Medium and Large tasks, get an independent critique of the plan before presenting it. The checks, with the plan already on disk at `.ultraplan/<plan-name>.md`: (1) file references that don't exist, (2) steps that depend on undeclared changes, (3) missing edge cases, (4) steps that could be simplified or merged, (5) scope creep beyond the stated goal.

**Reviewer, in order of preference:**

1. **The advisor**, when available. State the plan file and the five checks in-transcript immediately before calling it — the advisor takes no separate prompt and reviews your conversation as it stands.
2. **A read-only `Plan` subagent** (`subagent_type: "Plan"`), when no advisor is available. Not `Explore`: it reads excerpts and can miss content past its read window, which is exactly the workload here. The prompt must be self-contained: the task description, the plan file path, the five checks, the project conventions from CLAUDE.md/AGENTS.md, and an instruction to read the plan file in full, read each source file it references, and report findings only (no edits).
3. **Inline self-review**, only when neither exists: re-read the plan and the referenced source files and check against the same five criteria.

Incorporate valid criticisms into the plan. If the review finds phantom references or critical issues, fix them and re-validate.

### Step 7: Present to User

Display the final plan with a summary of exploration findings. Ask directly: **"Ready to execute this plan, or do you want changes?"** In a headless run, skip the question and print the full plan (every section, `## Assumptions` included) as the final output, since the workspace may not outlive the run; then end with the plan summary and the exact plan path.

The plan file persists at `.ultraplan/<plan-name>.md` for reference during implementation. Tell the user the exact filename.

## Constraints

- **Read-only mode for source**: Do NOT create, modify, or delete any file except inside `.ultraplan/`.
- **No implementation**: Do not write code, modify source files, or run build/test commands.
- **No false completion**: Do not present the plan until validation (and, for Medium and Large tasks, adversarial review) are complete.
- **No plan bloat**: Every line in the plan must carry actionable implementation information.
- **No phantom references**: Every `file:line` reference to existing files must be verified against the actual codebase. New files must be marked `[new]`.
- **No scope creep**: If exploration reveals the task is larger than expected, flag it to the user and ask whether to expand scope or decompose. In a headless run, don't ask: plan only the requested scope and record the larger finding under `## Assumptions` and in the final summary.
- **No findable questions**: Never ask the user something you could determine by reading code.
- **No blocking when headless**: Never wait for an answer nobody can give. Resolve questions via the advisor or a recorded best guess (Step 1).
- **Single orchestrator**: You are the orchestrator. Never nest another orchestrator inside this session.

## Complexity Scaling

| Task Size | Explore subagents | Clarification Depth | Adversarial review |
|-----------|-------------------|---------------------|--------------------|
| Small (1-2 files) | 0 | Light — 0-2 questions | None |
| Medium (3-5 files) | 1-2 (parallel) | Moderate — 2-4 questions | Yes, per Step 6 |
| Large (many files, architectural) | 3 (parallel, Three-Concern) | Deep — 4-6 questions | Yes, per Step 6 |

Question counts are ceilings, not quotas. Headless runs resolve them per Step 1 instead of asking.

## Prerequisites

- A native subagent tool (the `Agent`/`Task` tool) and the read-only `Explore` and `Plan` agent types are preferred, not required — Step 3's exploration and plan naming fall back to inline execution without one (slower, not different). Step 6 sets the reviewer fallback order.
- Standard POSIX shell utilities for recon and validation: `git`, `find`, `grep` (or `rg`), `sed`, `test`.

## Additional Resources

- `references/planning-patterns.md` — exploration strategies and subagent mission templates.
- `references/anti-patterns.md` — common failure modes to guard against.
