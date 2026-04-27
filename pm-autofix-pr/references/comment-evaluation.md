# Dual-Agent Review Comment Evaluation

Every unresolved review comment must be evaluated before any action is taken. This prevents wasting effort on invalid, out-of-scope, or irrelevant feedback. Two independent evaluators assess each comment in parallel, and their combined verdict determines the action.

## Evaluation Architecture

For each unresolved review comment, spawn two subagents **in parallel**:

1. **Opus Evaluator** — Claude Opus 4.6, model="opus", used via the Agent tool
2. **Codex Evaluator** — invokes the user-level `codex-2nd-opinion` skill (Skill tool, `skill="codex-2nd-opinion"`). **Never** substitute `codex:rescue`, `codex:codex-rescue`, or any other `codex:*` plugin skill — those are unrelated tools.

Both receive identical context and return independent verdicts.

## Context to Provide Each Evaluator

Each evaluator needs:
- The review comment text (use the **most recent reviewer comment** in the thread, not just the original)
- The file path and line number referenced
- The relevant code at that location (read it before spawning)
- The PR title and description (to understand scope)
- The PR diff summary (what files changed and why)
- The project's CLAUDE.md pre-commit requirements (if any)

## Opus Evaluator Prompt Template

```
Evaluate this review comment on a GitHub PR. Determine if it should be addressed.

## PR Context
- Title: {pr_title}
- Description: {pr_description}
- Files changed: {changed_files_summary}

## Review Comment
- File: {path}:{line}
- Reviewer: @{reviewer}
- Comment: {comment_body}

## Code at Location
{code_snippet}

## Evaluation Criteria

Rate this comment as VALID or INVALID:

VALID — Address it if:
- Points to a real bug, correctness issue, or security concern
- Identifies a violation of the project's documented standards
- Requests a necessary test, error check, or edge case
- Highlights a genuine readability/maintainability issue in changed code

INVALID — Reject if:
- NOT AN ISSUE: The reviewer is mistaken — the code is correct as-is
- SCOPE CREEP: Requests changes beyond what this PR set out to do
- UNRELATED: Concerns code not touched by this PR
- NOT RELEVANT: Stylistic preference not backed by project standards
- ALREADY HANDLED: The issue is already addressed elsewhere in the PR

## Output Format
VERDICT: VALID or INVALID
CATEGORY: (if INVALID) not-an-issue | scope-creep | unrelated | not-relevant | style-preference | already-handled
CONFIDENCE: HIGH | MEDIUM | LOW
REASONING: 2-3 sentences explaining the verdict
```

## Codex Evaluator Prompt

Invoke the `codex-2nd-opinion` skill via the Skill tool — exact form: `Skill(skill="codex-2nd-opinion", args=<the evaluation prompt above>)`. The skill handles Codex CLI formatting and invocation; pass the same template you used for Opus.

**Forbidden substitutes** (do not call any of these even if `codex-2nd-opinion` seems unavailable — stop and report instead):
- `codex:rescue` (Skill tool)
- `codex:codex-rescue` (Agent subagent)
- `codex:setup`, `codex:codex-cli-runtime`, `codex:gpt-5-4-prompting`, `codex:codex-result-handling`

These are unrelated tools from the `codex` plugin. The Codex Evaluator's purpose is to get an *independent verdict* on a review comment, not to delegate rescue work.

## Decision Matrix

| Opus Verdict | Codex Verdict | Action |
|-------------|---------------|--------|
| VALID | VALID | **Address** the comment — make the code fix |
| VALID | INVALID | **Address** the comment — err on the side of caution |
| INVALID | VALID | **Address** the comment — err on the side of caution |
| INVALID | INVALID | **Reject** the comment — post rejection reply |

When both are INVALID, select the rejection category from the evaluator with higher confidence. If confidence is equal, use the Opus category.

## Confidence-Based Override

If one evaluator says INVALID with HIGH confidence and the other says VALID with LOW confidence, treat as **INVALID** — the high-confidence evaluator's reasoning takes precedence.

## Rejection Taxonomy

When rejecting a comment, use one of these categories:

| Category | When to use | Example rejection message |
|---------|-------------|--------------------------|
| `not-an-issue` | Reviewer is factually wrong | "The null check is unnecessary here — `fetchUser()` is guaranteed to return a non-null value by the API contract (see UserService.ts:42)." |
| `scope-creep` | Valid concern but not for this PR | "Adding retry logic to the HTTP client is a good idea but is outside the scope of this PR, which only fixes the auth token refresh. Filed as #123." |
| `unrelated` | Concerns untouched code | "This function was not modified in this PR. The existing behavior is unchanged." |
| `not-relevant` | Style preference without backing | "This is a stylistic preference. The project has no documented convention for this pattern (checked CLAUDE.md, .eslintrc, .prettierrc)." |
| `style-preference` | Alternate style, equally valid | "Both approaches are valid here. The current style is consistent with the rest of the codebase (see similar patterns in utils/auth.ts and lib/api.ts)." |

## Handling Ambiguous Comments

If a review comment asks an open question, proposes multiple alternatives, or suggests an architectural change, classify it as **ambiguous** regardless of evaluator verdicts. Present it to the user with both evaluators' reasoning and ask for guidance.

## Thread Context

Always evaluate based on the **most recent reviewer comment** in the thread, not just the original. Reviewers often post follow-ups ("that's still not right, please also handle X"), and the latest comment reflects the current ask.

## Performance Note

Comment evaluation is the most expensive step but also the most important. Each comment spawns two subagents — for a PR with 10 review comments, that's 20 subagent calls (10 pairs running in parallel). This is intentional. Getting the evaluation right means fewer wasted iterations and no unnecessary code churn.
