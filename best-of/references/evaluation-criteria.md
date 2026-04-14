# Evaluation Criteria Reference

Comprehensive criteria for comparing two code solutions. Each category includes what to look for and how to score.

## Scoring

Each criterion is scored on a 5-point scale per worktree:

| Score | Meaning |
|-------|---------|
| 5 | Exemplary — textbook quality, nothing to improve |
| 4 | Good — minor nits only |
| 3 | Acceptable — some issues but functional and maintainable |
| 2 | Below average — notable problems that should be fixed |
| 1 | Poor — significant issues affecting correctness, security, or maintainability |

---

## 1. Correctness

- Does the code produce the right output for all specified inputs?
- Are edge cases handled (nulls, empty collections, boundary values, overflow)?
- Are error paths correct — do they fail gracefully or propagate meaningful errors?
- Are race conditions or concurrency issues avoided?

## 2. Readability & Clarity

- Can a new team member understand the code without explanation?
- Are names self-documenting (variables, functions, classes, modules)?
- Is the control flow straightforward — minimal nesting, early returns over deep `else` chains?
- Are comments used only where logic is non-obvious (not restating code)?
- Is formatting consistent with the project's style?

## 3. DRY (Don't Repeat Yourself)

- Is there duplicated logic that should be extracted?
- Are existing utilities reused rather than reimplemented?
- Is abstraction appropriate — no premature abstraction for one-off logic, but genuine duplication is consolidated?

## 4. SOLID Principles

- **Single Responsibility**: Does each function/class/module do one thing?
- **Open/Closed**: Can behavior be extended without modifying existing code?
- **Liskov Substitution**: Are subtypes interchangeable with their base types?
- **Interface Segregation**: Are interfaces minimal and focused?
- **Dependency Inversion**: Do high-level modules depend on abstractions, not concretions?

Note: Apply pragmatically. Not every piece of code needs full SOLID treatment — a 10-line script doesn't need dependency injection.

## 5. Error Handling

- Are errors caught at system boundaries (user input, external APIs, file I/O)?
- Are error messages actionable — do they say what went wrong and what to do?
- Is internal code trusted appropriately (no defensive checks for impossible states)?
- Are errors propagated rather than swallowed silently?

## 6. Security

- Is user input validated and sanitized before use?
- Are SQL queries parameterized (no string concatenation)?
- Is output encoded to prevent XSS?
- Are secrets kept out of code and logs?
- Are dependencies up to date and free of known vulnerabilities?
- Are file paths validated to prevent path traversal?
- Is authentication/authorization checked at the right boundaries?

## 7. Testing

- Are there tests for the new/changed behavior?
- Do tests cover happy paths, edge cases, and error paths?
- Are tests isolated — no shared mutable state, no order dependence?
- Do tests follow the project's existing test patterns and frameworks?
- Is test code itself clean and readable?
- Are tests meaningful (not just asserting `true === true`)?

## 8. Performance

- Are there unnecessary allocations, copies, or iterations?
- Are data structures appropriate for the access patterns (map vs list, set vs array)?
- Are expensive operations (I/O, network, DB) batched or cached where sensible?
- Is there algorithmic complexity that could be improved (O(n^2) where O(n) is possible)?
- No premature optimization — only flag performance issues that matter at realistic scale.

## 9. Naming & Conventions

- Do names follow the project's conventions (camelCase, snake_case, PascalCase as appropriate)?
- Are abbreviations avoided unless they're universally understood in the domain?
- Are boolean variables/functions named as questions (`isReady`, `hasPermission`, `canRetry`)?
- Are constants named in UPPER_SNAKE_CASE (or project convention)?
- Do file names follow the project's naming scheme?

## 10. Separation of Concerns

- Is business logic separated from I/O, presentation, and infrastructure?
- Are cross-cutting concerns (logging, auth, validation) handled consistently?
- Are module boundaries clean — no circular dependencies, minimal coupling?

## 11. Complexity

- Is cyclomatic complexity reasonable (no functions with 15+ branches)?
- Are deeply nested structures flattened (guard clauses, early returns, extraction)?
- Is cognitive load manageable — can you hold the function in your head?

## 12. Type Safety

- Are types used effectively to prevent invalid states?
- Are `any` types avoided (in TypeScript) or equivalent escape hatches minimized?
- Are function signatures precise — do they accept exactly what they need?
- Are nullability and optionality explicit?

## 13. API & Interface Design

- Are function signatures intuitive — do parameters follow a logical order?
- Are return types consistent and predictable?
- Is the public API surface minimal — only expose what consumers need?
- Are breaking changes avoided when modifying existing interfaces?

## 14. Git Hygiene

- Are commits atomic — one logical change per commit?
- Are commit messages clear and descriptive?
- Is the diff minimal — no unrelated changes, no formatting-only churn?
- Are temporary/debug artifacts removed (console.log, TODO hacks, commented-out code)?

## 15. Project Guideline Compliance

This is evaluated dynamically based on the project's contribution files:

- **CLAUDE.md / AGENTS.md**: Coding conventions, required checks, architectural constraints
- **CONTRIBUTING.md**: Contribution process, PR requirements, code style
- **.editorconfig**: Indentation, line endings, trailing whitespace
- **Linter configs** (.eslintrc, .prettierrc, pyproject.toml, etc.): Style rules
- **CI config** (.github/workflows, Makefile, etc.): Required checks and gates

Each rule found in these files becomes an evaluation point. Violations are flagged with the specific rule and file reference.
