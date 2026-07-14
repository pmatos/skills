# Dual-Agent Reviewer Feedback Evaluation

Every unresolved reviewer feedback item must be evaluated before any action is taken. This includes inline review threads, review summary bodies, and PR conversation comments. This prevents wasting effort on invalid, out-of-scope, or low-value feedback. Two independent evaluators assess each item in parallel, and their combined verdict picks one of three outcomes: **FIX** (apply in this PR), **DEFER** (file a tracking issue), or **REJECT** (reply with rationale, no code change).

The skill is fully automatic. Evaluators must never produce an "ask the user" verdict — uncertain or ambiguous items are auto-classified as DEFER (see "Handling Ambiguous Feedback" below).

## Evaluation Architecture

The skill is harness-symmetric: it runs under either Claude Code or Codex CLI, and the evaluator pair is always the local host model + the *other* harness's model. SKILL.md Step 0a captures `LOCAL_LABEL` / `REMOTE_LABEL` and the per-host invocation rows used below.

For each unresolved feedback item, spawn two subagents **in parallel**:

1. **Local Evaluator** — runs the host model in a clean context.
   - Claude host: Agent tool with `model="opus"`.
   - Codex host: Bash with `codex exec --full-auto --sandbox read-only --ephemeral - < /tmp/eval-XXXXXX` (10-minute timeout; write the prompt with `mktemp` and `rm -f` after).
2. **Cross-harness Evaluator** — runs the other harness's model.
   - Claude host: Skill tool with `skill="codex-2nd-opinion"`. **Never** substitute `codex:rescue`, `codex:codex-rescue`, or any other `codex:*` plugin skill — those are unrelated tools.
   - Codex host: Bash with `claude -p --permission-mode auto --output-format text < /tmp/eval-XXXXXX` (10-minute timeout; same `mktemp` / `rm -f` discipline; `--permission-mode auto` keeps `claude` from prompting when run headless inside the loop). **Never** call `codex exec` again here — that would just be the Local Evaluator.

Both receive identical context and return independent verdicts.

## Context to Provide Each Evaluator

Each evaluator needs:
- The feedback text. For inline threads, use the **most recent reviewer comment** in the thread, not just the original.
- The feedback source: inline thread, review summary, or PR conversation comment.
- The file path and line number referenced, if present.
- The relevant code at that location, or the PR diff/files/logs needed to judge a summary or conversation comment.
- The PR title and description (to understand scope)
- The PR diff summary (what files changed and why)
- The project's CLAUDE.md pre-commit requirements (if any)

## Evaluator Prompt Template (used by both Local and Cross-harness evaluators)

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

## Cross-harness Evaluator Invocation

### Claude host (cross-harness = Codex)

Invoke the `codex-2nd-opinion` skill via the Skill tool — exact form: `Skill(skill="codex-2nd-opinion", args=<the evaluation prompt above>)`. The skill handles Codex CLI formatting and invocation; pass the same template you used for the Local Evaluator.

**Forbidden substitutes** (do not call any of these even if `codex-2nd-opinion` seems unavailable — stop and report instead):
- `codex:rescue` (Skill tool)
- `codex:codex-rescue` (Agent subagent)
- `codex:setup`, `codex:codex-cli-runtime`, `codex:gpt-5-4-prompting`, `codex:codex-result-handling`

These are unrelated tools from the `codex` plugin. The Cross-harness Evaluator's purpose is to get an *independent verdict* on a review comment, not to delegate rescue work.

### Codex host (cross-harness = Claude)

Write the prompt above to `/tmp/eval-XXXXXX` via `mktemp`, then run via Bash with a 10-minute timeout:

```bash
claude -p --permission-mode auto --output-format text < /tmp/eval-XXXXXX
```

`--permission-mode auto` is required: without it, headless `claude` will block on permission prompts inside the loop and the evaluator call will hang.

Capture stdout as the evaluator's verdict, then `rm -f` the temp file. **Never** invoke `codex exec` here — that would re-run the Local Evaluator and lose the independent-verdict guarantee.

## Decision Matrix

The combined verdict resolves each disagreement toward action where both evaluators still consider the feedback valid. Concretely: FIX when both vote FIX, **or** when one votes FIX and the other DEFER (both agree the feedback is legitimate — they only disagree on timing, so fix it now rather than filing an issue); only REJECT when both vote REJECT; every remaining disagreement — all of which carry at least one REJECT vote — becomes DEFER (file an issue so nothing is silently dropped).

| Local Verdict | Cross-harness Verdict | Combined Action |
|---------------|-----------------------|-----------------|
| FIX | FIX | **FIX** — apply code change in this PR |
| FIX | DEFER | **FIX** — both agree the feedback is valid; apply it now instead of filing an issue |
| DEFER | FIX | **FIX** — both agree the feedback is valid; apply it now instead of filing an issue |
| REJECT | REJECT | **REJECT** — reply with rationale, no code change, no issue |
| DEFER | DEFER | **DEFER** — file tracking issue, reply with link |
| FIX | REJECT | **DEFER** — file tracking issue, reply with link |
| REJECT | FIX | **DEFER** — file tracking issue, reply with link |
| DEFER | REJECT | **DEFER** — file tracking issue, reply with link |
| REJECT | DEFER | **DEFER** — file tracking issue, reply with link |

This rule leans toward action while staying churn-averse: when both evaluators consider the feedback valid (FIX + DEFER, in either order) the change lands in this PR rather than on the tracker; but a REJECT vote from either evaluator is enough to keep the change out of this PR and file an issue instead. Use the category from the evaluator whose verdict matched the combined action; on ties, use the higher-confidence evaluator; on full ties, use the Local Evaluator's category.

For DEFER outcomes whose evaluators disagreed (e.g. FIX/REJECT), use category `ambiguous` so the filed issue carries a clear "humans need to break the tie" signal.

## Confidence Note

Confidence (HIGH | MEDIUM | LOW) is metadata for the rejection-category selection and the issue body, **not** an override knob. The decision matrix above is the only thing that picks the action — high confidence on one side does not flip a DEFER into a FIX or REJECT.

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

Feedback evaluation is the most expensive step but also the most important. Each item spawns two subagents — for a PR with 10 feedback items, that's 20 subagent calls (10 pairs running in parallel). This is intentional. Getting the evaluation right means fewer wasted iterations and no unnecessary code churn.
