# Planning Patterns Reference

All "agent" dispatches in this document are **`claude -p` CLI subagents** spawned by the Codex-hosted pm-plan workflow. Each subagent runs in its own headless Claude Code process, has zero inherited context, and must receive a fully self-contained prompt. The standard invocation is:

```bash
claude -p --permission-mode plan --verbose \
       < "$PLAN_TMP/<role>.prompt" \
       > "$PLAN_TMP/<role>.out" 2>&1
```

Run multiple subagents concurrently by backgrounding each call (`&`) and `wait`ing in a single Bash command — this is how parallelism is achieved here, not via any in-process agent tool.

## Exploration Strategies

### Three-Concern Decomposition (Large tasks — recommended)

For Large tasks, always dispatch exactly three parallel `claude -p` subagents with these fixed, non-overlapping missions. Stage each prompt as a file under `$PLAN_TMP`, then start all three with `&` and `wait` so they execute concurrently.

**Subagent 1 — Architecture Understanding** (`$PLAN_TMP/arch.prompt`)

Mission: Understand the codebase structure, patterns, and conventions in the subsystems the task touches.

Prompt template:
> "Task context: [task description].
> Explore the architecture of [subsystem/area]. Find: (1) directory structure and key files, (2) design patterns and conventions used (naming, error handling, dependency injection, etc.), (3) how similar features are structured — find at least one reference implementation, (4) relevant CLAUDE.md/AGENTS.md constraints. Report: file paths with line numbers, patterns observed, reference implementation paths. Do NOT look for what needs to change — only understand what exists."

**Subagent 2 — Change Surface Identification** (`$PLAN_TMP/surface.prompt`)

Mission: Find every file that will need modification and every existing utility that can be reused.

Prompt template:
> "Task context: [task description].
> Identify all files that would need to change to accomplish the task above. Find: (1) files to modify (with specific functions/sections), (2) files to create, (3) existing utilities, helpers, or base classes to reuse (with file:line), (4) type definitions, interfaces, or schemas that need updating. Report: complete file list with roles and lines of interest. Do NOT assess risks or propose solutions — only map the change surface."

**Subagent 3 — Risks, Edge Cases & Dependencies** (`$PLAN_TMP/risks.prompt`)

Mission: Identify what could go wrong, what edge cases exist, and what depends on the code being changed.

Prompt template:
> "Task context: [task description].
> Analyze risks for the task above. Find: (1) callers and consumers of the code being changed (grep for imports, function calls), (2) edge cases and boundary conditions, (3) test coverage gaps — existing tests and what's missing, (4) integration points with external systems or other subsystems, (5) backward compatibility concerns. Report: risks with severity, edge cases, dependency graph, test gaps. Do NOT propose the implementation — only identify what could break."

### Breadth-First Discovery (Medium tasks)
Launch parallel `claude -p` subagents, each scanning a different layer:
- **Subagent 1 — Data layer**: models, schemas, database migrations, ORM config
- **Subagent 2 — Business logic**: services, utilities, core modules, domain logic
- **Subagent 3 — Presentation**: components, routes, API endpoints, templates

### Feature Trace (Medium tasks)
Follow a feature through the entire stack with two parallel `claude -p` subagents:
- **Subagent 1**: Trace from UI → API → service → database, noting each touchpoint
- **Subagent 2**: Find all related tests and similar features as reference implementations

### Impact Analysis (Medium tasks)
Assess blast radius of a change with two parallel `claude -p` subagents:
- **Subagent 1**: What directly changes (files that will be edited)
- **Subagent 2**: What indirectly depends on the changed code (imports, callers, consumers, configs)

## Plan Templates

### Bug Fix (Minimal)
```markdown
# Plan: Fix <bug description>

## Goal
<What's broken and what correct behavior looks like>

## Key Files
| File | Role | Lines |
|------|------|-------|

## Steps
### 1. Reproduce — confirm the bug
### 2. Locate — root cause in `file:line`
### 3. Fix — precise change
### 4. Test — add regression test

## Verify
<command to confirm fix>
```

### Feature (Standard)
```markdown
# Plan: Add <feature>

## Goal
<What the feature does and why>

## Key Files
| File | Role | Lines |
|------|------|-------|

## Steps
### 1. <foundation change — types, schema, config>
### 2. <core logic — service, utility>
### 3. <integration — wire into existing code>
### 4. <tests — unit + integration>

## Testing
<test commands>

## Risks
<risk: mitigation>
```

### Refactoring (Preserve Behavior)
```markdown
# Plan: Refactor <what>

## Goal
<What improves and why, behavior stays the same>

## Steps
### 1. Identify boundaries — what's in scope, what's not
### 2. Add characterization tests if missing
### 3. Transform — incremental changes, each independently verifiable
### 4. Verify — run existing tests after each step
```

### Migration (Staged)
```markdown
# Plan: Migrate <from> to <to>

## Goal
<Why migrating and target state>

## Steps
### 1. Add compatibility layer — new code works alongside old
### 2. Migrate consumers — one at a time, verify each
### 3. Remove old code — only after all consumers migrated
### 4. Clean up compatibility layer
```

## Parallel Subagent Dispatch

### Large tasks (Three-Concern Decomposition)

Dispatch all three `claude -p` subagents in a single shell command using `&` + `wait` (parallel). Each subagent has a clear boundary — architecture doesn't propose changes, change surface doesn't assess risks, risks doesn't propose implementations. This prevents overlap and ensures each report is focused.

Reference shell template:

```bash
claude -p --permission-mode plan --verbose < "$PLAN_TMP/arch.prompt"    > "$PLAN_TMP/arch.out"    2>&1 &
claude -p --permission-mode plan --verbose < "$PLAN_TMP/surface.prompt" > "$PLAN_TMP/surface.out" 2>&1 &
claude -p --permission-mode plan --verbose < "$PLAN_TMP/risks.prompt"   > "$PLAN_TMP/risks.out"   2>&1 &
wait
```

Synthesize by:
1. Start with Subagent 1's architecture context as the foundation
2. Overlay Subagent 2's change surface to form the step list
3. Apply Subagent 3's risks to add mitigations and order dependencies

### Medium tasks (strategy-based)

When dispatching `claude -p` Explore subagents, structure each prompt file with:
1. **Specific mission**: "Find all files related to authentication and trace the login flow from controller to database"
2. **What to return**: "Report: key files found with paths and line numbers, patterns observed, dependencies, potential risks"
3. **Scope boundary**: "Only look at the auth subsystem, don't explore unrelated areas"
4. **Self-contained context**: include the full task description and any CLAUDE.md/AGENTS.md constraints — `claude -p` has no inherited conversation state.

Synthesize findings by: merging file lists, resolving conflicting observations, identifying cross-cutting concerns that appear in multiple subagents' reports.

## Step Decomposition Heuristics

- **One file per step** when possible — makes review and rollback easier
- **Group atomic changes** that must land together (e.g., type definition + its consumers)
- **Order by dependency**: foundation changes first, then consumers, then tests, then cleanup
- **Separate additive from destructive**: add new code before removing old code
