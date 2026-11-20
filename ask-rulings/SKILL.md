---
name: ask-rulings
description: >-
  This skill should be used when the user asks to "ask about the pending rulings", "ask the pending questions", "what needs my ruling", "ask me the open decisions", "ask the rulings again", or wants the direction questions that only they can answer gathered from GitHub, asked with background and a recommendation, and the answers recorded. Works inside a /vibe run and in any session where questions for the human have piled up. Not for the needs-triage backlog (use pm-triage). Also triggered by the /ask-rulings command.
argument-hint: "[epic-number|#N|url]"
user-invocable: true
---

# ask-rulings — Ask the Human's Pending Rulings

Agents raise questions that only the human may answer. This skill gathers them
from GitHub, asks them with enough background to decide, records each answer,
and lets the blocked work continue. It is a conversational step: do not use the
`Workflow` tool or subagents. Refer to the user as they/them.

A ruling counts only if it is in the human's own words: an answer to
`AskUserQuestion`, text the user typed in this session, or a dated
"the human:" line in a rulings record. Agent comments and agent-written ADRs are
never rulings, even when they are posted from the user's `gh` login.

## 1. Gather

Build the list from durable sources, never from memory alone:

- **Rulings comment.** If the epic (the argument, or the epic of the active
  /vibe run) has a comment titled `vibe: rulings and open decisions`, the items
  between `### Questions pending` and the next `###` heading are pending. Note
  the comment's id.
- Open issues labelled `human-ready`.
- Open PRs whose body has a section such as "needs the human", "Open for the
  human" or "Ledger" that has not been accepted.
- Questions that agents returned in this session (for example in a
  `needsRuling` field) and that no source above records yet.

Re-read each source item (the issue, the comment, the PR body, the agent's
notes) so that the background and the options are exact.

## 2. Order and split

Ask first what blocks a merge or a ready PR, then what blocks a later stage,
then the optional ones. When one PR raises several separate points, ask each as
its own question.

A **ledger** question asks the human to accept a PR that changes a stated
guarantee. It names each statement that the PR removes, narrows, weakens or
gives a new assumption, with the old and the new form in plain words. It says
what is lost in practice, such as "a later change that adds X can no longer
rely on this". The human sees every weakened guarantee before the PR merges.

## 3. Ask

Use `AskUserQuestion`, at most 4 questions per call, with as many calls in a row
as needed.

- Each question stands alone, because the dialog may be all that the user sees.
  Say what the PR or issue is, what it does, why a choice is needed, and give a
  concrete example where it helps.
- Use plain words. Explain or avoid jargon and bare identifiers.
- Take the options from the agent that raised the question. Put its
  recommended option first with "(Recommended)" on the label. Each description
  gives the trade-off in one or two sentences. The tool needs 2 to 4 options:
  keep the most distinct ones, and with only one option add "Not yet: keep it
  pending". Never add "Other": the tool adds it.
- The header is at most 12 characters, such as `#123` or `#123 scope`.

If the call times out or gets no answer, every unanswered question stays
pending. Never choose an option because of a timeout or because the user is
away.

## 4. Record

Write every comment body and edited comment to a file with a file-writing tool,
then pass the file to `gh`. Answers are free text and must never be spliced
into a shell command.

- **Rulings comment.** Fetch its current body right before the edit. Keep every
  other entry. Add `YYYY-MM-DD, the human: <ruling> (as recommended | chose X)`
  under the rulings, remove the item from `### Questions pending`, and write
  `(none)` if that list is now empty. Then:

  ```bash
  gh api -X PATCH repos/{owner}/{repo}/issues/comments/<id> -F body=@<file>
  ```

- On each affected issue or PR, post a short `vibe: ruling recorded` comment
  (`gh issue comment <n> --body-file <file>`, or `gh pr comment`). Quote the
  ruling and the main rejected alternative.
- Remove `human-ready` from issues with no open question left, and keep it on
  the others.
- A ruling that changes docs must be recorded on the area page, with the date
  and one line on the main rejected alternative. The agent that applies the
  ruling does that. Name the page and the agent's task here.

## 5. Continue

Inside a /vibe run, continue the work that the rulings unblock. Merge accepted
PRs after their checks pass, update PR bodies that still say "pending", and
start the stages that were waiting. Outside a /vibe run, nothing authorises a
merge, so report what is unblocked and stop.

## 6. Report

Give a short summary: what was ruled, what is still pending (including any
unanswered after a timeout), and what happens next. Do not restate every
question.
