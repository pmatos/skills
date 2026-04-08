# Anti-Patterns in Implementation Planning

Failure modes observed in AI-assisted planning, with symptoms and mitigations.

## 1. False Completion Claims

**Symptom:** Plan says "all tests pass" or "verified working" without actually running anything.

**Mitigation:** Report outcomes faithfully. If you didn't run a verification step, say so explicitly rather than implying success. Never claim success based on expected rather than observed outcomes.

## 2. Plan Bloat

**Symptom:** Plan exceeds useful density — prose paragraphs explaining motivation, background sections restating the user's request, multiple alternatives presented instead of one recommendation.

**Mitigation:** Every line must carry actionable implementation information. Cut summaries, background, and motivational text. Present only your recommended approach. If the plan has more prose than file paths, it's too bloated.

## 3. Phantom File References

**Symptom:** Plan references files, functions, or line numbers that don't exist in the actual codebase.

**Mitigation:** In the validation step, Read every critical file referenced in the plan. Verify paths exist and functions have expected signatures. This is non-negotiable — never skip validation.

## 4. Scope Creep

**Symptom:** Plan grows to include "while we're at it" improvements, refactors, and cleanup that weren't requested.

**Mitigation:** Each step must directly serve the stated goal. If you find adjacent issues during exploration, flag them to the user as separate work — don't fold them into the plan.

## 5. Shallow Exploration

**Symptom:** Plan is based on assumptions rather than actual code reading. Misses existing patterns, reinvents utilities that already exist, or conflicts with project conventions.

**Mitigation:** Don't finalize the plan before completing exploration. Read the actual code. Search for existing implementations before proposing new ones. Check how similar features are built in the same codebase.

## 6. Monolithic Steps

**Symptom:** A single step touches too many files or makes too many unrelated changes. Impossible to review or roll back independently.

**Mitigation:** Break steps down so each one is a reviewable unit. If a step description needs "and" more than once, it's probably multiple steps.

## 7. Missing Test Strategy

**Symptom:** Plan modifies behavior but the testing section is absent, empty, or just says "add tests."

**Mitigation:** Every behavioral change needs a concrete test step: which test file, what test cases, what assertion. If no test infrastructure exists, the plan should note that and suggest what to set up.

## 8. Dependency Blindness

**Symptom:** Steps are ordered without considering which changes depend on which. Step 3 requires types defined in step 5. Step 1 modifies a file that step 2 also modifies in conflicting ways.

**Mitigation:** For each step, explicitly list what it depends on. Order steps so dependencies are satisfied before dependents. If two steps modify the same file, consider merging them or specifying the order precisely.
