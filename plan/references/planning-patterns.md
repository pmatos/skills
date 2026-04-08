# Planning Patterns Reference

## Exploration Strategies

### Breadth-First Discovery
Launch parallel agents, each scanning a different layer:
- **Agent 1 — Data layer**: models, schemas, database migrations, ORM config
- **Agent 2 — Business logic**: services, utilities, core modules, domain logic
- **Agent 3 — Presentation**: components, routes, API endpoints, templates

### Feature Trace
Follow a feature through the entire stack:
- **Agent 1**: Trace from UI → API → service → database, noting each touchpoint
- **Agent 2**: Find all related tests and similar features as reference implementations

### Impact Analysis
Assess blast radius of a change:
- **Agent 1**: What directly changes (files that will be edited)
- **Agent 2**: What indirectly depends on the changed code (imports, callers, consumers, configs)

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

## Parallel Agent Dispatch

When dispatching Explore agents, structure prompts with:
1. **Specific mission**: "Find all files related to authentication and trace the login flow from controller to database"
2. **What to return**: "Report: key files found with paths and line numbers, patterns observed, dependencies, potential risks"
3. **Scope boundary**: "Only look at the auth subsystem, don't explore unrelated areas"

Synthesize findings by: merging file lists, resolving conflicting observations, identifying cross-cutting concerns that appear in multiple agents' reports.

## Step Decomposition Heuristics

- **One file per step** when possible — makes review and rollback easier
- **Group atomic changes** that must land together (e.g., type definition + its consumers)
- **Order by dependency**: foundation changes first, then consumers, then tests, then cleanup
- **Separate additive from destructive**: add new code before removing old code
