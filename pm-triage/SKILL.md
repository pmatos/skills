---
name: pm-triage
description: This skill should be used when the user asks to "triage issues", "run a triage session", "triage the backlog", "make triage decisions", "unblock issues", "decide on the needs-triage issues", "clear needs-triage", "go through human-needed issues", or wants an interactive, one-issue-at-a-time decision session over a project's needs-triage/human-needed/sym:human-needed GitHub issues that removes the label as each decision is made. Also triggered by the /pm-triage command.
argument-hint: "[owner/repo] [--labels a,b,c]"
user-invocable: true
---

# pm-triage — Decision Session for Blocked Issues

Some issues aren't blocked on code — they're blocked on a decision only a human with technical vision and product context can make. This skill runs a per-project decision session over exactly those issues: it gathers every open issue flagged `needs-triage`, `human-needed`, or `sym:human-needed` (the label symphonika inserts on personal projects), works out which of them are stale or already resolved, and walks the rest past the user one at a time so each decision unblocks implementation immediately.

**Scope is one project per run.** Pass `owner/repo` to target a repository other than the current one; with no argument, infer the repo from the current git remote.

## Why no local state file

Every decision is written back to GitHub itself — a comment recording the decision and a label removal — so the label *is* the queue. The next `/pm-triage` run re-queries open issues carrying the target labels and naturally picks up wherever the last session left off, including a session that ended early. Nothing needs to be tracked locally, and nothing can drift out of sync with what actually happened on the issue.

## Arguments

- `owner/repo` — triage this repository instead of the current one.
- `--labels a,b,c` — use exactly this label set instead of the default `needs-triage`, `human-needed`, `sym:human-needed`. Replaces the default entirely; include all the labels you want considered.

## Workflow

### 1. Resolve the repo and the label set

Determine the repo: the `owner/repo` argument if given, otherwise `gh repo view --json nameWithOwner -q .nameWithOwner`. Bail with a clear message if neither works (not a git repo, no `gh` auth, or `gh` unavailable — this skill is `gh`-only; it never uses a GitHub MCP server, since it targets arbitrary `owner/repo` values that may not be the current project).

Determine the label set: `--labels` if given, otherwise the three defaults. Check which of them actually exist in the repo with `gh label list --repo <repo> --json name -q '.[].name'`. Keep only the labels that exist.

If none of the target labels exist in the repo, don't guess. Ask the user which label marks issues needing a decision, offering as options any existing labels whose name suggests the same purpose (contains "triage", "decision", "blocked", "human", "needed") plus a "nothing to triage here" option that stops the skill.

### 2. Gather candidate issues

For each surviving label, run one search and merge the results by issue number (a label search is an AND filter across multiple `--label` flags, not the OR this needs, so query per label and union):

```bash
gh issue list --repo <repo> --search 'is:open label:"<label>"' \
  --json number,title,url,labels,createdAt,updatedAt --limit 200
```

If the merged set is empty, report "Nothing to triage — no open issues carry <labels> in <repo>" and stop. Nothing after this point runs.

### 3. Analyze each candidate (read-only, parallel)

Before asking the user anything, work out which issues genuinely still need a human decision. An issue can be:

- **`RESOLVED_BY_PR`** — a merged PR already made this call. Cite the PR.
- **`SUPERSEDED`** — the issue is stale: contradicted by a later issue/decision, or the thing it describes no longer exists. Cite the reason.
- **`NEEDS_DECISION`** — genuinely open; nothing has settled it.
- **`UNCLEAR`** — the analysis can't tell either way. Never auto-resolve this; it joins the decision queue with no synthesized options.

Dispatch this analysis in parallel — one read-only sub-agent per issue (or small batches of ~5-8 if the candidate count is large) via the `Agent` tool, `general-purpose`. (`Explore` is tuned for locating code by search pattern and reads excerpts rather than full content — not a good fit for reasoning over an issue's full discussion. If no sub-agent tool is available in the current harness, do this pass inline, one issue at a time; it's slower, not different.) Brief each agent explicitly: **read-only** — run `gh issue view`/`gh pr list`/`gh api` (GET) only, never `gh issue comment`/`edit`/`close` or any other mutating command; report the verdict back to the orchestrator instead of acting on it. Give it the issue number, repo, and this task:

1. `gh issue view <n> --repo <repo> --json title,body,comments,labels,url,createdAt,updatedAt,state`.
2. Look for a merged PR that already answers it: `gh pr list --repo <repo> --state merged --search "#<n> in:body"`, and check the issue's own cross-references via `gh api repos/<repo>/issues/<n>/timeline --jq '.[] | select(.event=="cross-referenced" or .event=="closed")'`.
3. Look for a newer issue or comment that explicitly supersedes it ("supersedes #<n>", "no longer needed", the described feature since removed).
4. If still open, read the issue body and comments for options already debated in the discussion — these become synthesized candidate resolutions, not invented ones.
5. Return the verdict as labeled lines, one field per line, so free text in the rationale or a candidate can't collide with a delimiter:

   ```text
   Issue: <number>
   Verdict: <RESOLVED_BY_PR|SUPERSEDED|NEEDS_DECISION|UNCLEAR>
   Rationale: <one sentence>
   Citation: <PR #/issue #/none>
   Candidate 1: <only for NEEDS_DECISION; omit both Candidate lines if genuinely open-ended>
   Candidate 2: <optional>
   ```

If a sub-agent errors (issue 404s, rate limit, malformed output) or its verdict line is missing/unparseable, don't drop the issue — record it as `UNCLEAR` with the citation `analysis failed`. The queue only ever loses an issue by resolving it, never by a failed lookup.

### 4. Present the plan, apply auto-resolutions

Summarize the merged verdicts in groups: resolved-by-PR (N), superseded (N), needs-decision (N + unclear folded in). One line per issue with its citation.

Ask once, before touching anything:

- Apply all auto-resolutions and proceed to the decision queue
- Review each auto-resolution individually
- Skip auto-resolutions — leave `RESOLVED_BY_PR`/`SUPERSEDED` issues untouched, go straight to decisions
- Stop here for today

**"Review each auto-resolution individually"** runs the same shape as step 5's loop, one auto-resolution at a time: `AskUserQuestion` with the issue, its verdict, and citation, options `Apply` / `Skip — leave the label` / `Stop for today`, handled exactly as those outcomes are handled in step 5. Once every auto-resolution has been reviewed (or the user stops), continue to the decision queue as normal.

Every comment this skill posts goes through a temp file, never inline in the shell command — the text can come from a sub-agent's rationale or (in step 5) the user's own verbatim words, and either can contain backticks, `$(...)`, or a stray quote that would break or, worse, execute inside a double-quoted `--body "..."`. Write the body to `mktemp`, pass it with `--body-file`, then `rm -f` it:

```bash
tmpfile=$(mktemp)
printf '%s\n' "**Triage (via /pm-triage, <today's date>):** resolved by #<pr> — <rationale>" > "$tmpfile"
# or: "**Triage (via /pm-triage, <today's date>):** superseded — <reason>"
gh issue comment <n> --repo <repo> --body-file "$tmpfile"
rm -f "$tmpfile"
```

then `gh issue edit <n> --repo <repo> --remove-label "<label>"` for each target label actually present on that issue (only the ones present — don't attempt to remove labels the issue doesn't carry). The matching `**Triage`/`**Decision` prefixes make both kinds of outcome grep-able later.

### 5. Interactive decision loop

Work the `NEEDS_DECISION` + `UNCLEAR` queue oldest-first by `createdAt`. For each issue, call `AskUserQuestion`:

- **question**: the issue title, a two-sentence summary of why it's blocked (from step 3's rationale), and the issue URL.
- **options**: up to 2 synthesized candidates from step 3 (pick the most distinct if there were more — the rest are still reachable via free text), plus always:
  - **"Skip — leave the label(s)"** (naming the actual target label(s) present on this specific issue; it stays flagged for next time — not a decision)
  - **"Stop for today"** (end the session now; this and every remaining issue stay untouched)

  Free-form text is always available through the tool's built-in "Other" — use it as the decision whenever the user's answer isn't one of the fixed options above.

Handle the answer:

- **Stop for today** → end the loop immediately. Do not touch this issue. Go to step 6.
- **Skip** → don't comment or relabel. Move to the next issue. Note it as skipped-this-session in the running summary (it still carries the label, so it resurfaces next run — no different than never having looked at it, just recorded so today's summary is complete).
- **Anything else** → this is the decision. Post it through a temp file, same discipline as step 4:

  ```bash
  tmpfile=$(mktemp)
  printf '%s\n' "**Decision (via /pm-triage, <today's date>):** <answer>" > "$tmpfile"
  gh issue comment <n> --repo <repo> --body-file "$tmpfile"
  rm -f "$tmpfile"
  ```

  Then remove every target label present on that issue: `gh issue edit <n> --repo <repo> --remove-label "<label>"`.

  If the decision text itself says to close the issue (won't-fix, not needed, no longer relevant), close it too — the decision comment above already carries the rationale, so close without repeating it: `gh issue close <n> --repo <repo> --reason "not planned"`. Otherwise leave it open — removing the label is what unblocks implementation; closing is a separate, explicit call.

### 6. Session summary

Report, grouped:

- **Decided** — issue, one-line decision, link.
- **Auto-resolved** — issue, reason (resolved-by-PR / superseded), link.
- **Skipped this session** — issue, link (still carries the label).
- **Untouched / remaining** — count, with the search query to see them (`is:open label:"<label>"` per surviving label), whether because the session was stopped early or because the queue is simply that long.

No file is written and no state is persisted beyond what's now on GitHub — the label removals and comments made this session are the entire record.
