# Dual-Agent Reviewer Feedback Evaluation

Every unresolved reviewer feedback item must be evaluated before any action is taken. This includes inline review threads, review summary bodies, and PR conversation comments. This prevents wasting effort on invalid, out-of-scope, or irrelevant feedback. Two independent evaluators assess each item in parallel, and their combined verdict determines the action.

## Evaluation Architecture

The skill is harness-symmetric: it runs under either Claude Code or Codex CLI, and the evaluator pair is always the local host model + the *other* harness's model. SKILL.md Step 0a captures `LOCAL_LABEL` / `REMOTE_LABEL` and the per-host invocation rows used below.

For each unresolved feedback item, spawn two subagents **in parallel**:

1. **Local Evaluator** — runs the host model in a clean context.
   - Claude host: Agent tool with `model="opus"`.
   - Codex host: Bash with `codex exec --full-auto --sandbox read-only --ephemeral - < /tmp/eval-XXXXXX` (10-minute timeout; write the prompt with `mktemp` and `rm -f` after).
2. **Cross-harness Evaluator** — runs the other harness's model.
   - Claude host: Skill tool with `skill="codex-2nd-opinion"`. **Never** substitute `codex:rescue`, `codex:codex-rescue`, or any other `codex:*` plugin skill — those are unrelated tools.
   - Codex host: Bash with `claude -p --output-format text < /tmp/eval-XXXXXX` (10-minute timeout; same `mktemp` / `rm -f` discipline). **Never** call `codex exec` again here — that would just be the Local Evaluator.

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
Evaluate this reviewer feedback item on a GitHub PR. Determine if it should be addressed.

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

## Evaluation Criteria

Rate this feedback as VALID or INVALID:

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
REPLY_GUIDANCE: one sentence describing what the PR reply should say
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
claude -p --output-format text < /tmp/eval-XXXXXX
```

Capture stdout as the evaluator's verdict, then `rm -f` the temp file. **Never** invoke `codex exec` here — that would re-run the Local Evaluator and lose the independent-verdict guarantee.

## Decision Matrix

| Local Verdict | Cross-harness Verdict | Action |
|---------------|-----------------------|--------|
| VALID | VALID | **Address** the feedback — make the code fix |
| VALID | INVALID | **Address** the feedback — err on the side of caution |
| INVALID | VALID | **Address** the feedback — err on the side of caution |
| INVALID | INVALID | **Reject** the feedback — post rejection reply |

When both are INVALID, select the rejection category from the evaluator with higher confidence. If confidence is equal, use the Local Evaluator's category.

## Confidence-Based Override

If one evaluator says INVALID with HIGH confidence and the other says VALID with LOW confidence, treat as **INVALID** — the high-confidence evaluator's reasoning takes precedence.

## Rejection Taxonomy

When rejecting feedback, use one of these categories:

| Category | When to use | Example rejection message |
|---------|-------------|--------------------------|
| `not-an-issue` | Reviewer is factually wrong | "The null check is unnecessary here — `fetchUser()` is guaranteed to return a non-null value by the API contract (see UserService.ts:42)." |
| `scope-creep` | Valid concern but not for this PR | "Adding retry logic to the HTTP client is a good idea but is outside the scope of this PR, which only fixes the auth token refresh. Filed as #123." |
| `unrelated` | Concerns untouched code | "This function was not modified in this PR. The existing behavior is unchanged." |
| `not-relevant` | Style preference without backing | "This is a stylistic preference. The project has no documented convention for this pattern (checked CLAUDE.md, .eslintrc, .prettierrc)." |
| `style-preference` | Alternate style, equally valid | "Both approaches are valid here. The current style is consistent with the rest of the codebase (see similar patterns in utils/auth.ts and lib/api.ts)." |
| `already-handled` | The requested behavior is already present in the PR | "This is already handled by `validateConfig()` and covered by `config.test.ts`; no code change was needed." |

## Reply Requirements

Every feedback item needs a reply after evaluation:
- VALID and fixed: say `Fixed in <sha>`, identify the changed file/function/behavior, and mention validation.
- INVALID and rejected: say no change was made, give the rejection category, and explain why.
- Ambiguous and user-decided: state the user-selected decision and either the fix location or the no-change rationale.

Reply before counting the item as addressed. If posting the reply fails, retry later and keep the item open in the loop.

## Handling Ambiguous Feedback

If a feedback item asks an open question, proposes multiple alternatives, or suggests an architectural change, classify it as **ambiguous** regardless of evaluator verdicts. Present it to the user with both evaluators' reasoning and ask for guidance.

## Thread Context

Always evaluate inline threads based on the **most recent reviewer comment** in the thread, not just the original. Reviewers often post follow-ups ("that's still not right, please also handle X"), and the latest comment reflects the current ask.

## Performance Note

Feedback evaluation is the most expensive step but also the most important. Each item spawns two subagents — for a PR with 10 feedback items, that's 20 subagent calls (10 pairs running in parallel). This is intentional. Getting the evaluation right means fewer wasted iterations and no unnecessary code churn.
