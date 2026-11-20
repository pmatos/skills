---
name: ask-rulings
description: >-
  This skill should be used when the user asks to "ask about the pending rulings", "ask the pending questions", "what needs my ruling", "ask me the open decisions", "ask the rulings again", or wants the open questions that block further progress, and that only they can answer, gathered, asked with background and a recommendation, and the answers recorded so the work can continue. Not for the needs-triage backlog (use pm-triage). Also triggered by the /ask-rulings command.
argument-hint: "[issue|PR|url ...]"
user-invocable: true
---

# ask-rulings — Ask the Questions That Block Progress

Work stalls on questions that only the human may answer. This skill gathers
them, asks them with enough background to decide, records each answer where the
question lives, and then lets the blocked work continue. It is a conversational
step: do not use the `Workflow` tool or subagents. Refer to the user as
they/them.

A ruling counts only if it is in the human's own words: an answer to
`AskUserQuestion`, text the user typed, or a record that quotes the human and is
dated. Agent comments and agent-written ADRs are never rulings, even when they
are posted from the user's `gh` login.

## 1. Gather

Build the list from durable sources, never from memory alone:

- Questions raised in this session, by you or by agents, that have no answer.
- Any record of open questions that this session or the project keeps, such as
  an issue comment or document that lists them, an issue label that marks
  "waiting on the human", or a PR body section waiting on acceptance.
- The issues, PRs or URLs passed as arguments.

Re-read each source item (the issue, the comment, the PR body, the agent's
notes) so that the background and the options are exact. If a record you
expected is missing or has an unfamiliar layout, say so rather than report that
nothing is pending.

## 2. Order and split

Ask first what blocks a merge or a ready PR, then what blocks a later step, then
the optional ones. When one change raises several separate points, ask each as
its own question.

When a change weakens a stated guarantee, ask the human to accept it. Name each
statement that the change removes, narrows, weakens or gives a new assumption,
with the old and the new form in plain words. Say what is lost in practice,
such as "a later change that adds X can no longer rely on this". The human sees
every weakened guarantee before the change merges.

## 3. Ask

Use `AskUserQuestion`, at most 4 questions per call, with as many calls in a row
as needed.

- Each question stands alone, because the dialog may be all that the user sees.
  Say what the issue or PR is, what it does, why a choice is needed, and give a
  concrete example where it helps.
- Use plain words. Explain or avoid jargon and bare identifiers.
- Take the options from whoever raised the question. Put the recommended option
  first with "(Recommended)" on the label. Each description gives the trade-off
  in one or two sentences. The tool needs 2 to 4 options: keep the most distinct
  ones, and with only one option add "Not yet: keep it pending". Never add
  "Other": the tool adds it.
- The header is at most 12 characters, such as `#123` or `#123 scope`.

If the call times out or gets no answer, every unanswered question stays
pending. Never choose an option because of a timeout or because the user is
away.

## 4. Record

Record each ruling where its question lives, so that a later session finds it.
Write every comment body and edited comment to a file with a file-writing tool,
then pass the file to `gh`. Answers are free text and must never be spliced
into a shell command.

- If a record lists the open questions, fetch it again right before you edit
  it. Keep every other entry, add `YYYY-MM-DD, the human: <ruling> (as
  recommended | chose X)`, and remove the question from the open list.
- On each affected issue or PR, post a short comment that quotes the ruling and
  the main rejected alternative.
- Remove a "waiting on the human" label from an issue with no open question
  left, and keep it on the others.

## 5. Continue

Resume the work that the rulings unblock, within what the session was already
authorised to do. A ruling is not permission to merge, close or push if the
session had no such permission before. In that case, report what is unblocked
and stop.

## 6. Report

Give a short summary: what was ruled, what is still pending (including any
unanswered after a timeout), and what happens next. Do not restate every
question.
