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

Determine the label set: `--labels` if given, otherwise the three defaults. Check which of them actually exist in the repo with `gh label list --repo <repo> --json name --limit 1000 -q '.[].name'` — `--limit` defaults to 30, and a repo with more labels than that would otherwise make a real target label look absent. Keep only the labels that exist.

If none of the target labels exist in the repo, don't guess. Ask the user which label marks issues needing a decision, offering as options any existing labels whose name suggests the same purpose (contains "triage", "decision", "blocked", "human", "needed") plus a "nothing to triage here" option that stops the skill.

### 2. Gather candidate issues

For each surviving label, run one search and merge the results by issue number (a label search is an AND filter across multiple `--label` flags, not the OR this needs, so query per label and union):

```bash
gh issue list --repo <repo> --search 'is:open label:"<label>"' \
  --json number,title,url,labels,createdAt,updatedAt --limit 1000
```

`gh` paginates internally for any `--limit` above one page, so 1000 comes back in full for the overwhelming majority of triage queues. If a query still returns exactly 1000 (the cap itself, not a coincidence), note in the step 6 summary that this label's queue may be truncated and more issues likely remain beyond what this run saw — a queue that size is far outside this skill's interactive, one-at-a-time use case, so flagging it is enough; it doesn't need its own cursor-pagination logic.

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

**"Review each auto-resolution individually"** runs the same shape as step 5's loop, one auto-resolution at a time: `AskUserQuestion` with the issue, its verdict, and citation, options `Apply` / `Skip — leave the label` / `Stop for today`. `Apply` and `Skip` are handled exactly as those outcomes are handled in step 5, and the sub-loop continues to the next auto-resolution. `Stop for today` is handled exactly as step 5 handles it too: end the session immediately, do not touch this or any remaining auto-resolution, and go straight to step 6 — it does **not** fall through to the decision queue. Only once every auto-resolution has been reviewed without the user stopping does the sub-loop end normally and continue to the decision queue.

Every comment this skill posts goes through a temp file, never inline in the shell command — the text can come from a sub-agent's rationale or (in step 5) the user's own verbatim words, and either can contain backticks, `$(...)`, or a stray quote. Splicing that text into a double-quoted shell argument (`--body "..."`, or even `printf '%s\n' "..."`) still expands or executes it before `gh` ever sees the file — the shell parses the argument first, so the temp-file step by itself is not the safety measure. Use a quoted heredoc instead: with a **quoted** delimiter (`<<'PMTRIAGE_EOF'`), the shell treats everything between the markers as inert literal text — no expansion, no substitution, no command execution — no matter what it contains:

```bash
tmpfile=$(mktemp)
cat > "$tmpfile" <<'PMTRIAGE_EOF'
**Triage (via /pm-triage, <today's date>):** resolved by #<pr> — <rationale>
PMTRIAGE_EOF
# or: **Triage (via /pm-triage, <today's date>):** superseded — <reason>
gh issue comment <n> --repo <repo> --body-file "$tmpfile"
rm -f "$tmpfile"
```

(Substitute the real values for `<pr>`/`<rationale>`/`<reason>` when writing the heredoc body — the delimiter's quoting is what keeps them inert, not their placeholder form. If a harness tool that writes files directly — not through a shell string — is available, that works too and sidesteps the heredoc entirely; the requirement is that the content never passes through shell parsing.)

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
- **Anything else** → this is the decision. Post it through a quoted heredoc, same discipline as step 4 — `<answer>` is the user's own verbatim text and just as capable of containing shell metacharacters as a sub-agent's rationale:

  ```bash
  tmpfile=$(mktemp)
  cat > "$tmpfile" <<'PMTRIAGE_EOF'
  **Decision (via /pm-triage, <today's date>):** <answer>
  PMTRIAGE_EOF
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
- **Possibly truncated** — only if step 2 flagged a label whose query hit the 1000-issue cap: name it and note that more issues than this run saw may exist.

No file is written and no state is persisted beyond what's now on GitHub — the label removals and comments made this session are the entire record.
