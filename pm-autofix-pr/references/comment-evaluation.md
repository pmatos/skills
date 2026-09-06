# Reviewer Feedback Evaluation

Every unresolved reviewer feedback item must be evaluated before any action is taken. This includes inline review threads, review summary bodies, and PR conversation comments. This prevents wasting effort on invalid, out-of-scope, or low-value feedback. A primary evaluator assesses each item, cross-checked by the advisor (when one is available) once per batch, and the combined verdict picks one of three outcomes: **FIX** (apply in this PR), **DEFER** (file a tracking issue), or **REJECT** (reply with rationale, no code change).

The skill is fully automatic. Evaluators must never produce an "ask the user" verdict — uncertain or ambiguous items are auto-classified as DEFER (see "Handling Ambiguous Feedback" below).

## Evaluation Architecture

The skill runs identically regardless of which harness hosts it. SKILL.md Step 0a records two capability flags: `SUBAGENT_TOOL` (a native `Agent`/`Task` tool is available) and `ADVISOR` (a consultable advisor is available).

For each unresolved feedback item:

1. **Primary Evaluator.** If `SUBAGENT_TOOL`, spawn a clean-context `Agent` subagent for this item. If not, evaluate it yourself, inline.

Once every item in this pass has a Primary verdict — not before, and not per item:

2. **Advisor check** (only if `ADVISOR`). State the whole batch in-transcript — each item's key, feedback, Primary verdict, confidence, and reasoning — then consult the advisor once for the batch. It reviews the conversation as it stands (it takes no separate prompt), so the batch must already be stated before the call. Ask it to flag any item where it would land on a different verdict.

If `ADVISOR` is false, skip step 2 — every item's Primary verdict is final, subject to the confidence rule in the Decision Matrix below.

## Context to Provide Each Evaluator

Each evaluator needs:
- The feedback text. For inline threads, use the **most recent reviewer comment** in the thread, not just the original.
- The feedback source: inline thread, review summary, or PR conversation comment.
- The file path and line number referenced, if present.
- The relevant code at that location, or the PR diff/files/logs needed to judge a summary or conversation comment.
- The PR title and description (to understand scope)
- The PR diff summary (what files changed and why)
- The project's CLAUDE.md pre-commit requirements (if any)

## Evaluator Prompt Template (used for the Primary Evaluator; restated in-transcript for the advisor batch)

```
Evaluate this reviewer feedback item on a GitHub PR. Pick exactly one of three outcomes: FIX, DEFER, or REJECT.

## PR Context
- Title: {pr_title}
- Description: {pr_description}
- Files changed: {changed_files_summary}

## Reviewer Feedback
- Source: {inline-thread | review-summary | pr-comment}
- File: {path}:{line or n/a}
- Reviewer: @{reviewer}
- Feedback: {comment_body}

## Context
{code_or_diff_context}

## Verdicts

FIX — Apply the change in this PR if ALL of the following hold:
- The reviewer is correct (it is a real bug, correctness issue, security concern, missing test/error-check/edge case, project-standard violation, or genuine readability problem on changed code).
- The change belongs in THIS PR's stated scope (it touches the same feature/area or fixes a regression introduced by the PR).
- The cost of the change is proportional to the value (not a sweeping refactor for a one-line nit).

DEFER — File a tracking issue and reply with a link if any of:
- SCOPE CREEP: The concern is correct but lives outside this PR's stated scope.
- DIMINISHING RETURNS: The concern is correct but minor — naming pickiness on reasonable names, micro-optimizations, refactor requests for working code, doc requests for internal helpers, "consider X" suggestions where the current code is fine. Fixing it in this PR adds churn without proportional value.
- AMBIGUOUS: The feedback is an open question, proposes multiple alternatives, or depends on context not in the PR. File the issue so a human can resolve it; do not block the loop.
- AUTOMATED-FIX-FAILED: (Used by the skill, not the evaluator.) A FIX was attempted but pre-commit blocked it. Recorded by Step 5c.

REJECT — Reply with a rationale, no code change, no issue, if any of:
- NOT AN ISSUE: The reviewer is factually mistaken — the code is correct as-is.
- UNRELATED: Concerns code not touched by this PR and is not a regression caused by it.
- NOT RELEVANT: Stylistic preference with no backing in CLAUDE.md, linter config, or established repo convention; current code is fine.
- STYLE PREFERENCE: Both styles are equally valid; the current style matches the surrounding code.
- ALREADY HANDLED: The requested behavior is already present in the PR.

## Output Format
VERDICT: FIX | DEFER | REJECT
CATEGORY:
  - if FIX: bug | correctness | security | missing-test | edge-case | standards | readability
  - if DEFER: scope-creep | diminishing-returns | ambiguous
  - if REJECT: not-an-issue | unrelated | not-relevant | style-preference | already-handled
CONFIDENCE: HIGH | MEDIUM | LOW
REASONING: 2-3 sentences explaining the verdict
REPLY_GUIDANCE: one sentence describing what the PR reply should say
ISSUE_TITLE: (only if VERDICT=DEFER) short imperative title for the tracking issue
```

## Decision Matrix

The combined verdict resolves each disagreement toward action where both the Primary Evaluator and the advisor still consider the feedback valid. Concretely: FIX when both agree FIX, **or** when one lands on FIX and the other on DEFER (both agree the feedback is legitimate — they only disagree on timing, so fix it now rather than filing an issue); only REJECT when there is no disagreement; every remaining disagreement — all of which carry at least one REJECT — becomes DEFER (file an issue so nothing is silently dropped). When no advisor is available, a **low-confidence** Primary verdict is not acted on unchecked — it routes to DEFER instead, since there is no second opinion to catch a bad call.

| Primary Verdict | Advisor (if consulted) | Combined Action |
|---|---|---|
| FIX | FIX, or not flagged | **FIX** — apply code change in this PR |
| FIX | DEFER | **FIX** — both agree the feedback is valid; apply it now instead of filing an issue |
| DEFER | FIX | **FIX** — both agree the feedback is valid; apply it now instead of filing an issue |
| REJECT | REJECT, or not flagged | **REJECT** — reply with rationale, no code change, no issue |
| DEFER | DEFER, or not flagged | **DEFER** — file tracking issue, reply with link |
| FIX | REJECT | **DEFER** — file tracking issue, reply with link |
| REJECT | FIX | **DEFER** — file tracking issue, reply with link |
| DEFER | REJECT | **DEFER** — file tracking issue, reply with link |
| REJECT | DEFER | **DEFER** — file tracking issue, reply with link |
| any | not consulted (`ADVISOR` false), **low confidence** | **DEFER** — file tracking issue, reply with link |

This rule leans toward action while staying churn-averse: when both sides consider the feedback valid (FIX + DEFER, in either order) the change lands in this PR rather than on the tracker; but a REJECT from either side is enough to keep the change out of this PR and file an issue instead. Use the Primary Evaluator's category when its verdict matches the combined action; when the advisor's disagreement changed the outcome, use `ambiguous` so the filed issue carries a clear "humans need to break the tie" signal.

## Confidence Note

Confidence (HIGH | MEDIUM | LOW) is metadata for the rejection-category selection and the issue body. It is **not** an override knob when an advisor was consulted — the decision matrix above is the only thing that picks the action in that case. It becomes load-bearing only in the no-advisor row above: with no second opinion available, a LOW-confidence verdict routes to DEFER regardless of what it was, as the compensating control for running without a cross-check.

## DEFER Taxonomy and Tracking Issue

When the combined action is DEFER, the skill files an issue and posts a reply with a link. Categories and example replies:

| Category | When to use | Example reply (issue link appended) |
|---------|-------------|-------------------------------------|
| `scope-creep` | Valid concern, but outside the PR's stated scope | "Adding retry logic to the HTTP client is a good idea but is outside this PR, which only fixes the auth token refresh. Tracked as #123." |
| `diminishing-returns` | Correct but a low-value nit; fixing here adds churn without proportional value | "Renaming `extractTokens` → `parseTokens` is reasonable but a churn-only change. Tracked as #124 for a follow-up sweep." |
| `ambiguous` | Open question, multiple alternatives, or evaluator disagreement | "This raises a design question that's worth its own thread. Tracked as #125 so we can resolve it without blocking this PR." |
| `automated-fix-failed` | Skill-internal: a FIX was attempted but pre-commit blocked the change (Step 5c) | "Auto-fix failed pre-commit (`tsc TS2322`). Reverted the change and tracked as #126 for manual follow-up." |

## REJECT Taxonomy

When the combined action is REJECT, the skill replies with a rationale and **does not** file an issue. Categories:

| Category | When to use | Example rejection reply |
|---------|-------------|--------------------------|
| `not-an-issue` | Reviewer is factually wrong | "The null check is unnecessary here — `fetchUser()` is guaranteed to return a non-null value by the API contract (see UserService.ts:42)." |
| `unrelated` | Concerns untouched code that is not a regression caused by this PR | "This function was not modified in this PR. The existing behavior is unchanged." |
| `not-relevant` | Style preference with no backing in repo conventions | "This is a stylistic preference. The project has no documented convention for this pattern (checked CLAUDE.md, .eslintrc, .prettierrc)." |
| `style-preference` | Alternate style, equally valid | "Both approaches are valid here. The current style is consistent with the rest of the codebase (see similar patterns in utils/auth.ts and lib/api.ts)." |
| `already-handled` | The requested behavior is already present in the PR | "This is already handled by `validateConfig()` and covered by `config.test.ts`; no code change was needed." |

## Reply Requirements

Every feedback item needs a reply after evaluation:
- **FIX**: say `Fixed in <sha>`, identify the changed file/function/behavior, and mention validation.
- **DEFER**: state the deferral category and rationale, then `Tracked as #<issue_number> (<issue_url>).` If issue creation failed, end with `TODO: file as a separate issue — automated issue creation failed (<error summary>).` instead of the link.
- **REJECT**: say no change was made, give the rejection category, and explain why.

Reply before counting the item as addressed. If posting the reply fails, retry later and keep the item open in the loop.

## Handling Ambiguous Feedback

If a feedback item asks an open question, proposes multiple alternatives, or suggests an architectural change, classify it as **DEFER / ambiguous** regardless of the matrix vote. The filed issue is the durable place for that conversation; the PR reply tells the reviewer where the discussion has moved. **Never** stop the loop to ask the user — this skill is fully automatic.

## Thread Context

Always evaluate inline threads based on the **most recent reviewer comment** in the thread, not just the original. Reviewers often post follow-ups ("that's still not right, please also handle X"), and the latest comment reflects the current ask.

## Performance Note

Feedback evaluation is the most expensive step but also the most important. Each item spawns at most one subagent (the Primary Evaluator) — for a PR with 10 feedback items, that's 10 subagent calls running in parallel, plus **one** advisor consultation for the whole batch, never one per item. The advisor forwards the full conversation on every call, so calling it per item would mean replaying an ever-growing transcript ten times over instead of once; batching is not an optimization here, it is the difference between usable and impractical.
